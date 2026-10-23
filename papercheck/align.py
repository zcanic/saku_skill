from __future__ import annotations

import difflib
from collections import defaultdict
from typing import Any

from . import CANONICALIZER_VERSION, PARSER_VERSION, SEGMENTER_VERSION
from .ids import PREFIXES, WIDTH, max_id
from .markdown import Block
from .segment import Sentence, segment_block
from .state import StateView, empty_sources
from .util import char_byte_offsets, now_iso, sha256_bytes, sha256_text


class Counter:
    def __init__(self, old: StateView | None) -> None:
        self.value = {kind: 0 for kind in PREFIXES}
        if old is not None:
            self.value["block"] = max_id(old.blocks, "block")
            self.value["container"] = max_id(old.containers, "container")
            self.value["variant"] = max_id(old.variants, "variant")
            self.value["event"] = max_id(old.events, "event")
            self.value["snapshot"] = max_id(old.snapshots, "snapshot")
            self.value["document"] = max_id([old.document], "document")
            for kind, key in {
                "claim": "claims", "relation": "relations", "revision": "revisions",
                "reference": "references", "evidence": "evidence", "quantity": "quantities",
                "assessment": "assessments", "review": "reviews", "check": "checks",
                "argument": "arguments", "invalidation": "invalidations", "binding": "bindings",
                "run": "runs",
            }.items():
                self.value[kind] = max_id(getattr(old, key, []), kind)
            placements = [
                {"id": sel.get("placement_id", "")}
                for snap in old.snapshots
                for sel in snap.get("selections", [])
            ]
            self.value["placement"] = max_id(placements, "placement")

    def take(self, kind: str) -> str:
        self.value[kind] += 1
        return f"{PREFIXES[kind]}{self.value[kind]:0{WIDTH}d}"


def _sentence_record(sel: dict[str, Any], containers: dict[str, dict], variants: dict[str, dict]) -> dict[str, Any] | None:
    container = containers.get(sel.get("container_id"))
    variant = variants.get(sel.get("variant_id"))
    if not container or not variant:
        return None
    return {
        "container_id": container["id"],
        "variant_id": variant["id"],
        "norm": variant.get("normalized_text", ""),
        "raw": variant.get("raw_text", ""),
        "block_id": container.get("parent_block_id"),
        "placement_id": sel.get("placement_id"),
        "placed": True,
    }


def _old_items(old: StateView) -> tuple[list[dict[str, Any]], set[str], list[dict[str, Any]]]:
    snap = old.snapshot
    containers = old.by_id("containers")
    variants = old.by_id("variants")
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    placed_containers: set[str] = set()
    for sel in snap.get("selections", []):
        record = _sentence_record(sel, containers, variants)
        if record is None:
            continue
        grouped[record["block_id"]].append(record)
        placed_containers.add(record["container_id"])
    blocks = old.by_id("blocks")
    items: list[dict[str, Any]] = []
    for block_id, sentences in grouped.items():
        sentences.sort(key=lambda row: int(row["placement_id"][2:]) if row["placement_id"] else 0)
        block = blocks.get(block_id)
        if block is None:
            continue
        items.append(
            {
                "block_id": block_id,
                "kind": block["kind"],
                "sentences": sentences,
                "sig": block["kind"] + "\x1f" + "\x1f".join(row["norm"] for row in sentences),
            }
        )
    items.sort(key=lambda item: min(int(row["placement_id"][2:]) for row in item["sentences"] if row["placement_id"]))
    for index, item in enumerate(items):
        item["order"] = index

    unplaced: list[dict[str, Any]] = []
    for container in old.containers:
        if container["id"] in placed_containers:
            continue
        candidates = [v for v in old.variants if v.get("container_id") == container["id"]]
        if not candidates:
            continue
        for variant in candidates:
            unplaced.append(
                {
                    "container_id": container["id"],
                    "variant_id": variant["id"],
                    "norm": variant.get("normalized_text", ""),
                    "raw": variant.get("raw_text", ""),
                    "block_id": container.get("parent_block_id"),
                    "placement_id": None,
                    "placed": False,
                }
            )
    return items, placed_containers, unplaced


def _new_items(blocks: list[Block], text: str, byte_offsets: list[int]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for block in blocks:
        if block.content is None:
            continue
        sentences = segment_block(block, text, byte_offsets)
        if not sentences:
            continue
        items.append(
            {
                "block": block,
                "block_index": block.order,
                "kind": block.kind,
                "order": block.order,
                "sentences": sentences,
                "sig": block.kind + "\x1f" + "\x1f".join(s.normalized_text for s in sentences),
            }
        )
    return items


def _pair_similar(old_group: list[int], new_group: list[int], old_items: list[dict], new_items: list[dict], threshold: float) -> dict[int, int]:
    candidates: list[tuple[float, int, int]] = []
    for oi in old_group:
        for ni in new_group:
            if old_items[oi]["kind"] != new_items[ni]["kind"]:
                continue
            ratio = difflib.SequenceMatcher(None, old_items[oi]["sig"], new_items[ni]["sig"], autojunk=False).ratio()
            if ratio >= threshold:
                candidates.append((ratio, oi, ni))
    candidates.sort(reverse=True)
    pairs: dict[int, int] = {}
    used_old: set[int] = set()
    for _, oi, ni in candidates:
        if oi in used_old or ni in pairs:
            continue
        pairs[ni] = oi
        used_old.add(oi)
    return pairs


def _match_blocks(old_items: list[dict], new_items: list[dict], threshold: float) -> dict[int, int]:
    pairs: dict[int, int] = {}
    used_old: set[int] = set()
    by_sig: dict[str, list[int]] = defaultdict(list)
    for oi, item in enumerate(old_items):
        by_sig[item["sig"]].append(oi)
    for ni, item in enumerate(new_items):
        candidates = [oi for oi in by_sig.get(item["sig"], []) if oi not in used_old]
        if not candidates:
            continue
        oi = min(candidates, key=lambda idx: abs(old_items[idx]["order"] - item["order"]))
        pairs[ni] = oi
        used_old.add(oi)

    old_rem = [oi for oi in range(len(old_items)) if oi not in used_old]
    new_rem = [ni for ni in range(len(new_items)) if ni not in pairs]
    if not old_rem or not new_rem:
        return pairs
    matcher = difflib.SequenceMatcher(
        None,
        [old_items[oi]["sig"] for oi in old_rem],
        [new_items[ni]["sig"] for ni in new_rem],
        autojunk=False,
    )
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                pairs[new_rem[j1 + k]] = old_rem[i1 + k]
        elif tag == "replace":
            pairs.update(
                _pair_similar(
                    old_rem[i1:i2],
                    new_rem[j1:j2],
                    old_items,
                    new_items,
                    threshold,
                )
            )
    return pairs


def _align_sentences(
    old_sents: list[dict[str, Any]],
    new_sents: list[Sentence],
    threshold: float,
) -> tuple[dict[int, int], list[tuple[int, list[int]]], list[tuple[list[int], int]]]:
    """Return new-index -> old-index pairs, split groups, merge groups."""
    pairs: dict[int, int] = {}
    splits: list[tuple[int, list[int]]] = []
    merges: list[tuple[list[int], int]] = []
    matcher = difflib.SequenceMatcher(
        None,
        [row["norm"] for row in old_sents],
        [s.normalized_text for s in new_sents],
        autojunk=False,
    )
    handled_old: set[int] = set()
    handled_new: set[int] = set()
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                pairs[j1 + k] = i1 + k
                handled_old.add(i1 + k)
                handled_new.add(j1 + k)
        elif tag == "replace":
            old_group = list(range(i1, i2))
            new_group = list(range(j1, j2))
            if len(old_group) == 1 and len(new_group) > 1:
                splits.append((old_group[0], new_group))
                handled_old.add(old_group[0])
                handled_new.update(new_group)
            elif len(old_group) > 1 and len(new_group) == 1:
                merges.append((old_group, new_group[0]))
                handled_old.update(old_group)
                handled_new.add(new_group[0])
            else:
                candidates: list[tuple[float, int, int]] = []
                for oi in old_group:
                    for ni in new_group:
                        ratio = difflib.SequenceMatcher(
                            None, old_sents[oi]["norm"], new_sents[ni].normalized_text, autojunk=False
                        ).ratio()
                        if ratio >= threshold:
                            candidates.append((ratio, oi, ni))
                candidates.sort(reverse=True)
                for _, oi, ni in candidates:
                    if oi in handled_old or ni in handled_new:
                        continue
                    pairs[ni] = oi
                    handled_old.add(oi)
                    handled_new.add(ni)
    # Exact moves inside the same block for leftovers.
    remaining_old = [i for i in range(len(old_sents)) if i not in handled_old]
    remaining_new = [i for i in range(len(new_sents)) if i not in handled_new]
    if remaining_old and remaining_new:
        by_norm: dict[str, list[int]] = defaultdict(list)
        for oi in remaining_old:
            by_norm[old_sents[oi]["norm"]].append(oi)
        for ni in remaining_new:
            candidates = [oi for oi in by_norm.get(new_sents[ni].normalized_text, []) if oi not in handled_old]
            if len(candidates) == 1:
                pairs[ni] = candidates[0]
                handled_old.add(candidates[0])
    return pairs, splits, merges


def _build_untracked(size: int, covered: list[tuple[int, int]], deferred: list[tuple[int, int, str]]) -> list[dict[str, Any]]:
    intervals: list[tuple[int, int, str]] = [(start, end, "selection") for start, end in covered]
    intervals.extend(deferred)
    intervals.sort(key=lambda item: (item[0], item[1]))
    out: list[dict[str, Any]] = []
    cursor = 0
    for start, end, label in intervals:
        if start > cursor:
            out.append({"start_byte": cursor, "end_byte": start, "reason": "between_selections"})
        if start < cursor:
            # Selections and deferred blocks must be disjoint; keep the wider
            # interval so validation can surface the problem.
            if label != "selection":
                out.append({"start_byte": start, "end_byte": end, "reason": label})
                cursor = max(cursor, end)
                continue
        cursor = max(cursor, end)
        if label != "selection":
            out.append({"start_byte": start, "end_byte": end, "reason": label})
    if cursor < size:
        out.append({"start_byte": cursor, "end_byte": size, "reason": "between_selections"})
    merged: list[dict[str, Any]] = []
    for row in out:
        if row["start_byte"] >= row["end_byte"]:
            continue
        if merged and merged[-1]["reason"] == row["reason"] and merged[-1]["end_byte"] == row["start_byte"]:
            merged[-1]["end_byte"] = row["end_byte"]
        else:
            merged.append(dict(row))
    return merged


def build_state(
    old: StateView | None,
    *,
    text: str,
    paper_bytes: bytes,
    blocks: list[Block],
    state_id: str,
    message: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    counter = Counter(old)
    events: list[dict[str, Any]] = []
    run_id = counter.take("run")
    snapshot_id = counter.take("snapshot")
    old_snapshot_id = old.snapshot_id if old else None
    document_id = old.document["id"] if old else counter.take("document")
    source_hash = sha256_bytes(paper_bytes)

    old_blocks = old.blocks if old else []
    old_containers = old.containers if old else []
    old_variants = old.variants if old else []
    old_events = old.events if old else []
    old_snapshots = old.snapshots if old else []
    old_claims = old.claims if old else []
    old_relations = old.relations if old else []
    old_references = old.references if old else []
    old_evidence = old.evidence if old else []
    old_assessments = old.assessments if old else []
    old_quantities = old.quantities if old else []
    old_checks = old.checks if old else []
    old_runs = old.runs if old else []

    blocks_by_id = {row["id"]: dict(row) for row in old_blocks}
    containers_by_id = {row["id"]: dict(row) for row in old_containers}
    variants_by_id = {row["id"]: dict(row) for row in old_variants}
    new_blocks: list[dict[str, Any]] = []
    new_containers: list[dict[str, Any]] = []
    new_variants: list[dict[str, Any]] = []

    def event(etype: str, before: list[str], after: list[str], reason: str = "") -> None:
        events.append(
            {
                "id": counter.take("event"),
                "schema_version": "1.0.0",
                "type": etype,
                "run_id": run_id,
                "state_id": state_id,
                "before": before,
                "after": after,
                "reason": reason,
                "actor": "system",
                "status": "confirmed",
                "occurred_at": now_iso(),
            }
        )

    old_items, placed_containers, unplaced_records = _old_items(old) if old else ([], set(), [])
    byte_offsets = char_byte_offsets(text)
    new_items = _new_items(blocks, text, byte_offsets)
    block_pairs = _match_blocks(old_items, new_items, 0.35)

    # Assign block identities.
    for ni, item in enumerate(new_items):
        oi = block_pairs.get(ni)
        if oi is not None:
            old_block = old_items[oi]
            block_id = old_block["block_id"]
            record = blocks_by_id.get(block_id)
            if record is not None:
                record["last_seen_state_id"] = state_id
                record["order"] = item["order"]
                record["kind"] = item["kind"]
                item["block_id"] = block_id
                continue
        block_id = counter.take("block")
        item["block_id"] = block_id
        record = {
            "id": block_id,
            "kind": item["kind"],
            "created_state_id": state_id,
            "last_seen_state_id": state_id,
            "order": item["order"],
        }
        blocks_by_id[block_id] = record
        new_blocks.append(record)
        event("BLOCK_CREATED", [], [block_id], f"new {item['kind']} block")

    old_sequence = [item["block_id"] for item in old_items]
    new_sequence = [item["block_id"] for item in new_items]
    moved_blocks: set[str] = set()
    if old_sequence and new_sequence:
        matcher = difflib.SequenceMatcher(None, old_sequence, new_sequence, autojunk=False)
        old_set = set(old_sequence)
        for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                continue
            for block_id in new_sequence[j1:j2]:
                if block_id in old_set and block_id not in moved_blocks:
                    moved_blocks.add(block_id)
                    event("BLOCK_MOVED", [], [block_id], "block moved in document order")

    plans: dict[int, list[dict[str, Any]]] = {ni: [] for ni in range(len(new_items))}
    split_groups: list[tuple[int, int, list[int]]] = []
    merge_groups: list[tuple[int, list[int], int]] = []
    used_containers: set[str] = set()
    pending: list[tuple[int, int]] = []

    for ni, item in enumerate(new_items):
        old_sents = old_items[block_pairs[ni]]["sentences"] if ni in block_pairs else []
        pairs, splits, merges = _align_sentences(old_sents, item["sentences"], 0.55)
        split_groups.extend((ni, old_idx, group) for old_idx, group in splits)
        merge_groups.extend((ni, old_group, new_idx) for old_group, new_idx in merges)
        split_new = {idx for _, group in splits for idx in group}
        merge_new = {idx for _, idx in merges}
        for si, sentence in enumerate(item["sentences"]):
            if si in pairs:
                old_sent = old_sents[pairs[si]]
                plans[ni].append(
                    {
                        "sentence": sentence,
                        "action": "reuse",
                        "container_id": old_sent["container_id"],
                        "variant_id": old_sent["variant_id"],
                        "old_variant_id": old_sent["variant_id"],
                        "old_norm": old_sent["norm"],
                        "moved": False,
                        "restored": False,
                    }
                )
                used_containers.add(old_sent["container_id"])
            elif si in split_new or si in merge_new:
                plans[ni].append({"sentence": sentence, "action": "new"})
            else:
                plans[ni].append({"sentence": sentence, "action": "pending"})
                pending.append((ni, si))

    # Global exact moves/restorations.
    candidates: list[dict[str, Any]] = []
    for item in old_items:
        for row in item["sentences"]:
            if row["container_id"] not in used_containers:
                candidates.append(dict(row))
    for row in unplaced_records:
        if row["container_id"] not in used_containers:
            candidates.append(dict(row))
    by_norm: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in candidates:
        by_norm[row["norm"]].append(row)

    for ni, si in pending:
        sentence = new_items[ni]["sentences"][si]
        matches = [row for row in by_norm.get(sentence.normalized_text, []) if row["container_id"] not in used_containers]
        unique_containers = {row["container_id"] for row in matches}
        if len(unique_containers) == 1:
            row = matches[0]
            plans[ni][si] = {
                "sentence": sentence,
                "action": "reuse",
                "container_id": row["container_id"],
                "variant_id": row["variant_id"],
                "old_variant_id": row["variant_id"],
                "old_norm": row["norm"],
                "moved": bool(row["placed"]),
                "restored": not row["placed"],
            }
            used_containers.add(row["container_id"])

    # Materialize plans.
    for ni, item in enumerate(new_items):
        block_id = item["block_id"]
        for plan in plans[ni]:
            sentence = plan["sentence"]
            if plan["action"] == "reuse":
                container_id = plan["container_id"]
                container = containers_by_id.get(container_id)
                if container is None:
                    plan["action"] = "new"
                else:
                    container["parent_block_id"] = block_id
                    container["last_seen_state_id"] = state_id
                    container["kind"] = item["kind"]
                    if variants_by_id[plan["variant_id"]]["raw_text"] == sentence.raw_text:
                        variant_id = plan["variant_id"]
                    else:
                        variant_id = counter.take("variant")
                        variant = {
                            "id": variant_id,
                            "container_id": container_id,
                            "first_seen_state_id": state_id,
                            "source_range": {
                                "start_byte": sentence.start_byte,
                                "end_byte": sentence.end_byte,
                                "end_exclusive": True,
                            },
                            "raw_text": sentence.raw_text,
                            "normalized_text": sentence.normalized_text,
                            "content_sha256": sha256_text(sentence.raw_text),
                        }
                        variants_by_id[variant_id] = variant
                        new_variants.append(variant)
                        event("VARIANT_CREATED", [plan["old_variant_id"]], [variant_id], "text changed")
                    plan["variant_id"] = variant_id
                    if plan["moved"]:
                        event("CONTAINER_MOVED", [], [container_id], f"moved to {block_id}")
                    if plan["restored"]:
                        event("RESTORED_IN_TEXT", [], [container_id], "previously removed text restored")
                    continue
            # New container/variant.
            container_id = counter.take("container")
            variant_id = counter.take("variant")
            container = {
                "id": container_id,
                "kind": item["kind"],
                "parent_block_id": block_id,
                "created_state_id": state_id,
                "last_seen_state_id": state_id,
            }
            variant = {
                "id": variant_id,
                "container_id": container_id,
                "first_seen_state_id": state_id,
                "source_range": {
                    "start_byte": sentence.start_byte,
                    "end_byte": sentence.end_byte,
                    "end_exclusive": True,
                },
                "raw_text": sentence.raw_text,
                "normalized_text": sentence.normalized_text,
                "content_sha256": sha256_text(sentence.raw_text),
            }
            containers_by_id[container_id] = container
            variants_by_id[variant_id] = variant
            new_containers.append(container)
            new_variants.append(variant)
            plan["container_id"] = container_id
            plan["variant_id"] = variant_id
            event("CONTAINER_CREATED", [], [container_id], f"new {item['kind']} container")
            event("VARIANT_CREATED", [], [variant_id], "new text")

            # Split/merge events are emitted after all new containers exist.

    # Split/merge events.
    for ni, old_index, group in split_groups:
        old_container = old_items[block_pairs[ni]]["sentences"][old_index]["container_id"]
        new_ids = [plans[ni][si].get("container_id") for si in group]
        new_ids = [cid for cid in new_ids if cid]
        if new_ids:
            event("TEXT_SPLIT", [old_container], new_ids, "one sentence split into several")
    for ni, old_group, new_index in merge_groups:
        old_ids = [
            old_items[block_pairs[ni]]["sentences"][oi]["container_id"] for oi in old_group
        ]
        new_id = plans[ni][new_index].get("container_id")
        if new_id:
            event("TEXT_MERGED", old_ids, [new_id], "several sentences merged into one")

    # Removals: placed containers that were not reused.
    for container_id in sorted(placed_containers - used_containers):
        event("REMOVED_FROM_TEXT", [container_id], [], "container no longer placed")

    # Placements.
    selections: list[dict[str, Any]] = []
    for ni, item in enumerate(new_items):
        for plan in plans[ni]:
            sentence = plan["sentence"]
            selections.append(
                {
                    "container_id": plan["container_id"],
                    "variant_id": plan["variant_id"],
                    "source_ranges": [{"start_byte": sentence.start_byte, "end_byte": sentence.end_byte}],
                }
            )
    selections.sort(key=lambda sel: (sel["source_ranges"][0]["start_byte"], sel["source_ranges"][0]["end_byte"]))
    for idx, sel in enumerate(selections, 1):
        sel["placement_id"] = counter.take("placement")
        sel["order"] = idx * 10

    covered = [(sel["source_ranges"][0]["start_byte"], sel["source_ranges"][0]["end_byte"]) for sel in selections]
    deferred = [
        (block.start_byte, block.end_byte, f"deferred:{block.kind}")
        for block in blocks
        if block.content is None
    ]
    untracked = _build_untracked(len(paper_bytes), covered, deferred)

    snapshot = {
        "id": snapshot_id,
        "state_id": state_id,
        "document_id": document_id,
        "source_hash": source_hash,
        "selections": selections,
        "untracked_blocks": untracked,
        "parser_version": PARSER_VERSION,
        "segmenter_version": SEGMENTER_VERSION,
    }
    event("SNAPSHOT_COMMITTED", [old_snapshot_id] if old_snapshot_id else [], [snapshot_id], message or "")

    document = dict(old.document) if old and old.document else {
        "id": document_id,
        "created_state_id": state_id,
    }
    run_record = {
        "id": run_id,
        "state_id": state_id,
        "snapshot_id": snapshot_id,
        "mode": "auto",
        "created_at": now_iso(),
        "message": message,
    }

    sources = empty_sources()
    sources.update(
        {
            "document": document,
            "blocks": list(blocks_by_id.values()),
            "containers": list(containers_by_id.values()),
            "variants": list(variants_by_id.values()),
            "snapshots": old_snapshots + [snapshot],
            "claims": old_claims,
            "relations": old_relations,
            "events": old_events + events,
            "references": old_references,
            "evidence": old_evidence,
            "assessments": old_assessments,
            "quantities": old_quantities,
            "checks": old_checks,
            "runs": old_runs + [run_record],
        }
    )
    summary = {
        "state_id": state_id,
        "run_id": run_id,
        "parent_state_id": old.state_id if old else None,
        "snapshot_id": snapshot_id,
        "paper_sha256": source_hash,
        "blocks_total": len(sources["blocks"]),
        "containers_total": len(sources["containers"]),
        "variants_total": len(sources["variants"]),
        "blocks_added": len(new_blocks),
        "containers_added": len(new_containers),
        "variants_added": len(new_variants),
        "removed": len(placed_containers - used_containers),
        "moved": sum(1 for row in events if row["type"] == "CONTAINER_MOVED"),
        "block_moves": len(moved_blocks),
        "restored": sum(1 for row in events if row["type"] == "RESTORED_IN_TEXT"),
        "splits": sum(1 for row in events if row["type"] == "TEXT_SPLIT"),
        "merges": sum(1 for row in events if row["type"] == "TEXT_MERGED"),
        "untracked_bytes": sum(row["end_byte"] - row["start_byte"] for row in untracked),
    }
    return sources, summary

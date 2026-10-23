from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from importlib.resources import files
from typing import Any

from jsonschema import Draft202012Validator

from . import PARSER_VERSION, SCHEMA_VERSION, SEGMENTER_VERSION
from .align import Counter
from .segment import normalize_text
from .state import StateView, coverage_issues, empty_sources
from .util import now_iso, sha256_bytes, sha256_text

PROPOSAL_SCHEMA_PATH = files("papercheck").joinpath("schemas/proposal.schema.json")


def _ranges(segment: dict[str, Any]) -> list[dict[str, int]]:
    out = []
    for rng in segment.get("source_ranges", []):
        start = rng.get("start_byte") if isinstance(rng, dict) else None
        end = rng.get("end_byte") if isinstance(rng, dict) else None
        if isinstance(start, bool) or isinstance(end, bool):
            continue
        if not isinstance(start, int) or not isinstance(end, int):
            continue
        out.append({"start_byte": start, "end_byte": end})
    return out


def raw_text_for_ranges(paper_bytes: bytes, ranges: list[dict[str, int]]) -> str:
    parts = [paper_bytes[r["start_byte"]:r["end_byte"]].decode("utf-8") for r in ranges]
    return "\n".join(parts)


def _segment_text(segment: dict[str, Any], paper_bytes: bytes) -> tuple[str, str]:
    """Variant text is always derived from the frozen source bytes."""
    ranges = _ranges(segment)
    raw = raw_text_for_ranges(paper_bytes, ranges)
    return raw, normalize_text(raw)


def validate_proposal(old: StateView | None, paper_bytes: bytes, proposal: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    if not isinstance(proposal, dict):
        return ["proposal must be a JSON object"]
    try:
        schema = json.loads(PROPOSAL_SCHEMA_PATH.read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema)
        errors = sorted(validator.iter_errors(proposal), key=lambda err: str(list(err.path)))
        for error in errors:
            path = ".".join(str(part) for part in error.path) or "<root>"
            issues.append(f"schema {path}: {error.message}")
    except Exception as exc:  # noqa: BLE001 - expose schema loading failures
        issues.append(f"cannot load proposal schema: {exc}")
    if issues:
        return issues
    if proposal.get("schema_version") not in ("1.0.0", SCHEMA_VERSION):
        issues.append(f"unsupported proposal schema_version {proposal.get('schema_version')}")
    if proposal.get("paper_sha256") != sha256_bytes(paper_bytes):
        issues.append("paper_sha256 does not match current paper.md")
    if old is not None:
        if proposal.get("base_state_id") != old.state_id:
            issues.append(f"base_state_id must be {old.state_id}")
        if proposal.get("base_sha256") != old.manifest.get("input", {}).get("sha256"):
            issues.append("base_sha256 does not match current state")
    else:
        if proposal.get("base_state_id") not in (None, ""):
            issues.append("base_state_id must be null for the first state")

    segments = proposal.get("segments")
    untracked = proposal.get("untracked", [])
    if not isinstance(segments, list):
        issues.append("segments must be a list")
        segments = []
    if not isinstance(untracked, list):
        issues.append("untracked must be a list")
        untracked = []

    containers = old.by_id("containers") if old else {}
    variants = old.by_id("variants") if old else {}
    blocks = old.by_id("blocks") if old else {}
    used_containers: set[str] = set()
    block_refs: dict[str, str] = {}

    split_groups: dict[str, list[str]] = {}
    split_counts: dict[str, int] = {}
    implicit_splits: dict[str, list[str]] = {}
    for index, segment in enumerate(segments):
        label = f"segment[{index}]"
        if not isinstance(segment, dict):
            issues.append(f"{label}: must be an object")
            continue
        ranges = segment.get("source_ranges")
        if not isinstance(ranges, list) or not ranges:
            issues.append(f"{label}: source_ranges must be a non-empty list")
            continue
        ranges_ok = True
        for rng in ranges:
            if not isinstance(rng, dict):
                issues.append(f"{label}: source range must be an object")
                ranges_ok = False
                continue
            start, end = rng.get("start_byte"), rng.get("end_byte")
            if (
                isinstance(start, bool)
                or isinstance(end, bool)
                or not isinstance(start, int)
                or not isinstance(end, int)
            ):
                issues.append(f"{label}: source range offsets must be integers")
                ranges_ok = False
                continue
            if start < 0 or end > len(paper_bytes) or start >= end:
                issues.append(f"{label}: range {start}-{end} out of bounds")
                ranges_ok = False
        source_norm = None
        if ranges_ok:
            try:
                _, source_norm = _segment_text(segment, paper_bytes)
            except UnicodeDecodeError:
                issues.append(f"{label}: range splits a UTF-8 character")
                continue
            text = segment.get("text")
            if isinstance(text, str) and text.strip() and normalize_text(text) != source_norm:
                issues.append(f"{label}: text does not match the frozen source bytes")
        cid = segment.get("container_id")
        vid = segment.get("variant_id")
        kind = segment.get("kind")
        if vid and not cid:
            issues.append(f"{label}: variant_id requires container_id")
        if cid:
            if cid not in containers:
                issues.append(f"{label}: container {cid} does not exist in base state")
            if cid in used_containers:
                issues.append(f"{label}: container {cid} is placed more than once")
            used_containers.add(cid)
            if vid:
                if vid not in variants:
                    issues.append(f"{label}: variant {vid} does not exist")
                elif variants[vid].get("container_id") != cid:
                    issues.append(f"{label}: variant {vid} does not belong to {cid}")
                elif source_norm is not None and source_norm != variants[vid].get("normalized_text"):
                    issues.append(f"{label}: variant {vid} does not match the frozen source bytes")
                elif raw_text_for_ranges(paper_bytes, _ranges(segment)) != variants[vid].get("raw_text"):
                    issues.append(f"{label}: variant raw text changed; omit variant_id")
        bid = segment.get("block_id")
        bref = segment.get("block_ref")
        if bid and bref:
            issues.append(f"{label}: use block_id or block_ref, not both")
        if bid:
            if old is None or bid not in blocks:
                issues.append(f"{label}: block {bid} does not exist in base state")
        if bref:
            if not isinstance(bref, str) or not bref:
                issues.append(f"{label}: block_ref must be a non-empty string")
            else:
                block_refs.setdefault(bref, kind or "paragraph")
        lineage = segment.get("lineage")
        if lineage is not None:
            if not isinstance(lineage, dict) or lineage.get("type") not in ("split", "merge"):
                issues.append(f"{label}: lineage.type must be split or merge")
            else:
                sources = lineage.get("from")
                if not isinstance(sources, list) or not sources:
                    issues.append(f"{label}: lineage.from must be a non-empty list")
                else:
                    for source in sources:
                        if source not in containers:
                            issues.append(f"{label}: lineage source {source} does not exist")
                    if lineage.get("type") == "split":
                        if len(sources) != 1:
                            issues.append(f"{label}: split requires exactly one source container")
                        group = lineage.get("group")
                        if group is not None:
                            if not isinstance(group, str) or not group:
                                issues.append(f"{label}: lineage.group must be a non-empty string")
                            else:
                                previous = split_groups.get(group)
                                if previous is not None and previous != sources:
                                    issues.append(f"{label}: split group {group} has inconsistent from")
                                else:
                                    split_groups[group] = sources
                                split_counts[group] = split_counts.get(group, 0) + 1
                        else:
                            block_key = bid or bref
                            if not block_key:
                                issues.append(f"{label}: implicit split requires block_id/block_ref; otherwise use an explicit group on every target")
                            elif block_key in implicit_splits and implicit_splits[block_key] != sources:
                                issues.append(f"{label}: multiple splits in one block require explicit lineage.group values")
                            else:
                                implicit_splits[block_key] = sources
                    elif len(set(sources)) < 2:
                        issues.append(f"{label}: merge requires at least two distinct source containers")

    for group, count in split_counts.items():
        if count < 2:
            issues.append(f"split group {group} requires at least two explicitly declared targets")

    pseudo = [
        {"placement_id": f"seg{idx}", "source_ranges": _ranges(segment)}
        for idx, segment in enumerate(segments)
        if isinstance(segment, dict) and segment.get("source_ranges")
    ]
    issues.extend(coverage_issues(len(paper_bytes), pseudo, untracked))
    if not issues:
        from .semantic import SemanticError, enrich

        try:
            sources, summary = build_from_proposal(old, text=paper_bytes.decode("utf-8"),
                paper_bytes=paper_bytes, proposal=proposal, state_id="D000000")
            enrich(old, sources, proposal, summary)
        except (SemanticError, UnicodeDecodeError) as exc:
            issues.append(str(exc))
    return issues


def build_from_proposal(
    old: StateView | None,
    *,
    text: str,
    paper_bytes: bytes,
    proposal: dict[str, Any],
    state_id: str,
    message: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    counter = Counter(old)
    events: list[dict[str, Any]] = []
    run_id = counter.take("run")
    snapshot_id = counter.take("snapshot")
    old_snapshot_id = old.snapshot_id if old else None
    document_id = old.document["id"] if old else counter.take("document")

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

    old_placements: dict[str, dict[str, Any]] = {}
    old_placed_containers: set[str] = set()
    old_block_order: list[str] = []
    if old is not None:
        old_containers_map = old.by_id("containers")
        for sel in old.snapshot.get("selections", []):
            cid = sel.get("container_id")
            if cid:
                old_placed_containers.add(cid)
                old_placements[cid] = sel
                parent = old_containers_map.get(cid, {}).get("parent_block_id")
                if parent and parent not in old_block_order:
                    old_block_order.append(parent)

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
                "actor": "agent",
                "status": "confirmed",
                "occurred_at": now_iso(),
            }
        )

    block_ref_map: dict[str, str] = {}
    used_containers: set[str] = set()
    placements: list[dict[str, Any]] = []
    new_block_order: list[str] = []
    split_groups: dict[str, dict[str, Any]] = {}
    merge_events: list[tuple[list[str], str]] = []
    new_containers_by_block: dict[str, list[str]] = defaultdict(list)
    explicit_split_targets: set[str] = set()

    for index, segment in enumerate(proposal.get("segments", [])):
        ranges = _ranges(segment)
        cid = segment.get("container_id")
        kind = segment.get("kind") or (
            containers_by_id[cid]["kind"] if cid and cid in containers_by_id else "paragraph"
        )
        bid = segment.get("block_id")
        bref = segment.get("block_ref")
        if bid:
            block = blocks_by_id[bid]
        elif bref:
            if bref not in block_ref_map:
                block_id = counter.take("block")
                block = {
                    "id": block_id,
                    "kind": kind,
                    "created_state_id": state_id,
                    "last_seen_state_id": state_id,
                    "order": index,
                }
                blocks_by_id[block_id] = block
                new_blocks.append(block)
                block_ref_map[bref] = block_id
                event("BLOCK_CREATED", [], [block_id], f"new {kind} block")
            block = blocks_by_id[block_ref_map[bref]]
        else:
            block_id = counter.take("block")
            block = {
                "id": block_id,
                "kind": kind,
                "created_state_id": state_id,
                "last_seen_state_id": state_id,
                "order": index,
            }
            blocks_by_id[block_id] = block
            new_blocks.append(block)
            event("BLOCK_CREATED", [], [block_id], f"new {kind} block")
        block["last_seen_state_id"] = state_id
        block["order"] = index

        existing_container = bool(cid)
        old_variant_id = None
        if cid:
            container = containers_by_id[cid]
            used_containers.add(cid)
            container["parent_block_id"] = block["id"]
            container["last_seen_state_id"] = state_id
            container["kind"] = kind
            if segment.get("variant_id"):
                old_variant_id = segment["variant_id"]
            else:
                existing = [v for v in old_variants if v.get("container_id") == cid]
                if existing:
                    old_variant_id = max(existing, key=lambda row: row["id"])["id"]
        else:
            cid = counter.take("container")
            container = {
                "id": cid,
                "kind": kind,
                "parent_block_id": block["id"],
                "created_state_id": state_id,
                "last_seen_state_id": state_id,
            }
            containers_by_id[cid] = container
            new_containers.append(container)
            new_containers_by_block[block["id"]].append(cid)
            event("CONTAINER_CREATED", [], [cid], f"new {kind} container")

        vid = segment.get("variant_id")
        raw, normalized = _segment_text(segment, paper_bytes)
        if vid:
            variant = variants_by_id[vid]
        else:
            vid = counter.take("variant")
            variant = {
                "id": vid,
                "container_id": cid,
                "first_seen_state_id": state_id,
                "source_range": {
                    "start_byte": ranges[0]["start_byte"],
                    "end_byte": ranges[0]["end_byte"],
                    "end_exclusive": True,
                },
                "source_ranges": ranges,
                "raw_text": raw,
                "normalized_text": normalized,
                "content_sha256": sha256_text(raw),
            }
            variants_by_id[vid] = variant
            new_variants.append(variant)
            event("VARIANT_CREATED", [old_variant_id] if old_variant_id else [], [vid], segment.get("reason", "text changed"))

        old_sel = old_placements.get(cid)
        old_block = None
        if old_sel and old is not None:
            old_container = next((row for row in old.containers if row["id"] == cid), None)
            old_block = old_container.get("parent_block_id") if old_container else None
        if existing_container:
            if old_sel is None:
                event("RESTORED_IN_TEXT", [], [cid], "container restored to text")
            elif old_block and old_block != block["id"]:
                event("CONTAINER_MOVED", [], [cid], f"moved to {block['id']}")

        lineage = segment.get("lineage")
        if lineage and lineage.get("type") == "split":
            explicit_group = lineage.get("group")
            group = explicit_group or f"__block_{block['id']}"
            entry = split_groups.setdefault(
                group,
                {"from": lineage.get("from", []), "targets": [], "implicit_block": None if explicit_group else block["id"]},
            )
            entry["targets"].append(cid)
            if explicit_group:
                explicit_split_targets.add(cid)
        elif lineage and lineage.get("type") == "merge":
            merge_events.append((cid, lineage.get("from", [])))

        placements.append({"container_id": cid, "variant_id": vid, "source_ranges": ranges})
        if block["id"] not in new_block_order:
            new_block_order.append(block["id"])

    for entry in split_groups.values():
        implicit_block = entry.get("implicit_block")
        if implicit_block:
            for cid in new_containers_by_block.get(implicit_block, []):
                if cid not in entry["targets"] and cid not in explicit_split_targets:
                    entry["targets"].append(cid)
        event("TEXT_SPLIT", entry["from"], entry["targets"], "agent-declared split")
    for new_container, old_containers in merge_events:
        event("TEXT_MERGED", old_containers, [new_container], "agent-declared merge")

    for cid in sorted(old_placed_containers - used_containers):
        event("REMOVED_FROM_TEXT", [cid], [], "container no longer placed")

    # Block moves: blocks present in both sequences but outside the LCS.
    if old_block_order and new_block_order:
        import difflib

        matcher = difflib.SequenceMatcher(None, old_block_order, new_block_order, autojunk=False)
        old_set = set(old_block_order)
        moved_blocks: set[str] = set()
        for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                continue
            for block_id in new_block_order[j1:j2]:
                if block_id in old_set and block_id not in moved_blocks:
                    moved_blocks.add(block_id)
                    event("BLOCK_MOVED", [], [block_id], "block moved in document order")
    else:
        moved_blocks = set()

    placements.sort(key=lambda row: (row["source_ranges"][0]["start_byte"], row["source_ranges"][0]["end_byte"]))
    for idx, sel in enumerate(placements, 1):
        sel["placement_id"] = counter.take("placement")
        sel["order"] = idx * 10

    # The proposal is the complete snapshot description. Validation already
    # proved coverage, so the committer must not invent extra gap records.
    filled = []
    for row in proposal.get("untracked", []):
        start, end = row.get("start_byte"), row.get("end_byte")
        if (
            isinstance(start, bool)
            or isinstance(end, bool)
            or not isinstance(start, int)
            or not isinstance(end, int)
        ):
            continue
        filled.append(
            {
                "start_byte": start,
                "end_byte": end,
                "reason": str(row.get("reason", "agent_untracked")),
            }
        )
    filled.sort(key=lambda row: row["start_byte"])

    snapshot = {
        "id": snapshot_id,
        "state_id": state_id,
        "document_id": document_id,
        "source_hash": sha256_bytes(paper_bytes),
        "selections": placements,
        "untracked_blocks": filled,
        "parser_version": PARSER_VERSION,
        "segmenter_version": SEGMENTER_VERSION,
    }
    event("SNAPSHOT_COMMITTED", [old_snapshot_id] if old_snapshot_id else [], [snapshot_id], message or "")

    document = dict(old.document) if old and old.document else {"id": document_id, "created_state_id": state_id}
    run_record = {
        "id": run_id,
        "state_id": state_id,
        "snapshot_id": snapshot_id,
        "mode": "proposal",
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
        "paper_sha256": sha256_bytes(paper_bytes),
        "blocks_total": len(sources["blocks"]),
        "containers_total": len(sources["containers"]),
        "variants_total": len(sources["variants"]),
        "blocks_added": len(new_blocks),
        "containers_added": len(new_containers),
        "variants_added": len(new_variants),
        "removed": len(old_placed_containers - used_containers),
        "moved": sum(1 for row in events if row["type"] == "CONTAINER_MOVED"),
        "block_moves": len(moved_blocks) if old_block_order and new_block_order else 0,
        "restored": sum(1 for row in events if row["type"] == "RESTORED_IN_TEXT"),
        "splits": sum(1 for row in events if row["type"] == "TEXT_SPLIT"),
        "merges": sum(1 for row in events if row["type"] == "TEXT_MERGED"),
        "untracked_bytes": sum(row["end_byte"] - row["start_byte"] for row in filled),
        "mode": "proposal",
    }
    return sources, summary


def build_context(old: StateView | None, paper_text: str, paper_bytes: bytes) -> dict[str, Any]:
    import difflib

    lines = []
    cursor = 0
    for idx, line in enumerate(paper_text.splitlines(keepends=True), 1):
        end = cursor + len(line.encode("utf-8"))
        lines.append(
            {
                "line": idx,
                "start_byte": cursor,
                "end_byte": end,
                "text": line,
            }
        )
        cursor = end

    selections = []
    if old is not None:
        variants = old.by_id("variants")
        containers = old.by_id("containers")
        for sel in old.snapshot.get("selections", []):
            variant = variants.get(sel.get("variant_id"), {})
            container = containers.get(sel.get("container_id"), {})
            selections.append(
                {
                    "placement_id": sel.get("placement_id"),
                    "container_id": sel.get("container_id"),
                    "variant_id": sel.get("variant_id"),
                    "block_id": container.get("parent_block_id"),
                    "kind": container.get("kind"),
                    "source_ranges": sel.get("source_ranges", []),
                    "raw_text": variant.get("raw_text"),
                    "normalized_text": variant.get("normalized_text"),
                }
            )

    diff = []
    if old is not None:
        old_lines = old.paper_text.splitlines(keepends=True)
        new_lines = paper_text.splitlines(keepends=True)
        matcher = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                continue
            diff.append(
                {
                    "tag": tag,
                    "old_lines": [i1 + 1, i2],
                    "new_lines": [j1 + 1, j2],
                    "old_text": "".join(old_lines[i1:i2]),
                    "new_text": "".join(new_lines[j1:j2]),
                }
            )

    return {
        "base_state_id": old.state_id if old else None,
        "base_sha256": old.manifest.get("input", {}).get("sha256") if old else None,
        "base_snapshot_id": old.snapshot_id if old else None,
        "paper_sha256": sha256_bytes(paper_bytes),
        "paper_size": len(paper_bytes),
        "line_count": len(lines),
        "lines": lines,
        "old_selections": selections,
        "old_untracked": old.snapshot.get("untracked_blocks", []) if old else [],
        "semantic_records": {key: getattr(old, key) if old else [] for key in (
            "claims", "bindings", "revisions", "relations", "references", "evidence", "assessments",
            "quantities", "checks", "arguments", "invalidations")},
        "historical_variants": old.variants if old else [],
        "diff": diff,
        "workflow": {
            **(old.snapshot.get("workflow", {}) if old else {"status": "pending", "tasks": []}),
            "schema_version": SCHEMA_VERSION,
            "proposal_required": True,
            "note": "Agent decides segmentation and reuse; committer only validates and persists.",
        },
    }

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from functools import lru_cache
from importlib.resources import files
import json

from jsonschema import Draft202012Validator

from . import CANONICALIZER_VERSION, PARSER_VERSION, SCHEMA_VERSION, SEGMENTER_VERSION
from .segment import normalize_text
from .util import (
    canonical_json,
    now_iso,
    read_bytes,
    read_json,
    read_jsonl,
    sha256_bytes,
    sha256_file,
    sha256_text,
    write_json,
    write_jsonl,
    atomic_write_bytes,
)


def _valid_range(rng: Any) -> tuple[int, int] | None:
    if not isinstance(rng, dict):
        return None
    start, end = rng.get("start_byte"), rng.get("end_byte")
    if isinstance(start, bool) or isinstance(end, bool):
        return None
    if not isinstance(start, int) or not isinstance(end, int):
        return None
    return start, end


def source_text_for_ranges(paper_bytes: bytes, ranges: list[dict[str, Any]]) -> str | None:
    parts = []
    for rng in ranges:
        pair = _valid_range(rng)
        if pair is None:
            return None
        start, end = pair
        if start < 0 or end > len(paper_bytes) or start >= end:
            return None
        try:
            parts.append(paper_bytes[start:end].decode("utf-8"))
        except UnicodeDecodeError:
            return None
    return "\n".join(parts)

JSONL_KEYS = [
    "blocks",
    "containers",
    "variants",
    "snapshots",
    "claims",
    "relations",
    "events",
    "references",
    "evidence",
    "assessments",
    "quantities",
    "checks",
    "runs",
    "revisions",
    "bindings",
    "arguments",
    "reviews",
    "invalidations",
]

SOURCE_FILES: dict[str, str] = {
    "paper": "sources/paper.md",
    "document": "sources/document.json",
    **{key: f"sources/{key}.jsonl" for key in JSONL_KEYS},
}

MANIFEST = "manifest.json"


@dataclass
class StateView:
    state_id: str
    path: Path
    manifest: dict[str, Any]
    paper_bytes: bytes
    paper_text: str
    document: dict[str, Any]
    blocks: list[dict[str, Any]] = field(default_factory=list)
    containers: list[dict[str, Any]] = field(default_factory=list)
    variants: list[dict[str, Any]] = field(default_factory=list)
    snapshots: list[dict[str, Any]] = field(default_factory=list)
    claims: list[dict[str, Any]] = field(default_factory=list)
    relations: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    references: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    assessments: list[dict[str, Any]] = field(default_factory=list)
    quantities: list[dict[str, Any]] = field(default_factory=list)
    checks: list[dict[str, Any]] = field(default_factory=list)
    runs: list[dict[str, Any]] = field(default_factory=list)
    revisions: list[dict[str, Any]] = field(default_factory=list)
    bindings: list[dict[str, Any]] = field(default_factory=list)
    arguments: list[dict[str, Any]] = field(default_factory=list)
    reviews: list[dict[str, Any]] = field(default_factory=list)
    invalidations: list[dict[str, Any]] = field(default_factory=list)

    @property
    def snapshot_id(self) -> str:
        return self.manifest["snapshot_id"]

    @property
    def snapshot(self) -> dict[str, Any]:
        for snap in self.snapshots:
            if snap["id"] == self.snapshot_id:
                return snap
        raise KeyError(f"snapshot {self.snapshot_id} not found in {self.state_id}")

    def by_id(self, key: str) -> dict[str, dict[str, Any]]:
        return {row["id"]: row for row in getattr(self, key)}


def empty_sources() -> dict[str, Any]:
    return {**{key: [] for key in JSONL_KEYS}, **{
        "document": {},
        "blocks": [],
        "containers": [],
        "variants": [],
        "snapshots": [],
        "claims": [],
        "relations": [],
        "events": [],
        "references": [],
        "evidence": [],
        "assessments": [],
        "quantities": [],
        "checks": [],
        "runs": [],
    }}


def load_state(path: Path) -> StateView:
    manifest = read_json(path / MANIFEST)
    if manifest is None:
        raise FileNotFoundError(f"{path}/{MANIFEST}")
    paper_bytes = read_bytes(path / "sources" / "paper.md")
    paper_text = paper_bytes.decode("utf-8")
    document = read_json(path / "sources" / "document.json", {}) or {}
    rows: dict[str, list[dict[str, Any]]] = {}
    for key in JSONL_KEYS:
        rows[key] = read_jsonl(path / "sources" / f"{key}.jsonl")
    return StateView(
        state_id=manifest.get("state_id", path.name),
        path=path,
        manifest=manifest,
        paper_bytes=paper_bytes,
        paper_text=paper_text,
        document=document,
        **rows,
    )


def build_manifest(
    *,
    state_id: str,
    parent_state_id: str | None,
    paper_bytes: bytes,
    snapshot_id: str,
    path: Path,
    message: str | None = None,
    semantic_status: str = "pending",
) -> dict[str, Any]:
    file_hashes: dict[str, str] = {}
    for relative in SOURCE_FILES.values():
        file_hashes[relative] = sha256_file(path / relative)
    return {
        "schema_version": SCHEMA_VERSION,
        "state_id": state_id,
        "parent_state_id": parent_state_id,
        "created_at": now_iso(),
        "input": {
            "path": "paper.md",
            "sha256": sha256_bytes(paper_bytes),
            "size_bytes": len(paper_bytes),
        },
        "parser_version": PARSER_VERSION,
        "segmenter_version": SEGMENTER_VERSION,
        "canonicalizer_version": CANONICALIZER_VERSION,
        "snapshot_id": snapshot_id,
        "source_files": dict(SOURCE_FILES),
        "file_hashes": file_hashes,
        "validation": {
            "structurally_valid": True,
            "semantic_status": semantic_status,
        },
        "message": message,
    }


def write_state_dir(
    path: Path,
    *,
    state_id: str,
    parent_state_id: str | None,
    paper_bytes: bytes,
    sources: dict[str, Any],
    snapshot_id: str,
    message: str | None = None,
) -> dict[str, Any]:
    sources_dir = path / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(sources_dir / "paper.md", paper_bytes)
    write_json(sources_dir / "document.json", sources["document"])
    for key in JSONL_KEYS:
        write_jsonl(sources_dir / f"{key}.jsonl", sources.get(key, []))
    manifest = build_manifest(
        state_id=state_id,
        parent_state_id=parent_state_id,
        paper_bytes=paper_bytes,
        snapshot_id=snapshot_id,
        path=path,
        message=message,
    )
    write_json(path / MANIFEST, manifest)
    return manifest


def _ids(rows: list[dict[str, Any]]) -> list[str]:
    return [row.get("id", "") for row in rows]


def _check_unique(rows: list[dict[str, Any]], label: str, issues: list[str]) -> None:
    seen: set[str] = set()
    for row in rows:
        rid = row.get("id")
        if not rid:
            issues.append(f"{label}: missing id")
        elif rid in seen:
            issues.append(f"{label}: duplicate id {rid}")
        else:
            seen.add(rid)


def coverage_issues(
    size: int,
    selections: list[dict[str, Any]],
    untracked: list[dict[str, Any]],
) -> list[str]:
    issues: list[str] = []
    intervals: list[tuple[int, int, str]] = []
    for sel in selections:
        for rng in sel.get("source_ranges", []):
            pair = _valid_range(rng)
            if pair is None:
                issues.append(f"selection {sel.get('placement_id')}: bad range")
                continue
            start, end = pair
            if start < 0 or end > size or start >= end:
                issues.append(f"selection {sel.get('placement_id')}: range {start}-{end} out of bounds")
            intervals.append((start, end, f"selection:{sel.get('placement_id')}"))
    for block in untracked:
        pair = _valid_range(block)
        if pair is None:
            issues.append("untracked: bad range")
            continue
        start, end = pair
        if start < 0 or end > size or start >= end:
            issues.append(f"untracked: range {start}-{end} out of bounds")
        intervals.append((start, end, f"untracked:{block.get('reason')}"))
    intervals.sort(key=lambda item: (item[0], item[1]))
    cursor = 0
    for start, end, label in intervals:
        if start < cursor:
            issues.append(f"overlap at byte {start} ({label})")
        elif start > cursor:
            issues.append(f"gap {cursor}-{start} before {label}")
        cursor = max(cursor, end)
    if cursor != size:
        issues.append(f"coverage ends at {cursor}, expected {size}")
    return issues


def validate_state(path: Path) -> list[str]:
    try:
        return _validate_state(path)
    except (KeyError, TypeError, ValueError, OSError, AttributeError) as exc:
        return [f"invalid state structure: {exc}"]


def _validate_state(path: Path) -> list[str]:
    issues: list[str] = []
    try:
        state = load_state(path)
    except Exception as exc:  # noqa: BLE001 - report as validation issue
        return [f"cannot load state: {exc}"]
    if state.manifest.get("schema_version") == SCHEMA_VERSION:
        for key in ["document", *JSONL_KEYS]:
            records = [state.document] if key == "document" else getattr(state, key)
            validator = _record_validator(key)
            for row in records:
                for error in validator.iter_errors(row):
                    issues.append(f"schema {key}: {error.message}")
        if issues:
            return issues

    required_manifest = {
        "schema_version",
        "state_id",
        "parent_state_id",
        "created_at",
        "input",
        "parser_version",
        "segmenter_version",
        "canonicalizer_version",
        "snapshot_id",
        "source_files",
        "file_hashes",
        "validation",
    }
    for key in sorted(required_manifest - set(state.manifest)):
        issues.append(f"manifest missing key {key}")
    if state.manifest.get("state_id") != path.name:
        issues.append(f"manifest state_id {state.manifest.get('state_id')} != directory {path.name}")

    version = state.manifest.get("schema_version")
    if version not in ("1.0.0", SCHEMA_VERSION):
        issues.append(f"unsupported state schema_version {version}")
    legacy_keys = {"revisions", "bindings", "arguments", "reviews", "invalidations"}
    required_files = {value for key, value in SOURCE_FILES.items() if version != "1.0.0" or key not in legacy_keys}
    declared_sources = set(state.manifest.get("source_files", {}).values())
    declared_hashes = set(state.manifest.get("file_hashes", {}).keys())
    missing_sources = required_files - declared_sources
    extra_sources = declared_sources - required_files
    missing_hashes = required_files - declared_hashes
    extra_hashes = declared_hashes - required_files
    for relative in sorted(missing_sources):
        issues.append(f"manifest source_files missing {relative}")
    for relative in sorted(extra_sources):
        issues.append(f"manifest source_files has unknown {relative}")
    for relative in sorted(missing_hashes):
        issues.append(f"manifest file_hashes missing {relative}")
    for relative in sorted(extra_hashes):
        issues.append(f"manifest file_hashes has unknown {relative}")
    for relative in sorted(required_files):
        target = path / relative
        if not target.exists():
            issues.append(f"missing source file {relative}")
            continue
        expected = state.manifest.get("file_hashes", {}).get(relative)
        if not expected:
            continue
        actual = sha256_file(target)
        if actual != expected:
            issues.append(f"hash mismatch {relative}")

    size = len(state.paper_bytes)
    if state.manifest.get("input", {}).get("sha256") != sha256_bytes(state.paper_bytes):
        issues.append("paper hash does not match manifest input")
    if state.manifest.get("input", {}).get("size_bytes") != size:
        issues.append("paper size does not match manifest input")

    for key in JSONL_KEYS:
        _check_unique(getattr(state, key), key, issues)

    blocks = state.by_id("blocks")
    containers = state.by_id("containers")
    variants = state.by_id("variants")
    snapshots = state.by_id("snapshots")

    for block in state.blocks:
        if not block.get("kind"):
            issues.append(f"block {block.get('id')}: missing kind")
    for container in state.containers:
        parent = container.get("parent_block_id")
        if parent and parent not in blocks:
            issues.append(f"container {container.get('id')}: missing parent block {parent}")
    meta_root = path.parent.parent
    states_dir = meta_root / "states"
    for variant in state.variants:
        if variant.get("container_id") not in containers:
            issues.append(f"variant {variant.get('id')}: missing container {variant.get('container_id')}")
        raw = variant.get("raw_text", "")
        if variant.get("content_sha256") != sha256_text(raw):
            issues.append(f"variant {variant.get('id')}: content hash mismatch")
        first = variant.get("source_range") or {}
        pair = _valid_range(first)
        if pair is None:
            issues.append(f"variant {variant.get('id')}: missing or invalid first source range")
            continue
        start, end = pair
        first_state = variant.get("first_seen_state_id")
        if not first_state:
            issues.append(f"variant {variant.get('id')}: missing first_seen_state_id")
            continue
        if first_state == state.state_id:
            first_size = size
        else:
            historical = states_dir / first_state / "sources" / "paper.md"
            if not historical.exists():
                issues.append(f"variant {variant.get('id')}: first_seen state {first_state} missing")
                continue
            first_size = historical.stat().st_size
        if start < 0 or end > first_size or start >= end:
            issues.append(f"variant {variant.get('id')}: first source range outside {first_state}")

    if state.snapshot_id not in snapshots:
        issues.append(f"manifest snapshot_id {state.snapshot_id} not found")
    for snap in state.snapshots:
        if snap.get("document_id") != state.document.get("id"):
            issues.append(f"snapshot {snap.get('id')}: document_id mismatch")
        placements: set[str] = set()
        placed_containers: set[str] = set()
        for sel in snap.get("selections", []):
            pid = sel.get("placement_id")
            if not pid or pid in placements:
                issues.append(f"snapshot {snap.get('id')}: duplicate/empty placement id")
            placements.add(pid or "")
            cid = sel.get("container_id")
            if cid in placed_containers:
                issues.append(f"snapshot {snap.get('id')}: container {cid} placed more than once")
            placed_containers.add(cid)
            vid = sel.get("variant_id")
            if cid not in containers:
                issues.append(f"snapshot {snap.get('id')}: missing container {cid}")
            if vid not in variants:
                issues.append(f"snapshot {snap.get('id')}: missing variant {vid}")
            elif variants[vid].get("container_id") != cid:
                issues.append(f"snapshot {snap.get('id')}: variant {vid} does not belong to {cid}")
        if snap.get("id") == state.snapshot_id:
            if snap.get("state_id") != state.state_id:
                issues.append(f"snapshot {snap.get('id')}: state_id mismatch")
            if snap.get("source_hash") != state.manifest.get("input", {}).get("sha256"):
                issues.append(f"snapshot {snap.get('id')}: source hash mismatch")
            for sel in snap.get("selections", []):
                variant = variants.get(sel.get("variant_id"))
                if variant is None:
                    continue
                source_text = source_text_for_ranges(state.paper_bytes, sel.get("source_ranges", []))
                if source_text is None:
                    issues.append(f"selection {sel.get('placement_id')}: invalid source ranges")
                    continue
                if source_text != variant.get("raw_text"):
                    issues.append(f"selection {sel.get('placement_id')}: raw text does not match frozen paper")
                elif normalize_text(source_text) != variant.get("normalized_text"):
                    issues.append(
                        f"selection {sel.get('placement_id')}: normalized text does not match frozen paper"
                    )
            issues.extend(coverage_issues(size, snap.get("selections", []), snap.get("untracked_blocks", [])))

    if not state.document.get("id"):
        issues.append("document id missing")
    from .semantic import state_issues

    try:
        issues.extend(state_issues(state))
    except (KeyError, TypeError, ValueError) as exc:
        issues.append(f"invalid semantic ledger: {exc}")
    return issues


def manifest_digest(path: Path) -> str:
    return sha256_bytes((path / MANIFEST).read_bytes())


@lru_cache(maxsize=None)
def _record_validator(key):
    schema = json.loads(files("papercheck").joinpath("schemas/records.schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator(schema["$defs"][key])


def canonical_row(row: dict[str, Any]) -> str:
    return canonical_json(row)

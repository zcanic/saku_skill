import hashlib
import json
from pathlib import Path

import pytest

from papercheck.index import query_counts
from papercheck.proposal import validate_proposal
from papercheck.storage import Repo, ValidationError
from papercheck.util import read_json, read_jsonl_tolerant, write_json


def sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def proposal(repo: Repo, data: bytes, segments: list[dict], untracked: list[dict] | None = None) -> dict:
    old = repo.load_current()
    return {
        "schema_version": "1.0.0",
        "base_state_id": old.state_id if old else None,
        "base_sha256": old.manifest["input"]["sha256"] if old else None,
        "paper_sha256": sha(data),
        "segments": segments,
        "untracked": untracked or [],
    }


def test_f01_stale_variant_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "paper.md").write_bytes(b"X hates Y.")
    repo = Repo(tmp_path)
    repo.commit(
        proposal=proposal(
            repo,
            b"X hates Y.",
            [{"kind": "paragraph", "block_ref": "p", "source_ranges": [{"start_byte": 0, "end_byte": 10}]}],
        )
    )
    old = repo.load_current()
    sel = old.snapshot["selections"][0]
    data = b"X loves Y."
    (tmp_path / "paper.md").write_bytes(data)
    bad = proposal(
        repo,
        data,
        [
            {
                "container_id": sel["container_id"],
                "variant_id": sel["variant_id"],
                "block_id": old.containers[0]["parent_block_id"],
                "text": "X hates Y.",
                "source_ranges": [{"start_byte": 0, "end_byte": 10}],
            }
        ],
    )
    issues = validate_proposal(old, data, bad)
    assert any("frozen source bytes" in issue for issue in issues)
    with pytest.raises(ValidationError):
        repo.commit(proposal=bad)
    assert repo.read_current() == "D000001"


def test_f02_shortening_document_succeeds(tmp_path: Path) -> None:
    (tmp_path / "paper.md").write_bytes(b"First sentence.\n\nSecond sentence, much longer.\n")
    repo = Repo(tmp_path)
    repo.init()
    old = repo.load_current()
    (tmp_path / "paper.md").write_bytes(b"First sentence.\n")
    result = repo.commit(auto=True)
    assert result.changed
    assert repo.verify() == []
    state = repo.load_current()
    assert state.state_id == "D000002"
    assert any("Second sentence" in v["raw_text"] for v in state.variants)
    assert old.state_id == "D000001"


def test_f03_truncated_commit_log_recovers(tmp_path: Path) -> None:
    (tmp_path / "paper.md").write_bytes(b"A sentence.")
    repo = Repo(tmp_path)
    repo.init()
    with (repo.recovery / "commit-log.jsonl").open("ab") as stream:
        stream.write(b'{"state_id":')
    repo.current_path.write_text("D999999\n", encoding="utf-8")
    assert repo.recover() == "D000001"
    assert repo.verify() == []


def test_f04_incomplete_hash_inventory_fails_verify(tmp_path: Path) -> None:
    (tmp_path / "paper.md").write_bytes(b"A sentence.")
    repo = Repo(tmp_path)
    repo.init()
    state = repo.load_current()
    manifest_path = state.path / "manifest.json"
    manifest = read_json(manifest_path)
    manifest["file_hashes"] = {}
    manifest["source_files"] = {}
    write_json(manifest_path, manifest)
    (state.path / "sources" / "claims.jsonl").unlink()
    issues = repo.verify()
    assert any("source_files missing" in issue for issue in issues)
    assert any("missing source file" in issue for issue in issues)


def test_f05_multi_range_placement_indexes(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("PAPERCHECK_DATABASE_URL", raising=False)
    data = b"Alpha\nBeta"
    (tmp_path / "paper.md").write_bytes(data)
    repo = Repo(tmp_path)
    result = repo.commit(
        proposal=proposal(
            repo,
            data,
            [
                {
                    "kind": "paragraph",
                    "block_ref": "p",
                    "source_ranges": [
                        {"start_byte": 0, "end_byte": 5},
                        {"start_byte": 6, "end_byte": 10},
                    ],
                }
            ],
            [{"start_byte": 5, "end_byte": 6, "reason": "newline"}],
        )
    )
    assert result.index_error is None
    assert repo.verify() == []
    index = repo.rebuild_index()
    assert query_counts(index)["placements"] == 2


def test_f06_fragmented_untracked_commits(tmp_path: Path) -> None:
    data = b"A.  B."
    (tmp_path / "paper.md").write_bytes(data)
    repo = Repo(tmp_path)
    repo.commit(
        proposal=proposal(
            repo,
            data,
            [
                {"kind": "paragraph", "block_ref": "p", "source_ranges": [{"start_byte": 0, "end_byte": 2}]},
                {"kind": "paragraph", "block_ref": "p", "source_ranges": [{"start_byte": 4, "end_byte": 6}]},
            ],
            [
                {"start_byte": 2, "end_byte": 3, "reason": "space1"},
                {"start_byte": 3, "end_byte": 4, "reason": "space2"},
            ],
        )
    )
    assert repo.verify() == []
    state = repo.load_current()
    assert len(state.snapshot["untracked_blocks"]) == 2


def test_f07_schema_rejects_float_offsets_but_allows_descriptive_fields(tmp_path: Path) -> None:
    data = b"A sentence."
    (tmp_path / "paper.md").write_bytes(data)
    repo = Repo(tmp_path)
    bad = proposal(
        repo,
        data,
        [
            {
                "kind": "paragraph",
                "block_ref": "p",
                "source_ranges": [{"start_byte": 0.9, "end_byte": 11.9}],
            }
        ],
    )
    issues = validate_proposal(None, data, bad)
    assert any("not of type 'integer'" in issue for issue in issues)
    with pytest.raises(ValidationError):
        repo.commit(proposal=bad)

    descriptive = {
        "schema_version": "1.0.0",
        "base_state_id": None,
        "base_sha256": None,
        "paper_sha256": sha(data),
        "segments": [
            {
                "kind": "not_a_kind",
                "block_ref": "p",
                "source_ranges": [{"start_byte": 0, "end_byte": 11}],
                "agent_note": "descriptive extra field",
            }
        ],
        "extra_top_level": {"ok": True},
    }
    repo.commit(proposal=descriptive)
    assert repo.verify() == []
    assert repo.load_current().containers[0]["kind"] == "not_a_kind"


def test_f08_split_event_contains_all_targets(tmp_path: Path) -> None:
    base = b"Alpha beta."
    (tmp_path / "paper.md").write_bytes(base)
    repo = Repo(tmp_path)
    repo.commit(
        proposal=proposal(
            repo,
            base,
            [{"kind": "paragraph", "block_ref": "p", "source_ranges": [{"start_byte": 0, "end_byte": 11}]}],
        )
    )
    old = repo.load_current()
    cid = old.containers[0]["id"]
    data = b"Alpha. Beta."
    (tmp_path / "paper.md").write_bytes(data)
    repo.commit(
        proposal=proposal(
            repo,
            data,
            [
                {
                    "kind": "paragraph",
                    "block_ref": "p",
                    "lineage": {"type": "split", "from": [cid]},
                    "source_ranges": [{"start_byte": 0, "end_byte": 6}],
                },
                {"kind": "paragraph", "block_ref": "p", "source_ranges": [{"start_byte": 7, "end_byte": 12}]},
            ],
            [{"start_byte": 6, "end_byte": 7, "reason": "space"}],
        )
    )
    state = repo.load_current()
    new_ids = {sel["container_id"] for sel in state.snapshot["selections"]}
    split = next(event for event in state.events if event["type"] == "TEXT_SPLIT")
    assert set(split["after"]) == new_ids


def test_run_ids_are_consistent(tmp_path: Path) -> None:
    (tmp_path / "paper.md").write_bytes(b"A sentence.")
    repo = Repo(tmp_path)
    repo.init()
    state = repo.load_current()
    assert len(state.runs) == 1
    run_id = state.runs[0]["id"]
    snapshot_event = next(event for event in state.events if event["type"] == "SNAPSHOT_COMMITTED")
    assert snapshot_event["run_id"] == run_id
    log = read_jsonl_tolerant(repo.recovery / "commit-log.jsonl")
    assert log[-1]["run_id"] == run_id

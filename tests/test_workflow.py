import hashlib
from pathlib import Path

import pytest

from papercheck.proposal import build_context, validate_proposal
from papercheck.state import load_state
from papercheck.storage import Repo, ValidationError


def sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def proposal_for(root: Path, state, paper_bytes: bytes, segments: list[dict], untracked: list[dict]) -> dict:
    return {
        "schema_version": "1.0.0",
        "base_state_id": state.state_id if state else None,
        "base_sha256": state.manifest["input"]["sha256"] if state else None,
        "paper_sha256": sha(paper_bytes),
        "segments": segments,
        "untracked": untracked,
    }


def first_state(tmp_path: Path) -> tuple[Repo, dict]:
    paper = b"Hello world.\nSecond sentence.\n"
    (tmp_path / "paper.md").write_bytes(paper)
    repo = Repo(tmp_path)
    proposal = proposal_for(
        tmp_path,
        None,
        paper,
        [
            {"block_ref": "p1", "kind": "paragraph", "text": "Hello world.", "source_ranges": [{"start_byte": 0, "end_byte": 12}]},
            {"block_ref": "p1", "kind": "paragraph", "text": "Second sentence.", "source_ranges": [{"start_byte": 13, "end_byte": 29}]},
        ],
        [
            {"start_byte": 12, "end_byte": 13, "reason": "space"},
            {"start_byte": 29, "end_byte": 30, "reason": "newline"},
        ],
    )
    result = repo.commit(proposal=proposal)
    assert result.changed and result.state_id == "D000001"
    return repo, proposal


def test_agent_revision_reuses_container(tmp_path: Path) -> None:
    repo, _ = first_state(tmp_path)
    paper = b"Hello there.\nSecond sentence.\n"
    (tmp_path / "paper.md").write_bytes(paper)
    old = repo.load_current()
    context = build_context(old, paper.decode(), paper)
    selections = context["old_selections"]
    first = next(s for s in selections if s["normalized_text"] == "Hello world.")
    second = next(s for s in selections if s["normalized_text"] == "Second sentence.")
    proposal = proposal_for(
        tmp_path,
        old,
        paper,
        [
            {
                "container_id": first["container_id"],
                "block_id": first["block_id"],
                "kind": first["kind"],
                "text": "Hello there.",
                "source_ranges": [{"start_byte": 0, "end_byte": 12}],
            },
            {
                "container_id": second["container_id"],
                "variant_id": second["variant_id"],
                "block_id": second["block_id"],
                "kind": second["kind"],
                "text": "Second sentence.",
                "source_ranges": second["source_ranges"],
            },
        ],
        context["old_untracked"],
    )
    assert validate_proposal(old, paper, proposal) == []
    result = repo.commit(proposal=proposal)
    assert result.state_id == "D000002"
    state = repo.load_current()
    assert repo.verify() == []
    assert len(state.containers) == 2
    assert len(state.variants) == 3
    assert state.snapshot["selections"][0]["container_id"] == first["container_id"]
    assert state.snapshot["selections"][1]["variant_id"] == second["variant_id"]
    old_variant = state.by_id("variants")[first["variant_id"]]
    assert old_variant["normalized_text"] == "Hello world."
    new_variant = state.by_id("variants")[state.snapshot["selections"][0]["variant_id"]]
    assert new_variant["normalized_text"] == "Hello there."


def test_split_then_merge(tmp_path: Path) -> None:
    paper = b"Alpha beta.\n"
    (tmp_path / "paper.md").write_bytes(paper)
    repo = Repo(tmp_path)
    base = proposal_for(
        tmp_path,
        None,
        paper,
        [{"block_ref": "p1", "kind": "paragraph", "text": "Alpha beta.", "source_ranges": [{"start_byte": 0, "end_byte": 11}]}],
        [{"start_byte": 11, "end_byte": 12, "reason": "newline"}],
    )
    repo.commit(proposal=base)
    base_state = repo.load_current()
    old_cid = base_state.snapshot["selections"][0]["container_id"]

    split_paper = b"Alpha.\nBeta.\n"
    (tmp_path / "paper.md").write_bytes(split_paper)
    split = proposal_for(
        tmp_path,
        base_state,
        split_paper,
        [
            {
                "block_ref": "p1",
                "kind": "paragraph",
                "text": "Alpha.",
                "source_ranges": [{"start_byte": 0, "end_byte": 6}],
                "lineage": {"type": "split", "from": [old_cid]},
            },
            {
                "block_ref": "p1",
                "kind": "paragraph",
                "text": "Beta.",
                "source_ranges": [{"start_byte": 7, "end_byte": 12}],
            },
        ],
        [
            {"start_byte": 6, "end_byte": 7, "reason": "space"},
            {"start_byte": 12, "end_byte": 13, "reason": "newline"},
        ],
    )
    split_result = repo.commit(proposal=split)
    split_state = repo.load_current()
    types = [row["type"] for row in split_state.events]
    assert "TEXT_SPLIT" in types
    assert "REMOVED_FROM_TEXT" in types
    assert old_cid not in {sel["container_id"] for sel in split_state.snapshot["selections"]}
    assert len(split_state.snapshot["selections"]) == 2
    split_ids = [sel["container_id"] for sel in split_state.snapshot["selections"]]

    merge_paper = b"Alpha beta.\n"
    (tmp_path / "paper.md").write_bytes(merge_paper)
    merge = proposal_for(
        tmp_path,
        split_state,
        merge_paper,
        [
            {
                "block_ref": "p2",
                "kind": "paragraph",
                "text": "Alpha beta.",
                "source_ranges": [{"start_byte": 0, "end_byte": 11}],
                "lineage": {"type": "merge", "from": split_ids},
            }
        ],
        [{"start_byte": 11, "end_byte": 12, "reason": "newline"}],
    )
    repo.commit(proposal=merge)
    merged = repo.load_current()
    assert "TEXT_MERGED" in [row["type"] for row in merged.events]
    assert repo.verify() == []


def test_duplicate_sentences_stay_distinct(tmp_path: Path) -> None:
    paper = b"Same.\nSame.\n"
    (tmp_path / "paper.md").write_bytes(paper)
    repo = Repo(tmp_path)
    base = proposal_for(
        tmp_path,
        None,
        paper,
        [
            {"block_ref": "p1", "kind": "paragraph", "text": "Same.", "source_ranges": [{"start_byte": 0, "end_byte": 5}]},
            {"block_ref": "p2", "kind": "paragraph", "text": "Same.", "source_ranges": [{"start_byte": 6, "end_byte": 11}]},
        ],
        [
            {"start_byte": 5, "end_byte": 6, "reason": "newline"},
            {"start_byte": 11, "end_byte": 12, "reason": "newline"},
        ],
    )
    repo.commit(proposal=base)
    state = repo.load_current()
    cids = [sel["container_id"] for sel in state.snapshot["selections"]]
    assert len(set(cids)) == 2

    changed = b"Diff.\nSame.\n"
    (tmp_path / "paper.md").write_bytes(changed)
    proposal = proposal_for(
        tmp_path,
        state,
        changed,
        [
            {"container_id": cids[0], "block_id": state.snapshot["selections"][0]["container_id"], "kind": "paragraph", "text": "Diff.", "source_ranges": [{"start_byte": 0, "end_byte": 5}]},
            {"container_id": cids[1], "variant_id": state.snapshot["selections"][1]["variant_id"], "block_id": state.snapshot["selections"][1]["container_id"], "kind": "paragraph", "text": "Same.", "source_ranges": [{"start_byte": 6, "end_byte": 11}]},
        ],
        [
            {"start_byte": 5, "end_byte": 6, "reason": "newline"},
            {"start_byte": 11, "end_byte": 12, "reason": "newline"},
        ],
    )
    # block_id above is deliberately the container id; correct it from context.
    context = build_context(state, changed.decode(), changed)
    by_container = {s["container_id"]: s for s in context["old_selections"]}
    for seg in proposal["segments"]:
        seg["block_id"] = by_container[seg["container_id"]]["block_id"]
    repo.commit(proposal=proposal)
    after = repo.load_current()
    assert len(after.containers) == 2
    assert len(after.variants) == 3
    variants = after.by_id("variants")
    assert variants[after.snapshot["selections"][1]["variant_id"]]["normalized_text"] == "Same."


def test_proposal_validation_rejects_gaps_and_wrong_base(tmp_path: Path) -> None:
    paper = b"Hello world.\n"
    (tmp_path / "paper.md").write_bytes(paper)
    repo = Repo(tmp_path)
    bad = proposal_for(
        tmp_path,
        None,
        paper,
        [{"block_ref": "p", "kind": "paragraph", "text": "Hello world.", "source_ranges": [{"start_byte": 0, "end_byte": 12}]}],
        [],
    )
    issues = validate_proposal(None, paper, bad)
    assert any("gap" in issue or "coverage" in issue for issue in issues)
    with pytest.raises(ValidationError):
        repo.commit(proposal=bad)
    assert repo.read_current() is None

    good = proposal_for(
        tmp_path,
        None,
        paper,
        [{"block_ref": "p", "kind": "paragraph", "text": "Hello world.", "source_ranges": [{"start_byte": 0, "end_byte": 12}]}],
        [{"start_byte": 12, "end_byte": 13, "reason": "newline"}],
    )
    repo.commit(proposal=good)
    state = repo.load_current()
    wrong = dict(good)
    wrong["base_state_id"] = "D999999"
    wrong["paper_sha256"] = sha(b"different")
    issues = validate_proposal(state, paper, wrong)
    assert any("base_state_id" in issue for issue in issues)
    assert any("paper_sha256" in issue for issue in issues)


def test_context_has_byte_offsets_and_untracked(tmp_path: Path) -> None:
    repo, _ = first_state(tmp_path)
    state = repo.load_current()
    paper = (tmp_path / "paper.md").read_bytes()
    context = build_context(state, paper.decode(), paper)
    assert context["base_state_id"] == state.state_id
    assert context["paper_size"] == len(paper)
    assert context["old_untracked"]
    assert context["lines"][0]["start_byte"] == 0
    assert context["lines"][0]["end_byte"] == 13
    assert len(context["old_selections"]) == 2


def test_reorder_reuses_placements(tmp_path: Path) -> None:
    paper = b"First.\nSecond.\n"
    (tmp_path / "paper.md").write_bytes(paper)
    repo = Repo(tmp_path)
    base = proposal_for(
        tmp_path,
        None,
        paper,
        [
            {"block_ref": "p", "kind": "paragraph", "text": "First.", "source_ranges": [{"start_byte": 0, "end_byte": 6}]},
            {"block_ref": "p", "kind": "paragraph", "text": "Second.", "source_ranges": [{"start_byte": 7, "end_byte": 14}]},
        ],
        [
            {"start_byte": 6, "end_byte": 7, "reason": "newline"},
            {"start_byte": 14, "end_byte": 15, "reason": "newline"},
        ],
    )
    repo.commit(proposal=base)
    state = repo.load_current()
    first, second = state.snapshot["selections"]
    containers = state.by_id("containers")
    first_block = containers[first["container_id"]]["parent_block_id"]
    second_block = containers[second["container_id"]]["parent_block_id"]
    moved_paper = b"Second.\nFirst.\n"
    (tmp_path / "paper.md").write_bytes(moved_paper)
    proposal = proposal_for(
        tmp_path,
        state,
        moved_paper,
        [
            {
                "container_id": second["container_id"],
                "variant_id": second["variant_id"],
                "block_id": second_block,
                "kind": "paragraph",
                "text": "Second.",
                "source_ranges": [{"start_byte": 0, "end_byte": 7}],
            },
            {
                "container_id": first["container_id"],
                "variant_id": first["variant_id"],
                "block_id": first_block,
                "kind": "paragraph",
                "text": "First.",
                "source_ranges": [{"start_byte": 8, "end_byte": 14}],
            },
        ],
        [
            {"start_byte": 7, "end_byte": 8, "reason": "newline"},
            {"start_byte": 14, "end_byte": 15, "reason": "newline"},
        ],
    )
    repo.commit(proposal=proposal)
    after = repo.load_current()
    assert len(after.variants) == 2
    assert [s["container_id"] for s in after.snapshot["selections"]] == [
        second["container_id"],
        first["container_id"],
    ]
    assert repo.verify() == []

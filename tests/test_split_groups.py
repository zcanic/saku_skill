import pytest

from papercheck.storage import Repo, ValidationError
from papercheck.util import sha256_bytes


def p(repo, data, segments):
    repo.paper_path.write_bytes(data)
    old = repo.load_current()
    return {"schema_version": "1.1.0", "paper_sha256": sha256_bytes(data),
            "base_state_id": old.state_id if old else None,
            "base_sha256": old.manifest["input"]["sha256"] if old else None,
            "segments": segments, "untracked": []}


def segments(count):
    return [{"ref": str(i), "block_ref": "p", "kind": "paragraph",
             "source_ranges": [{"start_byte": i, "end_byte": i + 1}]} for i in range(count)]


def test_two_independent_splits_in_same_block_have_separate_groups(tmp_path):
    repo = Repo(tmp_path)
    repo.commit(proposal=p(repo, b"AB", segments(2)))
    old_ids = [s["id"] for s in repo.load_current().containers]
    targets = segments(4)
    for index, target in enumerate(targets):
        target["lineage"] = {"type": "split", "from": [old_ids[index // 2]], "group": f"g{index // 2}"}
    repo.commit(proposal=p(repo, b"ABCD", targets))
    events = [e for e in repo.load_current().events if e["type"] == "TEXT_SPLIT"]
    assert len(events) == 2
    assert [len(e["after"]) for e in events] == [2, 2]
    assert not set(events[0]["after"]) & set(events[1]["after"])


def test_ambiguous_implicit_splits_are_rejected(tmp_path):
    repo = Repo(tmp_path)
    repo.commit(proposal=p(repo, b"AB", segments(2)))
    old_ids = [s["id"] for s in repo.load_current().containers]
    targets = segments(4)
    for index in [0, 2]:
        targets[index]["lineage"] = {"type": "split", "from": [old_ids[index // 2]]}
    with pytest.raises(ValidationError, match="explicit lineage.group"):
        repo.commit(proposal=p(repo, b"ABCD", targets))


def test_explicit_group_does_not_capture_independent_new_text(tmp_path):
    repo = Repo(tmp_path)
    repo.commit(proposal=p(repo, b"A", segments(1)))
    old_id = repo.load_current().containers[0]["id"]
    targets = segments(3)
    for target in targets[:2]:
        target["lineage"] = {"type": "split", "from": [old_id], "group": "g"}
    repo.commit(proposal=p(repo, b"ABC", targets))
    state = repo.load_current()
    split = next(e for e in state.events if e["type"] == "TEXT_SPLIT")
    assert len(split["after"]) == 2
    assert state.snapshot["selections"][2]["container_id"] not in split["after"]

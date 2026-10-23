import pytest

from papercheck.storage import PapercheckError, Repo
from papercheck.util import read_json, read_jsonl, write_json


@pytest.mark.parametrize("stage", ["after_stage", "after_publish", "before_current", "after_current"])
def test_all_commit_failure_points_leave_a_verifiable_current(tmp_path, monkeypatch, stage):
    repo = Repo(tmp_path)
    repo.paper_path.write_bytes(b"Original assertion.")
    repo.init()
    repo.paper_path.write_bytes(b"Updated assertion.")
    monkeypatch.setenv("PAPERCHECK_FAULT", stage)
    with pytest.raises(PapercheckError, match="injected fault"):
        repo.commit(auto=True)
    assert repo.verify() == []
    assert repo.read_current() == ("D000002" if stage == "after_current" else "D000001")
    assert repo.paper_path.read_bytes() == b"Updated assertion."


def test_commit_after_truncated_log_remains_recoverable(tmp_path):
    repo = Repo(tmp_path)
    repo.paper_path.write_bytes(b"Original assertion.")
    repo.init()
    with (repo.recovery / "commit-log.jsonl").open("ab") as stream:
        stream.write(b'{"state_id":')
    repo.paper_path.write_bytes(b"Updated assertion.")
    repo.commit(auto=True)
    assert len(read_jsonl(repo.recovery / "commit-log.jsonl")) == 2
    repo.current_path.write_text("D999999", encoding="utf-8")
    assert repo.recover() == "D000002"


def test_recovery_does_not_accept_a_manifest_that_disagrees_with_log(tmp_path):
    repo = Repo(tmp_path)
    repo.paper_path.write_bytes(b"Original assertion.")
    repo.init()
    path = repo.load_current().path / "manifest.json"
    manifest = read_json(path)
    manifest["message"] = "Edited manifest with correct source hashes"
    write_json(path, manifest)
    repo.current_path.write_text("D999999", encoding="utf-8")
    with pytest.raises(PapercheckError, match="recovery log"):
        repo.recover()


def test_valid_legacy_state_is_read_without_rewriting_then_upgrades(tmp_path):
    repo = Repo(tmp_path)
    repo.paper_path.write_bytes(b"Legacy assertion.")
    repo.init()
    path = repo.load_current().path / "manifest.json"
    manifest = read_json(path)
    manifest["schema_version"] = "1.0.0"
    for key in ["revisions", "bindings", "arguments", "reviews", "invalidations"]:
        relative = manifest["source_files"].pop(key)
        manifest["file_hashes"].pop(relative)
        (path.parent / relative).unlink()
    write_json(path, manifest)
    frozen = path.read_bytes()
    assert repo.verify() == []
    repo.paper_path.write_bytes(b"A revised legacy assertion.")
    repo.commit(auto=True)
    assert repo.load_current().manifest["schema_version"] == "1.1.0"
    assert path.read_bytes() == frozen
    assert repo.verify() == []

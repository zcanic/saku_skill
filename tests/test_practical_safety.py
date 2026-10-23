import json

import pytest

from papercheck.cli import main
from papercheck.storage import Repo
from papercheck.util import sha256_bytes


def completed_repo(tmp_path):
    data = b"A heading."
    (tmp_path / "paper.md").write_bytes(data)
    repo = Repo(tmp_path)
    repo.commit(proposal={"schema_version": "1.1.0", "paper_sha256": sha256_bytes(data),
        "segments": [{"ref": "heading", "kind": "heading", "source_ranges": [{"start_byte": 0, "end_byte": len(data)}]}],
        "untracked": [], "semantic": {"bindings": [], "non_claim_segments": [{"segment": "heading", "reason": "Only a title"}]}})
    assert repo.load_current().snapshot["workflow"]["status"] == "completed"
    return repo


@pytest.mark.parametrize("target", ["paper.md", ".papercheck/CURRENT", ".papercheck/states/D000001/manifest.json"])
def test_context_output_cannot_overwrite_authoritative_inputs(tmp_path, target, capsys):
    repo = completed_repo(tmp_path)
    path = tmp_path / target
    original = path.read_bytes()
    assert main(["--root", str(tmp_path), "context", "--output", str(path)]) == 2
    assert "must not overwrite" in capsys.readouterr().err
    assert path.read_bytes() == original
    assert repo.verify() == []


@pytest.mark.parametrize("missing", [False, True])
def test_workflow_distinguishes_unprocessed_paper_from_completed_history(tmp_path, capsys, missing):
    repo = completed_repo(tmp_path)
    frozen = repo.load_current()
    snapshot_bytes = (frozen.path / "sources" / "snapshots.jsonl").read_bytes()
    if missing:
        repo.paper_path.unlink()
    else:
        repo.paper_path.write_bytes("新增未检查的实质性断言。".encode())
    assert main(["--root", str(tmp_path), "workflow", "--json"]) == 0
    workflow = json.loads(capsys.readouterr().out)
    assert workflow["recorded_status"] == "completed" and workflow["status"] == "pending"
    assert workflow["working_copy_changed"]
    assert workflow["tasks"][0]["type"] == "update_snapshot"
    assert repo.status()["working_copy"]["changed"]
    assert main(["--root", str(tmp_path), "context"]) == (1 if missing else 0)
    captured = capsys.readouterr()
    if not missing:
        assert json.loads(captured.out)["workflow"]["status"] == "pending"
    assert main(["--root", str(tmp_path), "report"]) == 0
    report = (repo.reports / "D000001.md").read_text(encoding="utf-8")
    assert "工作副本尚待处理" in report and "**pending**" in report
    assert (frozen.path / "sources" / "snapshots.jsonl").read_bytes() == snapshot_bytes


def test_windows_bom_proposal_can_be_validated_and_staged(tmp_path, capsys):
    data = b"A sentence."
    (tmp_path / "paper.md").write_bytes(data)
    proposal = {"schema_version": "1.1.0", "paper_sha256": sha256_bytes(data), "segments": [
        {"kind": "paragraph", "source_ranges": [{"start_byte": 0, "end_byte": len(data)}]}], "untracked": []}
    path = tmp_path / "proposal.json"
    path.write_text(json.dumps(proposal), encoding="utf-8-sig")
    assert main(["--root", str(tmp_path), "validate", "--proposal", str(path)]) == 0
    assert main(["--root", str(tmp_path), "propose", str(path)]) == 0
    capsys.readouterr()


def test_status_of_missing_current_is_a_controlled_diagnostic(tmp_path, capsys):
    repo = completed_repo(tmp_path)
    repo.current_path.write_bytes(b"D999999\n")
    assert main(["--root", str(tmp_path), "status"]) == 1
    captured = capsys.readouterr()
    assert "missing state D999999" in captured.out
    assert "Traceback" not in captured.err
    assert main(["--root", str(tmp_path), "recover"]) == 0
    assert repo.verify() == []

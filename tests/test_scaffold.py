import json
from importlib.resources import files

import pytest

from papercheck.cli import main
from papercheck.scaffold import scaffold


def test_scaffold_and_packaged_proposal_work_end_to_end(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("PAPERCHECK_DATABASE_URL", raising=False)
    root, names = scaffold(tmp_path / "project")
    assert "AGENTS.md" in names
    assert (root / "workflow" / "03-evidence-and-checks.md").exists()
    assert (root / "workflow" / "05-semantic-contract.md").exists()
    contract = json.loads((root / "contracts" / "proposal.schema.json").read_text(encoding="utf-8"))
    assert "semantic" in contract["properties"]
    assert (root / "contracts" / "records.schema.json").exists()
    (root / "paper.md").write_bytes(b"X causes Y.\n")
    proposal = root / "templates" / "proposal.example.json"
    assert main(["--root", str(root), "context", "--output", str(root / "context.json")]) == 0
    assert json.loads((root / "context.json").read_text(encoding="utf-8"))["paper_size"] == 12
    assert main(["--root", str(root), "validate", "--proposal", str(proposal)]) == 0
    assert main(["--root", str(root), "commit", "--proposal", str(proposal)]) == 0
    assert main(["--root", str(root), "verify"]) == 0
    capsys.readouterr()
    assert main(["--root", str(root), "workflow", "--json"]) == 0
    workflow = json.loads(capsys.readouterr().out)
    assert workflow["status"] == "pending"
    assert any(t["type"] == "obtain_source" for t in workflow["tasks"])
    assert main(["--root", str(root), "show", "--json"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["paper_text"] == "X causes Y.\n" and shown["records"]["claims"]
    assert main(["--root", str(root), "report"]) == 0
    report = (root / ".papercheck" / "reports" / "D000001.md").read_text(encoding="utf-8")
    assert "pending" in report and "unavailable" in report


def test_scaffold_never_overwrites_an_existing_paper(tmp_path):
    paper = tmp_path / "paper.md"
    paper.write_bytes(b"Original paper")
    with pytest.raises(ValueError, match="overwrite"):
        scaffold(tmp_path)
    assert paper.read_bytes() == b"Original paper"
    assert not (tmp_path / "AGENTS.md").exists()


def test_scaffold_copies_source_bytes_exactly(tmp_path):
    source = tmp_path / "source.md"
    data = "中文\r\n".encode("utf-8")
    source.write_bytes(data)
    root, _ = scaffold(tmp_path / "new", source)
    assert (root / "paper.md").read_bytes() == data


def test_schema_copies_match_the_packaged_resources():
    from pathlib import Path
    for name in ["proposal.schema.json", "records.schema.json"]:
        package = json.loads(files("papercheck").joinpath("schemas", name).read_text(encoding="utf-8"))
        repository = json.loads((Path(__file__).parents[1] / "schema" / name).read_text(encoding="utf-8"))
        assert package == repository


def test_utf8_character_splitting_returns_a_diagnostic(tmp_path):
    from papercheck.proposal import validate_proposal
    from papercheck.util import sha256_bytes
    data = "中".encode()
    p = {"schema_version": "1.1.0", "paper_sha256": sha256_bytes(data), "segments": [
        {"kind": "paragraph", "source_ranges": [{"start_byte": 0, "end_byte": 1}]},
        {"kind": "paragraph", "source_ranges": [{"start_byte": 1, "end_byte": 3}]}], "untracked": []}
    assert any("UTF-8" in issue for issue in validate_proposal(None, data, p))

import hashlib
import json
from pathlib import Path

from papercheck.cli import main


def sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def test_cli_context_propose_commit(tmp_path: Path, capsys) -> None:
    paper = b"Hello world.\n"
    (tmp_path / "paper.md").write_bytes(paper)
    proposal = {
        "schema_version": "1.0.0",
        "base_state_id": None,
        "base_sha256": None,
        "paper_sha256": sha(paper),
        "segments": [
            {
                "block_ref": "p1",
                "kind": "paragraph",
                "text": "Hello world.",
                "source_ranges": [{"start_byte": 0, "end_byte": 12}],
            }
        ],
        "untracked": [{"start_byte": 12, "end_byte": 13, "reason": "newline"}],
    }
    path = tmp_path / "proposal.json"
    path.write_text(json.dumps(proposal), encoding="utf-8")

    assert main(["--root", str(tmp_path), "context"]) == 0
    context = json.loads(capsys.readouterr().out)
    assert context["paper_size"] == 13
    assert context["base_state_id"] is None

    assert main(["--root", str(tmp_path), "propose", str(path)]) == 0
    capsys.readouterr()
    assert main(["--root", str(tmp_path), "validate"]) == 0
    capsys.readouterr()
    assert main(["--root", str(tmp_path), "commit"]) == 0
    out = capsys.readouterr().out
    assert "committed D000001" in out
    assert main(["--root", str(tmp_path), "verify"]) == 0
    capsys.readouterr()

    bad = dict(proposal)
    bad["paper_sha256"] = sha(b"wrong")
    bad_path = tmp_path / "bad.json"
    bad_path.write_text(json.dumps(bad), encoding="utf-8")
    assert main(["--root", str(tmp_path), "validate", "--proposal", str(bad_path)]) == 2
    assert "paper_sha256" in capsys.readouterr().err

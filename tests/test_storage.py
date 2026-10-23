from pathlib import Path

import pytest

from papercheck.index import query_counts
from papercheck.storage import PapercheckError, Repo


def make_repo(tmp_path: Path, text: str = "# Title\n\nHello world.\n") -> Repo:
    (tmp_path / "paper.md").write_bytes(text.encode("utf-8"))
    return Repo(tmp_path)


def test_init_idempotent_and_verify(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    first = repo.init()
    assert first.changed and first.state_id == "D000001"
    assert repo.verify() == []
    second = repo.commit(auto=True)
    assert not second.changed and second.state_id == "D000001"
    assert len(list((repo.states).iterdir())) == 1


def test_verify_detects_tamper(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.init()
    state = repo.load_current()
    target = state.path / "sources" / "blocks.jsonl"
    target.write_text(target.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    issues = repo.verify()
    assert any("hash mismatch" in issue for issue in issues)


def test_recover_from_bad_current(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    repo.init()
    (tmp_path / "paper.md").write_bytes(b"# Title\n\nHello brave world.\n")
    repo.commit(auto=True)
    assert repo.read_current() == "D000002"
    repo.current_path.write_text("D999999\n", encoding="utf-8")
    assert repo.verify()
    assert repo.recover() == "D000002"
    assert repo.verify() == []


def test_fault_after_publish_keeps_current(tmp_path: Path, monkeypatch) -> None:
    repo = make_repo(tmp_path)
    repo.init()
    (tmp_path / "paper.md").write_bytes(b"# Title\n\nChanged text.\n")
    monkeypatch.setenv("PAPERCHECK_FAULT", "after_publish")
    with pytest.raises(PapercheckError):
        repo.commit(auto=True)
    assert repo.read_current() == "D000001"
    assert repo.verify() == []
    assert (repo.states / "D000002").is_dir()

    monkeypatch.delenv("PAPERCHECK_FAULT")
    result = repo.commit(auto=True)
    assert result.changed
    assert result.state_id == "D000003"
    assert repo.verify() == []


def test_sqlite_index_rebuild(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("PAPERCHECK_DATABASE_URL", raising=False)
    repo = make_repo(tmp_path)
    repo.init()
    target = repo.rebuild_index()
    assert isinstance(target, Path)
    counts = query_counts(target)
    assert counts["blocks"] >= 1
    assert counts["containers"] >= 1
    assert counts["snapshots"] == 1


def test_deferred_blocks_are_untracked(tmp_path: Path) -> None:
    paper = "# T\n\nText.\n\n```py\nprint('x')\n```\n\n| A | B |\n|---|---|\n| 1 | 2 |\n"
    repo = make_repo(tmp_path, paper)
    repo.init()
    assert repo.verify() == []
    state = repo.load_current()
    reasons = {row["reason"] for row in state.snapshot["untracked_blocks"]}
    assert "deferred:code_block" in reasons
    assert "deferred:table" in reasons


def test_concurrent_paper_change_aborts(tmp_path: Path, monkeypatch) -> None:
    import papercheck.storage as storage_mod
    from papercheck.storage import ConcurrentModification

    repo = make_repo(tmp_path)
    repo.init()
    (tmp_path / "paper.md").write_bytes(b"# Title\n\nA new sentence.\n")
    original = storage_mod.write_state_dir

    def racing_write(*args, **kwargs):
        result = original(*args, **kwargs)
        (tmp_path / "paper.md").write_bytes(b"# Title\n\nEven newer text.\n")
        return result

    monkeypatch.setattr(storage_mod, "write_state_dir", racing_write)
    with pytest.raises(ConcurrentModification):
        repo.commit(auto=True)
    assert repo.read_current() == "D000001"
    assert repo.verify() == []

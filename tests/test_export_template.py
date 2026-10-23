import hashlib
import importlib.util
import json
from pathlib import Path
import tomllib
import zipfile

import pytest

SPEC = importlib.util.spec_from_file_location("export_template", Path(__file__).parents[1] / "scripts" / "export_template.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_template_is_complete_clean_and_manifest_matches(tmp_path):
    target, archive = tmp_path / "template", tmp_path / "template.zip"
    files = MODULE.export(target, archive)
    assert (target / "paper.md").read_bytes() == b""
    license_bytes=(Path(__file__).parents[1]/'LICENSE').read_bytes().replace(b'\r\n',b'\n')
    assert files['LICENSE']==license_bytes
    assert files['papercheck/template/LICENSE']==license_bytes
    assert files['papercheck/inspector_assets/runtime/LICENSE'].replace(b'\r\n',b'\n')==license_bytes
    assert all(name in files for name in ["README.md", "AGENTS.md", "PROJECT.md", "pyproject.toml",
        "papercheck/__main__.py", "papercheck/semantic.py", "contracts/proposal.schema.json",
        "workflow/05-semantic-contract.md", "references/.gitkeep"])
    assert not any(part in {".env", ".git", ".tmp", "__pycache__", ".papercheck", "tests", "examples"}
                   for name in files for part in Path(name).parts)
    assert not any(name.endswith((".pyc", ".sqlite", ".whl")) for name in files)
    manifest = json.loads(files["TEMPLATE-MANIFEST.json"])
    assert manifest["files"] == {name: "sha256:" + hashlib.sha256(data).hexdigest()
                                 for name, data in files.items() if name != "TEMPLATE-MANIFEST.json"}
    config = tomllib.loads(files["pyproject.toml"].decode())
    assert "pytest" not in config.get("tool", {})
    assert config["project"]["scripts"]["papercheck"] == "papercheck.cli:main"
    with zipfile.ZipFile(archive) as zipped:
        assert {name.removeprefix("papercheck-template/"): zipped.read(name) for name in zipped.namelist()} == files
    assert MODULE.export(target, check=True) == files


def test_template_export_never_overwrites_user_edits(tmp_path):
    target = tmp_path / "template"
    MODULE.export(target)
    paper = target / "paper.md"
    paper.write_bytes(b"Author's actual manuscript")
    with pytest.raises(ValueError, match="overwrite"):
        MODULE.export(target)
    with pytest.raises(ValueError, match="differs"):
        MODULE.export(target, check=True)
    assert paper.read_bytes() == b"Author's actual manuscript"


def test_template_and_archive_are_reproducible(tmp_path):
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"
    MODULE.export(tmp_path / "first", first)
    MODULE.export(tmp_path / "second", second)
    assert first.read_bytes() == second.read_bytes()


def test_verified_template_can_be_archived_without_overwriting_it(tmp_path):
    target, initial, rebuilt = tmp_path / "template", tmp_path / "initial.zip", tmp_path / "rebuilt.zip"
    expected = MODULE.export(target, initial)
    assert MODULE.export(target, rebuilt, check=True) == expected
    assert initial.read_bytes() == rebuilt.read_bytes()
    with pytest.raises(FileExistsError):
        MODULE.export(target, rebuilt, check=True)

"""Exercise an installed wheel outside the source checkout (global deps remain available)."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--installed", required=True)
    args = parser.parse_args()
    installed = str(Path(args.installed).resolve())
    code = r'''
import json, os
from pathlib import Path
from importlib.resources import files
import papercheck
from papercheck.cli import main
from papercheck.scaffold import scaffold
assert Path(papercheck.__file__).is_relative_to(Path(os.environ["PYTHONPATH"]))
root, _ = scaffold("project")
assert (root / ".gitignore").exists()
assert (root / "workflow" / "05-semantic-contract.md").exists()
assert (root / "contracts" / "proposal.schema.json").exists()
assert (root / "contracts" / "records.schema.json").exists()
(root / "paper.md").write_bytes(b"X causes Y.\n")
proposal = root / "templates" / "proposal.example.json"
assert main(["--root", str(root), "validate", "--proposal", str(proposal)]) == 0
assert main(["--root", str(root), "commit", "--proposal", str(proposal)]) == 0
assert main(["--root", str(root), "verify"]) == 0
assert main(["--root", str(root), "workflow", "--json"]) == 0
print("INSTALLED PACKAGE SMOKE PASSED:", papercheck.__file__)
'''
    env = {**os.environ, "PYTHONPATH": installed, "PYTHONIOENCODING": "utf-8"}
    env.pop("PAPERCHECK_DATABASE_URL", None)
    with tempfile.TemporaryDirectory(prefix="papercheck-wheel-") as directory:
        subprocess.run([sys.executable, "-c", code], cwd=directory, env=env, check=True)


if __name__ == "__main__":
    main()

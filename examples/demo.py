"""Offline, deterministic Agent-proposal demonstration. No model or network required."""
import argparse
import json
from pathlib import Path

from papercheck.scaffold import scaffold
from papercheck.storage import Repo
from papercheck.util import sha256_bytes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, help="a new or empty project directory")
    args = parser.parse_args()
    initial = json.loads((Path(__file__).parent / "initial-proposal.json").read_text(encoding="utf-8"))
    root, _ = scaffold(args.root, Path(__file__).parent / "paper.md")
    repo = Repo(root)
    first = repo.commit(proposal=initial)
    old = repo.load_current()
    updated = b"X is associated with Y.\n"
    repo.paper_path.write_bytes(updated)
    second = json.loads(json.dumps(initial))
    second.update(base_state_id=old.state_id, base_sha256=old.manifest["input"]["sha256"], paper_sha256=sha256_bytes(updated))
    segment = second["segments"][0]
    segment.update(container_id=old.containers[0]["id"], block_id=old.blocks[0]["id"], text=updated.decode(),
                   source_ranges=[{"start_byte": 0, "end_byte": len(updated)}])
    segment.pop("block_ref")
    claim = second["semantic"]["claims"][0]
    claim.update(surface_statement=updated.decode().strip())
    claim["canonical_statement"].update(predicate="associated_with", causality="associational")
    second["semantic"]["references"] = []
    second["semantic"]["reference_ids"] = ["REF000001"]
    second["semantic"]["revisions"] = [{"operation": "REPLACEMENT", "status": "confirmed",
        "reason": "因果断言改为相关断言；证据仍未取得，等待核查。",
        "before": [{"claim": "C000001", "placements": [old.snapshot["selections"][0]["placement_id"]]}],
        "after": [{"claim": "c", "segments": ["s"]}]}]
    result = repo.commit(proposal=second)
    assert repo.verify() == []
    print(json.dumps({"root": str(root), "states": [first.state_id, result.state_id],
        "report": result.report_path, "workflow": repo.load_current().snapshot["workflow"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

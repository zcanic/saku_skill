from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__
from .proposal import build_context, validate_proposal
from .state import load_state
from .storage import ConcurrentModification, PapercheckError, Repo, ValidationError
from .util import read_bytes, write_json


def _repo(args: argparse.Namespace) -> Repo:
    return Repo(args.root)


def _print_commit(result) -> None:
    if not result.changed:
        print(f"no changes: {result.state_id} already matches paper.md")
        return
    summary = result.summary
    print(f"committed {result.state_id} (parent {result.parent_state_id})")
    print(f"paper {summary.get('paper_sha256')}")
    print(
        "blocks {blocks_total} (+{blocks_added})  containers {containers_total} (+{containers_added})  variants {variants_total} (+{variants_added})".format(
            **summary
        )
    )
    print(
        "moved {moved}  block_moves {block_moves}  restored {restored}  removed {removed}  splits {splits}  merges {merges}  untracked {untracked_bytes} bytes".format(
            **summary
        )
    )
    if result.report_path:
        print(f"report {result.report_path}")
    if getattr(result, "index_error", None):
        print(f"index error (state committed, derived index stale): {result.index_error}")


def _load_proposal(path: str) -> dict:
    target = Path(path)
    if not target.exists():
        raise PapercheckError(f"proposal not found: {path}")
    data = json.loads(target.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise PapercheckError("proposal must be a JSON object")
    return data


def cmd_init(args: argparse.Namespace) -> int:
    repo = _repo(args)
    proposal = _load_proposal(args.proposal) if args.proposal else None
    result = repo.init(proposal=proposal)
    print(f"initialized {repo.meta}")
    _print_commit(result)
    return 0


def cmd_context(args: argparse.Namespace) -> int:
    repo = _repo(args)
    if not repo.paper_path.exists():
        print(f"missing {repo.paper_path}", file=sys.stderr)
        return 1
    paper_bytes = read_bytes(repo.paper_path)
    try:
        paper_text = paper_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        print(f"paper.md is not valid UTF-8: {exc}", file=sys.stderr)
        return 1
    old = repo.load_current()
    if repo.read_current() and repo.verify():
        raise PapercheckError("CURRENT is invalid; run verify/recover before requesting context")
    context = build_context(old, paper_text, paper_bytes)
    if old is not None:
        from .workflow import current_workflow

        context["workflow"].update(current_workflow(repo, old))
    if getattr(args, "output", None):
        target = Path(args.output).resolve()
        protected_meta = repo.meta.resolve()
        if target == repo.paper_path.resolve() or target == protected_meta or protected_meta in target.parents:
            raise PapercheckError("context output must not overwrite paper.md or files inside .papercheck")
        write_json(target, context)
        print(f"context {args.output}")
    else:
        print(json.dumps(context, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def cmd_propose(args: argparse.Namespace) -> int:
    repo = _repo(args)
    repo.ensure()
    proposal = _load_proposal(args.proposal)
    old = repo.load_current()
    paper_bytes = read_bytes(repo.paper_path)
    issues = validate_proposal(old, paper_bytes, proposal)
    if issues:
        for issue in issues:
            print(f"issue: {issue}", file=sys.stderr)
        return 2
    write_json(repo.staging / "proposal.json", proposal)
    print(f"staged {repo.staging / 'proposal.json'}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    repo = _repo(args)
    path = Path(args.proposal) if args.proposal else repo.staging / "proposal.json"
    if not path.exists():
        print(f"proposal not found: {path}", file=sys.stderr)
        return 1
    proposal = _load_proposal(str(path))
    old = repo.load_current()
    paper_bytes = read_bytes(repo.paper_path)
    issues = validate_proposal(old, paper_bytes, proposal)
    if issues:
        for issue in issues:
            print(f"issue: {issue}", file=sys.stderr)
        return 2
    print(f"ok: {path}")
    return 0


def cmd_commit(args: argparse.Namespace) -> int:
    repo = _repo(args)
    proposal = None
    auto = bool(args.auto)
    if args.proposal:
        proposal = _load_proposal(args.proposal)
    elif not auto:
        staged = repo.staging / "proposal.json"
        if staged.exists():
            proposal = _load_proposal(str(staged))
        else:
            print("no proposal staged; pass --proposal <file> or --auto", file=sys.stderr)
            return 2
    try:
        result = repo.commit(message=args.message, proposal=proposal, auto=auto)
    except ConcurrentModification as exc:
        print(f"not committed: {exc}", file=sys.stderr)
        return 3
    _print_commit(result)
    if result.changed:
        staged = repo.staging / "proposal.json"
        if staged.exists():
            staged.unlink()
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    repo = _repo(args)
    status = repo.status()
    if not status.get("initialized"):
        print(f"not initialized: {repo.meta}")
        return 1
    print(f"root        {status['root']}")
    print(f"current     {status['current']}")
    print(f"valid       {status['valid']}")
    print(f"working copy changed: {status.get('working_copy', {}).get('changed', False)}")
    print(f"paper       {status.get('paper_sha256')} ({status.get('paper_size')} bytes)")
    if "blocks" in status:
        print(
            "objects     blocks {blocks} containers {containers} variants {variants} selections {selections} untracked {untracked}".format(
                **status
            )
        )
    print(f"index       {status.get('index_state_id')}")
    for issue in status.get("issues", []):
        print(f"issue       {issue}")
    return 0 if status["valid"] else 1


def cmd_verify(args: argparse.Namespace) -> int:
    repo = _repo(args)
    issues = repo.verify()
    if not issues:
        print(f"ok: {repo.read_current()}")
        return 0
    for issue in issues:
        print(f"issue: {issue}")
    return 1


def cmd_recover(args: argparse.Namespace) -> int:
    repo = _repo(args)
    state_id = repo.recover()
    print(f"recovered {state_id}")
    return 0


def cmd_rebuild_index(args: argparse.Namespace) -> int:
    import os

    repo = _repo(args)
    try:
        path = repo.rebuild_index()
    except Exception as exc:  # noqa: BLE001 - CLI diagnostic
        raise PapercheckError(f"index rebuild failed: {exc}") from exc
    from .index import query_counts

    target = os.environ.get("PAPERCHECK_DATABASE_URL") or path
    counts = query_counts(target)
    print(f"indexed {path}")
    for key, value in counts.items():
        print(f"{key} {value}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    repo = _repo(args)
    state_id = args.state or repo.read_current()
    if not state_id:
        print("no current state", file=sys.stderr)
        return 1
    path = repo.states / state_id
    if not path.is_dir():
        candidate = Path(state_id)
        if candidate.is_dir():
            path = candidate
        else:
            print(f"state not found: {state_id}", file=sys.stderr)
            return 1
    state = load_state(path)
    payload = {
        "manifest": state.manifest,
        "snapshot": state.snapshot,
        "paper_text": state.paper_text,
        "records": {key: getattr(state, key) for key in (
            "claims", "bindings", "revisions", "relations", "references", "evidence",
            "assessments", "quantities", "checks", "arguments", "reviews", "invalidations", "runs")},
        "current_claims": [{**c, "flags": [f for f in c.get("flags", []) if f != "replacement"] +
            (["replacement"] if c["id"] in state.snapshot.get("replacement_claim_ids", []) else [])}
            for c in state.claims if c["id"] in state.snapshot.get("claim_ids", [])],
        "counts": {
            "blocks": len(state.blocks),
            "containers": len(state.containers),
            "variants": len(state.variants),
            "events": len(state.events),
        },
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"state      {state.state_id}")
        print(f"snapshot   {state.snapshot_id}")
        print(f"paper      {state.manifest.get('input', {}).get('sha256')}")
        print(f"blocks     {len(state.blocks)}")
        print(f"containers {len(state.containers)}")
        print(f"variants   {len(state.variants)}")
        print(f"events     {len(state.events)}")
        print("selections")
        for sel in state.snapshot.get("selections", []):
            rng = sel["source_ranges"][0]
            print(
                f"  {sel['placement_id']} {sel['container_id']} {sel['variant_id']} "
                f"{rng['start_byte']}-{rng['end_byte']}"
            )
    return 0


def cmd_scaffold(args):
    from .scaffold import scaffold

    root, names = scaffold(args.destination, args.paper)
    print(f"created {root}")
    for name in names:
        print(name)
    return 0


def cmd_workflow(args):
    from .workflow import current_workflow
    repo = _repo(args)
    issues = repo.verify()
    if issues:
        raise ValidationError(issues)
    state = repo.load_current()
    workflow = current_workflow(repo, state)
    if args.json:
        print(json.dumps({"state_id": state.state_id, **workflow}, ensure_ascii=False, indent=2))
    else:
        from collections import Counter

        tasks = workflow["tasks"]
        print(f"workflow {state.state_id}: {workflow['status']} ({len(tasks)} tasks)")
        for (kind, status), count in Counter((t["type"], t["status"]) for t in tasks).items():
            print(f"  {count:>5} {status} {kind}")
        selected = [t for t in tasks if not args.type or t["type"] in args.type]
        # Blocking items first so they are not lost behind hundreds of extraction tasks.
        selected.sort(key=lambda t: t["status"] != "action_required")
        shown = selected[:args.limit] if args.limit else selected
        for task in shown:
            print(f"{task['status']} {task['type']} {task['target']}: {task['reason']}")
        if len(shown) < len(selected):
            print(f"... {len(selected) - len(shown)} more; use --limit 0, --type or --json")
    return 0


def cmd_report(args):
    from .report import write_report

    repo = _repo(args)
    if repo.verify():
        raise ValidationError(repo.verify())
    state = repo.load_current()
    summary = state.runs[-1].get("summary", {}) if state.runs else {}
    print(write_report(repo, state, summary))
    return 0


def cmd_inspector(args):
    from .inspector import init_inspector, export_inspector, package_inspector, serve_inspector
    repo = _repo(args)
    if args.action == 'init':
        print(init_inspector(repo, args.directory))
    elif args.action == 'export':
        print(json.dumps(export_inspector(repo, args.directory, args.pdf, args.release_id), ensure_ascii=False, indent=2))
    elif args.action == 'package':
        print(package_inspector(repo, args.output, args.directory, args.release_only))
    else:
        return serve_inspector(repo, args.directory, args.port, args.node)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="papercheck", description=__doc__)
    parser.add_argument("--root", default=".", help="project root containing paper.md")
    parser.add_argument("--version", action="version", version=f"papercheck {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser('inspector', help='create, export, preview or package the read-only inspection website')
    actions = p.add_subparsers(dest='action', required=True)
    for action in ['init', 'export', 'serve', 'package']:
        command = actions.add_parser(action)
        command.add_argument('--directory', default='inspector')
        command.set_defaults(func=cmd_inspector)
        if action == 'export':
            command.add_argument('--pdf', help='optional existing PDF matching this manuscript')
            command.add_argument('--release-id')
        elif action == 'serve':
            command.add_argument('--port', type=int, default=4178)
            command.add_argument('--node', default='node')
        elif action == 'package':
            command.add_argument('--output', required=True)
            command.add_argument('--release-only', action='store_true', help='data-only ZIP for an existing deployment')

    p = sub.add_parser("scaffold", help="create a reusable project folder without overwriting files")
    p.add_argument("destination")
    p.add_argument("--paper", help="copy an existing UTF-8 manuscript")
    p.set_defaults(func=cmd_scaffold)

    p = sub.add_parser("workflow", help="show pending work and review gaps")
    p.add_argument("--json", action="store_true")
    p.add_argument("--type", action="append", help="only list tasks of this type (repeatable)")
    p.add_argument("--limit", type=int, default=0, help="list at most N tasks after the summary (0 = all)")
    p.set_defaults(func=cmd_workflow)

    p = sub.add_parser("report", help="rebuild the current human-readable report")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("init", help="create .papercheck and commit the first state")
    p.add_argument("--proposal", default=None, help="agent proposal JSON for the first state")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("context", help="emit the frozen agent context as JSON")
    p.add_argument("--output", help="write UTF-8 JSON directly (safe on Windows PowerShell)")
    p.set_defaults(func=cmd_context)

    p = sub.add_parser("propose", help="validate a proposal and stage it")
    p.add_argument("proposal")
    p.set_defaults(func=cmd_propose)

    p = sub.add_parser("validate", help="validate a proposal file or the staged proposal")
    p.add_argument("--proposal", default=None)
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("commit", help="commit a validated proposal or the automatic baseline")
    p.add_argument("--proposal", default=None)
    p.add_argument("--auto", action="store_true", help="use the deterministic parser/alignment baseline")
    p.add_argument("-m", "--message", default=None)
    p.set_defaults(func=cmd_commit)

    p = sub.add_parser("status", help="show current state summary")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("verify", help="validate CURRENT and its state")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("recover", help="restore CURRENT from the commit log")
    p.set_defaults(func=cmd_recover)

    p = sub.add_parser("rebuild-index", help="rebuild the query index")
    p.set_defaults(func=cmd_rebuild_index)

    p = sub.add_parser("show", help="print a state, snapshot and selections")
    p.add_argument("--state", default=None)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_show)
    return parser


def main(argv: list[str] | None = None) -> int:
    # Pipes on Windows otherwise default to a locale encoding, corrupting JSON.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except ValidationError as exc:
        for issue in exc.issues:
            print(f"issue: {issue}", file=sys.stderr)
        return 2
    except PapercheckError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except BrokenPipeError:
        # `papercheck workflow | head` closed the pipe; that is not a command failure.
        sys.stdout = open(os.devnull, "w")
        return 0
    except (OSError, ValueError, UnicodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

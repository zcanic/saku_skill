from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .align import build_state
from .ids import next_state_id
from .markdown import parse_document
from .state import StateView, load_state, manifest_digest, validate_state, write_state_dir
from .util import (
    append_jsonl,
    atomic_write_text,
    exclusive_lock,
    now_iso,
    read_jsonl,
    read_bytes,
    sha256_bytes,
    sha256_file,
    write_json,
    write_jsonl,
)


class PapercheckError(RuntimeError):
    pass


class ValidationError(PapercheckError):
    def __init__(self, issues: list[str]):
        self.issues = issues
        super().__init__("state validation failed:\n" + "\n".join(f"- {issue}" for issue in issues))


class ConcurrentModification(PapercheckError):
    pass


@dataclass
class CommitResult:
    changed: bool
    state_id: str | None
    parent_state_id: str | None = None
    summary: dict[str, Any] = field(default_factory=dict)
    report_path: str | None = None
    index_error: str | None = None
    issues: list[str] = field(default_factory=list)


def _fault(stage: str) -> None:
    if os.environ.get("PAPERCHECK_FAULT") == stage:
        raise PapercheckError(f"injected fault at {stage}")


class Repo:
    def __init__(self, root: str | Path = ".") -> None:
        self.root = Path(root).resolve()
        from .util import load_env_file

        load_env_file(self.root / ".env")
        self.meta = self.root / ".papercheck"
        self.states = self.meta / "states"
        self.staging = self.meta / "staging"
        self.recovery = self.meta / "recovery"
        self.reports = self.meta / "reports"
        self.index_path = self.meta / "index.sqlite"
        self.current_path = self.meta / "CURRENT"
        self.lock_path = self.meta / "lock"
        self.paper_path = self.root / "paper.md"

    def ensure(self) -> None:
        for path in (self.meta, self.states, self.staging, self.recovery, self.reports):
            path.mkdir(parents=True, exist_ok=True)

    def read_current(self) -> str | None:
        if not self.current_path.exists():
            return None
        text = self.current_path.read_text(encoding="utf-8").strip()
        return text or None

    def write_current(self, state_id: str) -> None:
        atomic_write_text(self.current_path, state_id + "\n")

    def load_current(self) -> StateView | None:
        state_id = self.read_current()
        if not state_id:
            return None
        path = self.states / state_id
        if not path.is_dir():
            return None
        return load_state(path)

    def state_dirs(self) -> list[Path]:
        if not self.states.exists():
            return []
        return sorted(path for path in self.states.iterdir() if path.is_dir())

    def verify(self) -> list[str]:
        state_id = self.read_current()
        if not state_id:
            return ["CURRENT is missing"]
        path = self.states / state_id
        if not path.is_dir():
            return [f"CURRENT points at missing state {state_id}"]
        return validate_state(path)

    def init(self, *, proposal: dict[str, Any] | None = None) -> CommitResult:
        self.ensure()
        if not self.paper_path.exists():
            atomic_write_text(self.paper_path, "")
        return self.commit(message="initial state", proposal=proposal, auto=proposal is None)

    def commit(
        self,
        *,
        message: str | None = None,
        proposal: dict[str, Any] | None = None,
        auto: bool = False,
    ) -> CommitResult:
        self.ensure()
        with exclusive_lock(self.lock_path):
            parent_id = self.read_current()
            old: StateView | None = None
            if parent_id:
                path = self.states / parent_id
                if not path.is_dir():
                    raise PapercheckError(f"CURRENT points at missing state {parent_id}")
                old = load_state(path)
                issues = validate_state(path)
                if issues:
                    # A broken parent must not be silently extended.
                    raise ValidationError(issues)

            if not self.paper_path.exists():
                raise PapercheckError(f"missing {self.paper_path}")
            paper_bytes = read_bytes(self.paper_path)
            paper_sha = sha256_bytes(paper_bytes)
            if proposal is None and old is not None and old.manifest.get("input", {}).get("sha256") == paper_sha:
                return CommitResult(
                    changed=False,
                    state_id=old.state_id,
                    parent_state_id=old.state_id,
                    summary={
                        "state_id": old.state_id,
                        "paper_sha256": paper_sha,
                        "blocks_total": len(old.blocks),
                        "containers_total": len(old.containers),
                        "variants_total": len(old.variants),
                    },
                )

            try:
                text = paper_bytes.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise PapercheckError(f"paper.md is not valid UTF-8: {exc}") from exc
            state_id = next_state_id(self.states)
            if proposal is not None:
                from .proposal import build_from_proposal, validate_proposal

                proposal_issues = validate_proposal(old, paper_bytes, proposal)
                if proposal_issues:
                    raise ValidationError(proposal_issues)
                sources, summary = build_from_proposal(
                    old,
                    text=text,
                    paper_bytes=paper_bytes,
                    proposal=proposal,
                    state_id=state_id,
                    message=message,
                )
            elif auto:
                blocks = parse_document(text)
                sources, summary = build_state(
                    old,
                    text=text,
                    paper_bytes=paper_bytes,
                    blocks=blocks,
                    state_id=state_id,
                    message=message,
                )
            else:
                raise PapercheckError("commit requires a validated proposal (--proposal) or --auto")
            from .semantic import SemanticError, enrich

            try:
                sources, summary = enrich(old, sources, proposal, summary)
            except SemanticError as exc:
                raise ValidationError([str(exc)]) from exc
            run_id = summary.get("run_id") or f"RUN{state_id[1:]}"
            stage = self.staging / state_id
            if stage.exists():
                shutil.rmtree(stage)
            write_state_dir(
                stage,
                state_id=state_id,
                parent_state_id=parent_id,
                paper_bytes=paper_bytes,
                sources=sources,
                snapshot_id=summary["snapshot_id"],
                message=message,
            )
            _fault("after_stage")

            issues = validate_state(stage)
            if issues:
                raise ValidationError(issues)

            # The author may have saved again while we were working.
            if self.read_current() != parent_id or sha256_file(self.paper_path) != paper_sha:
                raise ConcurrentModification("paper.md or CURRENT changed during commit; retry")

            final = self.states / state_id
            if final.exists():
                raise PapercheckError(f"state already exists: {final}")
            os.replace(stage, final)
            _fault("after_publish")

            manifest_hash = manifest_digest(final)
            log_path = self.recovery / "commit-log.jsonl"
            from .util import read_jsonl_tolerant

            # Repair an interrupted append before adding another record; otherwise
            # the truncated tail would become an unrecoverable malformed middle line.
            write_jsonl(log_path, read_jsonl_tolerant(log_path))
            append_jsonl(
                log_path,
                {
                    "state_id": state_id,
                    "parent_state_id": parent_id,
                    "manifest_sha256": manifest_hash,
                    "paper_sha256": paper_sha,
                    "run_id": run_id,
                    "created_at": now_iso(),
                },
            )
            _fault("before_current")
            self.write_current(state_id)
            _fault("after_current")

            report_path = None
            try:
                from .report import write_report

                report_path = str(write_report(self, load_state(final), summary))
            except Exception:
                report_path = None
            index_error = None
            try:
                self.rebuild_index()
            except Exception as exc:  # noqa: BLE001 - surface, do not roll back the commit
                index_error = str(exc)
            return CommitResult(
                changed=True,
                state_id=state_id,
                parent_state_id=parent_id,
                summary=summary,
                report_path=report_path,
                index_error=index_error,
            )

    def recover(self) -> str:
        self.ensure()
        with exclusive_lock(self.lock_path):
            return self._recover_locked()

    def _recover_locked(self) -> str:
        current = self.read_current()
        if current:
            path = self.states / current
            if path.is_dir() and not validate_state(path):
                return current

        from .util import read_jsonl_tolerant

        log = read_jsonl_tolerant(self.recovery / "commit-log.jsonl")
        for row in reversed(log):
            state_id = row.get("state_id")
            if not state_id:
                continue
            path = self.states / state_id
            if not path.is_dir():
                continue
            expected_digest = row.get("manifest_sha256")
            if expected_digest:
                try:
                    if manifest_digest(path) != expected_digest:
                        continue
                except OSError:
                    continue
            if not validate_state(path):
                self.write_current(state_id)
                return state_id

        if log:
            raise PapercheckError("no valid state matching the recovery log; refusing unlogged candidates")
        # Last resort only when no recovery records exist.
        for path in reversed(self.state_dirs()):
            if not validate_state(path):
                self.write_current(path.name)
                return path.name
        raise PapercheckError("no valid committed state to recover")

    def rebuild_index(self) -> Path | str:
        issues = self.verify()
        if issues:
            raise ValidationError(issues)
        state = self.load_current()
        if state is None:
            raise PapercheckError("no current state")
        database_url = os.environ.get("PAPERCHECK_DATABASE_URL")
        if database_url:
            from .index import rebuild_postgres

            return rebuild_postgres(state, database_url)
        from .index import rebuild_index

        return rebuild_index(state, self.index_path)

    def status(self) -> dict[str, Any]:
        state_id = self.read_current()
        out: dict[str, Any] = {
            "root": str(self.root),
            "current": state_id,
            "initialized": state_id is not None,
        }
        if not state_id:
            return out
        path = self.states / state_id
        issues = validate_state(path) if path.is_dir() else [f"missing state {state_id}"]
        out["valid"] = not issues
        out["issues"] = issues
        out["working_copy"] = self.working_copy_status()
        if path.is_dir():
            state = load_state(path)
            out.update(
                {
                    "paper_sha256": state.manifest.get("input", {}).get("sha256"),
                    "paper_size": len(state.paper_bytes),
                    "blocks": len(state.blocks),
                    "containers": len(state.containers),
                    "variants": len(state.variants),
                    "snapshot": state.snapshot_id,
                    "selections": len(state.snapshot.get("selections", [])),
                    "untracked": len(state.snapshot.get("untracked_blocks", [])),
                }
            )
        from .index import indexed_state

        database_url = os.environ.get("PAPERCHECK_DATABASE_URL")
        if database_url:
            out["index_target"] = "postgres"
            out["index_state_id"] = indexed_state(database_url)
        elif self.index_path.exists():
            out["index_target"] = str(self.index_path)
            out["index_state_id"] = indexed_state(self.index_path)
        else:
            out["index_target"] = None
            out["index_state_id"] = None
        return out

    def working_copy_status(self, state: StateView | None = None) -> dict[str, Any]:
        state = state or self.load_current()
        frozen_hash = state.manifest.get("input", {}).get("sha256") if state else None
        exists = self.paper_path.is_file()
        current_hash = sha256_file(self.paper_path) if exists else None
        return {"exists": exists, "sha256": current_hash, "committed_sha256": frozen_hash,
                "changed": current_hash != frozen_hash or not exists}

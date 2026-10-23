"""Exercise the public CLI as an external Agent using explicitly synthetic material.

Writes a reproducible project and command transcript into a new output directory.
No model, remote service or application internals are used to construct proposals.
"""
import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def sha(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def write_json(path, data):
    path.write_bytes((json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode())


def canonical(predicate, quantity=None):
    return {"subject": {"entity_id": "sample" if quantity else "X"}, "predicate": predicate,
            "object": {"entity_id": "sample_size" if quantity else "Y"}, "polarity": "positive",
            "modality": "asserted", "causality": "not_applicable" if quantity else (
                "causal" if predicate == "causes" else "associational"), "quantifier": None,
            "population": "synthetic_test_population", "time_scope": None, "conditions": [],
            "quantity_ids": [quantity] if quantity else []}


class PracticalCheck:
    def __init__(self, output, package_path):
        self.output = output.resolve()
        if self.output.exists():
            raise ValueError("choose a new output directory")
        self.output.mkdir(parents=True)
        self.root = self.output / "中文论文 工作区"
        self.env = {**os.environ, "PYTHONPATH": str(package_path.resolve()), "PYTHONIOENCODING": "utf-8"}
        for name in ["PAPERCHECK_DATABASE_URL", "PAPERCHECK_FAULT"]:
            self.env.pop(name, None)
        self.commands = []
        self.observations = []
        self.identity = {}
        self.blocks = {}
        self.seen_variants = {}
        self.frozen = {}

    def cli(self, *args, code=0, parse=False, project=True):
        argv = [sys.executable, "-m", "papercheck", *args]
        result = subprocess.run(argv, cwd=self.root if project else self.output, env=self.env,
                                capture_output=True, text=True, encoding="utf-8")
        self.commands.append({"args": list(args), "exit_code": result.returncode,
                              "stdout": result.stdout, "stderr": result.stderr})
        write_json(self.output / "commands.json", self.commands)
        assert result.returncode == code, (args, result.stdout, result.stderr)
        return json.loads(result.stdout) if parse else result.stdout

    def observe(self, name, **details):
        self.observations.append({"scenario": name, "status": "passed", **details})
        write_json(self.output / "results.json", self.observations)

    def paper(self, method="3038", predicate="causes", order=None, include_conclusion=True):
        parts = {
            "title": "# 实践检查：合成数据示例\r\n",
            "abstract": "摘要：样本量 N=3038。\r\n",
            "methods": f"方法：样本量 N={method}。\r\n",
            "conclusion": "结论：X 导致 Y。\r\n" if predicate == "causes" else "结论：X 与 Y 相关。\r\n",
        }
        order = order or ["title", "abstract", "methods", "conclusion"]
        if not include_conclusion:
            order = [part for part in order if part != "conclusion"]
        body = "\r\n".join(parts[name] for name in order)
        body += "\r\n```text\r\n测试代码块，暂不抽取。\r\n```\r\n"
        data = body.encode()
        (self.root / "paper.md").write_bytes(data)
        return data, {name: parts[name].encode() for name in order}

    def context(self, number):
        path = self.root / f"context-{number}.json"
        self.cli("context", "--output", str(path))
        context = json.loads(path.read_text(encoding="utf-8"))
        for selection in context["old_selections"]:
            self.blocks[selection["container_id"]] = selection["block_id"]
        for variant in context["historical_variants"]:
            self.seen_variants[(variant["container_id"], variant["raw_text"])] = variant["id"]
        return context

    def make_proposal(self, context, data, parts, predicate="causes", references=None):
        segments, intervals = [], []
        for ref, raw in parts.items():
            start = data.index(raw)
            segment = {"ref": ref, "kind": "heading" if ref == "title" else "paragraph",
                       "source_ranges": [{"start_byte": start, "end_byte": start + len(raw)}]}
            if ref in self.identity:
                cid = self.identity[ref]
                segment.update(container_id=cid, block_id=self.blocks[cid])
                vid = self.seen_variants.get((cid, raw.decode()))
                if vid:
                    segment["variant_id"] = vid
            else:
                segment["block_ref"] = ref
            segments.append(segment)
            intervals.append((start, start + len(raw)))
        untracked, cursor = [], 0
        for start, end in sorted(intervals):
            if cursor < start:
                untracked.append({"start_byte": cursor, "end_byte": start, "reason": "whitespace"})
            cursor = end
        if cursor < len(data):
            untracked.append({"start_byte": cursor, "end_byte": len(data), "reason": "deferred:code_block"})
        quantities, claims, bindings = [], [], []
        for ref in ["abstract", "methods"]:
            raw = parts[ref].decode()
            value = "3012" if "3012" in raw else "3038"
            quantities.append({"ref": f"q-{ref}", "claim": ref, "metric_id": "sample_size",
                "value": {"type": "point", "value_decimal": value}, "unit": "person", "segment": ref,
                "source_expression": "N=" + value, "extraction_status": "confirmed",
                "population": "synthetic_test_population", "dataset_id": "synthetic_fixture",
                "dataset_version": "v1", "sample_filter": "all", "time_scope": None})
            claims.append({"ref": ref, "surface_statement": raw.strip(),
                           "canonical_statement": canonical("sample_size", f"q-{ref}")})
            bindings.append({"claim": ref, "segment": ref, "reason": "Agent read this synthetic sample-size statement."})
        if "conclusion" in parts:
            claims.append({"ref": "relation", "surface_statement": parts["conclusion"].decode().strip(),
                           "canonical_statement": canonical(predicate)})
            bindings.append({"claim": "relation", "segment": "conclusion", "reason": "Agent read the relation assertion."})
        semantic = {"claims": claims, "quantities": quantities, "bindings": bindings,
                    "non_claim_segments": [{"segment": "title", "reason": "Document title"}],
                    "reference_ids": references or []}
        return {"schema_version": "1.1.0", "base_state_id": context["base_state_id"],
                "base_sha256": context["base_sha256"], "paper_sha256": sha(data),
                "segments": segments, "untracked": untracked, "semantic": semantic,
                "agent_note": "Explicitly synthetic fixture; no real research findings asserted."}

    def commit(self, number, proposal):
        path = self.root / f"proposal-{number}.json"
        write_json(path, proposal)
        before = (self.root / "paper.md").read_bytes()
        self.cli("validate", "--proposal", str(path))
        self.cli("propose", str(path))
        self.cli("commit")
        self.cli("verify")
        self.cli("status")
        shown = self.cli("show", "--json", parse=True)
        assert (self.root / "paper.md").read_bytes() == before
        assert shown["paper_text"].encode() == before
        placements = {tuple((r["start_byte"], r["end_byte"]) for r in s["source_ranges"]): s
                      for s in shown["snapshot"]["selections"]}
        for segment in proposal["segments"]:
            key = tuple((r["start_byte"], r["end_byte"]) for r in segment["source_ranges"])
            self.identity[segment["ref"]] = placements[key]["container_id"]
        for previous in self.frozen:
            assert self.state_digest(previous) == self.frozen[previous], f"historical state changed: {previous}"
        state_id = shown["manifest"]["state_id"]
        self.frozen[state_id] = self.state_digest(state_id)
        self.cli("workflow", "--json", parse=True)
        self.cli("report")
        return shown

    def state_digest(self, state_id):
        path = self.root / ".papercheck" / "states" / state_id
        return {str(p.relative_to(path)): sha(p.read_bytes()) for p in path.rglob("*") if p.is_file()}

    def run(self):
        probe = subprocess.run([sys.executable, "-c", "import json, papercheck; print(json.dumps({'module': papercheck.__file__, 'version': papercheck.__version__}))"],
                               cwd=self.output, env=self.env, capture_output=True, text=True, encoding="utf-8", check=True)
        runtime = json.loads(probe.stdout)
        assert Path(runtime["module"]).resolve().is_relative_to(Path(self.env["PYTHONPATH"]))
        write_json(self.output / "runtime.json", runtime)
        self.cli("scaffold", str(self.root), project=False)
        data, parts = self.paper()
        initial = self.make_proposal(self.context(1), data, parts)
        initial["semantic"]["references"] = [{"ref": "missing", "title": "合成测试材料（尚未提供）", "source_access": "unavailable"}]
        bom_proposal = self.root / "proposal-bom.json"
        bom_proposal.write_bytes(b"\xef\xbb\xbf" + json.dumps(initial, ensure_ascii=False).encode())
        self.cli("validate", "--proposal", str(bom_proposal))
        self.observe("windows_utf8_bom_proposal_is_accepted")
        first = self.commit(1, initial)
        assert len(first["current_claims"]) == 2  # Same N in two locations shares one identity.
        assert any(t["type"] == "obtain_source" for t in first["snapshot"]["workflow"]["tasks"])
        self.observe("chinese_crlf_baseline_and_missing_source", state=first["manifest"]["state_id"])
        for target in [self.root / "paper.md", self.root / ".papercheck" / "CURRENT"]:
            frozen = target.read_bytes()
            self.cli("context", "--output", str(target), code=2)
            assert target.read_bytes() == frozen
        self.observe("context_cannot_overwrite_paper_or_current")

        data, parts = self.paper("3012", "associated_with")
        stale_current = (self.root / ".papercheck" / "CURRENT").read_bytes()
        self.cli("validate", "--proposal", str(self.root / "proposal-1.json"), code=2)
        assert (self.root / ".papercheck" / "CURRENT").read_bytes() == stale_current
        self.observe("stale_proposal_rejected")
        revised = self.make_proposal(self.context(2), data, parts, "associated_with", ["REF000001"])
        second = self.commit(2, revised)
        checks = [c for c in second["records"]["checks"] if c["id"] in second["snapshot"]["check_ids"]]
        assert any(c["kind"] == "quantity_consistency" and c["outcome"] == "conflict" for c in checks)
        assert len(second["records"]["revisions"]) == 2
        self.observe("numeric_conflict_and_causal_replacement_candidates")

        # This local file is test material, not a purported real paper.
        source = self.root / "references" / "合成实验记录.md"
        source_text = "# 合成实验记录（仅测试）\n样本量 N=3038。\nX 与 Y 相关，不作因果推断。\n"
        source.write_bytes(source_text.encode())
        data, parts = self.paper("3038", "associated_with")
        restored = self.make_proposal(self.context(3), data, parts, "associated_with")
        restored["semantic"].update(
            references=[{"ref": "local", "title": "合成实验记录（仅测试）", "source_access": "full_text",
                         "path": "references/合成实验记录.md", "file_sha256": sha(source.read_bytes())}],
            evidence=[{"ref": "n-source", "reference": "local", "quote": "样本量 N=3038。", "locator": {"path": "references/合成实验记录.md", "line": 2}},
                      {"ref": "relation-source", "reference": "local", "quote": "X 与 Y 相关，不作因果推断。", "locator": {"path": "references/合成实验记录.md", "line": 3}}],
            assessments=[{"claim": "abstract", "evidence": "n-source", "status": "supported", "reason": "Read the explicitly synthetic local fixture, line 2."},
                         {"claim": "relation", "evidence": "relation-source", "status": "supported", "reason": "Read the explicitly synthetic local fixture, line 3."}],
            revision_decisions=[{"revision_id": r["id"], "status": "confirmed" if any(
                second_claim["canonical_statement"]["predicate"] == "associated_with"
                for entry in r["after"] for second_claim in second["records"]["claims"] if second_claim["id"] == entry["claim_id"]
            ) else "rejected", "reason": "Reviewed against synthetic fixture; accept association, reject the erroneous sample size."}
                for r in second["records"]["revisions"]])
        third = self.commit(3, restored)
        assert third["snapshot"]["workflow"]["status"] == "completed", third["snapshot"]["workflow"]
        assert len(third["snapshot"]["replacement_claim_ids"]) == 1
        self.observe("fixture_evidence_and_candidate_decisions_close_pending_work")

        data, parts = self.paper("3038", "associated_with", ["title", "methods", "abstract", "conclusion"])
        live_workflow = self.cli("workflow", "--json", parse=True)
        assert live_workflow["working_copy_changed"] and live_workflow["status"] == "pending"
        moved_context = self.context(4)
        assert moved_context["workflow"]["status"] == "pending"
        self.observe("uncommitted_edits_never_appear_as_completed")
        moved = self.make_proposal(moved_context, data, parts, "associated_with", ["REF000002"])
        fourth = self.commit(4, moved)
        assert fourth["snapshot"]["workflow"]["status"] == "completed"
        assert fourth["snapshot"]["claim_ids"] == third["snapshot"]["claim_ids"]
        assert fourth["records"]["runs"][-1]["summary"]["checks_reused"] >= 2
        self.observe("paragraph_move_preserves_identity_and_reuses_checks")

        data, parts = self.paper("3038", "associated_with", include_conclusion=False)
        deletion = self.make_proposal(self.context(5), data, parts, "associated_with", ["REF000002"])
        fifth = self.commit(5, deletion)
        assert len(fifth["current_claims"]) == 1
        assert fifth["records"]["invalidations"]
        self.observe("delete_shortens_document_without_erasing_history")

        data, parts = self.paper("3038", "causes")
        restore = self.make_proposal(self.context(6), data, parts, "causes", ["REF000002"])
        restore["semantic"]["revisions"] = [{"operation": "RESTORE", "status": "confirmed", "reason": "Restore original text to test identity, not to endorse causality.",
            "before": [], "after": [{"claim": "relation", "segments": ["conclusion"]}]}]
        sixth = self.commit(6, restore)
        original_relation = next(c["id"] for c in first["current_claims"] if c["canonical_statement"]["predicate"] == "causes")
        assert original_relation in sixth["snapshot"]["claim_ids"]
        assert sixth["snapshot"]["workflow"]["status"] == "pending"
        assert len([r for r in sixth["records"]["relations"] if r["type"] == "REPLACES"]) == len(
            [r for r in fifth["records"]["relations"] if r["type"] == "REPLACES"])
        self.observe("restore_keeps_original_identity_and_requires_new_causal_evidence")

        previous = self.cli("show", "--state", "D000001", "--json", parse=True)
        assert previous["paper_text"] == first["paper_text"]
        assert previous["snapshot"]["claim_ids"] == first["snapshot"]["claim_ids"]
        self.observe("historical_paper_and_claims_are_recoverable")
        (self.root / ".papercheck" / "index.sqlite").unlink()
        self.cli("rebuild-index")
        self.observe("index_can_be_deleted_and_rebuilt")
        (self.root / ".papercheck" / "CURRENT").write_bytes(b"D999999\n")
        with (self.root / ".papercheck" / "recovery" / "commit-log.jsonl").open("ab") as stream:
            stream.write(b'{"state_id":')
        self.cli("verify", code=1)
        self.cli("status", code=1)
        self.cli("recover")
        self.cli("verify")
        assert (self.root / ".papercheck" / "CURRENT").read_text().strip() == "D000006"
        assert all(self.state_digest(sid) == digest for sid, digest in self.frozen.items())
        self.observe("recovery_with_truncated_log_preserves_all_frozen_sources")
        assert all((self.root / p).exists() for p in ["contracts/proposal.schema.json", "contracts/records.schema.json", "workflow/05-semantic-contract.md"]), "standalone template lacks its full contract"
        self.observe("standalone_agent_can_read_full_contract")
        write_json(self.output / "summary.json", {"status": "passed", "scenarios": len(self.observations),
                   "cli_calls": len(self.commands), "states": len(self.frozen), "project": str(self.root)})
        return self.output / "summary.json"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--package-path", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    check = PracticalCheck(args.output, args.package_path)
    try:
        path = check.run()
    except Exception as exc:
        write_json(check.output / "failure.json", {"type": type(exc).__name__, "message": str(exc)})
        raise
    print(path)


if __name__ == "__main__":
    main()

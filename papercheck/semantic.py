"""Versioned semantic ledger for an external Agent, with conservative identity rules."""
from copy import deepcopy
import unicodedata

from . import CANONICALIZER_VERSION, SCHEMA_VERSION
from .ids import PREFIXES, max_id
from .quantity import decimal, quantity_checks, validate_quantity
from .util import canonical_json, now_iso, sha256_text

CANONICAL_FIELDS = {"subject", "predicate", "object", "polarity", "modality", "causality",
                    "quantifier", "population", "time_scope", "conditions", "quantity_ids"}
KINDS = {"claims": "claim", "references": "reference", "evidence": "evidence",
         "quantities": "quantity", "assessments": "assessment", "relations": "relation",
         "revisions": "revision", "bindings": "binding", "checks": "check", "arguments": "argument",
         "reviews": "review", "invalidations": "invalidation", "events": "event"}


class SemanticError(ValueError):
    pass


def _need(condition, message):
    if not condition:
        raise SemanticError(message)


def _unknown(value):
    if isinstance(value, str):
        return value.casefold() in {"unknown", "未知"}
    if isinstance(value, dict):
        return value.get("unknown") is True or any(_unknown(v) for v in value.values())
    if isinstance(value, list):
        return any(_unknown(v) for v in value)
    return False


def _normalize(value, key=""):
    if isinstance(value, str):
        return unicodedata.normalize("NFC", " ".join(value.split()))
    if isinstance(value, dict):
        return {k: _normalize(v, k) for k, v in value.items()}
    if isinstance(value, list):
        result = [_normalize(v) for v in value]
        # Only these fields are explicitly sets; argument order remains significant.
        return sorted(result, key=canonical_json) if key in {"conditions", "quantity_ids"} else result
    return value


def fingerprint(statement, quantities):
    if not CANONICAL_FIELDS.issubset(statement) or _unknown(statement):
        return None
    if any(statement[k] is None for k in ("subject", "predicate", "object", "polarity", "modality", "causality")):
        return None
    value = _normalize(statement)
    resolved = []
    for qid in value["quantity_ids"]:
        _need(qid in quantities, f"canonical quantity {qid} does not exist")
        quantity = quantities[qid]
        from .quantity import SCOPE
        if quantity.get("extraction_status") != "confirmed" or any(k not in quantity or quantity[k] == "unknown" for k in SCOPE):
            return None
        comparable = {k: v for k, v in quantity.items() if k in {
            "metric_id", "value", "unit", "operator", "population", "dataset_id", "dataset_version",
            "sample_filter", "time_scope", "percent_base", "tolerance_decimal"}}
        comparable = deepcopy(comparable)
        for key in ("value_decimal", "value_lower", "value_upper", "confidence"):
            if comparable["value"].get(key) is not None:
                comparable["value"][key] = format(decimal(comparable["value"][key]).normalize(), "f")
        resolved.append(comparable)
    value["quantity_ids"] = sorted(resolved, key=canonical_json)
    return sha256_text(canonical_json({"canonicalizer_version": CANONICALIZER_VERSION,
                                     "serialization": "canonical-json-v1", "statement": value}))


def _resolve(value, mapping, records, label):
    resolved = mapping.get(value, value)
    _need(isinstance(resolved, str) and resolved in records, f"unknown {label}: {value}")
    return resolved


def _event(append, kind, before, after, reason):
    append("events", {"type": kind, "before": before, "after": after, "reason": reason,
                      "actor": "agent", "status": "confirmed", "occurred_at": now_iso()})


def _effective_revisions(revisions):
    superseded = {r["supersedes"] for r in revisions if r.get("supersedes")}
    return [r for r in revisions if r["id"] not in superseded]


def _replacement_cycle(relations, revisions):
    active = {r["id"] for r in _effective_revisions(revisions)}
    graph, indegree = {}, {}
    for edge in relations:
        if edge["type"] != "REPLACES" or edge["status"] != "confirmed" or edge.get("revision_id") not in active:
            continue
        src, dst = edge["src"], edge["dst"]
        graph.setdefault(src, []).append(dst)
        indegree.setdefault(src, 0)
        indegree[dst] = indegree.get(dst, 0) + 1
    queue = [node for node, degree in indegree.items() if degree == 0]
    seen = 0
    while queue:
        node = queue.pop()
        seen += 1
        for child in graph.get(node, []):
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
    return seen != len(indegree)


def enrich(old, sources, proposal, summary):
    """Apply Agent records to a candidate; raises before any state is published."""
    snapshot = sources["snapshots"][-1]
    sid, snapid, runid = summary["state_id"], snapshot["id"], summary["run_id"]
    for key in ("claims", "relations", "references", "evidence", "assessments", "quantities", "checks",
                "revisions", "bindings", "arguments", "reviews", "invalidations"):
        sources[key] = deepcopy(getattr(old, key, [])) if old else []
    counts = {key: max_id(sources[key], kind) for key, kind in KINDS.items()}

    def append(key, values):
        counts[key] += 1
        row = deepcopy(values)
        row.update(id=f"{PREFIXES[KINDS[key]]}{counts[key]:06d}", state_id=sid, run_id=runid,
                   schema_version=SCHEMA_VERSION, created_at=now_iso())
        sources[key].append(row)
        return row

    rows = lambda key: {row["id"]: row for row in sources[key]}
    segment_map = {}
    selections = snapshot["selections"]
    ranges_map = {canonical_json(s["source_ranges"]): s for s in selections}
    for index, segment in enumerate((proposal or {}).get("segments", [])):
        ref = segment.get("ref", f"segment:{index}")
        _need(ref not in segment_map, f"duplicate segment ref {ref}")
        segment_map[ref] = ranges_map[canonical_json(segment["source_ranges"])]
    data = (proposal or {}).get("semantic")
    current_bindings = []
    revision_rows = []
    new_claims = set()
    current_quantities = []
    explicit_reference_ids = set()
    changed_relation_claims = set()
    old_bindings = [row for row in sources["bindings"] if old and row["snapshot_id"] == old.snapshot_id]
    if data is None:
        # Text-only edits preserve only bindings whose exact variant is unchanged.
        for binding in old_bindings:
            match = next((s for s in selections if s["container_id"] == binding["container_id"]
                          and s["variant_id"] == binding["variant_id"]), None)
            if match:
                current_bindings.append(append("bindings", {**match, "snapshot_id": snapid,
                    "claim_id": binding["claim_id"], "reason": "unchanged variant", "previous_binding_id": binding["id"]}))
        old_non_claim = set(old.snapshot.get("non_claim_placements", [])) if old else set()
        old_pairs = {(s["container_id"], s["variant_id"]) for s in (old.snapshot["selections"] if old else [])
                     if s["placement_id"] in old_non_claim}
        snapshot["non_claim_placements"] = [s["placement_id"] for s in selections if (s["container_id"], s["variant_id"]) in old_pairs]
    else:
        _need((proposal or {}).get("schema_version") == SCHEMA_VERSION, "semantic proposals require schema_version 1.1.0")
        aliases = {key: {} for key in ("claims", "references", "evidence", "quantities", "arguments")}

        def new_alias(key, ref, row):
            _need(ref not in aliases[key] and ref not in rows(key), f"duplicate or reserved {key} ref {ref}")
            aliases[key][ref] = row["id"]

        def resolve(key, value):
            return _resolve(value, aliases.get(key, {}), rows(key), key)

        def placement(ref):
            _need(ref in segment_map, f"unknown segment {ref}")
            return segment_map[ref]

        for record in data.get("references", []):
            row = append("references", {k: v for k, v in record.items() if k != "ref"})
            new_alias("references", record["ref"], row)
            explicit_reference_ids.add(row["id"])
        explicit_reference_ids.update(resolve("references", ref) for ref in data.get("reference_ids", []))
        for record in data.get("evidence", []):
            reference_id = resolve("references", record["reference"])
            reference = rows("references")[reference_id]
            _need(reference["source_access"] not in {"metadata_only", "unavailable"},
                  "a quote cannot be verified from an unavailable or metadata-only reference")
            row = append("evidence", {**record, "reference_id": reference_id,
                "source_access": reference["source_access"], "shared_source_ids": record.get("shared_source_ids", []),
                "dataset_id": record.get("dataset_id", reference.get("dataset_id")),
                "study_id": record.get("study_id", reference.get("study_id"))})
            new_alias("evidence", record["ref"], row)
        for record in data.get("quantities", []):
            try:
                validate_quantity(record)
            except ValueError as exc:
                raise SemanticError(str(exc)) from exc
            sel = placement(record["segment"])
            source = rows("variants")[sel["variant_id"]]["raw_text"]
            _need(record["source_expression"] in source, "quantity expression is not present at its segment")
            row = append("quantities", {**record, "locator": {"snapshot_id": snapid, **sel}, "claim_ids": []})
            current_quantities.append(row)
            new_alias("quantities", record["ref"], row)
        for record in data.get("claims", []):
            canonical = deepcopy(record["canonical_statement"])
            qrefs = canonical.get("quantity_ids", [])
            _need(isinstance(qrefs, list) and all(isinstance(q, str) for q in qrefs),
                  "canonical quantity_ids must be an array of reference strings")
            canonical["quantity_ids"] = [resolve("quantities", q) for q in qrefs]
            fp = fingerprint(canonical, rows("quantities"))
            requested = record.get("claim_id")
            matches = [r for r in sources["claims"] if fp and r.get("semantic_fingerprint") == fp]
            if requested:
                _need(requested in rows("claims"), f"unknown claim_id {requested}")
                row = rows("claims")[requested]
                _need(fp is not None and row.get("semantic_fingerprint") == fp,
                      "claim_id reuse requires identical, known truth conditions")
            elif matches:
                row = matches[0]
            else:
                row = append("claims", {"surface_statement": record["surface_statement"],
                    "canonical_statement": canonical, "canonicalizer_version": CANONICALIZER_VERSION,
                    "semantic_fingerprint": fp, "kind": record.get("kind", "assertion"), "flags": [],
                    "identity_status": "known" if fp else "unknown",
                    "review_requirements": record.get("review_requirements", [
                        {"definition": "logic", "method": "methodology"}.get(record.get("kind"), "evidence")])})
                new_claims.add(row["id"])
                _event(append, "CLAIM_CREATED", [], [row["id"]], "Agent supplied canonical statement")
            new_alias("claims", record["ref"], row)
        for row in current_quantities:
            if row.get("claim"):
                row["claim_ids"] = [resolve("claims", row["claim"])]

        seen_bindings = set()
        for record in data["bindings"]:
            cid = resolve("claims", record["claim"])
            sel = placement(record["segment"])
            pair = (cid, sel["placement_id"])
            _need(pair not in seen_bindings, "duplicate claim/placement binding")
            seen_bindings.add(pair)
            current_bindings.append(append("bindings", {**sel, "snapshot_id": snapid,
                "claim_id": cid, "reason": record["reason"]}))
        non_claim = [placement(r["segment"])["placement_id"] for r in data.get("non_claim_segments", [])]
        _need(not set(non_claim) & {b["placement_id"] for b in current_bindings},
              "a segment cannot be both non-claim and claim-bearing")
        snapshot["non_claim_placements"] = non_claim
        old_by_place = {(b["claim_id"], b["placement_id"]) for b in old_bindings}
        new_by_place = {(b["claim_id"], b["placement_id"]) for b in current_bindings}
        revision_inputs = list(data.get("revisions", []))
        explicit_targets = {resolve("claims", item["claim"]) for record in revision_inputs for item in record["after"]}
        for binding in current_bindings:
            cid = binding["claim_id"]
            previous = [b for b in old_bindings if b["container_id"] == binding["container_id"] and b["claim_id"] != cid
                and not any(c["claim_id"] == b["claim_id"] and c["container_id"] == b["container_id"] for c in current_bindings)]
            if cid in new_claims and previous and cid not in explicit_targets:
                segments = [ref for ref, p in segment_map.items() if p["placement_id"] == binding["placement_id"]]
                revision_inputs.append({"operation": "REPLACEMENT", "status": "proposed",
                    "reason": "同一容器的命题变化；需由 Agent 确认替代范围。",
                    "before": [{"claim": b["claim_id"], "placements": [b["placement_id"]]} for b in previous],
                    "after": [{"claim": cid, "segments": segments}]})
        for record in revision_inputs:
            _need(old is not None, "revisions require a previous snapshot")
            before, after = [], []
            for item in record["before"]:
                cid = resolve("claims", item["claim"])
                _need(all((cid, p) in old_by_place for p in item["placements"]),
                      "revision before context is not a binding in the previous snapshot")
                before.append({"claim_id": cid, "contexts": [{"placement_id": p} for p in item["placements"]]})
            for item in record["after"]:
                cid = resolve("claims", item["claim"])
                contexts = [{"placement_id": placement(p)["placement_id"]} for p in item["segments"]]
                _need(all((cid, p["placement_id"]) in new_by_place for p in contexts),
                      "revision after context has no current claim binding")
                after.append({"claim_id": cid, "contexts": contexts})
            operation = record["operation"]
            _need(before or after, "empty revision")
            _need(operation != "DELETE" or (before and not after), "DELETE requires before and empty after")
            _need(operation in {"DELETE", "RESTORE"} or (before and after), "replacement requires both sides")
            if operation not in {"RESTORE", "DELETE"}:
                _need(not {b["claim_id"] for b in before} & {a["claim_id"] for a in after},
                      "same Claim on both sides: use a text revision, not REPLACES")
            revision = append("revisions", {**record, "before": before, "after": after,
                "before_snapshot_id": old.snapshot_id, "after_snapshot_id": snapid})
            revision_rows.append(revision)
            if operation not in {"RESTORE", "DELETE"}:
                for previous in before:
                    for current in after:
                        append("relations", {"src": current["claim_id"], "dst": previous["claim_id"],
                            "type": "REPLACES", "revision_id": revision["id"], "status": record["status"]})
                        if current["claim_id"] in new_claims and record["status"] == "confirmed":
                            flags = rows("claims")[current["claim_id"]]["flags"]
                            if "replacement" not in flags:
                                flags.append("replacement")
            _event(append, "CLAIM_REPLACED" if operation not in {"RESTORE", "DELETE"} else "CLAIM_REVISION",
                   [r["claim_id"] for r in before], [r["claim_id"] for r in after], record["reason"])
        for decision in data.get("revision_decisions", []):
            rid = decision["revision_id"]
            effective = {r["id"]: r for r in _effective_revisions(sources["revisions"])}
            _need(rid in effective, f"revision decision must reference a current revision record: {rid}")
            previous = effective[rid]
            _need(decision["status"] != previous["status"], "revision decision must change status")
            revision = append("revisions", {**previous, "supersedes": rid, "status": decision["status"],
                "reason": decision["reason"], "decision_snapshot_id": snapid})
            revision_rows.append(revision)
            if previous["operation"] not in {"RESTORE", "DELETE"}:
                for before in previous["before"]:
                    for after in previous["after"]:
                        append("relations", {"src": after["claim_id"], "dst": before["claim_id"], "type": "REPLACES",
                            "revision_id": revision["id"], "status": revision["status"]})
            _event(append, "CLAIM_REVISION", [rid], [revision["id"]], decision["reason"])
        for record in data.get("relations", []):
            src, dst = resolve("claims", record["src"]), resolve("claims", record["dst"])
            _need(src != dst, "self relation is not allowed")
            previous = [r for r in sources["relations"] if r.get("src") == src and r.get("dst") == dst and r.get("type") == record["type"]]
            if not previous or previous[-1]["status"] != record["status"]:
                append("relations", {**record, "src": src, "dst": dst,
                    "supersedes": previous[-1]["id"] if previous else None})
                if previous:
                    changed_relation_claims.add(src if record["type"] == "DEPENDS_ON" else dst)
        for record in data.get("arguments", []):
            conclusion = resolve("claims", record["conclusion"])
            premises = [resolve("claims", p) for p in record["premises"]]
            _need(conclusion not in premises, "argument cannot depend on itself")
            row = append("arguments", {**record, "conclusion": conclusion, "premises": premises})
            new_alias("arguments", record["ref"], row)
            for premise in premises:
                append("relations", {"src": conclusion, "dst": premise, "type": "DEPENDS_ON",
                    "status": record["status"], "argument_id": row["id"], "reason": record["reason"]})
        supplied_checks = []
        for record in data.get("assessments", []):
            cid, eid = resolve("claims", record["claim"]), resolve("evidence", record["evidence"])
            _need(cid in {b["claim_id"] for b in current_bindings}, "assessment must target a current claim")
            ev = rows("evidence")[eid]
            _need(record["status"] != "supported" or ev["source_access"] == "full_text",
                  "full support requires full_text evidence; use partial/unknown and explain limitations")
            independence = "unknown"
            for assessment in sources["assessments"]:
                if assessment["claim_id"] != cid:
                    continue
                other = rows("evidence")[assessment["evidence_id"]]
                if ev["reference_id"] == other["reference_id"] or set(ev["shared_source_ids"]) & set(other["shared_source_ids"]):
                    independence = "shared_source"
                elif ev.get("dataset_id") and ev.get("dataset_id") == other.get("dataset_id"):
                    independence = "shared_dataset"
                elif ev.get("study_id") and ev.get("study_id") == other.get("study_id"):
                    independence = "shared_study"
            assessment = append("assessments", {**record, "claim_id": cid, "evidence_id": eid,
                "snapshot_id": snapid, "independence_status": independence})
            outcome = {"supported": "pass", "partially_supported": "insufficient_evidence",
                       "unsupported": "fail", "counterevidence": "conflict"}.get(record["status"], "pending")
            supplied_checks.append(append("checks", {"kind": "evidence", "claim_ids": [cid],
                "evidence_ids": [eid], "snapshot_id": snapid, "outcome": outcome,
                "reason": record["reason"], "method": "agent_evidence_assessment", "assessment_id": assessment["id"]}))
        for record in data.get("checks", []):
            cids = [resolve("claims", c) for c in record["claim_ids"]]
            eids = [resolve("evidence", e) for e in record.get("evidence_ids", [])]
            _need(set(cids) <= {b["claim_id"] for b in current_bindings}, "checks must target current claims")
            if record["kind"] == "evidence" and record["outcome"] == "pass":
                _need(eids and all(rows("evidence")[e]["source_access"] == "full_text" for e in eids),
                      "evidence check pass requires full_text sources")
            supplied_checks.append(append("checks", {**record, "claim_ids": cids, "evidence_ids": eids,
                                                      "snapshot_id": snapid}))
            append("reviews", {"snapshot_id": snapid, "claim_ids": cids, "check_id": supplied_checks[-1]["id"],
                               "reason": record["reason"], "outcome": record["outcome"], "method": record["method"]})
        snapshot["supplied_check_ids"] = [r["id"] for r in supplied_checks]

    snapshot["binding_ids"] = [b["id"] for b in current_bindings]
    snapshot["claim_ids"] = sorted({b["claim_id"] for b in current_bindings})
    snapshot["quantity_ids"] = [q["id"] for q in current_quantities]
    if old:
        # Retain quantity provenance only when its exact text occurrence survives.
        old_qids = set(old.snapshot.get("quantity_ids", []))
        for q in sources["quantities"]:
            loc = q.get("locator", {})
            if q["id"] in old_qids and not any(n.get("source_expression") == q.get("source_expression") and
                n["metric_id"] == q["metric_id"] and n["locator"].get("container_id") == loc.get("container_id") for n in current_quantities) and any(s["container_id"] == loc.get("container_id") and
                s["variant_id"] == loc.get("variant_id") for s in selections):
                current_quantities.append(q)
        snapshot["quantity_ids"] = [q["id"] for q in current_quantities]
    old_active = set(old.snapshot.get("claim_ids", [])) if old else set()
    affected = old_active - set(snapshot["claim_ids"])
    affected.update(changed_relation_claims)
    for revision in revision_rows:
        if revision["operation"] != "RESTORE":
            affected.update(b["claim_id"] for b in revision["before"])
    # A lost occurrence can change citation or context even if the Claim remains elsewhere.
    current_pairs = {(b["claim_id"], b["container_id"], b["variant_id"]) for b in current_bindings}
    affected.update(b["claim_id"] for b in old_bindings
                    if (b["claim_id"], b["container_id"], b["variant_id"]) not in current_pairs
                    and not (data is not None and b["claim_id"] in snapshot["claim_ids"]
                             and rows("claims")[b["claim_id"]].get("semantic_fingerprint")))
    changed = True
    while changed:
        previous = set(affected)
        current_edges = {(r["src"], r["dst"], r["type"]): r for r in sources["relations"]}
        for edge in current_edges.values():
            if edge.get("status") != "confirmed":
                continue
            if edge["type"] == "DEPENDS_ON" and edge["dst"] in affected:
                affected.add(edge["src"])
            if edge["type"] in {"SUPPORTS", "ENTAILS"} and edge["src"] in affected:
                affected.add(edge["dst"])
        changed = previous != affected
    snapshot["affected_claim_ids"] = sorted(affected)
    old_checks = set(old.snapshot.get("check_ids", [])) if old else set()
    current_checks = []
    new_checks = [r for r in sources["checks"] if r["id"] in snapshot.get("supplied_check_ids", [])]
    requested_invalidations = {r["check_id"]: r["reason"] for r in ((data or {}).get("invalidate_checks", []))}
    _need(set(requested_invalidations) <= old_checks, "invalidate_checks must reference checks active in the previous snapshot")
    for check in sources["checks"][:]:
        if check["id"] not in old_checks:
            continue
        if set(check.get("claim_ids", [])) & affected or check["kind"] == "quantity_consistency" or check["id"] in requested_invalidations:
            append("invalidations", {"check_id": check["id"], "cause_claim_ids": sorted(affected),
                "reason": requested_invalidations.get(check["id"], "text, revision or dependency changed"), "snapshot_id": snapid})
            _event(append, "CHECK_INVALIDATED", [check["id"]], [], "affected inputs require review")
        elif not any(r["kind"] == check["kind"] and set(r["claim_ids"]) & set(check["claim_ids"]) for r in new_checks):
            current_checks.append(check)
    current_checks.extend(new_checks)
    for values in quantity_checks(current_quantities):
        current_checks.append(append("checks", {**values, "snapshot_id": snapid}))
    snapshot["check_ids"] = [r["id"] for r in current_checks]
    active_references = set(explicit_reference_ids)
    active_references.update(rows("evidence")[eid]["reference_id"] for check in current_checks for eid in check.get("evidence_ids", []))
    if data is None and old and snapshot["claim_ids"]:
        active_references.update(old.snapshot.get("reference_ids", []))
    snapshot["reference_ids"] = sorted(active_references)
    tasks = []

    def task(kind, target, reason, status="pending"):
        tasks.append({"type": kind, "target": target, "status": status, "reason": reason})

    bound = {b["placement_id"] for b in current_bindings} | set(snapshot.get("non_claim_placements", []))
    for sel in selections:
        if sel["placement_id"] not in bound:
            task("extract_claims", sel["placement_id"], "尚未判定此处是否包含命题。")
    for cid in snapshot["claim_ids"]:
        related = [c for c in current_checks if cid in c.get("claim_ids", [])]
        for required in rows("claims")[cid].get("review_requirements", ["evidence"]):
            if not any(c["kind"] == required and c["outcome"] in {"pass", "fail", "conflict"} for c in related):
                task("review_claim", cid, ("受影响需复核：" if cid in affected else "尚无已完成审核：") + required)
        if rows("claims")[cid].get("identity_status") == "unknown":
            task("resolve_identity", cid, "真值条件含未知字段，禁止通过指纹复用。")
    for check in current_checks:
        if check["outcome"] in {"fail", "conflict", "error", "insufficient_context", "insufficient_evidence", "pending"}:
            task("resolve_check", check["id"], check["reason"],
                 "action_required" if check["outcome"] in {"fail", "conflict", "error"} else "pending")
    for reference in (rows("references")[ref] for ref in snapshot["reference_ids"]):
        if reference["source_access"] != "full_text":
            task("obtain_source", reference["id"], f"原始材料访问级别：{reference['source_access']}。")
    for revision in _effective_revisions(sources["revisions"]):
        if revision["status"] == "proposed":
            if any(r["claim_id"] in snapshot["claim_ids"] for r in revision["after"]):
                task("review_revision", revision["id"], revision["reason"])
    active_revisions = {r["id"] for r in _effective_revisions(sources["revisions"])}
    snapshot["replacement_claim_ids"] = sorted({r["src"] for r in sources["relations"]
        if r["type"] == "REPLACES" and r["status"] == "confirmed" and r["revision_id"] in active_revisions})
    _need(not _replacement_cycle(sources["relations"], sources["revisions"]), "confirmed REPLACES cycle: use RESTORE for historical identity")
    snapshot["workflow"] = {"status": "pending" if tasks else "completed", "tasks": tasks,
                             "agent_supplied_semantics": data is not None}
    summary.update(claims_total=len(sources["claims"]), claims_active=len(snapshot["claim_ids"]),
        revisions_added=len(revision_rows), checks_current=len(current_checks),
        checks_reused=sum(r["id"] in old_checks for r in current_checks),
        affected_claim_ids=sorted(affected), pending_tasks=len(tasks))
    sources["runs"][-1]["proposal"] = deepcopy(proposal) if proposal is not None else None
    sources["runs"][-1]["summary"] = deepcopy(summary)
    for check in new_checks:
        check["input_fingerprint"] = sha256_text(canonical_json({
            "claims": [rows("claims")[cid].get("semantic_fingerprint") or cid for cid in check["claim_ids"]],
            "evidence": [rows("evidence")[eid] for eid in check.get("evidence_ids", [])],
            "method": check["method"], "version": SCHEMA_VERSION}))
    return sources, summary


def state_issues(state):
    """Cross-record invariants checked again when loading a committed ledger."""
    issues = []
    claims = state.by_id("claims")
    all_places = {s["id"]: {p["placement_id"] for p in s["selections"]} for s in state.snapshots}
    if _replacement_cycle(state.relations, state.revisions):
        issues.append("confirmed REPLACES cycle")
    for claim in state.claims:
        if claim.get("semantic_fingerprint") != fingerprint(claim["canonical_statement"], state.by_id("quantities")):
            issues.append(f"claim {claim['id']}: semantic fingerprint mismatch")
    for binding in state.bindings:
        if binding.get("claim_id") not in claims:
            issues.append(f"binding {binding['id']}: missing claim")
        if binding.get("placement_id") not in all_places.get(binding.get("snapshot_id"), set()):
            issues.append(f"binding {binding['id']}: missing placement")
    revisions = state.by_id("revisions")
    for revision in state.revisions:
        for side, field in (("before", "before_snapshot_id"), ("after", "after_snapshot_id")):
            for entry in revision[side]:
                if entry["claim_id"] not in claims or any(c["placement_id"] not in all_places.get(revision[field], set()) for c in entry["contexts"]):
                    issues.append(f"revision {revision['id']}: invalid {side} context")
    for edge in state.relations:
        if edge.get("src") not in claims or edge.get("dst") not in claims:
            issues.append(f"relation {edge['id']}: missing claim endpoint")
        if edge.get("type") == "REPLACES" and edge.get("revision_id") not in revisions:
            issues.append(f"relation {edge['id']}: REPLACES must derive from a Revision Group")
        elif edge.get("type") == "REPLACES":
            revision = revisions[edge["revision_id"]]
            if edge["src"] not in {r["claim_id"] for r in revision["after"]} or edge["dst"] not in {r["claim_id"] for r in revision["before"]} or edge["status"] != revision["status"]:
                issues.append(f"relation {edge['id']}: inconsistent revision projection")
    for key, ids in (("bindings", "binding_ids"), ("claims", "claim_ids"), ("checks", "check_ids"), ("quantities", "quantity_ids")):
        valid = state.by_id(key)
        for item in state.snapshot.get(ids, []):
            if item not in valid:
                issues.append(f"snapshot: missing {key} {item}")
    return issues

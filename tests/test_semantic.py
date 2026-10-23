from copy import deepcopy

import pytest

from papercheck.proposal import validate_proposal
from papercheck.storage import Repo, ValidationError
from papercheck.util import sha256_bytes


def canonical(predicate="causes", **changes):
    value = {"subject": {"entity_id": "X"}, "predicate": predicate, "object": {"entity_id": "Y"},
             "polarity": "positive", "modality": "asserted", "causality": "causal",
             "quantifier": None, "population": None, "time_scope": None, "conditions": [], "quantity_ids": []}
    value.update(changes)
    return value


def proposal(repo, text="X causes Y.", statement=None):
    data = text.encode()
    repo.paper_path.write_bytes(data)
    old = repo.load_current()
    segment = {"ref": "s", "kind": "paragraph", "block_ref": "p",
               "source_ranges": [{"start_byte": 0, "end_byte": len(data)}]}
    if old and old.snapshot["selections"]:
        previous = old.snapshot["selections"][0]
        segment.update(container_id=previous["container_id"],
                       block_id=old.by_id("containers")[previous["container_id"]]["parent_block_id"])
        segment.pop("block_ref")
        if old.by_id("variants")[previous["variant_id"]]["raw_text"] == text:
            segment["variant_id"] = previous["variant_id"]
    return {"schema_version": "1.1.0", "base_state_id": old.state_id if old else None,
            "base_sha256": old.manifest["input"]["sha256"] if old else None,
            "paper_sha256": sha256_bytes(data), "segments": [segment], "untracked": [],
            "semantic": {"claims": [{"ref": "c", "surface_statement": text,
                                      "canonical_statement": statement or canonical()}],
                         "bindings": [{"claim": "c", "segment": "s", "reason": "Read the current assertion"}]}}


def test_paraphrase_reuses_claim_and_preserves_original_state(tmp_path):
    repo = Repo(tmp_path)
    repo.commit(proposal=proposal(repo))
    first = repo.load_current()
    repo.commit(proposal=proposal(repo, "X brings about Y."))
    second = repo.load_current()
    assert len(second.claims) == 1 and len(second.variants) == 2
    assert not second.revisions
    assert second.snapshot["claim_ids"] == first.snapshot["claim_ids"]
    assert (first.path / "sources" / "paper.md").read_bytes() == b"X causes Y."
    assert repo.verify() == []


def test_causality_replacement_and_multi_position_contexts(tmp_path):
    repo = Repo(tmp_path)
    repo.commit(proposal=proposal(repo))
    old = repo.load_current()
    p = proposal(repo, "X is associated with Y.", canonical("associated_with", causality="associational"))
    p["semantic"]["revisions"] = [{"operation": "REPLACEMENT", "status": "confirmed", "reason": "Causal assertion weakened",
        "before": [{"claim": old.claims[0]["id"], "placements": [old.snapshot["selections"][0]["placement_id"]]}],
        "after": [{"claim": "c", "segments": ["s"]}]}]
    repo.commit(proposal=p)
    state = repo.load_current()
    assert len(state.claims) == 2 and len(state.revisions) == 1
    edge = next(r for r in state.relations if r["type"] == "REPLACES")
    assert edge["src"] == "C000002" and edge["dst"] == "C000001"
    assert state.claims[1]["flags"] == ["replacement"]
    assert repo.verify() == []


def test_unknown_truth_conditions_force_new_identity(tmp_path):
    repo = Repo(tmp_path)
    for _ in range(2):
        repo.commit(proposal=proposal(repo, statement=canonical(population="unknown")))
    assert len(repo.load_current().claims) == 2
    assert all(c["semantic_fingerprint"] is None for c in repo.load_current().claims)
    assert repo.load_current().revisions[0]["status"] == "proposed"


def test_incorrect_explicit_claim_reuse_is_rejected(tmp_path):
    repo = Repo(tmp_path)
    repo.commit(proposal=proposal(repo))
    p = proposal(repo, statement=canonical("associated_with"))
    p["semantic"]["claims"][0]["claim_id"] = "C000001"
    with pytest.raises(ValidationError, match="truth conditions"):
        repo.commit(proposal=p)


def test_validate_checks_semantic_references_before_commit(tmp_path):
    repo = Repo(tmp_path)
    p = proposal(repo)
    p["semantic"]["bindings"][0]["segment"] = "missing"
    assert any("unknown segment" in issue for issue in validate_proposal(None, repo.paper_path.read_bytes(), p))
    assert repo.read_current() is None


def test_unavailable_source_stays_pending_and_cannot_supply_quote(tmp_path):
    repo = Repo(tmp_path)
    p = proposal(repo)
    p["semantic"]["references"] = [{"ref": "r", "title": "Missing paper", "source_access": "unavailable"}]
    repo.commit(proposal=p)
    assert any(t["type"] == "obtain_source" for t in repo.load_current().snapshot["workflow"]["tasks"])
    p = proposal(repo)
    p["semantic"]["evidence"] = [{"ref": "e", "reference": "REF000001", "quote": "Invented quote", "locator": {"page": 1}}]
    with pytest.raises(ValidationError, match="unavailable"):
        repo.commit(proposal=p)


def test_abstract_does_not_become_full_support(tmp_path):
    repo = Repo(tmp_path)
    p = proposal(repo)
    p["semantic"].update(references=[{"ref": "r", "title": "Abstract", "source_access": "abstract_only"}],
        evidence=[{"ref": "e", "reference": "r", "quote": "X causes Y", "locator": {"section": "abstract"}}],
        assessments=[{"claim": "c", "evidence": "e", "status": "supported", "reason": "A quote"}])
    with pytest.raises(ValidationError, match="full_text"):
        repo.commit(proposal=p)


def test_completed_assessment_can_be_reused_and_then_invalidates(tmp_path):
    repo = Repo(tmp_path)
    p = proposal(repo)
    p["semantic"].update(references=[{"ref": "r", "title": "Original", "source_access": "full_text"}],
        evidence=[{"ref": "e", "reference": "r", "quote": "X causes Y", "locator": {"page": 3}}],
        assessments=[{"claim": "c", "evidence": "e", "status": "supported", "reason": "Agent read page 3"}])
    repo.commit(proposal=p)
    assert repo.load_current().snapshot["workflow"]["status"] == "completed"
    # An equivalent paraphrase explicitly reuses the same truth conditions.
    repo.commit(proposal=proposal(repo, "X brings about Y."))
    state = repo.load_current()
    assert not state.invalidations
    assert state.snapshot["workflow"]["status"] == "completed"
    assert state.runs[-1]["summary"]["checks_reused"] == 1
    repo.commit(proposal=proposal(repo, "X is associated with Y.", canonical("associated_with")))
    assert repo.load_current().invalidations
    assert repo.load_current().snapshot["workflow"]["status"] == "pending"


def test_text_only_change_drops_stale_bindings_and_keeps_history(tmp_path):
    repo = Repo(tmp_path)
    repo.commit(proposal=proposal(repo))
    repo.paper_path.write_bytes(b"A different assertion.")
    repo.commit(auto=True)
    state = repo.load_current()
    assert state.claims and not state.snapshot["claim_ids"]
    assert any(t["type"] == "extract_claims" for t in state.snapshot["workflow"]["tasks"])


def test_downstream_checks_become_stale_when_premise_changes(tmp_path):
    repo = Repo(tmp_path)
    p = proposal(repo)
    p["semantic"]["claims"].append({"ref": "conclusion", "surface_statement": "Conclusion", "canonical_statement": canonical("conclusion")})
    p["semantic"]["bindings"].append({"claim": "conclusion", "segment": "s", "reason": "Also asserted"})
    p["semantic"]["relations"] = [{"src": "conclusion", "dst": "c", "type": "DEPENDS_ON", "status": "confirmed", "reason": "Necessary premise"}]
    p["semantic"]["checks"] = [{"claim_ids": ["conclusion"], "kind": "logic", "outcome": "pass", "reason": "Checked", "method": "agent"}]
    repo.commit(proposal=p)
    p = proposal(repo, "A revised premise.", canonical("new_predicate"))
    p["semantic"]["bindings"].append({"claim": "C000002", "segment": "s", "reason": "Conclusion remains"})
    repo.commit(proposal=p)
    state = repo.load_current()
    assert "C000002" in state.snapshot["affected_claim_ids"]
    assert state.invalidations[0]["check_id"] == "CHK000001"
    assert state.checks[0]["outcome"] == "pass"  # historical result is immutable


def test_restore_uses_historical_identity_without_reverse_replaces(tmp_path):
    repo = Repo(tmp_path)
    repo.commit(proposal=proposal(repo))
    first = repo.load_current()
    repo.commit(proposal=proposal(repo, "Different predicate.", canonical("other")))
    p = proposal(repo)
    p["semantic"]["revisions"] = [{"operation": "RESTORE", "before": [],
        "after": [{"claim": "c", "segments": ["s"]}], "status": "confirmed", "reason": "Restore original assertion"}]
    repo.commit(proposal=p)
    assert repo.load_current().snapshot["claim_ids"] == first.snapshot["claim_ids"]
    assert len(repo.load_current().claims) == 2
    edges = [e for e in repo.load_current().relations if e["type"] == "REPLACES"]
    assert len(edges) == 1 and edges[0]["src"] == "C000002" and edges[0]["dst"] == "C000001"


def test_quantity_conflict_is_deterministic(tmp_path):
    repo = Repo(tmp_path)
    p = proposal(repo, "N=3038. N=3012.")
    quantities = []
    for i, value in enumerate(["3038", "3012"]):
        quantities.append({"ref": f"q{i}", "claim": "c", "metric_id": "sample_size",
            "value": {"type": "point", "value_decimal": value}, "unit": "person", "segment": "s",
            "source_expression": "N=" + value, "extraction_status": "confirmed", "population": "adults",
            "dataset_id": "study", "dataset_version": "v1", "sample_filter": "all", "time_scope": None})
    p["semantic"]["quantities"] = quantities
    repo.commit(proposal=p)
    check = next(c for c in repo.load_current().checks if c["kind"] == "quantity_consistency")
    assert check["outcome"] == "conflict"
    assert any(t["status"] == "action_required" for t in repo.load_current().snapshot["workflow"]["tasks"])


def test_unknown_quantity_scope_is_not_a_conflict(tmp_path):
    from papercheck.quantity import compare
    base = {"metric_id": "N", "unit": "person", "value": {"type": "point", "value_decimal": "3"}, "extraction_status": "confirmed"}
    assert compare(base, {**base, "value": {"type": "point", "value_decimal": "4"}})[0] == "insufficient_context"


def test_units_and_decimal_tolerance():
    from papercheck.quantity import compare
    base = {"metric_id": "weight", "unit": "kg", "value": {"type": "point", "value_decimal": "1"},
            "extraction_status": "confirmed", "population": "P", "dataset_id": "D", "dataset_version": "v1",
            "sample_filter": "all", "time_scope": None}
    other = {**base, "unit": "g", "value": {"type": "point", "value_decimal": "1000"}}
    assert compare(base, other)[0] == "pass"
    assert compare(base, {**other, "population": "other"})[0] == "incomparable"
    open_range = {**base, "value": {"type": "range", "value_lower": "1", "value_upper": "2", "inclusive": [False, True]}}
    assert compare(base, open_range)[0] == "conflict"


@pytest.mark.parametrize("value", ["NaN", "Infinity", "not-a-number"])
def test_invalid_quantity_values_fail_validation(tmp_path, value):
    repo = Repo(tmp_path)
    p = proposal(repo)
    p["semantic"]["quantities"] = [{"ref": "q", "metric_id": "N", "unit": "count", "segment": "s",
        "value": {"type": "point", "value_decimal": value}, "source_expression": "X", "extraction_status": "confirmed"}]
    with pytest.raises(ValidationError):
        repo.commit(proposal=p)


def test_segment_refs_must_be_unique(tmp_path):
    repo = Repo(tmp_path)
    p = proposal(repo, "AB")
    p["segments"][0]["source_ranges"] = [{"start_byte": 0, "end_byte": 1}]
    p["segments"].append({**deepcopy(p["segments"][0]), "source_ranges": [{"start_byte": 1, "end_byte": 2}]})
    with pytest.raises(ValidationError, match="duplicate segment"):
        repo.commit(proposal=p)


def test_candidate_can_be_confirmed_later_without_overwriting_history(tmp_path):
    repo = Repo(tmp_path)
    repo.commit(proposal=proposal(repo))
    repo.commit(proposal=proposal(repo, "Revised assertion.", canonical("other")))
    candidate = deepcopy(repo.load_current().revisions[0])
    p = proposal(repo, "Revised assertion.", canonical("other"))
    p["semantic"]["revision_decisions"] = [{"revision_id": candidate["id"], "status": "confirmed", "reason": "Agent checked both contexts"}]
    repo.commit(proposal=p)
    state = repo.load_current()
    assert state.revisions[0] == candidate
    assert state.revisions[-1]["supersedes"] == candidate["id"]
    assert state.snapshot["replacement_claim_ids"] == ["C000002"]
    assert not any(t["type"] == "review_revision" for t in state.snapshot["workflow"]["tasks"])
    assert repo.verify() == []


def test_rejected_candidate_is_not_a_replacement_flag(tmp_path):
    repo = Repo(tmp_path)
    repo.commit(proposal=proposal(repo))
    repo.commit(proposal=proposal(repo, "Independent new assertion.", canonical("other")))
    p = proposal(repo, "Independent new assertion.", canonical("other"))
    p["semantic"]["revision_decisions"] = [{"revision_id": "REV000001", "status": "rejected", "reason": "Different claim introduced independently"}]
    repo.commit(proposal=p)
    assert repo.load_current().snapshot["replacement_claim_ids"] == []


def test_multi_position_replacement_leaves_old_claim_active_elsewhere(tmp_path):
    repo = Repo(tmp_path)
    p = proposal(repo, "X causes Y. X causes Y.")
    p["segments"] = [
        {"ref": "one", "kind": "paragraph", "block_ref": "p", "source_ranges": [{"start_byte": 0, "end_byte": 11}]},
        {"ref": "two", "kind": "paragraph", "block_ref": "p", "source_ranges": [{"start_byte": 12, "end_byte": 23}]}]
    p["untracked"] = [{"start_byte": 11, "end_byte": 12}]
    p["semantic"]["bindings"] = [{"claim": "c", "segment": ref, "reason": "Repeated assertion"} for ref in ["one", "two"]]
    repo.commit(proposal=p)
    old = repo.load_current()
    data = b"X loves Y. X causes Y."
    repo.paper_path.write_bytes(data)
    p.update(base_state_id=old.state_id, base_sha256=old.manifest["input"]["sha256"], paper_sha256=sha256_bytes(data))
    p["segments"][0]["source_ranges"] = [{"start_byte": 0, "end_byte": 10}]
    p["segments"][1]["source_ranges"] = [{"start_byte": 11, "end_byte": 22}]
    p["untracked"] = [{"start_byte": 10, "end_byte": 11}]
    for segment, previous in zip(p["segments"], old.snapshot["selections"]):
        segment["container_id"] = previous["container_id"]
    p["semantic"]["claims"] = [{"ref": "new", "surface_statement": "X loves Y.", "canonical_statement": canonical("loves")}]
    p["semantic"]["bindings"] = [{"claim": "new", "segment": "one", "reason": "Changed assertion"},
                                      {"claim": "C000001", "segment": "two", "reason": "Original still here"}]
    p["semantic"]["revisions"] = [{"operation": "REPLACEMENT", "status": "confirmed", "reason": "Only first occurrence changed",
        "before": [{"claim": "C000001", "placements": [old.snapshot["selections"][0]["placement_id"]]}],
        "after": [{"claim": "new", "segments": ["one"]}]}]
    repo.commit(proposal=p)
    state = repo.load_current()
    assert state.snapshot["claim_ids"] == ["C000001", "C000002"]
    assert len(state.revisions[0]["before"][0]["contexts"]) == 1
    assert repo.verify() == []


def test_candidate_remains_pending_across_later_runs(tmp_path):
    repo = Repo(tmp_path)
    repo.commit(proposal=proposal(repo))
    repo.commit(proposal=proposal(repo, "Different.", canonical("other")))
    repo.commit(proposal=proposal(repo, "Different.", canonical("other")))
    assert any(t["type"] == "review_revision" for t in repo.load_current().snapshot["workflow"]["tasks"])


def test_agent_can_invalidate_a_citation_check_without_changing_claim(tmp_path):
    repo = Repo(tmp_path)
    p = proposal(repo)
    p["semantic"]["checks"] = [{"claim_ids": ["c"], "kind": "citation", "outcome": "pass", "reason": "Citation scope checked", "method": "agent"}]
    repo.commit(proposal=p)
    p = proposal(repo)
    p["semantic"]["invalidate_checks"] = [{"check_id": "CHK000001", "reason": "Citation target changed outside the statement"}]
    repo.commit(proposal=p)
    assert repo.load_current().invalidations[0]["reason"].startswith("Citation target")
    assert "CHK000001" not in repo.load_current().snapshot["check_ids"]


def test_semantic_index_and_run_history_are_rebuildable(tmp_path):
    from papercheck.index import query_counts
    repo = Repo(tmp_path)
    for _ in range(2):
        repo.commit(proposal=proposal(repo))
    state = repo.load_current()
    assert [r["id"] for r in state.runs] == ["RUN000001", "RUN000002"]
    counts = query_counts(repo.rebuild_index())
    assert counts["claims"] == 1 and counts["bindings"] == 2 and counts["runs"] == 2


def test_confirmed_replacement_cycle_is_rejected(tmp_path):
    repo = Repo(tmp_path)
    repo.commit(proposal=proposal(repo))
    p = proposal(repo, "Other.", canonical("other"))
    p["semantic"]["revisions"] = [{"operation": "REPLACEMENT", "status": "confirmed", "reason": "Changed",
        "before": [{"claim": "C000001", "placements": ["PL000001"]}], "after": [{"claim": "c", "segments": ["s"]}]}]
    repo.commit(proposal=p)
    p = proposal(repo)
    p["semantic"]["revisions"] = [{"operation": "REPLACEMENT", "status": "confirmed", "reason": "Incorrect reverse edge",
        "before": [{"claim": "C000002", "placements": ["PL000002"]}], "after": [{"claim": "c", "segments": ["s"]}]}]
    with pytest.raises(ValidationError, match="RESTORE"):
        repo.commit(proposal=p)

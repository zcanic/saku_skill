"""Generate the shipped, self-contained proposal contract and its repository copy."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def obj(properties, required=()):
    return {"type": "object", "additionalProperties": True,
            "properties": properties, "required": list(required)}


def arr(item):
    return {"type": "array", "items": item}


S = {"type": "string", "minLength": 1}
STATUS = {"enum": ["proposed", "confirmed", "rejected"]}
VALUE = obj({"type": {"enum": ["point", "range", "interval"]},
             "value_decimal": S, "value_lower": S, "value_upper": S,
             "confidence": {"type": ["string", "null"]}}, ["type"])
CLAIM = obj({"ref": S, "claim_id": S, "surface_statement": S,
             "canonical_statement": {"type": "object"}, "kind": S,
             "review_requirements": {**arr(S), "minItems": 1, "uniqueItems": True}},
            ["ref", "surface_statement", "canonical_statement"])
REFERENCE = obj({"ref": S, "title": S, "source_access": {"enum": [
    "full_text", "abstract_only", "snippet_only", "metadata_only", "unavailable"]},
    "url": S, "file_sha256": S, "dataset_id": S, "study_id": S},
    ["ref", "title", "source_access"])
EVIDENCE = obj({"ref": S, "reference": S, "quote": S,
                "locator": {"type": "object", "minProperties": 1},
                "shared_source_ids": arr(S), "dataset_id": S, "study_id": S},
               ["ref", "reference", "quote", "locator"])
QUANTITY = obj({"ref": S, "claim": S, "metric_id": S, "value": VALUE,
                "operator": {"enum": ["=", "<", ">", "<=", ">="]},
                "unit": S, "segment": S, "source_expression": S,
                "extraction_status": {"enum": ["proposed", "confirmed", "pending"]},
                "tolerance_decimal": S, "precision": {"enum": ["exact", "as_written"]},
                "derivation": {"type": ["object", "null"], "additionalProperties": True, "properties": {
                    "op": {"enum": ["sum", "difference", "product", "ratio", "mean", "weighted_mean", "share"]},
                    "inputs": {**arr(S), "minItems": 1}, "weights": arr(S), "of": arr(S), "scale": S},
                    "required": ["op", "inputs"]}},
               ["ref", "metric_id", "value", "unit", "segment", "source_expression", "extraction_status"])
BEFORE = obj({"claim": S, "placements": {**arr(S), "minItems": 1}}, ["claim", "placements"])
AFTER = obj({"claim": S, "segments": {**arr(S), "minItems": 1}}, ["claim", "segments"])
REVISION = obj({"operation": {"enum": ["REPLACEMENT", "SPLIT", "MERGE", "RESTORE", "DELETE"]},
                "before": arr(BEFORE), "after": arr(AFTER), "status": STATUS, "reason": S},
               ["operation", "before", "after", "status", "reason"])
RELATION = obj({"src": S, "dst": S, "type": {"enum": [
    "DEPENDS_ON", "SUPPORTS", "ENTAILS", "CONTRADICTS", "QUALIFIES"]},
    "status": STATUS, "reason": S}, ["src", "dst", "type", "status", "reason"])
ASSESSMENT = obj({"claim": S, "evidence": S, "status": {"enum": [
    "supported", "partially_supported", "unsupported", "counterevidence", "unknown", "pending"]},
    "reason": S, "limitations": arr(S)}, ["claim", "evidence", "status", "reason"])
CHECK = obj({"claim_ids": {**arr(S), "minItems": 1}, "kind": S,
             "outcome": {"enum": ["pass", "fail", "conflict", "insufficient_evidence", "incomparable", "pending", "error"]},
             "reason": S, "method": S, "evidence_ids": arr(S)},
            ["claim_ids", "kind", "outcome", "reason", "method"])
ARGUMENT = obj({"ref": S, "conclusion": S, "premises": {**arr(S), "minItems": 1},
                "status": STATUS, "reason": S}, ["ref", "conclusion", "premises", "status", "reason"])
SEMANTIC = obj({"claims": arr(CLAIM), "bindings": arr(obj({"claim": S, "segment": S, "reason": S},
    ["claim", "segment", "reason"])), "non_claim_segments": arr(obj({"segment": S, "reason": S}, ["segment", "reason"])),
    "revisions": arr(REVISION), "references": arr(REFERENCE), "evidence": arr(EVIDENCE),
    "quantities": arr(QUANTITY), "relations": arr(RELATION), "assessments": arr(ASSESSMENT),
    "checks": arr(CHECK), "arguments": arr(ARGUMENT)}, ["bindings"])
SEMANTIC["properties"]["reference_ids"] = arr(S)
SEMANTIC["properties"]["revision_decisions"] = arr(obj({"revision_id": S, "status": STATUS, "reason": S},
                                                      ["revision_id", "status", "reason"]))
SEMANTIC["properties"]["invalidate_checks"] = arr(obj({"check_id": S, "reason": S}, ["check_id", "reason"]))


def main():
    path = ROOT / "schema" / "proposal.schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    schema["properties"]["schema_version"] = {"enum": ["1.0.0", "1.1.0"]}
    schema["properties"]["segments"]["items"]["properties"]["ref"] = S
    schema["properties"]["semantic"] = SEMANTIC
    schema["description"] = "Agent proposals. Descriptive extensions are retained in the run; identity, byte ranges and semantic references are validated."
    for target in [path, ROOT / "papercheck" / "schemas" / "proposal.schema.json"]:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    record_defs = {
        "document": obj({"id": S, "created_state_id": S}, ["id", "created_state_id"]),
        "blocks": obj({"id": S, "kind": S}, ["id", "kind"]),
        "containers": obj({"id": S, "kind": S, "parent_block_id": S, "created_state_id": S}, ["id", "kind", "parent_block_id", "created_state_id"]),
        "variants": obj({"id": S, "container_id": S, "first_seen_state_id": S, "raw_text": {"type": "string"},
            "normalized_text": {"type": "string"}, "content_sha256": S, "source_range": {"type": "object"}},
            ["id", "container_id", "first_seen_state_id", "raw_text", "normalized_text", "content_sha256", "source_range"]),
        "snapshots": obj({"id": S, "state_id": S, "document_id": S, "source_hash": S,
            "selections": arr(obj({"placement_id": S, "container_id": S, "variant_id": S,
                                   "order": {"type": "integer"}, "source_ranges": arr({"type": "object"})},
                                  ["placement_id", "container_id", "variant_id", "order", "source_ranges"])),
            "untracked_blocks": arr({"type": "object"})}, ["id", "state_id", "document_id", "source_hash", "selections", "untracked_blocks"]),
        "events": obj({"id": S, "type": S, "run_id": S, "state_id": S, "before": arr(S), "after": arr(S), "reason": {"type": "string"}},
                      ["id", "type", "run_id", "state_id", "before", "after", "reason"]),
        "runs": obj({"id": S, "state_id": S, "snapshot_id": S, "mode": S}, ["id", "state_id", "snapshot_id", "mode"]),
    }
    columns = {
        "claims": {"surface_statement": S, "canonical_statement": {"type": "object"}, "flags": arr(S),
                   "semantic_fingerprint": {"type": ["string", "null"]}, "identity_status": {"enum": ["known", "unknown"]}},
        "references": {"title": S, "source_access": REFERENCE["properties"]["source_access"]},
        "evidence": {"reference_id": S, "quote": S, "locator": {"type": "object"}, "source_access": S, "shared_source_ids": arr(S)},
        "bindings": {"claim_id": S, "placement_id": S, "snapshot_id": S, "container_id": S, "variant_id": S, "reason": S},
        "revisions": {"operation": REVISION["properties"]["operation"], "before_snapshot_id": S,
                      "after_snapshot_id": S, "before": arr({"type": "object"}), "after": arr({"type": "object"}), "status": STATUS},
        "relations": {"src": S, "dst": S, "type": S, "status": STATUS},
        "quantities": {"metric_id": S, "value": VALUE, "unit": S, "locator": {"type": "object"}, "extraction_status": S, "claim_ids": arr(S)},
        "assessments": {"claim_id": S, "evidence_id": S, "snapshot_id": S, "status": ASSESSMENT["properties"]["status"], "reason": S},
        "checks": {"claim_ids": arr(S), "kind": S, "outcome": S, "reason": S, "method": S, "snapshot_id": S},
        "arguments": {"conclusion": S, "premises": arr(S), "status": STATUS, "reason": S},
        "reviews": {"claim_ids": arr(S), "snapshot_id": S, "check_id": S, "outcome": S, "reason": S, "method": S},
        "invalidations": {"check_id": S, "snapshot_id": S, "cause_claim_ids": arr(S), "reason": S},
    }
    for key, props in columns.items():
        record_defs[key] = obj({"id": S, "schema_version": {"const": "1.1.0"}, "state_id": S, "run_id": S, **props},
                               ["id", "schema_version", "state_id", "run_id", *props])
    record_schema = {"$schema": "https://json-schema.org/draft/2020-12/schema", "$defs": record_defs}
    for target in [ROOT / "schema" / "records.schema.json", ROOT / "papercheck" / "schemas" / "records.schema.json"]:
        target.write_text(json.dumps(record_schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    import hashlib
    text = "X causes Y.\n"
    example = {"schema_version": "1.1.0", "base_state_id": None, "base_sha256": None,
        "paper_sha256": "sha256:" + hashlib.sha256(text.encode()).hexdigest(),
        "segments": [{"ref": "s", "kind": "paragraph", "block_ref": "p", "text": text,
                      "source_ranges": [{"start_byte": 0, "end_byte": len(text.encode())}]}], "untracked": [],
        "semantic": {"claims": [{"ref": "c", "surface_statement": "X causes Y.", "kind": "assertion",
            "canonical_statement": {"subject": {"entity_id": "X"}, "predicate": "causes", "object": {"entity_id": "Y"},
                "polarity": "positive", "modality": "asserted", "causality": "causal", "quantifier": None,
                "population": None, "time_scope": None, "conditions": [], "quantity_ids": []}}],
            "bindings": [{"claim": "c", "segment": "s", "reason": "The paragraph expresses this assertion."}],
            "references": [{"ref": "r", "title": "Original study (not supplied)", "source_access": "unavailable"}]}}
    for target in [ROOT / "examples" / "initial-proposal.json", ROOT / "papercheck" / "template" / "templates" / "proposal.example.json"]:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(example, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (ROOT / "examples" / "paper.md").write_bytes(text.encode("utf-8"))
    guide = ROOT / "papercheck" / "template" / "workflow" / "05-semantic-contract.md"
    guide.write_bytes((
        "> 独立工作区提示：完整机器契约已导出到 `contracts/proposal.schema.json` 和 `contracts/records.schema.json`。\n\n"
        + (ROOT / "docs" / "semantic-contract.md").read_text(encoding="utf-8")
    ).encode("utf-8"))


if __name__ == "__main__":
    main()

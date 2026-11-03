"""Arithmetic re-computation of reported numbers, plus readable output for long manuscripts.

All manuscripts are synthetic; the numbers mirror the rounding patterns of real results tables.
"""
from copy import deepcopy

import pytest

from papercheck.cli import main
from papercheck.inspector import project
from papercheck.quantity import derive
from papercheck.report import write_report
from papercheck.storage import Repo, ValidationError
from test_semantic import proposal

SCOPE = {"population": "validation works", "dataset_id": "synthetic", "dataset_version": "v1",
         "sample_filter": "pooled", "time_scope": "2020-2026"}
TEXT = ("Cohorts hold 273, 215 and 169 works, 657 in total. "
        "Ablated MAE is 12.729 against a full-model MAE of 11.158, a rise of 1.572.")


def q(ref, metric, value, expression, derivation=None, **extra):
    row = {"ref": ref, "metric_id": metric, "value": {"type": "point", "value_decimal": value},
           "unit": "works" if "." not in value else "points", "segment": "s", "source_expression": expression,
           "extraction_status": "confirmed", **SCOPE, **extra}
    if derivation:
        row["derivation"] = derivation
    return row


def quantities(total="657", delta="1.572"):
    return [q("a", "n.c1", "273", "273"), q("b", "n.c2", "215", "215"), q("c", "n.c3", "169", "169"),
            q("t", "n.total", total, f"{total} in total", {"op": "sum", "inputs": ["a", "b", "c"]}, claim="c"),
            q("abl", "mae.ablated", "12.729", "12.729"), q("full", "mae.full", "11.158", "11.158"),
            q("d", "mae.delta", delta, delta, {"op": "difference", "inputs": ["abl", "full"]})]


def commit(repo, rows, text=TEXT):
    p = proposal(repo, text)
    p["semantic"]["quantities"] = rows
    repo.commit(proposal=p)
    state = repo.load_current()
    return state, [c for c in state.checks if c["id"] in state.snapshot["check_ids"] and c["kind"] == "quantity_derivation"]


def test_rounded_difference_passes_and_sample_sum_is_recomputed(tmp_path):
    state, checks = commit(Repo(tmp_path), quantities())
    assert sorted(c["outcome"] for c in checks) == ["pass", "pass"]
    # 12.729 - 11.158 = 1.571; three-decimal rounding of all three numbers admits 1.572.
    delta = next(c for c in checks if "mae.delta" in c["reason"])
    assert "1.571" in delta["reason"]
    stored = next(r for r in state.quantities if r["metric_id"] == "n.total")
    assert stored["derivation"]["inputs"] == ["Q000001", "Q000002", "Q000003"]
    assert next(c for c in checks if "n.total" in c["reason"])["claim_ids"] == ["C000001"]


def test_transposed_digit_is_an_action_required_conflict(tmp_path):
    text = TEXT.replace("657", "675")
    state, checks = commit(Repo(tmp_path), quantities(total="675"), text)
    conflict = next(c for c in checks if c["outcome"] == "conflict")
    assert "657" in conflict["reason"] and "675" in conflict["reason"]
    tasks = state.snapshot["workflow"]["tasks"]
    assert any(t["type"] == "resolve_check" and t["status"] == "action_required" and t["target"] == conflict["id"] for t in tasks)


def test_difference_outside_rounding_is_a_conflict(tmp_path):
    text = TEXT.replace("1.572", "1.575")
    _, checks = commit(Repo(tmp_path), quantities(delta="1.575"), text)
    assert next(c for c in checks if "mae.delta" in c["reason"])["outcome"] == "conflict"


def test_weighted_mean_and_share_use_interval_bounds():
    rows = {"m1": q("m1", "mae.c1", "9.825", ""), "m2": q("m2", "mae.c2", "12.689", ""),
            "m3": q("m3", "mae.c3", "11.363", ""), "n1": q("n1", "n1", "273", ""),
            "n2": q("n2", "n2", "215", ""), "n3": q("n3", "n3", "169", "")}
    target = q("p", "mae.pooled", "11.158", "", {"op": "weighted_mean", "inputs": ["m1", "m2", "m3"],
                                                  "weights": ["n1", "n2", "n3"]})
    assert derive(target, rows, {})[0] == "pass"
    assert derive({**target, "value": {"type": "point", "value_decimal": "11.200"}}, rows, {})[0] == "conflict"
    share = q("s", "share", "74.0", "", {"op": "share", "inputs": ["n1"], "of": ["n1", "n2", "n3"], "scale": "100"})
    assert derive(share, rows, {})[0] == "conflict"  # 273 / 657 = 41.55 %
    assert derive({**share, "value": {"type": "point", "value_decimal": "41.6"}}, rows, {})[0] == "pass"
    mean = q("h", "hybrid", "67.444", "", {"op": "mean", "inputs": ["m1", "m2"]})
    assert derive(mean, rows, {})[0] == "conflict"


def test_unconfirmed_or_missing_inputs_do_not_pass(tmp_path):
    rows = {"a": q("a", "a", "1", "", extraction_status="proposed"), "b": q("b", "b", "2", "")}
    target = q("t", "t", "3", "", {"op": "sum", "inputs": ["a", "b"]})
    assert derive(target, rows, {})[0] == "pending"
    assert derive({**target, "derivation": {"op": "sum", "inputs": ["a", "gone"]}}, rows, {})[0] == "insufficient_context"
    zero = {"x": q("x", "x", "0.0", ""), "y": q("y", "y", "1", "")}
    ratio = q("r", "r", "2", "", {"op": "ratio", "inputs": ["y", "x"]})
    assert derive(ratio, zero, {})[0] == "error"


@pytest.mark.parametrize("derivation,match", [
    ({"op": "median", "inputs": ["a"]}, "derivation.op"),
    ({"op": "difference", "inputs": ["a"]}, "at least 2"),
    ({"op": "weighted_mean", "inputs": ["a", "b"], "weights": ["a"]}, "one weight"),
    ({"op": "sum", "inputs": ["a", "missing"]}, "unknown quantities: missing"),
    ({"op": "sum", "inputs": ["t", "a"]}, "refers to itself"),
])
def test_malformed_derivations_name_the_quantity(tmp_path, derivation, match):
    repo = Repo(tmp_path)
    rows = quantities()
    rows[3]["derivation"] = derivation
    with pytest.raises(ValidationError, match=match):
        commit(repo, rows)


def test_missing_expression_error_names_quantity_and_segment(tmp_path):
    rows = quantities()
    rows[0]["source_expression"] = "n = 273"
    with pytest.raises(ValidationError, match="quantity a: source_expression 'n = 273' is not present at segment s"):
        commit(Repo(tmp_path), rows)


def test_derivation_checks_are_recomputed_after_an_edit(tmp_path):
    repo = Repo(tmp_path)
    first, checks = commit(repo, quantities())
    old_ids = {c["id"] for c in checks}
    second, checks = commit(repo, quantities(total="675"), TEXT.replace("657", "675"))
    assert old_ids <= {i["check_id"] for i in second.invalidations}
    assert any(c["outcome"] == "conflict" for c in checks)
    assert all(c["outcome"] == "pass" for c in first.checks if c["id"] in old_ids)  # history unchanged


def test_report_lists_conflicts_first_with_quantity_names(tmp_path):
    repo = Repo(tmp_path)
    p = proposal(repo, TEXT.replace("657", "675"))
    p["semantic"]["quantities"] = quantities(total="675")
    repo.commit(proposal=p)
    report = write_report(repo, repo.load_current(), {}).read_text(encoding="utf-8")
    checks = report.split("## 本轮有效检查")[1].split("##")[0]
    assert "quantity_derivation / conflict × 1" in checks
    lines = [line for line in checks.splitlines() if line.startswith("- CHK")]
    assert "conflict" in lines[0] and "n.total" in lines[0]


def test_report_folds_markup_gaps_and_long_task_lists(tmp_path):
    repo = Repo(tmp_path)
    body = "\n\n".join(f"## Part {i}\n\nParagraph {i} states a result." for i in range(30))
    repo.paper_path.write_text("# Title\n\n" + body + "\n\n| a | b |\n|---|---|\n| 1 | 2 |\n", encoding="utf-8")
    repo.commit(auto=True)
    report = write_report(repo, repo.load_current(), {}).read_text(encoding="utf-8")
    assert "| 结构性间隔 |" not in report and "空白与 Markdown 标记" in report
    assert "| a \\| b \\|" in report  # substantive untracked table text is still listed
    assert "另有" in report and "workflow --json" in report


def test_workflow_cli_summarises_and_limits(tmp_path, capsys):
    repo = Repo(tmp_path)
    commit(repo, quantities(total="675"), TEXT.replace("657", "675"))
    assert main(["--root", str(tmp_path), "workflow", "--limit", "1"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert "action_required resolve_check" in out[-2] and out[-1].startswith("... ")
    assert any("review_claim" in line and line.strip()[0].isdigit() for line in out)
    assert main(["--root", str(tmp_path), "workflow", "--type", "review_claim"]) == 0
    listed = [l for l in capsys.readouterr().out.splitlines() if l.startswith(("pending", "action_required"))]
    assert listed and all(" review_claim " in l for l in listed)


def test_inspector_sections_follow_parsed_headings(tmp_path):
    repo = Repo(tmp_path)
    repo.paper_path.write_text("# Methods\n\nWe count works.\n\n## Results\n\nThe total is 657.\n", encoding="utf-8")
    repo.commit(auto=True)
    data, _, _ = project(repo)
    headings = [b["raw"] for b in data["blocks"] if b["kind"] == "heading"]
    assert headings == ["Methods", "Results"]
    assert next(b for b in data["blocks"] if "657" in b["raw"])["section"] == "Results"


def test_inspector_hides_bare_markdown_markers(tmp_path):
    repo = Repo(tmp_path)
    repo.paper_path.write_text("## 3. Results\n\nText here.\n", encoding="utf-8")
    repo.commit(auto=True)
    data, _, _ = project(repo)
    assert all(b["raw"].strip("# \n") for b in data["blocks"])

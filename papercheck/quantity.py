"""Deterministic comparison of Agent-extracted quantities; no text guessing."""
from decimal import Decimal, InvalidOperation, localcontext
from itertools import combinations, product

SCOPE = ("metric_id", "population", "dataset_id", "dataset_version", "sample_filter", "time_scope")
UNITS = {
    "%": ("ratio", "0.01"), "percent": ("ratio", "0.01"), "ratio": ("ratio", "1"),
    "kg": ("mass", "1000"), "g": ("mass", "1"), "mg": ("mass", "0.001"),
    "m": ("length", "1"), "cm": ("length", "0.01"), "mm": ("length", "0.001"),
    "s": ("time", "1"), "ms": ("time", "0.001"),
}


def decimal(value):
    if not isinstance(value, str):
        raise ValueError("quantity values must be decimal strings")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"invalid decimal {value!r}") from exc
    if not result.is_finite():
        raise ValueError("quantity must be finite")
    return result


def validate_quantity(row):
    value = row.get("value", {})
    kind = value.get("type")
    if kind == "point":
        decimal(value.get("value_decimal"))
    elif kind in ("range", "interval"):
        if decimal(value.get("value_lower")) > decimal(value.get("value_upper")):
            raise ValueError("quantity lower bound exceeds upper bound")
        if kind == "interval":
            confidence = decimal(value.get("confidence"))
            if not 0 < confidence < 1:
                raise ValueError("confidence must be between zero and one")
    else:
        raise ValueError("quantity value.type must be point, range or interval")
    if decimal(row.get("tolerance_decimal", "0")) < 0:
        raise ValueError("quantity tolerance must be non-negative")
    inclusive = value.get("inclusive", True)
    if not isinstance(inclusive, bool) and not (isinstance(inclusive, list) and len(inclusive) == 2 and all(isinstance(v, bool) for v in inclusive)):
        raise ValueError("inclusive must be a boolean or a pair of booleans")
    if row.get("derivation") is not None:
        validate_derivation(row["derivation"])


def compare(left, right):
    if any(key not in row or row[key] == "unknown" for row in (left, right) for key in SCOPE):
        return "insufficient_context", "缺少可比性范围；需要总体、数据集、版本、筛选与时间范围。"
    if any(left[key] != right[key] for key in SCOPE):
        return "incomparable", "指标或研究范围不同。"
    if any(row.get("extraction_status") != "confirmed" for row in (left, right)):
        return "pending", "数值抽取尚未确认。"
    if any(row.get("operator", "=") != "=" for row in (left, right)):
        return "pending", "非等值比较符需要专门的约束检查。"
    lu, ls = UNITS.get(left["unit"], (left["unit"], "1"))
    ru, rs = UNITS.get(right["unit"], (right["unit"], "1"))
    if lu != ru:
        return "incomparable", "单位无法按已登记规则换算。"
    if lu == "ratio" and left.get("percent_base") != right.get("percent_base"):
        return "insufficient_context", "百分比的基数不一致或缺失。"
    if lu == "ratio" and not left.get("percent_base"):
        return "insufficient_context", "百分比/比例需要明确基数。"

    def bounds(row, scale):
        value = row["value"]
        if value["type"] == "point":
            low = high = decimal(value["value_decimal"])
        else:
            low, high = decimal(value["value_lower"]), decimal(value["value_upper"])
        tolerance = decimal(row.get("tolerance_decimal", "0"))
        factor = decimal(scale)
        inclusive = value.get("inclusive", True)
        flags = [inclusive, inclusive] if isinstance(inclusive, bool) else inclusive
        if tolerance > 0 or value["type"] == "point":
            flags = [True, True]
        return (low - tolerance) * factor, (high + tolerance) * factor, flags

    ll, lh, li = bounds(left, ls)
    rl, rh, ri = bounds(right, rs)
    conflict = lh < rl or rh < ll or (lh == rl and not (li[1] and ri[0])) or (rh == ll and not (ri[1] and li[0]))
    return ("conflict", "相同指标与范围的数值区间不相容。") if conflict else ("pass", "按十进制数值、单位和容差比较一致。")


def quantity_checks(rows):
    # Different metrics are independent and do not require pairwise work.
    groups = {}
    for row in rows:
        groups.setdefault(row["metric_id"], []).append(row)
    for group in groups.values():
        for left, right in combinations(group, 2):
            outcome, reason = compare(left, right)
            yield {"kind": "quantity_consistency", "outcome": outcome, "reason": reason,
                   "method": "decimal_quantity_v1", "quantity_ids": [left["id"], right["id"]],
                   "claim_ids": sorted({cid for row in (left, right) for cid in row.get("claim_ids", [])}),
                   "evidence_ids": []}


# Arithmetic re-computation of a stated value from other extracted quantities.
DERIVATION_OPS = {"sum", "difference", "product", "ratio", "mean", "weighted_mean", "share"}
MAX_DERIVATION_INPUTS = 12


def derivation_refs(derivation):
    return [*derivation.get("inputs", []), *derivation.get("weights", []), *derivation.get("of", [])]


def validate_derivation(derivation):
    if not isinstance(derivation, dict):
        raise ValueError("derivation must be an object")
    op = derivation.get("op")
    if op not in DERIVATION_OPS:
        raise ValueError(f"derivation.op must be one of {sorted(DERIVATION_OPS)}")
    inputs = derivation.get("inputs")
    if not isinstance(inputs, list) or not inputs or not all(isinstance(v, str) and v for v in inputs):
        raise ValueError("derivation.inputs must be a non-empty array of quantity references")
    minimum = {"difference": 2, "ratio": 2, "product": 2}.get(op, 1)
    if len(inputs) < minimum or (op == "ratio" and len(inputs) != 2):
        raise ValueError(f"derivation {op} needs {'exactly 2' if op == 'ratio' else f'at least {minimum}'} inputs")
    if op == "weighted_mean" and len(derivation.get("weights") or []) != len(inputs):
        raise ValueError("weighted_mean needs one weight quantity per input")
    if op == "share" and not derivation.get("of"):
        raise ValueError("share needs an 'of' array naming the denominator quantities")
    for key in ("weights", "of"):
        if key in derivation and not all(isinstance(v, str) and v for v in derivation[key] or [None]):
            raise ValueError(f"derivation.{key} must be an array of quantity references")
    if len(set(derivation_refs(derivation))) > MAX_DERIVATION_INPUTS:
        raise ValueError(f"derivation uses more than {MAX_DERIVATION_INPUTS} distinct quantities")
    decimal(derivation.get("scale", "1"))


def reported_halfwidth(row):
    """Rounding half-width implied by how the value is written (integers are exact counts)."""
    value = row["value"]
    if value["type"] != "point":
        raise ValueError("derivations use point quantities")
    exponent = decimal(value["value_decimal"]).as_tuple().exponent
    half = Decimal(5).scaleb(exponent - 1) if exponent < 0 else Decimal(0)
    if row.get("precision") == "exact":
        half = Decimal(0)
    return half + decimal(row.get("tolerance_decimal", "0"))


def _evaluate(op, values, derivation):
    inputs = [values[r] for r in derivation["inputs"]]
    if op == "sum":
        result = sum(inputs, Decimal(0))
    elif op == "difference":
        result = inputs[0] - sum(inputs[1:], Decimal(0))
    elif op == "product":
        result = Decimal(1)
        for item in inputs:
            result *= item
    elif op == "ratio":
        result = inputs[0] / inputs[1]
    elif op == "mean":
        result = sum(inputs, Decimal(0)) / len(inputs)
    elif op == "weighted_mean":
        weights = [values[r] for r in derivation["weights"]]
        result = sum((v * w for v, w in zip(inputs, weights)), Decimal(0)) / sum(weights, Decimal(0))
    else:  # share
        result = sum(inputs, Decimal(0)) / sum((values[r] for r in derivation["of"]), Decimal(0))
    return result * decimal(derivation.get("scale", "1"))


def _fmt(value):
    return format(value.quantize(Decimal("0.000001")).normalize(), "f")


def derive(target, rows_by_id, refs):
    """Recompute target from rounded inputs; returns (outcome, reason, low, high)."""
    derivation = target["derivation"]
    inputs = {ref: rows_by_id.get(refs.get(ref, ref)) for ref in derivation_refs(derivation)}
    missing = sorted(ref for ref, row in inputs.items() if row is None)
    if missing:
        return "insufficient_context", f"推导输入不在当前快照中：{', '.join(missing)}。", None, None
    if any(row.get("extraction_status") != "confirmed" for row in [target, *inputs.values()]):
        return "pending", "推导所用数值尚未全部确认抽取。", None, None
    try:
        bounds = {}
        for ref, row in inputs.items():
            centre, half = decimal(row["value"]["value_decimal"]), reported_halfwidth(row)
            bounds[ref] = (centre - half, centre + half)
        stated, half = decimal(target["value"]["value_decimal"]), reported_halfwidth(target)
        names = list(bounds)
        denominator = {"ratio": derivation["inputs"][1:], "weighted_mean": derivation.get("weights", []),
                       "share": derivation.get("of", [])}.get(derivation["op"], [])
        if denominator:
            low_d = sum((bounds[r][0] for r in denominator), Decimal(0))
            high_d = sum((bounds[r][1] for r in denominator), Decimal(0))
            if low_d <= 0 <= high_d:
                return "error", "推导分母在舍入范围内可能为零，无法确定比较区间。", None, None
        results = []
        with localcontext() as ctx:
            ctx.prec = 40
            # Each operation is multilinear or linear-fractional with a sign-definite
            # denominator, so its extremes over the rounding box lie at the corners.
            for corner in product(*([bounds[n][0], bounds[n][1]] for n in names)):
                results.append(_evaluate(derivation["op"], dict(zip(names, corner)), derivation))
            point = _evaluate(derivation["op"], {n: decimal(inputs[n]["value"]["value_decimal"]) for n in names}, derivation)
    except (ArithmeticError, ValueError) as exc:
        return "error", f"推导无法计算：{exc}", None, None
    low, high = min(results), max(results)
    if stated + half < low or stated - half > high:
        return ("conflict", f"按输入重算得 {_fmt(point)}（考虑舍入后可取 [{_fmt(low)}, {_fmt(high)}]），"
                f"与所写 {target['value']['value_decimal']} 不相容。", low, high)
    return "pass", f"按输入重算得 {_fmt(point)}，与所写 {target['value']['value_decimal']} 在舍入范围内一致。", low, high


def derivation_checks(rows, refs=None):
    """Yield one check per current quantity that declares a derivation."""
    by_id = {row["id"]: row for row in rows}
    for row in rows:
        if not row.get("derivation"):
            continue
        outcome, reason, _, _ = derive(row, by_id, refs or {})
        reason = f"{row['metric_id']}「{row.get('source_expression', '')}」：{reason}"
        inputs = [(refs or {}).get(ref, ref) for ref in derivation_refs(row["derivation"])]
        involved = [row, *(by_id[i] for i in inputs if i in by_id)]
        yield {"kind": "quantity_derivation", "outcome": outcome, "reason": reason,
               "method": "decimal_interval_derivation_v1",
               "quantity_ids": list(dict.fromkeys([row["id"], *inputs])),
               "claim_ids": sorted({cid for q in involved for cid in q.get("claim_ids", [])}),
               "evidence_ids": []}

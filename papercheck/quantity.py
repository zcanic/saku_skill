"""Deterministic comparison of Agent-extracted quantities; no text guessing."""
from decimal import Decimal, InvalidOperation
from itertools import combinations

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

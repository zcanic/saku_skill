from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable

PREFIXES = {
    "state": "D",
    "document": "DOC",
    "snapshot": "SNAP",
    "block": "B",
    "container": "S",
    "variant": "V",
    "placement": "PL",
    "claim": "C",
    "relation": "L",
    "revision": "REV",
    "evidence": "E",
    "reference": "REF",
    "quantity": "Q",
    "check": "CHK",
    "event": "EV",
    "run": "RUN",
    "dataset": "DATASET",
    "study": "STUDY",
    "assessment": "A",
    "review": "RV",
    "argument": "ARG",
    "invalidation": "INV",
    "binding": "BD",
}

WIDTH = 6


def _suffix(value: str, prefix: str) -> int | None:
    match = re.fullmatch(re.escape(prefix) + r"(\d+)", value)
    return int(match.group(1)) if match else None


def max_id(records: Iterable[dict[str, Any]], kind: str, key: str = "id") -> int:
    prefix = PREFIXES[kind]
    maximum = 0
    for record in records:
        value = record.get(key) if isinstance(record, dict) else record
        if not isinstance(value, str):
            continue
        suffix = _suffix(value, prefix)
        if suffix is not None and suffix > maximum:
            maximum = suffix
    return maximum


def next_id(records: Iterable[dict[str, Any]], kind: str, key: str = "id") -> str:
    return f"{PREFIXES[kind]}{max_id(records, kind, key) + 1:0{WIDTH}d}"


def next_state_id(states_dir: Path) -> str:
    maximum = 0
    if states_dir.exists():
        for child in states_dir.iterdir():
            if not child.is_dir():
                continue
            suffix = _suffix(child.name, PREFIXES["state"])
            if suffix is not None and suffix > maximum:
                maximum = suffix
    return f"{PREFIXES['state']}{maximum + 1:0{WIDTH}d}"

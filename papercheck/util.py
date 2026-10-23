from __future__ import annotations

import contextlib
import datetime as _dt
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Iterable, Iterator

try:  # Windows
    import msvcrt
except ImportError:  # pragma: no cover - POSIX
    msvcrt = None  # type: ignore[assignment]

try:  # POSIX
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]


def load_env_file(path: Path) -> None:
    """Load KEY=VALUE lines without overriding an existing environment."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return "sha256:" + h.hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def read_text(path: Path) -> str:
    with open(path, "r", encoding="utf-8", newline="") as f:
        return f.read()


def read_bytes(path: Path) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{lineno}: invalid JSONL: {exc}") from exc
    return out


def read_jsonl_tolerant(path: Path) -> list[dict[str, Any]]:
    """Read JSONL, ignoring only an incomplete final line from a crash."""
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    out: list[dict[str, Any]] = []
    for index, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            if any(later.strip() for later in lines[index + 1:]):
                raise ValueError(f"{path}:{index + 1}: invalid JSONL")
            break
    return out


def _fsync_file(f) -> None:
    f.flush()
    os.fsync(f.fileno())


def _fsync_dir(path: Path) -> None:
    # Directory handles are not portable on Windows; best effort only.
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    with open(tmp, "wb") as f:
        f.write(data)
        _fsync_file(f)
    os.replace(tmp, path)
    _fsync_dir(path.parent)


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def write_json(path: Path, value: Any, *, indent: int = 2) -> None:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=indent) + "\n"
    atomic_write_text(path, text)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    lines = [canonical_json(row) for row in rows]
    payload = ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")
    atomic_write_bytes(path, payload)


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(canonical_json(row) + "\n")
        _fsync_file(f)


class LockTimeout(RuntimeError):
    pass


@contextlib.contextmanager
def exclusive_lock(path: Path, timeout: float = 30.0) -> Iterator[None]:
    """Single-writer lock. Windows uses msvcrt byte locking."""
    path.parent.mkdir(parents=True, exist_ok=True)
    f = open(path, "a+b")
    try:
        f.seek(0, os.SEEK_END)
        if f.tell() == 0:
            f.write(b"0")
            f.flush()
            os.fsync(f.fileno())
        f.seek(0)
        deadline = time.monotonic() + timeout
        while True:
            try:
                if msvcrt is not None:
                    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                elif fcntl is not None:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if time.monotonic() >= deadline:
                    raise LockTimeout(f"could not acquire {path}") from exc
                time.sleep(0.05)
        yield
    finally:
        try:
            if msvcrt is not None:
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            elif fcntl is not None:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        finally:
            f.close()


def char_byte_offsets(text: str) -> list[int]:
    """offsets[i] is the UTF-8 byte offset of text[:i]."""
    offsets = [0] * (len(text) + 1)
    total = 0
    for i, ch in enumerate(text):
        total += len(ch.encode("utf-8"))
        offsets[i + 1] = total
    return offsets

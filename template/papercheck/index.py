from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from .state import StateView
from .util import canonical_json

TABLES = ("blocks", "containers", "variants", "snapshots", "placements", "events")
LEDGER_KEYS = ("claims", "bindings", "revisions", "relations", "references", "evidence",
               "assessments", "quantities", "checks", "arguments", "reviews", "invalidations", "runs")

SQLITE_SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE blocks (id TEXT PRIMARY KEY, kind TEXT NOT NULL, created_state_id TEXT, last_seen_state_id TEXT);
CREATE TABLE containers (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  parent_block_id TEXT,
  created_state_id TEXT,
  last_seen_state_id TEXT
);
CREATE TABLE variants (
  id TEXT PRIMARY KEY,
  container_id TEXT NOT NULL,
  normalized_text TEXT,
  content_sha256 TEXT,
  first_seen_state_id TEXT
);
CREATE TABLE snapshots (
  id TEXT PRIMARY KEY,
  state_id TEXT NOT NULL,
  source_hash TEXT,
  created_state_id TEXT
);
CREATE TABLE placements (
  placement_id TEXT NOT NULL,
  seq INTEGER NOT NULL,
  snapshot_id TEXT NOT NULL,
  container_id TEXT NOT NULL,
  variant_id TEXT NOT NULL,
  ord INTEGER,
  start_byte INTEGER,
  end_byte INTEGER,
  PRIMARY KEY (placement_id, seq)
);
CREATE TABLE events (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL,
  state_id TEXT,
  run_id TEXT,
  before_json TEXT,
  after_json TEXT,
  occurred_at TEXT
);
CREATE INDEX idx_placements_snapshot ON placements(snapshot_id);
CREATE INDEX idx_variants_container ON variants(container_id);
CREATE INDEX idx_events_type ON events(type);
"""

POSTGRES_SCHEMA = """
DROP TABLE IF EXISTS meta, blocks, containers, variants, snapshots, placements, events, semantic_records CASCADE;
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE blocks (id TEXT PRIMARY KEY, kind TEXT NOT NULL, created_state_id TEXT, last_seen_state_id TEXT);
CREATE TABLE containers (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  parent_block_id TEXT,
  created_state_id TEXT,
  last_seen_state_id TEXT
);
CREATE TABLE variants (
  id TEXT PRIMARY KEY,
  container_id TEXT NOT NULL,
  normalized_text TEXT,
  content_sha256 TEXT,
  first_seen_state_id TEXT
);
CREATE TABLE snapshots (
  id TEXT PRIMARY KEY,
  state_id TEXT NOT NULL,
  source_hash TEXT,
  created_state_id TEXT
);
CREATE TABLE placements (
  placement_id TEXT NOT NULL,
  seq INTEGER NOT NULL,
  snapshot_id TEXT NOT NULL,
  container_id TEXT NOT NULL,
  variant_id TEXT NOT NULL,
  ord INTEGER,
  start_byte INTEGER,
  end_byte INTEGER,
  PRIMARY KEY (placement_id, seq)
);
CREATE TABLE events (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL,
  state_id TEXT,
  run_id TEXT,
  before_json TEXT,
  after_json TEXT,
  occurred_at TEXT
);
CREATE INDEX idx_placements_snapshot ON placements(snapshot_id);
CREATE INDEX idx_variants_container ON variants(container_id);
CREATE INDEX idx_events_type ON events(type);
"""

SEMANTIC_SCHEMA = """
CREATE TABLE semantic_records (kind TEXT NOT NULL, id TEXT NOT NULL, body_json TEXT NOT NULL,
                              PRIMARY KEY (kind, id));
"""
SQLITE_SCHEMA += SEMANTIC_SCHEMA
POSTGRES_SCHEMA += SEMANTIC_SCHEMA


def _ledger_rows(state):
    return [(key, row["id"], canonical_json(row)) for key in LEDGER_KEYS for row in getattr(state, key)]


def _rows(state: StateView):
    meta = [
        ("indexed_state_id", state.state_id),
        ("schema_version", state.manifest.get("schema_version", "")),
        ("snapshot_id", state.snapshot_id),
    ]
    blocks = [
        (row.get("id"), row.get("kind"), row.get("created_state_id"), row.get("last_seen_state_id"))
        for row in state.blocks
    ]
    containers = [
        (
            row.get("id"),
            row.get("kind"),
            row.get("parent_block_id"),
            row.get("created_state_id"),
            row.get("last_seen_state_id"),
        )
        for row in state.containers
    ]
    variants = [
        (
            row.get("id"),
            row.get("container_id"),
            row.get("normalized_text"),
            row.get("content_sha256"),
            row.get("first_seen_state_id"),
        )
        for row in state.variants
    ]
    snapshots = [
        (row.get("id"), row.get("state_id"), row.get("source_hash"), row.get("state_id"))
        for row in state.snapshots
    ]
    placements = []
    for snap in state.snapshots:
        for sel in snap.get("selections", []):
            for seq, rng in enumerate(sel.get("source_ranges", [])):
                placements.append(
                    (
                        sel.get("placement_id"),
                        seq,
                        snap.get("id"),
                        sel.get("container_id"),
                        sel.get("variant_id"),
                        sel.get("order"),
                        rng.get("start_byte"),
                        rng.get("end_byte"),
                    )
                )
    events = [
        (
            row.get("id"),
            row.get("type"),
            row.get("state_id"),
            row.get("run_id"),
            canonical_json(row.get("before", [])),
            canonical_json(row.get("after", [])),
            row.get("occurred_at"),
        )
        for row in state.events
    ]
    return meta, blocks, containers, variants, snapshots, placements, events


def _redacted(url: str) -> str:
    parts = urlsplit(url)
    netloc = parts.hostname or ""
    if parts.port:
        netloc += f":{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, "", ""))


def rebuild_postgres(state: StateView, url: str) -> str:
    import psycopg2

    meta, blocks, containers, variants, snapshots, placements, events = _rows(state)
    conn = psycopg2.connect(url, connect_timeout=10)
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(POSTGRES_SCHEMA)
                cur.executemany("INSERT INTO meta(key, value) VALUES (%s, %s)", meta)
                cur.executemany(
                    "INSERT INTO blocks(id, kind, created_state_id, last_seen_state_id) VALUES (%s, %s, %s, %s)",
                    blocks,
                )
                cur.executemany(
                    "INSERT INTO containers(id, kind, parent_block_id, created_state_id, last_seen_state_id) VALUES (%s, %s, %s, %s, %s)",
                    containers,
                )
                cur.executemany(
                    "INSERT INTO variants(id, container_id, normalized_text, content_sha256, first_seen_state_id) VALUES (%s, %s, %s, %s, %s)",
                    variants,
                )
                cur.executemany(
                    "INSERT INTO snapshots(id, state_id, source_hash, created_state_id) VALUES (%s, %s, %s, %s)",
                    snapshots,
                )
                cur.executemany(
                    "INSERT INTO placements(placement_id, seq, snapshot_id, container_id, variant_id, ord, start_byte, end_byte) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                    placements,
                )
                cur.executemany(
                    "INSERT INTO events(id, type, state_id, run_id, before_json, after_json, occurred_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    events,
                )
                cur.executemany("INSERT INTO semantic_records(kind, id, body_json) VALUES (%s, %s, %s)", _ledger_rows(state))
    finally:
        conn.close()
    return _redacted(url)


def rebuild_index(state: StateView, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    if tmp.exists():
        tmp.unlink()
    meta, blocks, containers, variants, snapshots, placements, events = _rows(state)
    conn = sqlite3.connect(tmp)
    try:
        conn.executescript(SQLITE_SCHEMA)
        conn.executemany("INSERT INTO meta(key, value) VALUES (?, ?)", meta)
        conn.executemany(
            "INSERT INTO blocks(id, kind, created_state_id, last_seen_state_id) VALUES (?, ?, ?, ?)", blocks
        )
        conn.executemany(
            "INSERT INTO containers(id, kind, parent_block_id, created_state_id, last_seen_state_id) VALUES (?, ?, ?, ?, ?)",
            containers,
        )
        conn.executemany(
            "INSERT INTO variants(id, container_id, normalized_text, content_sha256, first_seen_state_id) VALUES (?, ?, ?, ?, ?)",
            variants,
        )
        conn.executemany(
            "INSERT INTO snapshots(id, state_id, source_hash, created_state_id) VALUES (?, ?, ?, ?)", snapshots
        )
        conn.executemany(
            "INSERT INTO placements(placement_id, seq, snapshot_id, container_id, variant_id, ord, start_byte, end_byte) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            placements,
        )
        conn.executemany(
            "INSERT INTO events(id, type, state_id, run_id, before_json, after_json, occurred_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            events,
        )
        conn.executemany("INSERT INTO semantic_records(kind, id, body_json) VALUES (?, ?, ?)", _ledger_rows(state))
        conn.commit()
    finally:
        conn.close()
    try:
        os.replace(tmp, path)
    except OSError:
        if path.exists():
            path.unlink()
        os.replace(tmp, path)
    return path


def query_counts(target) -> dict[str, int]:
    if isinstance(target, str) and target.startswith(("postgres://", "postgresql://")):
        import psycopg2

        with psycopg2.connect(target, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                out = {}
                for table in TABLES:
                    cur.execute(f"SELECT COUNT(*) FROM {table}")
                    out[table] = cur.fetchone()[0]
                for key in LEDGER_KEYS:
                    cur.execute("SELECT COUNT(*) FROM semantic_records WHERE kind=%s", (key,))
                    out[key] = cur.fetchone()[0]
                return out
    with sqlite3.connect(target) as conn:
        out = {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in TABLES
        }
        out.update({key: conn.execute("SELECT COUNT(*) FROM semantic_records WHERE kind=?", (key,)).fetchone()[0]
                    for key in LEDGER_KEYS})
        return out


def indexed_state(target) -> str | None:
    try:
        if isinstance(target, str) and target.startswith(("postgres://", "postgresql://")):
            import psycopg2

            with psycopg2.connect(target, connect_timeout=5) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT value FROM meta WHERE key='indexed_state_id'")
                    row = cur.fetchone()
                    return row[0] if row else None
        with sqlite3.connect(target) as conn:
            row = conn.execute("SELECT value FROM meta WHERE key='indexed_state_id'").fetchone()
            return row[0] if row else None
    except Exception:
        return None

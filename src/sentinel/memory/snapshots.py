"""Keep decision memory across redeploys when a Postgres URL is configured.

A repo's memory is a small SQLite file (FTS5 search needs SQLite), so the
whole file is mirrored as one Postgres row after every build and written back
to local disk on server start. Without SENTINEL_DATABASE_URL this is a no-op:
the local file is already the durable copy.
"""

from __future__ import annotations

import logging
import os
import time

from sentinel.db import DB
from sentinel.memory.store import db_path_for

log = logging.getLogger("sentinel.memory")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_snapshots (
    repo TEXT PRIMARY KEY,
    data BYTEA NOT NULL,
    updated_ts DOUBLE PRECISION NOT NULL
);
"""


def save(settings, repo: str) -> bool:
    """Mirror the repo's local memory file to Postgres. False when not applicable."""
    if not settings.database_url:
        return False
    path = db_path_for(settings.memory_home, repo)
    if not path.exists():
        return False
    conn = DB(settings.database_url)
    try:
        conn.script(_SCHEMA)
        conn.execute(
            "INSERT INTO memory_snapshots (repo, data, updated_ts) VALUES (?,?,?)"
            " ON CONFLICT(repo) DO UPDATE SET data=excluded.data,"
            " updated_ts=excluded.updated_ts",
            (repo, path.read_bytes(), time.time()),
        )
    finally:
        conn.close()
    return True


def restore_all(settings) -> int:
    """Write every mirrored memory missing on local disk. Returns files restored."""
    if not settings.database_url:
        return 0
    conn = DB(settings.database_url)
    try:
        conn.script(_SCHEMA)
        rows = conn.execute("SELECT repo, data FROM memory_snapshots").fetchall()
    finally:
        conn.close()
    restored = 0
    for repo, data in rows:
        path = db_path_for(settings.memory_home, repo)
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(bytes(data))
        os.replace(tmp, path)
        restored += 1
    if restored:
        log.info("restored %d decision memories from the database", restored)
    return restored

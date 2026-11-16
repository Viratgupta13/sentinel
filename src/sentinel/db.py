"""One tiny connection layer for the server's durable tables: SQLite or Postgres.

SQLite (a file under memory_home) is the default and needs nothing. When
`SENTINEL_DATABASE_URL` is set (e.g. a free Neon Postgres), review history and
the tenant store live there instead, so they survive redeploys on hosts with
ephemeral disks. The rebuildable caches (repo code index, decision memory) stay
on SQLite FTS5 either way.

Store code writes SQLite-flavoured SQL with `?` placeholders; the Postgres
path rewrites placeholders and shares one autocommit connection per process
(reconnecting once if the server dropped it - Neon closes idle connections).
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any

_pg_conns: dict[str, Any] = {}
_pg_lock = threading.Lock()


def location(settings, filename: str) -> str | Path:
    """Postgres URL when configured, else `<memory_home>/<filename>`."""
    url = getattr(settings, "database_url", "") or ""
    if url:
        return url
    home = Path(settings.memory_home).expanduser()
    home.mkdir(parents=True, exist_ok=True)
    return home / filename


def is_postgres(target: str | Path) -> bool:
    return isinstance(target, str) and target.startswith(("postgres://", "postgresql://"))


class DB:
    """Minimal connection facade: execute / executemany / script / commit / close."""

    def __init__(self, target: str | Path) -> None:
        self.dialect = "postgres" if is_postgres(target) else "sqlite"
        self._target = target
        if self.dialect == "sqlite":
            self._conn = sqlite3.connect(target)
        else:
            self._conn = _pg_connect(str(target))

    # --- statements ---

    def execute(self, sql: str, params: tuple | list = ()):
        if self.dialect == "sqlite":
            return self._conn.execute(sql, params)
        return self._pg(lambda c: c.execute(sql.replace("?", "%s"), params))

    def executemany(self, sql: str, rows: list) -> None:
        if self.dialect == "sqlite":
            self._conn.executemany(sql, rows)
            return
        if not rows:
            return

        def run(c):
            with c.cursor() as cur:
                cur.executemany(sql.replace("?", "%s"), rows)

        self._pg(run)

    def script(self, sql: str) -> None:
        if self.dialect == "sqlite":
            self._conn.executescript(sql)
        else:
            self._pg(lambda c: c.execute(sql))

    def commit(self) -> None:
        if self.dialect == "sqlite":
            self._conn.commit()
        # Postgres connections are autocommit.

    def close(self) -> None:
        if self.dialect == "sqlite":
            self._conn.close()
        # The Postgres connection is shared process-wide; it stays open.

    # --- postgres plumbing ---

    def _pg(self, fn):
        import psycopg

        try:
            return fn(self._conn)
        except psycopg.OperationalError:
            if not self._conn.closed and not self._conn.broken:
                raise
            self._conn = _pg_connect(str(self._target), fresh=True)
            return fn(self._conn)


def _pg_connect(url: str, fresh: bool = False):
    try:
        import psycopg
    except ImportError as e:  # pragma: no cover - depends on install extras
        raise RuntimeError(
            "SENTINEL_DATABASE_URL points at Postgres but psycopg is not installed "
            "(pip install -e '.[server]')."
        ) from e
    with _pg_lock:
        conn = _pg_conns.get(url)
        if fresh or conn is None or conn.closed or conn.broken:
            if conn is not None and not conn.closed:
                conn.close()
            conn = psycopg.connect(url, autocommit=True, connect_timeout=15)
            _pg_conns[url] = conn
        return conn

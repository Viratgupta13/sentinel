"""Tenant store: users, app installations, and which repos each covers.

One SQLite DB at <memory_home>/hub.db. Written from two directions:
the OAuth callback (who signed in, which installations they can see) and
webhook `installation` events (installed/uninstalled, repos added/removed).
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    github_id INTEGER PRIMARY KEY,
    login TEXT NOT NULL,
    name TEXT DEFAULT '',
    avatar_url TEXT DEFAULT '',
    created_ts REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS installations (
    installation_id INTEGER PRIMARY KEY,
    account_login TEXT NOT NULL,
    created_ts REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS user_installations (
    user_github_id INTEGER NOT NULL,
    installation_id INTEGER NOT NULL,
    UNIQUE(user_github_id, installation_id)
);
CREATE TABLE IF NOT EXISTS installation_repos (
    installation_id INTEGER NOT NULL,
    repo TEXT NOT NULL,              -- owner/name
    UNIQUE(installation_id, repo)
);
"""


def hub_db_path(memory_home: str) -> Path:
    home = Path(memory_home).expanduser()
    home.mkdir(parents=True, exist_ok=True)
    return home / "hub.db"


class HubStore:
    def __init__(self, db_path: Path) -> None:
        self._conn = sqlite3.connect(db_path)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # --- users / login ---

    def upsert_user(self, user: dict) -> None:
        self._conn.execute(
            "INSERT INTO users (github_id, login, name, avatar_url, created_ts)"
            " VALUES (?,?,?,?,?) ON CONFLICT(github_id) DO UPDATE SET"
            " login=excluded.login, name=excluded.name, avatar_url=excluded.avatar_url",
            (user["github_id"], user["login"], user.get("name", ""),
             user.get("avatar_url", ""), time.time()),
        )
        self._conn.commit()

    def link_user(self, github_id: int, installation_ids: list[int]) -> None:
        self._conn.executemany(
            "INSERT OR IGNORE INTO user_installations (user_github_id, installation_id)"
            " VALUES (?,?)",
            [(github_id, iid) for iid in installation_ids],
        )
        self._conn.commit()

    # --- installations (webhook + callback) ---

    def record_installation(self, installation_id: int, account_login: str) -> None:
        self._conn.execute(
            "INSERT INTO installations (installation_id, account_login, created_ts)"
            " VALUES (?,?,?) ON CONFLICT(installation_id) DO UPDATE SET"
            " account_login=excluded.account_login",
            (installation_id, account_login, time.time()),
        )
        self._conn.commit()

    def remove_installation(self, installation_id: int) -> None:
        for table in ("installations", "installation_repos", "user_installations"):
            self._conn.execute(
                f"DELETE FROM {table} WHERE installation_id = ?", (installation_id,)
            )
        self._conn.commit()

    def set_repos(self, installation_id: int, repos: list[str]) -> None:
        self._conn.execute(
            "DELETE FROM installation_repos WHERE installation_id = ?", (installation_id,)
        )
        self.add_repos(installation_id, repos)

    def add_repos(self, installation_id: int, repos: list[str]) -> None:
        self._conn.executemany(
            "INSERT OR IGNORE INTO installation_repos (installation_id, repo) VALUES (?,?)",
            [(installation_id, r) for r in repos],
        )
        self._conn.commit()

    def remove_repos(self, installation_id: int, repos: list[str]) -> None:
        self._conn.executemany(
            "DELETE FROM installation_repos WHERE installation_id = ? AND repo = ?",
            [(installation_id, r) for r in repos],
        )
        self._conn.commit()

    # --- queries ---

    def repos_for_user(self, github_id: int) -> set[str]:
        cur = self._conn.execute(
            "SELECT ir.repo FROM installation_repos ir"
            " JOIN user_installations ui ON ui.installation_id = ir.installation_id"
            " WHERE ui.user_github_id = ?",
            (github_id,),
        )
        return {r[0] for r in cur.fetchall()}

    def user(self, github_id: int) -> dict | None:
        cur = self._conn.execute(
            "SELECT github_id, login, name, avatar_url FROM users WHERE github_id = ?",
            (github_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {"github_id": row[0], "login": row[1], "name": row[2], "avatar_url": row[3]}

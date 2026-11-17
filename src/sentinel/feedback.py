"""Reviewer feedback: Sentinel's inline PR comments and the 👍/👎 they earned.

GitHub sends no webhook for reactions, so the counts are pulled: after each
review, and in the background when someone opens the repo page. One row per
posted comment, in the same database as review history (SQLite or Postgres,
see sentinel.db).
"""

from __future__ import annotations

import time
from pathlib import Path

from sentinel.db import DB

_SCHEMA = """
CREATE TABLE IF NOT EXISTS inline_comments (
    comment_id BIGINT PRIMARY KEY,  -- GitHub review comment id
    repo TEXT NOT NULL,
    pr_number INTEGER NOT NULL,
    finding_key TEXT NOT NULL,
    severity TEXT NOT NULL,
    title TEXT NOT NULL,
    path TEXT NOT NULL,
    line INTEGER,
    url TEXT DEFAULT '',
    up INTEGER DEFAULT 0,
    down INTEGER DEFAULT 0,
    created_ts DOUBLE PRECISION NOT NULL,
    synced_ts DOUBLE PRECISION DEFAULT 0
);
CREATE INDEX IF NOT EXISTS inline_comments_repo ON inline_comments (repo, pr_number);
"""


class FeedbackStore:
    def __init__(self, target: str | Path) -> None:
        self._conn = DB(target)
        self._conn.script(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def record_posted(self, repo: str, pr_number: int, posted: list[dict]) -> None:
        """posted: [{id, html_url, path, line, key, severity, title}]."""
        now = time.time()
        self._conn.executemany(
            "INSERT INTO inline_comments (comment_id, repo, pr_number, finding_key,"
            " severity, title, path, line, url, created_ts) VALUES (?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT (comment_id) DO NOTHING",
            [
                (c["id"], repo, pr_number, c["key"], c["severity"], c["title"],
                 c["path"], c.get("line"), c.get("html_url") or "", now)
                for c in posted
            ],
        )
        self._conn.commit()

    def keys_for_pr(self, repo: str, pr_number: int) -> set[str]:
        cur = self._conn.execute(
            "SELECT finding_key FROM inline_comments WHERE repo = ? AND pr_number = ?",
            (repo, pr_number),
        )
        return {r[0] for r in cur.fetchall()}

    def prs_for_repo(self, repo: str) -> list[int]:
        cur = self._conn.execute(
            "SELECT DISTINCT pr_number FROM inline_comments WHERE repo = ?", (repo,)
        )
        return sorted(r[0] for r in cur.fetchall())

    def update_reactions(self, counts: dict[int, tuple[int, int]]) -> None:
        """counts: {comment_id: (up, down)} as read from GitHub."""
        now = time.time()
        self._conn.executemany(
            "UPDATE inline_comments SET up = ?, down = ?, synced_ts = ? WHERE comment_id = ?",
            [(up, down, now, cid) for cid, (up, down) in counts.items()],
        )
        self._conn.commit()

    def rows(self, repos: set[str] | None = None) -> list[dict]:
        cur = self._conn.execute(
            "SELECT comment_id, repo, pr_number, severity, title, path, line, url,"
            " up, down, created_ts FROM inline_comments ORDER BY created_ts DESC"
        )
        cols = ("comment_id", "repo", "pr_number", "severity", "title", "path", "line",
                "url", "up", "down", "created_ts")
        out = [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]
        return [r for r in out if repos is None or r["repo"] in repos]


def summarize_feedback(rows: list[dict]) -> dict:
    """posted / rated / useful counts; a comment is rated once it has any reaction,
    and useful when its 👍 outnumber its 👎."""
    rated = [r for r in rows if r["up"] or r["down"]]
    useful = sum(1 for r in rated if r["up"] > r["down"])
    return {
        "posted": len(rows),
        "rated": len(rated),
        "useful": useful,
        "not_useful": len(rated) - useful,
        "useful_pct": round(100 * useful / len(rated)) if rated else None,
    }


def reaction_counts(comments: list[dict]) -> dict[int, tuple[int, int]]:
    """{comment_id: (👍, 👎)} from GitHub review-comment objects."""
    return {
        c["id"]: (int((c.get("reactions") or {}).get("+1", 0)),
                  int((c.get("reactions") or {}).get("-1", 0)))
        for c in comments
    }

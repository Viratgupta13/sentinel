"""Per-repo decision memory: SQLite + FTS5 (BM25) with a LIKE fallback.

One DB per repo under `<memory_home>/memory/<owner>__<repo>.db`. Deterministic
keyword/path retrieval keeps Phase 2 dependency-free; a vector index can be added
behind the same interface later without touching callers.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

from sentinel.models import Decision, DecisionKind

log = logging.getLogger("sentinel.memory")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo TEXT NOT NULL,
    pr_number INTEGER NOT NULL,
    pr_title TEXT DEFAULT '',
    pr_url TEXT DEFAULT '',
    merged_at TEXT DEFAULT '',
    kind TEXT DEFAULT 'other',
    decision TEXT NOT NULL,
    rationale TEXT DEFAULT '',
    files TEXT DEFAULT '[]',
    confidence REAL DEFAULT 0.5
);
CREATE TABLE IF NOT EXISTS harvested_prs (
    pr_number INTEGER PRIMARY KEY,
    decisions_count INTEGER DEFAULT 0
);
"""

_FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS decisions_fts USING fts5(
    decision, rationale, files_text
);
"""


def db_path_for(memory_home: str, repo: str) -> Path:
    safe = repo.replace("/", "__")
    return Path(memory_home).expanduser() / "memory" / f"{safe}.db"


class MemoryStore:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(self.path))
        self._db.executescript(_SCHEMA)
        try:
            self._db.executescript(_FTS_SCHEMA)
            self._fts = True
        except sqlite3.OperationalError:  # SQLite built without FTS5
            self._fts = False
            log.warning("SQLite lacks FTS5; falling back to LIKE search.")
        self._db.commit()

    def close(self) -> None:
        self._db.close()

    # --- writes ---

    def add_decisions(self, decisions: list[Decision]) -> int:
        cur = self._db.cursor()
        for d in decisions:
            cur.execute(
                "INSERT INTO decisions (repo, pr_number, pr_title, pr_url, merged_at,"
                " kind, decision, rationale, files, confidence)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    d.repo,
                    d.pr_number,
                    d.pr_title,
                    d.pr_url,
                    d.merged_at,
                    d.kind.value,
                    d.decision,
                    d.rationale,
                    json.dumps(d.files),
                    d.confidence,
                ),
            )
            if self._fts:
                cur.execute(
                    "INSERT INTO decisions_fts (rowid, decision, rationale, files_text)"
                    " VALUES (?, ?, ?, ?)",
                    (cur.lastrowid, d.decision, d.rationale, " ".join(d.files)),
                )
        self._db.commit()
        return len(decisions)

    def mark_harvested(self, pr_number: int, decisions_count: int) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO harvested_prs (pr_number, decisions_count) VALUES (?, ?)",
            (pr_number, decisions_count),
        )
        self._db.commit()

    def is_harvested(self, pr_number: int) -> bool:
        row = self._db.execute(
            "SELECT 1 FROM harvested_prs WHERE pr_number = ?", (pr_number,)
        ).fetchone()
        return row is not None

    # --- reads ---

    def stats(self) -> dict:
        decisions = self._db.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]
        prs = self._db.execute("SELECT COUNT(*) FROM harvested_prs").fetchone()[0]
        by_kind = dict(
            self._db.execute("SELECT kind, COUNT(*) FROM decisions GROUP BY kind").fetchall()
        )
        return {"decisions": decisions, "harvested_prs": prs, "by_kind": by_kind}

    def search(self, query_tokens: list[str], limit: int = 50) -> list[Decision]:
        """Ranked keyword search. Tokens must be \\w-only (callers guarantee this)."""
        tokens = [t for t in query_tokens if t.strip()]
        if not tokens:
            return []
        if self._fts:
            match = " OR ".join(f'"{t}"' for t in tokens)
            rows = self._db.execute(
                "SELECT d.* FROM decisions_fts f JOIN decisions d ON d.id = f.rowid"
                " WHERE decisions_fts MATCH ? ORDER BY rank LIMIT ?",
                (match, limit),
            ).fetchall()
        else:
            clauses = " OR ".join(
                "(decision LIKE ? OR rationale LIKE ? OR files LIKE ?)" for _ in tokens
            )
            params: list[str] = []
            for t in tokens:
                params += [f"%{t}%"] * 3
            rows = self._db.execute(
                f"SELECT * FROM decisions WHERE {clauses} LIMIT ?",  # noqa: S608
                (*params, limit),
            ).fetchall()
        return [self._row_to_decision(row) for row in rows]

    @staticmethod
    def _row_to_decision(row: tuple) -> Decision:
        return Decision(
            id=row[0],
            repo=row[1],
            pr_number=row[2],
            pr_title=row[3],
            pr_url=row[4],
            merged_at=row[5],
            kind=DecisionKind(row[6]),
            decision=row[7],
            rationale=row[8],
            files=json.loads(row[9] or "[]"),
            confidence=row[10],
        )


def all_repo_stats(memory_home: str) -> list[dict]:
    """Stats for every repo memory DB under <memory_home>/memory (dashboard use)."""
    root = Path(memory_home).expanduser() / "memory"
    out: list[dict] = []
    for db in sorted(root.glob("*.db")):
        store = MemoryStore(db)
        try:
            stats = store.stats()
        finally:
            store.close()
        stats["repo"] = db.stem.replace("__", "/")
        out.append(stats)
    return out

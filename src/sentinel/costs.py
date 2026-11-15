"""Phase 3: persistent cost history - every run's ledger, queryable + dashboard.

One SQLite DB at <memory_home>/costs.db. `sentinel review` and
`sentinel memory build` append a row per run; `sentinel costs` aggregates and
can render a self-contained HTML dashboard (no external assets).
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from sentinel.models import ReviewReport

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    ts REAL NOT NULL,
    command TEXT NOT NULL,          -- review | memory-build
    repo TEXT NOT NULL,             -- owner/name or local/diff
    pr_number INTEGER,
    total_hunks INTEGER DEFAULT 0,
    skipped_hunks INTEGER DEFAULT 0,
    deep_reviewed_hunks INTEGER DEFAULT 0,
    cost_usd REAL NOT NULL,
    naive_cost_usd REAL DEFAULT 0,
    models_json TEXT NOT NULL,      -- [{model, calls, in, out, cache_read, usd}]
    max_risk INTEGER DEFAULT 0,
    findings_json TEXT DEFAULT '[]' -- [{severity, title, file}]
);
"""

# Columns added after the first release; applied idempotently on open so
# existing DBs upgrade in place.
_MIGRATIONS = (
    "ALTER TABLE runs ADD COLUMN max_risk INTEGER DEFAULT 0",
    "ALTER TABLE runs ADD COLUMN findings_json TEXT DEFAULT '[]'",
)


@dataclass
class RunRow:
    ts: float
    command: str
    repo: str
    pr_number: int | None
    total_hunks: int
    skipped_hunks: int
    deep_reviewed_hunks: int
    cost_usd: float
    naive_cost_usd: float
    models: list[dict]
    max_risk: int = 0
    findings: list[dict] | None = None


def costs_db_path(memory_home: str) -> Path:
    home = Path(memory_home).expanduser()
    home.mkdir(parents=True, exist_ok=True)
    return home / "costs.db"


class CostHistory:
    def __init__(self, db_path: Path) -> None:
        self._conn = sqlite3.connect(db_path)
        self._conn.executescript(_SCHEMA)
        for migration in _MIGRATIONS:
            try:
                self._conn.execute(migration)
            except sqlite3.OperationalError:
                pass  # column already exists
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def record_report(self, report: ReviewReport) -> None:
        risks = [v.risk for v in report.verdicts] + [r.risk_score for r in report.reviews]
        findings = [
            {"severity": f.severity, "title": f.title, "file": r.file_path}
            for r in report.reviews
            for f in r.findings
        ]
        findings.sort(key=lambda f: {"high": 0, "medium": 1, "low": 2}[f["severity"]])
        self._insert(
            max_risk=max(risks, default=0),
            findings=findings[:20],
            command="review",
            repo=f"{report.pr.owner}/{report.pr.repo}",
            pr_number=report.pr.number or None,
            total_hunks=report.total_hunks,
            skipped_hunks=report.skipped_hunks,
            deep=report.deep_reviewed_hunks,
            cost=report.total_cost_usd,
            naive=report.naive_cost_estimate_usd,
            models=[
                {
                    "model": c.model,
                    "calls": c.calls,
                    "in": c.input_tokens,
                    "out": c.output_tokens,
                    "cache_read": c.cache_read_tokens,
                    "usd": c.cost_usd,
                }
                for c in report.cost_lines
            ],
        )

    def record_harvest(self, repo: str, cost_usd: float, models: list[dict]) -> None:
        self._insert(
            command="memory-build", repo=repo, pr_number=None, total_hunks=0,
            skipped_hunks=0, deep=0, cost=cost_usd, naive=0.0, models=models,
        )

    def _insert(
        self, *, command, repo, pr_number, total_hunks, skipped_hunks, deep, cost, naive,
        models, max_risk=0, findings=None,
    ) -> None:
        self._conn.execute(
            "INSERT INTO runs (ts, command, repo, pr_number, total_hunks, skipped_hunks,"
            " deep_reviewed_hunks, cost_usd, naive_cost_usd, models_json, max_risk,"
            " findings_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                time.time(), command, repo, pr_number, total_hunks, skipped_hunks,
                deep, cost, naive, json.dumps(models), max_risk,
                json.dumps(findings or []),
            ),
        )
        self._conn.commit()

    def rows(self, limit: int = 200) -> list[RunRow]:
        cur = self._conn.execute(
            "SELECT ts, command, repo, pr_number, total_hunks, skipped_hunks,"
            " deep_reviewed_hunks, cost_usd, naive_cost_usd, models_json, max_risk,"
            " findings_json FROM runs ORDER BY ts DESC LIMIT ?",
            (limit,),
        )
        return [
            RunRow(
                ts=r[0], command=r[1], repo=r[2], pr_number=r[3], total_hunks=r[4],
                skipped_hunks=r[5], deep_reviewed_hunks=r[6], cost_usd=r[7],
                naive_cost_usd=r[8], models=json.loads(r[9]), max_risk=r[10] or 0,
                findings=json.loads(r[11] or "[]"),
            )
            for r in cur.fetchall()
        ]

    def summary(self) -> dict:
        return summarize(self.rows(limit=10_000))


def summarize(rows: list[RunRow]) -> dict:
    """Aggregate any row subset - the hub uses this for per-user views."""
    by_model: dict[str, dict] = {}
    for row in rows:
        for m in row.models:
            agg = by_model.setdefault(
                m["model"], {"calls": 0, "in": 0, "out": 0, "usd": 0.0}
            )
            agg["calls"] += m["calls"]
            agg["in"] += m["in"]
            agg["out"] += m["out"]
            agg["usd"] += m["usd"]
    return {
        "runs": len(rows),
        "total_usd": sum(r.cost_usd for r in rows),
        "naive_usd": sum(r.naive_cost_usd for r in rows),
        "by_model": by_model,
    }

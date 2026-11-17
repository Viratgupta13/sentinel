"""Run Sentinel over a labeled dataset under each ablation config.

Configs:
    static  - parser + static signals only (zero LLM calls)
    triage  - + cheap-model triage scores (no deep review)
    full    - + deep review of escalated hunks (hunk only, no verification: the
              original pipeline, kept as the baseline)
    verified - full + surrounding-code context + skeptic verification pass
    memory  - verified + decision memory (pass an explicitly built, time-cutoff DB)

One JSONL result row per (PR, config). The runner is resumable: rows already
present in the output file are skipped, so rate-limited free tiers can finish
a dataset across several invocations.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel

from sentinel.config import Settings
from sentinel.evals.collect import EvalPR
from sentinel.memory.store import MemoryStore
from sentinel.models import ReviewReport
from sentinel.pipeline import load_pr, review_pr

log = logging.getLogger("sentinel.evals")

CONFIGS = ("static", "triage", "full", "verified", "memory")


class EvalResult(BaseModel):
    """Outcome of one config on one PR (JSONL row)."""

    repo: str
    number: int
    label: str
    config: str
    max_risk: int  # max triage/static hunk risk (0-10)
    max_review_risk: int  # max deep-review risk_score, 0 if no deep review
    # max triage risk over hunks that were NOT deep-reviewed (the review's own
    # risk replaces triage for hunks it saw); -1 in rows recorded before this field
    max_unreviewed_risk: int = -1
    n_findings: int
    n_high: int
    llm_triaged: int  # hunks actually scored by the LLM (vs static fallback)
    total_hunks: int
    cost_usd: float
    tokens: int  # total in+out (the cost story when free models price at $0)
    naive_cost_usd: float


def run_config(
    pr_row: EvalPR,
    config: str,
    settings: Settings,
    memory_db: Path | None = None,
) -> EvalResult:
    if config in ("static", "triage", "full"):
        settings = settings.model_copy(
            update={"review_context_lines": 0, "verify_findings": False}
        )
    else:  # verified / memory measure the full pipeline, skeptic included
        settings = settings.model_copy(update={"verify_findings": True})
    pr, files = load_pr(pr_row.url, settings)
    store = None
    try:
        if config == "memory":
            if memory_db is None or not memory_db.exists():
                raise FileNotFoundError(
                    "memory config needs --memory-db (build one with a time cutoff: "
                    "`sentinel memory build <repo> --before <earliest merged_at>`)"
                )
            store = MemoryStore(memory_db)
        report = review_pr(
            pr,
            files,
            settings,
            static_only=(config == "static"),
            skip_deep=(config == "triage"),
            memory_store=store,
        )
    finally:
        if store is not None:
            store.close()
    failed = [r.hunk_id for r in report.reviews if r.failed]
    if failed:  # a rate-limited call would skew the ablation: retry on resume
        raise RuntimeError(f"model call failed for {', '.join(failed)}")
    return _to_result(pr_row, config, report)


def _to_result(pr_row: EvalPR, config: str, report: ReviewReport) -> EvalResult:
    hunk_risks = [v.risk for v in report.verdicts if v.source != "skip"]
    reviewed = {r.hunk_id for r in report.reviews}
    unreviewed_risks = [
        v.risk for v in report.verdicts if v.source != "skip" and v.hunk_id not in reviewed
    ]
    review_risks = [r.risk_score for r in report.reviews]
    findings = [f for r in report.reviews for f in r.findings]
    return EvalResult(
        repo=pr_row.repo,
        number=pr_row.number,
        label=pr_row.label,
        config=config,
        max_risk=max(hunk_risks, default=0),
        max_review_risk=max(review_risks, default=0),
        max_unreviewed_risk=max(unreviewed_risks, default=0),
        n_findings=len(findings),
        n_high=sum(1 for f in findings if f.severity == "high"),
        llm_triaged=sum(1 for v in report.verdicts if v.source == "llm"),
        total_hunks=report.total_hunks,
        cost_usd=report.total_cost_usd,
        tokens=sum(c.input_tokens + c.output_tokens for c in report.cost_lines),
        naive_cost_usd=report.naive_cost_estimate_usd,
    )


def run_backtest(
    rows: list[EvalPR],
    settings: Settings,
    out_path: Path,
    configs: tuple[str, ...] = CONFIGS,
    limit: int | None = None,
    memory_db: Path | None = None,
    sleep_s: float = 0.0,
    on_progress: Callable[[str], None] | None = None,
) -> dict:
    """Append-only, resumable run; returns {attempted, done, failed, skipped}."""
    say = on_progress or (lambda _msg: None)
    done_keys: set[tuple[int, str]] = set()
    if out_path.exists():
        with open(out_path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    row = json.loads(line)
                    done_keys.add((row["number"], row["config"]))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    stats = {"attempted": 0, "done": 0, "failed": 0, "skipped": len(done_keys)}
    with open(out_path, "a", encoding="utf-8") as out:
        for pr_row in rows[: limit or len(rows)]:
            for config in configs:
                if (pr_row.number, config) in done_keys:
                    continue
                stats["attempted"] += 1
                try:
                    result = run_config(pr_row, config, settings, memory_db)
                except Exception as e:  # noqa: BLE001 - one bad PR must not kill the run
                    log.warning("#%s [%s] failed: %s", pr_row.number, config, e)
                    stats["failed"] += 1
                    continue
                if config != "static" and result.tokens == 0:
                    # Every LLM call fell back (rate limit / outage): recording this
                    # as an LLM result would poison the ablation - retry on resume.
                    log.warning(
                        "#%s [%s] no LLM tokens (fallback); will retry", pr_row.number, config
                    )
                    stats["failed"] += 1
                    continue
                out.write(result.model_dump_json() + "\n")
                out.flush()
                stats["done"] += 1
                say(
                    f"#{pr_row.number} [{config}] {pr_row.label}: "
                    f"risk {result.max_risk}, {result.n_high} high, "
                    f"${result.cost_usd:.4f}"
                )
                if sleep_s and config not in ("static",):
                    time.sleep(sleep_s)
    return stats


def load_results(path: Path) -> list[EvalResult]:
    with open(path, encoding="utf-8") as f:
        return [EvalResult.model_validate(json.loads(line)) for line in f if line.strip()]

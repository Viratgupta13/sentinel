"""Grade backtest results into the ablation table (the resume numbers).

A PR counts as *flagged* under a config when its max hunk/review risk reaches
`hi_threshold`, or any high-severity finding fired. Metrics per config:

    recall        - flagged regressive PRs / all regressive PRs
    clean flag %  - flagged clean PRs / all clean PRs (noise; lower is better)
    avg cost/PR   - usage-ledger USD (free models price at $0; tokens shown too)
    vs naive      - avg naive Opus-on-everything estimate for the same PRs
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from sentinel.evals.backtest import EvalResult


@dataclass
class ConfigMetrics:
    config: str
    n_regressive: int
    n_clean: int
    recall: float
    clean_flag_rate: float
    avg_cost_usd: float
    avg_tokens: int
    avg_naive_cost_usd: float


def flagged(r: EvalResult, hi_threshold: int) -> bool:
    return max(r.max_risk, r.max_review_risk) >= hi_threshold or r.n_high > 0


def compute_metrics(results: list[EvalResult], hi_threshold: int = 7) -> list[ConfigMetrics]:
    by_config: dict[str, list[EvalResult]] = defaultdict(list)
    for r in results:
        by_config[r.config].append(r)

    out: list[ConfigMetrics] = []
    for config in ("static", "triage", "full", "memory"):
        rows = by_config.get(config)
        if not rows:
            continue
        reg = [r for r in rows if r.label == "regressive"]
        cln = [r for r in rows if r.label == "clean"]
        out.append(
            ConfigMetrics(
                config=config,
                n_regressive=len(reg),
                n_clean=len(cln),
                recall=(
                    sum(flagged(r, hi_threshold) for r in reg) / len(reg) if reg else 0.0
                ),
                clean_flag_rate=(
                    sum(flagged(r, hi_threshold) for r in cln) / len(cln) if cln else 0.0
                ),
                avg_cost_usd=sum(r.cost_usd for r in rows) / len(rows),
                avg_tokens=int(sum(r.tokens for r in rows) / len(rows)),
                avg_naive_cost_usd=sum(r.naive_cost_usd for r in rows) / len(rows),
            )
        )
    return out


def to_markdown(metrics: list[ConfigMetrics], repo: str, hi_threshold: int) -> str:
    lines = [
        f"# Sentinel ablation - {repo}",
        "",
        f"Flag rule: max risk >= {hi_threshold} or any high-severity finding.",
        "Regressive = merged PR later reverted (conservative labels; recall is a lower bound).",
        "",
        "| config | regressive flagged (recall) | clean flagged (noise) "
        "| avg cost/PR | avg tokens/PR |",
        "|---|---|---|---|---|",
    ]
    for m in metrics:
        lines.append(
            f"| {m.config} | {m.recall:.0%} ({m.n_regressive} PRs) "
            f"| {m.clean_flag_rate:.0%} ({m.n_clean} PRs) "
            f"| ${m.avg_cost_usd:.4f} | {m.avg_tokens:,} |"
        )
    naive = next((m.avg_naive_cost_usd for m in metrics if m.avg_naive_cost_usd), 0.0)
    if naive:
        lines += ["", f"Naive strong-model-on-everything estimate: ${naive:.4f}/PR."]
    return "\n".join(lines) + "\n"

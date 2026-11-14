"""Render a ReviewReport as terminal output (rich) and markdown."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from sentinel.models import ReviewReport

_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
_SEVERITY_ICON = {"high": "🔴", "medium": "🟡", "low": "🔵"}


def to_markdown(report: ReviewReport) -> str:
    pr = report.pr
    lines: list[str] = [
        f"# Sentinel review: {pr.title or pr.url}",
        "",
        f"PR: {pr.url}  ",
        f"Hunks: {report.total_hunks} total · {report.skipped_hunks} skipped (zero-cost) · "
        f"{report.triaged_hunks} triaged · {report.deep_reviewed_hunks} deep-reviewed",
        "",
    ]

    all_findings = [
        (review, finding)
        for review in report.reviews
        for finding in review.findings
    ]
    all_findings.sort(key=lambda rf: (_SEVERITY_ORDER[rf[1].severity], -rf[1].confidence))

    if all_findings:
        lines.append("## Findings")
        for review, finding in all_findings:
            icon = _SEVERITY_ICON[finding.severity]
            lines += [
                "",
                f"### {icon} [{finding.severity.upper()}] {finding.title}",
                f"`{review.file_path}` · hunk `{review.hunk_id}` · "
                f"confidence {finding.confidence:.0%}",
                "",
                finding.detail,
            ]
            if finding.suggestion:
                lines += ["", "**Suggestion:**", "", f"> {finding.suggestion}"]
    elif report.reviews:
        lines.append("## Findings\n\nNo blocking findings from deep review. ✅")

    if report.reviews:
        lines += ["", "## Deep-reviewed hunks", ""]
        lines.append("| Hunk | Risk | Summary |")
        lines.append("|---|---|---|")
        for review in report.reviews:
            summary = review.summary.replace("|", "\\|").replace("\n", " ")
            lines.append(f"| `{review.hunk_id}` | {review.risk_score}/10 | {summary} |")

    lines += ["", "## Cost", ""]
    lines.append("| Model | Calls | Input | Output | Cache read | Cost (USD) |")
    lines.append("|---|---|---|---|---|---|")
    for cost_line in report.cost_lines:
        lines.append(
            f"| {cost_line.model} | {cost_line.calls} | {cost_line.input_tokens:,} "
            f"| {cost_line.output_tokens:,} | {cost_line.cache_read_tokens:,} "
            f"| ${cost_line.cost_usd:.4f} |"
        )
    lines.append(f"| **Total** |  |  |  |  | **${report.total_cost_usd:.4f}** |")
    if report.naive_cost_estimate_usd > 0:
        saved = report.naive_cost_estimate_usd - report.total_cost_usd
        lines += [
            "",
            f"Naive baseline (review model on every hunk, est.): "
            f"${report.naive_cost_estimate_usd:.4f} → tiered routing saved "
            f"~${max(saved, 0):.4f} ({max(saved, 0) / report.naive_cost_estimate_usd:.0%}).",
        ]
    lines.append("")
    return "\n".join(lines)


def print_console(report: ReviewReport, console: Console | None = None) -> None:
    console = console or Console()
    pr = report.pr

    console.print(f"\n[bold]Sentinel[/bold] · {pr.title or pr.url}")
    console.print(
        f"hunks: {report.total_hunks} total · [dim]{report.skipped_hunks} skipped[/dim] · "
        f"{report.triaged_hunks} triaged · "
        f"[bold]{report.deep_reviewed_hunks} deep-reviewed[/bold]\n"
    )

    risky = [v for v in report.verdicts if v.needs_deep_review]
    if risky:
        table = Table(title="Escalated hunks", show_lines=False)
        table.add_column("hunk")
        table.add_column("risk", justify="right")
        table.add_column("category")
        table.add_column("reason", overflow="fold", max_width=60)
        for verdict in sorted(risky, key=lambda v: -v.risk):
            table.add_row(
                verdict.hunk_id, f"{verdict.risk}/10", verdict.category, verdict.reason
            )
        console.print(table)

    for review in report.reviews:
        for finding in sorted(
            review.findings, key=lambda f: (_SEVERITY_ORDER[f.severity], -f.confidence)
        ):
            icon = _SEVERITY_ICON[finding.severity]
            console.print(
                f"{icon} [bold]{finding.severity.upper()}[/bold] {finding.title} "
                f"[dim]({review.file_path}, {finding.confidence:.0%})[/dim]"
            )
            console.print(f"   {finding.detail}")
            if finding.suggestion:
                console.print(f"   [green]fix:[/green] {finding.suggestion}")

    if report.cost_lines:
        cost = Table(title="Cost")
        cost.add_column("model")
        cost.add_column("calls", justify="right")
        cost.add_column("in", justify="right")
        cost.add_column("out", justify="right")
        cost.add_column("cache read", justify="right")
        cost.add_column("USD", justify="right")
        for line in report.cost_lines:
            cost.add_row(
                line.model,
                str(line.calls),
                f"{line.input_tokens:,}",
                f"{line.output_tokens:,}",
                f"{line.cache_read_tokens:,}",
                f"${line.cost_usd:.4f}",
            )
        console.print(cost)
        console.print(
            f"total: [bold]${report.total_cost_usd:.4f}[/bold]  ·  naive Opus-on-everything "
            f"est.: ${report.naive_cost_estimate_usd:.4f}"
        )

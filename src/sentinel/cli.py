"""Sentinel CLI.

    sentinel review https://github.com/owner/repo/pull/123
    sentinel review --diff path/to/changes.diff --static-only
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import typer
from rich.console import Console

from sentinel import __version__
from sentinel.config import load_settings
from sentinel.github.client import GitHubError
from sentinel.llm import SentinelLLMError
from sentinel.pipeline import load_local_diff, load_pr, open_memory_if_exists, review_pr
from sentinel.report.render import print_console, to_markdown

app = typer.Typer(add_completion=False, no_args_is_help=True)
memory_app = typer.Typer(no_args_is_help=True, help="Build and inspect decision memory.")
app.add_typer(memory_app, name="memory")
eval_app = typer.Typer(no_args_is_help=True, help="Time-travel backtest evals (Phase 4).")
app.add_typer(eval_app, name="eval")
console = Console()


def _llm_key_missing(settings) -> bool:
    if settings.provider == "anthropic":
        return not os.environ.get("ANTHROPIC_API_KEY")
    return not settings.openai_api_key


def _key_hint(settings) -> str:
    if settings.provider == "anthropic":
        return "ANTHROPIC_API_KEY is not set"
    return "SENTINEL_OPENAI_API_KEY is not set"


def _record_run(settings, report) -> None:
    """Append this run to the cost history; never let bookkeeping break a review."""
    from sentinel.costs import CostHistory
    from sentinel.db import location as db_location

    try:
        history = CostHistory(db_location(settings, "costs.db"))
        try:
            history.record_report(report)
        finally:
            history.close()
    except OSError as e:  # pragma: no cover - e.g. unwritable home
        logging.getLogger("sentinel.costs").warning("cost history not recorded: %s", e)


def _parse_repo(repo: str) -> str:
    repo = repo.strip().removeprefix("https://github.com/").strip("/")
    if repo.count("/") != 1:
        raise typer.BadParameter(f"Expected owner/name, got {repo!r}")
    return repo


@app.callback()
def _main(verbose: bool = typer.Option(False, "--verbose", "-v")) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING,
        format="%(name)s %(levelname)s %(message)s",
    )


@app.command()
def version() -> None:
    console.print(f"sentinel {__version__}")


@app.command()
def review(
    pr_url: str = typer.Argument(None, help="GitHub PR URL"),
    diff: Path = typer.Option(None, "--diff", help="Review a local diff file instead of a PR"),
    static_only: bool = typer.Option(
        False, "--static-only", help="No LLM calls: parser + static signals only"
    ),
    threshold: int = typer.Option(None, "--threshold", min=0, max=10),
    max_hunks: int = typer.Option(None, "--max-hunks", min=1),
    out: Path = typer.Option(None, "--out", help="Write a markdown report to this path"),
    json_out: Path = typer.Option(None, "--json", help="Write the full report as JSON"),
) -> None:
    """Review a pull request (or local diff) with tiered LLM routing."""
    settings = load_settings()
    if threshold is not None:
        settings.risk_threshold = threshold
    if max_hunks is not None:
        settings.max_review_hunks = max_hunks

    if not static_only and _llm_key_missing(settings):
        console.print(
            f"[yellow]{_key_hint(settings)} - LLM stages will fail. "
            "Use --static-only for a zero-cost dry run, or set the key (see .env.example)."
            "[/yellow]"
        )

    try:
        if diff is not None:
            pr, files = load_local_diff(str(diff))
        elif pr_url:
            with console.status("Fetching PR from GitHub..."):
                pr, files = load_pr(pr_url, settings)
        else:
            raise typer.BadParameter("Pass a PR URL or --diff <file>.")

        memory_store = None if static_only else open_memory_if_exists(pr, settings)
        if memory_store is not None:
            console.print(
                f"[dim]decision memory loaded: {memory_store.stats()['decisions']} "
                f"decisions[/dim]"
            )

        stage = "static signals" if static_only else "triage + deep review"
        with console.status(f"Running {stage}..."):
            report = review_pr(
                pr, files, settings, static_only=static_only, memory_store=memory_store
            )
    except (GitHubError, SentinelLLMError, OSError) as e:
        console.print(f"[red]error:[/red] {e}")
        raise typer.Exit(1) from e

    _record_run(settings, report)
    print_console(report, console)

    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(to_markdown(report), encoding="utf-8")
        console.print(f"\nmarkdown report → {out}")
    if json_out is not None:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(
            json.dumps(report.model_dump(mode="json"), indent=2), encoding="utf-8"
        )
        console.print(f"json report → {json_out}")

    high = sum(
        1 for review in report.reviews for f in review.findings if f.severity == "high"
    )
    if high:
        console.print(f"\n[red]{high} high-severity finding(s).[/red]")
        raise typer.Exit(2)


@memory_app.command("build")
def memory_build(
    repo: str = typer.Argument(..., help="owner/name, e.g. fastapi/fastapi"),
    limit: int = typer.Option(None, "--limit", min=1, help="Merged PRs to harvest"),
    before: str = typer.Option(
        None, "--before", help="Only PRs merged before this ISO time (eval time-travel cutoff)"
    ),
) -> None:
    """Mine merged PR history into this repo's decision memory (idempotent)."""
    from sentinel.llm import LLMClient
    from sentinel.memory.harvest import build_memory
    from sentinel.memory.store import MemoryStore, db_path_for

    settings = load_settings()
    repo = _parse_repo(repo)
    if _llm_key_missing(settings):
        console.print(f"[red]{_key_hint(settings)} - required for extraction.[/red]")
        raise typer.Exit(1)

    store = MemoryStore(db_path_for(settings.memory_home, repo))
    llm = LLMClient(settings=settings)
    try:
        with console.status(f"Harvesting {repo}..."):
            result = build_memory(
                repo, store, settings, llm, limit=limit, merged_before=before,
                on_progress=lambda msg: console.print(f"[dim]{msg}[/dim]"),
            )
    except (GitHubError, SentinelLLMError) as e:
        console.print(f"[red]error:[/red] {e}")
        raise typer.Exit(1) from e
    finally:
        store.close()

    from sentinel.costs import CostHistory
    from sentinel.db import location as db_location
    from sentinel.memory import snapshots

    snapshots.save(settings, repo)
    history = CostHistory(db_location(settings, "costs.db"))
    try:
        history.record_harvest(
            repo,
            result["cost_usd"],
            [
                {
                    "model": c.model, "calls": c.calls, "in": c.input_tokens,
                    "out": c.output_tokens, "cache_read": c.cache_read_tokens,
                    "usd": c.cost_usd,
                }
                for c in llm.ledger.cost_lines()
            ],
        )
    finally:
        history.close()

    console.print(
        f"\n[bold]done[/bold]: {result['prs_processed']} new PRs processed "
        f"({result['prs_seen']} seen), {result['new_decisions']} decisions stored, "
        f"cost ${result['cost_usd']:.4f}"
    )


@memory_app.command("search")
def memory_search(
    repo: str = typer.Argument(...),
    query: str = typer.Argument(..., help="Keywords, e.g. 'retry payment timeout'"),
    k: int = typer.Option(5, "--top", min=1),
) -> None:
    """Keyword-search a repo's decision memory."""
    from sentinel.memory.store import MemoryStore, db_path_for

    settings = load_settings()
    repo = _parse_repo(repo)
    path = db_path_for(settings.memory_home, repo)
    if not path.exists():
        console.print(f"[red]No memory for {repo}. Run `sentinel memory build {repo}`.[/red]")
        raise typer.Exit(1)

    store = MemoryStore(path)
    try:
        tokens = [t for t in query.replace(",", " ").split() if t]
        for d in store.search(tokens, limit=k):
            console.print(
                f"[bold]#{d.pr_number}[/bold] [{d.kind.value}] {d.decision} "
                f"[dim]({d.pr_url}, conf {d.confidence:.0%})[/dim]"
            )
            if d.rationale:
                console.print(f"   [dim]{d.rationale}[/dim]")
    finally:
        store.close()


@memory_app.command("stats")
def memory_stats(repo: str = typer.Argument(...)) -> None:
    """Show what a repo's decision memory contains."""
    from sentinel.memory.store import MemoryStore, db_path_for

    settings = load_settings()
    repo = _parse_repo(repo)
    path = db_path_for(settings.memory_home, repo)
    if not path.exists():
        console.print(f"[red]No memory for {repo}. Run `sentinel memory build {repo}`.[/red]")
        raise typer.Exit(1)

    store = MemoryStore(path)
    try:
        stats = store.stats()
    finally:
        store.close()
    console.print(
        f"{repo}: {stats['decisions']} decisions from {stats['harvested_prs']} PRs "
        f"({path})"
    )
    for kind, count in sorted(stats["by_kind"].items()):
        console.print(f"  {kind}: {count}")


@app.command()
def costs(
    limit: int = typer.Option(20, "--limit", min=1, help="Recent runs to show"),
    html_out: Path = typer.Option(None, "--html", help="Write a self-contained HTML dashboard"),
) -> None:
    """Show the recorded cost history across all runs (and build the dashboard)."""
    from rich.table import Table

    from sentinel.costs import CostHistory
    from sentinel.db import location as db_location

    settings = load_settings()
    db = db_location(settings, "costs.db")
    history = CostHistory(db)
    try:
        rows = history.rows(limit=10_000)
        summary = history.summary()
    finally:
        history.close()

    if not rows:
        console.print("No runs recorded yet - run `sentinel review` or `sentinel memory build`.")
        raise typer.Exit(0)

    saved = summary["naive_usd"] - summary["total_usd"]
    console.print(
        f"[bold]{summary['runs']}[/bold] runs · spend [bold]${summary['total_usd']:.4f}[/bold] "
        f"· naive est. ${summary['naive_usd']:.4f} · saved ${saved:.4f}"
    )

    table = Table(title="Recent runs")
    for col in ("when", "command", "target", "hunks", "deep", "cost", "naive est."):
        table.add_column(col, justify="right" if col in ("hunks", "deep") else "left")
    import time as _time

    for r in rows[:limit]:
        table.add_row(
            _time.strftime("%m-%d %H:%M", _time.localtime(r.ts)),
            r.command,
            f"{r.repo}{f'#{r.pr_number}' if r.pr_number else ''}",
            str(r.total_hunks or ""),
            str(r.deep_reviewed_hunks or ""),
            f"${r.cost_usd:.4f}",
            f"${r.naive_cost_usd:.4f}",
        )
    console.print(table)

    if html_out is not None:
        from sentinel.memory.store import all_repo_stats
        from sentinel.report.dashboard import render_dashboard

        html_out.parent.mkdir(parents=True, exist_ok=True)
        html_out.write_text(
            render_dashboard(rows, summary, memory=all_repo_stats(settings.memory_home)),
            encoding="utf-8",
        )
        console.print(f"dashboard → {html_out}")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8000, "--port", min=1, max=65535),
) -> None:
    """Run the webhook server: PR opened => auto-review => comment (Phase 5).

    Endpoints: POST /webhook/github, GET /dashboard, GET /healthz.
    """
    try:
        import uvicorn

        from sentinel.server import create_app
    except ImportError as e:
        console.print(
            "[red]error:[/red] server dependencies missing - "
            "install with: pip install 'sentinel-review[server]'"
        )
        raise typer.Exit(1) from e

    settings = load_settings()
    if _llm_key_missing(settings):
        console.print(f"[yellow]{_key_hint(settings)} - webhook reviews will fail.[/yellow]")
    if not settings.webhook_secret:
        console.print(
            "[yellow]SENTINEL_WEBHOOK_SECRET unset - unsigned payloads accepted "
            "(fine locally, never in prod).[/yellow]"
        )
    console.print(f"dashboard: http://{host}:{port}/dashboard")
    uvicorn.run(create_app(settings), host=host, port=port, log_level="info")


@eval_app.command("collect")
def eval_collect(
    repo: str = typer.Argument(..., help="owner/name"),
    scan: int = typer.Option(400, "--scan", min=10, help="Merged PRs to scan for reverts"),
    clean: int = typer.Option(30, "--clean", min=1, help="Clean PRs to sample"),
    out: Path = typer.Option(None, "--out", help="Dataset JSONL path"),
) -> None:
    """Build a labeled dataset: reverted PRs = regressive, sampled rest = clean."""
    from sentinel.evals.collect import collect_dataset, save_dataset
    from sentinel.github.client import GitHubClient

    settings = load_settings()
    repo = _parse_repo(repo)
    out = out or Path("evals/datasets") / (repo.replace("/", "__") + ".jsonl")
    gh = GitHubClient(settings.github_token)
    try:
        with console.status(f"Scanning {repo} history..."):
            rows = collect_dataset(
                repo, gh, scan=scan, clean=clean,
                on_progress=lambda msg: console.print(f"[dim]{msg}[/dim]"),
            )
    except GitHubError as e:
        console.print(f"[red]error:[/red] {e}")
        raise typer.Exit(1) from e
    if not any(r.label == "regressive" for r in rows):
        console.print(
            "[yellow]No reverted PRs found in this window - increase --scan or "
            "pick a busier repo.[/yellow]"
        )
    save_dataset(rows, out)
    console.print(f"dataset → {out} ({len(rows)} PRs)")


@eval_app.command("run")
def eval_run(
    dataset: Path = typer.Argument(..., help="Dataset JSONL from `sentinel eval collect`"),
    configs: str = typer.Option(
        "static,triage,full", "--configs",
        help="Comma list of: static,triage,full,verified,memory",
    ),
    limit: int = typer.Option(None, "--limit", min=1, help="Max PRs from the dataset"),
    out: Path = typer.Option(None, "--out", help="Results JSONL (appended; resumable)"),
    memory_db: Path = typer.Option(
        None, "--memory-db", help="Time-cutoff memory DB (required for the memory config)"
    ),
    sleep: float = typer.Option(
        0.0, "--sleep", help="Seconds between LLM configs (free-tier rate limits)"
    ),
) -> None:
    """Run Sentinel over the dataset under each ablation config (resumable)."""
    from sentinel.evals.backtest import CONFIGS, run_backtest
    from sentinel.evals.collect import load_dataset

    settings = load_settings()
    chosen = tuple(c.strip() for c in configs.split(",") if c.strip())
    bad = [c for c in chosen if c not in CONFIGS]
    if bad:
        raise typer.BadParameter(f"Unknown config(s) {bad}; valid: {', '.join(CONFIGS)}")
    needs_llm = any(c != "static" for c in chosen)
    if needs_llm and _llm_key_missing(settings):
        console.print(f"[red]{_key_hint(settings)} - required for configs beyond static.[/red]")
        raise typer.Exit(1)

    rows = load_dataset(dataset)
    out = out or dataset.with_name(dataset.stem + ".results.jsonl")
    stats = run_backtest(
        rows, settings, out, configs=chosen, limit=limit, memory_db=memory_db,
        sleep_s=sleep, on_progress=lambda msg: console.print(f"[dim]{msg}[/dim]"),
    )
    console.print(
        f"\n[bold]done[/bold]: {stats['done']} new results, {stats['failed']} failed, "
        f"{stats['skipped']} already present → {out}"
    )


@eval_app.command("grade")
def eval_grade(
    results: Path = typer.Argument(..., help="Results JSONL from `sentinel eval run`"),
    hi: int = typer.Option(7, "--hi", min=1, max=10, help="Risk threshold that counts as flagged"),
    out: Path = typer.Option(None, "--out", help="Write the ablation table (markdown)"),
) -> None:
    """Compute recall / noise / cost per config and print the ablation table."""
    from sentinel.evals.backtest import load_results
    from sentinel.evals.grade import compute_metrics, to_markdown

    rows = load_results(results)
    if not rows:
        console.print("[red]No results in file.[/red]")
        raise typer.Exit(1)
    metrics = compute_metrics(rows, hi_threshold=hi)
    md = to_markdown(metrics, rows[0].repo, hi)
    console.print(md)
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(md, encoding="utf-8")
        console.print(f"ablation table → {out}")


if __name__ == "__main__":
    app()

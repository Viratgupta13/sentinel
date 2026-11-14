"""End-to-end pipeline: fetch -> parse -> signals -> triage -> deep review -> report."""

from __future__ import annotations

import logging

from sentinel.config import Settings
from sentinel.diff.parser import parse_diff
from sentinel.github.client import GitHubClient, parse_pr_url
from sentinel.llm import LLMClient, UsageLedger
from sentinel.models import FileDiff, PRInfo, ReviewReport, StaticSignals, TriageVerdict
from sentinel.review.reviewer import run_deep_review
from sentinel.signals.static import compute_signals
from sentinel.triage.triage import run_triage

log = logging.getLogger("sentinel.pipeline")

# Rough counterfactual constants for the "no triage, Opus reviews everything" estimate.
_CHARS_PER_TOKEN = 4
_SYSTEM_OVERHEAD_TOKENS = 900
_ASSUMED_REVIEW_OUTPUT_TOKENS = 900


def load_pr(pr_url: str, settings: Settings) -> tuple[PRInfo, list[FileDiff]]:
    owner, repo, number = parse_pr_url(pr_url)
    gh = GitHubClient(settings.github_token)
    pr = gh.fetch_pr(owner, repo, number)
    diff_text = gh.fetch_diff(owner, repo, number)
    if len(diff_text.encode()) > settings.max_diff_bytes:
        log.warning(
            "Diff is %d bytes (> %d); truncating. Large-PR pagination lands in a later phase.",
            len(diff_text.encode()),
            settings.max_diff_bytes,
        )
        diff_text = diff_text[: settings.max_diff_bytes]
    return pr, parse_diff(diff_text)


def load_local_diff(path: str) -> tuple[PRInfo, list[FileDiff]]:
    """Local-diff mode: run the pipeline on a `git diff` file without GitHub."""
    with open(path, encoding="utf-8", errors="replace") as f:
        diff_text = f.read()
    pr = PRInfo(owner="local", repo="diff", number=0, title=f"local diff: {path}", url=path)
    return pr, parse_diff(diff_text)


def naive_cost_estimate(
    settings: Settings,
    files: list[FileDiff],
    signals: dict[str, StaticSignals],
    ledger: UsageLedger,
) -> float:
    """What this PR would cost if EVERY non-skipped hunk went straight to the review model."""
    total_input = 0
    total_output = 0
    for file in files:
        for hunk in file.hunks:
            sig = signals.get(hunk.hunk_id)
            if sig is None or sig.skip_reason:
                continue
            total_input += _SYSTEM_OVERHEAD_TOKENS + len(hunk.content) // _CHARS_PER_TOKEN
            total_output += _ASSUMED_REVIEW_OUTPUT_TOKENS
    return ledger.price_tokens(settings.review_model, total_input, total_output)


def open_memory_if_exists(pr: PRInfo, settings: Settings):
    """Open the repo's decision memory when one has been built; else None."""
    from sentinel.memory.store import MemoryStore, db_path_for

    if pr.owner == "local":
        return None
    path = db_path_for(settings.memory_home, f"{pr.owner}/{pr.repo}")
    if not path.exists():
        return None
    log.info("Using decision memory: %s", path)
    return MemoryStore(path)


def review_pr(
    pr: PRInfo,
    files: list[FileDiff],
    settings: Settings,
    static_only: bool = False,
    memory_store=None,
    skip_deep: bool = False,
) -> ReviewReport:
    all_hunks = [hunk for file in files for hunk in file.hunks]
    hunks_by_id = {hunk.hunk_id: hunk for hunk in all_hunks}
    signal_list = compute_signals(files)
    signals = {sig.hunk_id: sig for sig in signal_list}
    file_paths = [file.path for file in files]

    ledger = UsageLedger()

    if static_only:
        # No model calls: verdicts come purely from static priors (pipeline dry wiring).
        verdicts = [
            TriageVerdict(
                hunk_id=sig.hunk_id,
                risk=round(sig.prior_score),
                category=sig.area.value,
                reason=sig.skip_reason and f"skipped: {sig.skip_reason}" or "static prior",
                source="skip" if sig.skip_reason else "static",
                needs_deep_review=(
                    not sig.skip_reason and sig.prior_score >= settings.risk_threshold
                ),
            )
            for sig in signal_list
        ]
        reviews = []
    else:
        llm = LLMClient(ledger, settings)
        verdicts = run_triage(llm, settings, pr, all_hunks, signals)

        if skip_deep:  # ablation config: triage scores only, no deep-review cost
            return _report(pr, files, settings, all_hunks, signals, verdicts, [], ledger)

        retriever = None
        if memory_store is not None:
            from sentinel.memory.retrieve import retrieve_for_hunk

            def retriever(hunk):  # noqa: F811 - closure over the open store
                return retrieve_for_hunk(memory_store, hunk, settings.retrieve_top_k)

        reviews = run_deep_review(
            llm, settings, pr, hunks_by_id, signals, verdicts, file_paths,
            retriever=retriever,
        )

    return _report(pr, files, settings, all_hunks, signals, verdicts, reviews, ledger)


def _report(pr, files, settings, all_hunks, signals, verdicts, reviews, ledger) -> ReviewReport:
    skipped = sum(1 for v in verdicts if v.source == "skip")
    return ReviewReport(
        pr=pr,
        total_hunks=len(all_hunks),
        skipped_hunks=skipped,
        triaged_hunks=len(all_hunks) - skipped,
        deep_reviewed_hunks=len(reviews),
        verdicts=verdicts,
        reviews=reviews,
        cost_lines=ledger.cost_lines(),
        total_cost_usd=round(ledger.total_cost(), 4),
        naive_cost_estimate_usd=round(
            naive_cost_estimate(settings, files, signals, ledger), 4
        ),
    )

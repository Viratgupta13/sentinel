"""Harvest pipeline: GitHub history -> extraction -> memory store."""

from __future__ import annotations

import logging
from collections.abc import Callable

from sentinel.config import Settings
from sentinel.github.client import GitHubClient
from sentinel.llm import LLMClient
from sentinel.memory.extract import HarvestedPR, extract_decisions
from sentinel.memory.store import MemoryStore

log = logging.getLogger("sentinel.harvest")


def build_memory(
    repo: str,
    store: MemoryStore,
    settings: Settings,
    llm: LLMClient,
    limit: int | None = None,
    merged_before: str | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> dict:
    """Harvest up to `limit` merged PRs into the store. Idempotent per PR.

    `merged_before` (ISO timestamp) keeps only PRs merged strictly before that
    instant - the time-travel cutoff evals use to prevent label leakage.
    """
    owner, name = repo.split("/", 1)
    gh = GitHubClient(settings.github_token)
    notify = on_progress or (lambda _msg: None)

    limit = limit or settings.harvest_limit
    prs = gh.list_merged_prs(owner, name, limit=limit)
    if merged_before:
        prs = [pr for pr in prs if (pr.get("merged_at") or "") < merged_before]
    notify(f"found {len(prs)} merged PRs" + (f" (before {merged_before})" if merged_before else ""))

    new_prs = 0
    new_decisions = 0
    failed = 0
    for raw in prs:
        number = raw["number"]
        if store.is_harvested(number):
            continue
        harvested = HarvestedPR(
            repo=repo,
            number=number,
            title=raw.get("title") or "",
            body=raw.get("body") or "",
            url=raw.get("html_url") or f"https://github.com/{repo}/pull/{number}",
            merged_at=raw.get("merged_at") or "",
            files=gh.fetch_pr_files(owner, name, number),
            # Bot comments (Sentinel's own included) are not team decisions.
            comments=[
                c for c in gh.fetch_review_comments(
                    owner, name, number, cap=settings.harvest_max_comments
                )
                if not c["author"].endswith("[bot]")
            ],
        )
        decisions = extract_decisions(llm, settings, harvested)
        if decisions is None:  # model call failed: leave unmarked, retry next build
            failed += 1
            notify(f"PR #{number}: extraction failed, will retry")
            continue
        store.add_decisions(decisions)
        store.mark_harvested(number, len(decisions))
        new_prs += 1
        new_decisions += len(decisions)
        if decisions:
            notify(f"PR #{number}: {len(decisions)} decision(s)")

    return {
        "prs_seen": len(prs),
        "prs_processed": new_prs,
        "new_decisions": new_decisions,
        "failed": failed,
        "cost_usd": round(llm.ledger.total_cost(), 4),
    }

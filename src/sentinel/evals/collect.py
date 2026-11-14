"""Collect a labeled PR dataset: regressive (later reverted) vs clean.

Labeling v1 is revert-based and deliberately conservative: a merged PR is
*regressive* when a later merged PR is a GitHub revert of it ("Revert ..."
title + "Reverts owner/repo#N" body). Commit-level reverts and bug-fix
follow-ups are not detected yet; that under-labels regressions, which makes
the recall numbers honest lower bounds rather than inflated ones.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel

_REVERT_TITLE_RE = re.compile(r"^Revert\b", re.IGNORECASE)
_REVERT_BODY_RE = re.compile(r"[Rr]everts [\w.-]+/[\w.-]+#(\d+)")
# Fallbacks for hand-written revert titles: 'Revert "..." (#123)', "Revert PR 123".
_TITLE_NUM_RES = (re.compile(r"\(#(\d+)\)"), re.compile(r"\bPR #?(\d+)\b", re.IGNORECASE))


def _revert_target(title: str, body: str) -> int | None:
    m = _REVERT_BODY_RE.search(body)
    if m:
        return int(m.group(1))
    for pattern in _TITLE_NUM_RES:
        m = pattern.search(title)
        if m:
            return int(m.group(1))
    return None


class EvalPR(BaseModel):
    """One labeled PR in a dataset (JSONL row)."""

    repo: str
    number: int
    title: str
    url: str
    merged_at: str
    label: str  # "regressive" | "clean"
    labeled_by: str  # e.g. "reverted by #123" | "sampled clean"


def collect_dataset(
    repo: str,
    gh,  # GitHubClient (duck-typed for tests)
    scan: int = 400,
    clean: int = 30,
    on_progress: Callable[[str], None] | None = None,
) -> list[EvalPR]:
    """Scan merged history; label reverted PRs regressive, sample the rest clean."""
    say = on_progress or (lambda _msg: None)
    owner, name = repo.split("/")

    # Reverts via repo-wide search (the merged-PR window of a busy repo is often
    # too recent to contain any); targets resolved from body, then title.
    reverts = gh.search_merged_prs(owner, name, "Revert in:title", limit=max(scan // 4, 50))
    revert_prs: set[int] = set()
    regressive: dict[int, str] = {}
    for pr in reverts:
        if not _REVERT_TITLE_RE.match(pr.get("title") or ""):
            continue
        revert_prs.add(pr["number"])
        target = _revert_target(pr.get("title") or "", pr.get("body") or "")
        if target and target not in revert_prs:
            regressive[target] = f"reverted by #{pr['number']}"
    say(f"found {len(reverts)} revert PRs → {len(regressive)} labeled targets")

    merged = gh.list_merged_prs(owner, name, limit=scan)
    say(f"scanned {len(merged)} recent merged PRs for the clean sample")
    by_number = {pr["number"]: pr for pr in merged}

    rows: list[EvalPR] = []
    for number, why in sorted(regressive.items(), reverse=True):
        data = by_number.get(number)
        if data is None:
            try:
                data = gh.fetch_pr_json(owner, name, number)
            except Exception:  # noqa: BLE001 - skip unfetchable targets, keep collecting
                say(f"  skipping #{number} (could not fetch)")
                continue
        if not data.get("merged_at"):
            continue  # revert of an unmerged PR: not a regression we can test
        rows.append(_row(repo, data, "regressive", why))

    n_clean = 0
    for pr in merged:  # newest first
        if n_clean >= clean:
            break
        if pr["number"] in regressive or pr["number"] in revert_prs:
            continue
        rows.append(_row(repo, pr, "clean", "sampled clean"))
        n_clean += 1
    say(f"dataset: {len(rows) - n_clean} regressive + {n_clean} clean")
    return rows


def _row(repo: str, data: dict, label: str, why: str) -> EvalPR:
    return EvalPR(
        repo=repo,
        number=data["number"],
        title=(data.get("title") or "")[:200],
        url=data.get("html_url") or f"https://github.com/{repo}/pull/{data['number']}",
        merged_at=data.get("merged_at") or "",
        label=label,
        labeled_by=why,
    )


def save_dataset(rows: list[EvalPR], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(row.model_dump_json() + "\n")


def load_dataset(path: Path) -> list[EvalPR]:
    with open(path, encoding="utf-8") as f:
        return [EvalPR.model_validate(json.loads(line)) for line in f if line.strip()]

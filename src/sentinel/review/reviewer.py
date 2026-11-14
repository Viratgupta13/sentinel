"""Stage 2 - deep review.

Only hunks escalated by triage reach the strong model (Opus). The PR-level
context lives in a cached system block, so the 2nd..Nth hunk of the same PR
reuses the prefix instead of paying for it again.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from pydantic import BaseModel, Field

from sentinel.config import Settings
from sentinel.llm import LLMClient, SentinelLLMError
from sentinel.models import (
    Finding,
    Hunk,
    HunkReview,
    PRInfo,
    RetrievedDecision,
    StaticSignals,
    TriageVerdict,
)

Retriever = Callable[[Hunk], list[RetrievedDecision]]

log = logging.getLogger("sentinel.review")

REVIEW_SYSTEM = """You are a senior code reviewer doing a focused risk review of one \
hunk from a pull request. Your job is to find real problems that could cause bugs, \
incidents, security issues, or data loss - not style nits.

Rules:
- Only report findings you can ground in the visible code. No speculation chains.
- Prefer few high-precision findings over many weak ones. Zero findings is a valid answer.
- severity "high" = likely incident/security/data-loss if merged; "medium" = plausible \
bug or contract break; "low" = worth a comment but not blocking.
- confidence is YOUR estimate (0-1) that a maintainer would act on the finding.
- suggestion, when present, must be concrete (code-level), not "consider improving X".
- summary: one or two sentences on what the hunk does and the overall risk.
- If a "Team memory" block is present, weigh those past decisions heavily: a hunk \
that re-introduces something the team removed on purpose (constraint/incident) is \
high severity, and the finding detail must cite the source PR number. Memories can \
be stale - if the visible code clearly supersedes one, say so instead of citing it."""

_REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "risk_score": {"type": "integer", "minimum": 0, "maximum": 10},
        "summary": {"type": "string"},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "severity": {"type": "string", "enum": ["high", "medium", "low"]},
                    "title": {"type": "string"},
                    "detail": {"type": "string"},
                    "suggestion": {"type": ["string", "null"]},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["severity", "title", "detail", "suggestion", "confidence"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["risk_score", "summary", "findings"],
    "additionalProperties": False,
}


class _ReviewOut(BaseModel):
    risk_score: int = Field(ge=0, le=10)
    summary: str = ""
    findings: list[Finding] = Field(default_factory=list)


def _pr_context_block(pr: PRInfo, file_paths: list[str]) -> list[dict]:
    """System blocks: static role prompt + per-PR context, both cacheable."""
    files_list = "\n".join(f"- {p}" for p in file_paths[:200])
    pr_context = (
        f"Pull request under review: {pr.url}\n"
        f"Title: {pr.title}\nAuthor: {pr.author}\n"
        f"Branches: {pr.base_ref} <- {pr.head_ref}\n"
        f"Description (may be empty):\n{pr.body or '(none)'}\n\n"
        f"Files changed in this PR:\n{files_list}"
    )
    return [
        {"type": "text", "text": REVIEW_SYSTEM},
        # Cache breakpoint after PR context: hunk 2..N of the same PR hit the cache.
        {"type": "text", "text": pr_context, "cache_control": {"type": "ephemeral"}},
    ]


def run_deep_review(
    llm: LLMClient,
    settings: Settings,
    pr: PRInfo,
    hunks_by_id: dict[str, Hunk],
    signals: dict[str, StaticSignals],
    verdicts: list[TriageVerdict],
    file_paths: list[str],
    retriever: Retriever | None = None,
) -> list[HunkReview]:
    selected = sorted(
        (v for v in verdicts if v.needs_deep_review),
        key=lambda v: v.risk,
        reverse=True,
    )[: settings.max_review_hunks]

    system = _pr_context_block(pr, file_paths)
    reviews: list[HunkReview] = []

    for verdict in selected:
        hunk = hunks_by_id[verdict.hunk_id]
        sig = signals[hunk.hunk_id]

        # Memory goes in the USER message so the cached system prefix stays stable.
        memory_block = ""
        if retriever is not None:
            from sentinel.memory.retrieve import render_memory_block

            retrieved = retriever(hunk)
            if retrieved:
                memory_block = "\n\n" + render_memory_block(retrieved)

        user_content = (
            f"Review this hunk.\n"
            f"file: {hunk.file_path}\n"
            f"area: {sig.area.value} | triage risk: {verdict.risk}/10 "
            f"({verdict.reason or 'n/a'}) | +{hunk.added}/-{hunk.removed}"
            f"{memory_block}\n\n"
            f"```diff\n{hunk.content[: settings.max_hunk_chars * 3]}\n```"
        )
        try:
            out = llm.structured(
                model=settings.review_model,
                system=system,
                user_content=user_content,
                schema=_REVIEW_SCHEMA,
                output_model=_ReviewOut,
                effort=settings.review_effort,
                max_tokens=16000,
            )
        except SentinelLLMError as e:
            log.warning("Deep review failed for %s: %s", hunk.hunk_id, e)
            reviews.append(
                HunkReview(
                    hunk_id=hunk.hunk_id,
                    file_path=hunk.file_path,
                    risk_score=verdict.risk,
                    summary=f"Deep review failed: {e}",
                    findings=[],
                )
            )
            continue

        reviews.append(
            HunkReview(
                hunk_id=hunk.hunk_id,
                file_path=hunk.file_path,
                risk_score=out.risk_score,
                summary=out.summary,
                findings=out.findings,
            )
        )
    return reviews

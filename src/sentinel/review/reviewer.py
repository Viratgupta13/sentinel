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
FileText = Callable[[str], str | None]  # path -> the file's text at the PR head

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
- line: the new-file line number (the number before "|" in the diff) the finding \
points at, or null if it is about the hunk as a whole or a removed line.
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
                    "line": {"type": ["integer", "null"]},
                },
                "required": [
                    "severity", "title", "detail", "suggestion", "confidence", "line",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["risk_score", "summary", "findings"],
    "additionalProperties": False,
}


VERIFY_SYSTEM = """You are a skeptical staff engineer checking another reviewer's \
findings on one hunk of a pull request before they are posted. Most automated \
review noise comes from guesses about code the reviewer could not see, generic \
best practices, and misreading the diff.

For each finding, decide:
- "confirmed": the visible code clearly shows the problem, and it would matter if merged.
- "refuted": the visible code (hunk or surrounding code) contradicts it, or it is \
style, a generic best practice, or a hypothetical that needs unseen code to be true.
- "uncertain": plausible, but the visible code does not settle it.
reason: one sentence that points at the code that decides it."""

_VERIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "verdict": {"type": "string",
                                "enum": ["confirmed", "refuted", "uncertain"]},
                    "reason": {"type": "string"},
                },
                "required": ["index", "verdict", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["verdicts"],
    "additionalProperties": False,
}

# Highest hunk risk the surviving findings can support.
_RISK_CAP = {"high": 10, "medium": 6, "low": 3}


class _Verdict(BaseModel):
    index: int
    verdict: str
    reason: str = ""


class _VerifyOut(BaseModel):
    verdicts: list[_Verdict] = Field(default_factory=list)


class _ReviewOut(BaseModel):
    risk_score: int = Field(ge=0, le=10)
    summary: str = ""
    findings: list[Finding] = Field(default_factory=list)


def numbered_hunk(hunk: Hunk) -> str:
    """Hunk text with new-file line numbers ("  42| +code"), so the model can
    point a finding at a line. Removed lines get a blank number column."""
    lines = hunk.content.split("\n")
    out = [lines[0]]  # @@ header
    n = hunk.new_start
    for line in lines[1:]:
        if line.startswith("-"):
            out.append(f"{'':>5}| {line}")
        elif line.startswith("\\"):  # "\ No newline at end of file"
            out.append(f"{'':>5}| {line}")
        else:
            out.append(f"{n:>5}| {line}")
            n += 1
    return "\n".join(out)


def surrounding_code(hunk: Hunk, text: str, lines: int, max_chars: int) -> str:
    """The new file around a hunk, numbered like numbered_hunk(), or ''."""
    file_lines = text.split("\n")
    if lines <= 0 or not file_lines or hunk.new_lines == 0:
        return ""
    start = max(1, hunk.new_start - lines)
    end = min(len(file_lines), hunk.new_start + hunk.new_lines - 1 + lines)
    out = "\n".join(f"{n:>5}| {file_lines[n - 1]}" for n in range(start, end + 1))
    return out[:max_chars]


def verify_findings(
    llm: LLMClient, settings: Settings, system: list[dict], context: str,
    review: HunkReview,
) -> HunkReview:
    """Skeptic pass: drop findings the code refutes and cap the hunk's risk at
    what the surviving findings support. "Uncertain" findings keep their
    severity: on a first eval, downgrading them also buried real bugs. A
    failed call keeps the review as it was."""
    if not review.findings:
        return review
    listed = "\n".join(
        f"[{i}] {f.severity.upper()} - {f.title}: {f.detail}"
        for i, f in enumerate(review.findings)
    )
    try:
        out = llm.structured(
            model=settings.review_model,
            system=[{"type": "text", "text": VERIFY_SYSTEM}] + system[1:],
            user_content=f"{context}\n\nFindings to check:\n{listed}",
            schema=_VERIFY_SCHEMA,
            output_model=_VerifyOut,
            effort=settings.review_effort,
            max_tokens=8000,
        )
    except SentinelLLMError as e:
        log.warning("Verification failed for %s: %s", review.hunk_id, e)
        return review.model_copy(update={"failed": True})

    verdict_by_index = {v.index: v.verdict for v in out.verdicts}
    kept = [
        f for i, f in enumerate(review.findings)
        if verdict_by_index.get(i, "uncertain") != "refuted"
    ]
    cap = max((_RISK_CAP[f.severity] for f in kept), default=_RISK_CAP["low"])
    return review.model_copy(
        update={"findings": kept, "risk_score": min(review.risk_score, cap)}
    )


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
    file_text: FileText | None = None,
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

        diff_block = f"```diff\n{numbered_hunk(hunk)[: settings.max_hunk_chars * 3]}\n```"
        around = ""
        if file_text is not None and settings.review_context_lines > 0:
            text = file_text(hunk.file_path)
            if text:
                around = surrounding_code(
                    hunk, text, settings.review_context_lines, settings.max_hunk_chars * 2
                )
        context_block = (
            f"\n\nSurrounding code in the new version of {hunk.file_path} (for "
            f"context only; review the hunk):\n```\n{around}\n```"
            if around else ""
        )
        user_content = (
            f"Review this hunk.\n"
            f"file: {hunk.file_path}\n"
            f"area: {sig.area.value} | triage risk: {verdict.risk}/10 "
            f"({verdict.reason or 'n/a'}) | +{hunk.added}/-{hunk.removed}"
            f"{memory_block}\n\n{diff_block}{context_block}"
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
                    failed=True,
                )
            )
            continue

        review = HunkReview(
            hunk_id=hunk.hunk_id,
            file_path=hunk.file_path,
            risk_score=out.risk_score,
            summary=out.summary,
            findings=out.findings,
        )
        if settings.verify_findings:
            review = verify_findings(
                llm, settings, system,
                f"file: {hunk.file_path}{memory_block}\n\n{diff_block}{context_block}",
                review,
            )
        reviews.append(review)
    return reviews

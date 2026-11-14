"""Stage 1 - cheap triage.

Every non-skipped hunk goes through the triage model (Haiku) in batches.
The LLM risk is merged with the static prior: critical areas keep a floor,
so a mild LLM verdict can't bury an auth/payments change.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from sentinel.config import Settings
from sentinel.llm import LLMClient, SentinelLLMError
from sentinel.models import Hunk, PRInfo, StaticSignals, TriageVerdict
from sentinel.signals.static import CRITICAL_AREAS

log = logging.getLogger("sentinel.triage")

TRIAGE_SYSTEM = """You are a code-review triage engine. You receive hunks from one \
pull request and score how risky each hunk is to merge, from 0 (cosmetic) to 10 \
(likely to cause an incident).

Score high (7-10): auth/session logic, payment flows, data migrations, concurrency, \
error-handling removal, input validation removal, secrets handling, retry/timeout \
changes, SQL/queries, permission checks.
Score medium (4-6): business logic changes without tests, API contract changes, \
non-trivial refactors, dependency/config changes with runtime impact.
Score low (0-3): comments, formatting, renames, log messages, test-only changes, \
straightforward additions with tests.

Judge only what is visible in the hunk. Be terse: one short reason per hunk."""

# Structured output schema (hand-written: full control over strictness).
_TRIAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "hunk_id": {"type": "string"},
                    "risk": {"type": "integer", "minimum": 0, "maximum": 10},
                    "category": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["hunk_id", "risk", "category", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}


class _TriageItem(BaseModel):
    hunk_id: str
    risk: int = Field(ge=0, le=10)
    category: str = "other"
    reason: str = ""


class _TriageBatch(BaseModel):
    items: list[_TriageItem]


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [truncated, {len(text) - limit} more chars]"


def _render_hunk(hunk: Hunk, sig: StaticSignals, limit: int) -> str:
    return (
        f"### hunk_id: {hunk.hunk_id}\n"
        f"file: {hunk.file_path} | area: {sig.area.value} | +{hunk.added}/-{hunk.removed}\n"
        f"```diff\n{_truncate(hunk.content, limit)}\n```"
    )


def run_triage(
    llm: LLMClient,
    settings: Settings,
    pr: PRInfo,
    hunks: list[Hunk],
    signals: dict[str, StaticSignals],
) -> list[TriageVerdict]:
    """Triage all hunks; returns one verdict per hunk (skipped ones included)."""
    verdicts: list[TriageVerdict] = []
    to_triage: list[Hunk] = []

    for hunk in hunks:
        sig = signals[hunk.hunk_id]
        if sig.skip_reason:
            verdicts.append(
                TriageVerdict(
                    hunk_id=hunk.hunk_id,
                    risk=0,
                    category=sig.area.value,
                    reason=f"skipped: {sig.skip_reason}",
                    source="skip",
                )
            )
        else:
            to_triage.append(hunk)

    for start in range(0, len(to_triage), settings.triage_batch_size):
        batch = to_triage[start : start + settings.triage_batch_size]
        rendered = "\n\n".join(
            _render_hunk(h, signals[h.hunk_id], settings.max_hunk_chars) for h in batch
        )
        user_content = (
            f"PR: {pr.title!r} by {pr.author} ({pr.base_ref} <- {pr.head_ref})\n"
            f"Score every hunk below. Return exactly one item per hunk_id.\n\n{rendered}"
        )
        try:
            result = llm.structured(
                model=settings.triage_model,
                system=TRIAGE_SYSTEM,
                user_content=user_content,
                schema=_TRIAGE_SCHEMA,
                output_model=_TriageBatch,
                effort=settings.triage_effort,
                max_tokens=8000,
            )
            by_id = {item.hunk_id: item for item in result.items}
        except SentinelLLMError as e:
            log.warning("Triage batch failed (%s); falling back to static priors.", e)
            by_id = {}

        for hunk in batch:
            sig = signals[hunk.hunk_id]
            item = by_id.get(hunk.hunk_id)
            if item is None:
                # Triage missed/failed this hunk -> trust the static prior (fail safe).
                verdicts.append(
                    TriageVerdict(
                        hunk_id=hunk.hunk_id,
                        risk=round(sig.prior_score),
                        category=sig.area.value,
                        reason="triage unavailable; static prior used",
                        source="static",
                    )
                )
                continue
            risk = item.risk
            # Critical-area floor: static prior can raise, never lower, the LLM score.
            if sig.area in CRITICAL_AREAS:
                risk = max(risk, round(sig.prior_score))
            verdicts.append(
                TriageVerdict(
                    hunk_id=hunk.hunk_id,
                    risk=min(risk, 10),
                    category=item.category or sig.area.value,
                    reason=item.reason,
                    source="llm",
                )
            )

    for verdict in verdicts:
        verdict.needs_deep_review = (
            verdict.source != "skip" and verdict.risk >= settings.risk_threshold
        )
    return verdicts

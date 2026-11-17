"""Decision extraction: merged PR (+ review comments) -> durable Decision records.

Runs on the mid-tier model (Sonnet). Most PRs yield ZERO decisions - that is the
intended behavior; the memory is only valuable if it stays high-precision.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from sentinel.config import Settings
from sentinel.llm import LLMClient, SentinelLLMError
from sentinel.models import Decision, DecisionKind

log = logging.getLogger("sentinel.extract")

EXTRACT_SYSTEM = """You mine merged pull requests for DURABLE team decisions - knowledge \
a future code reviewer of this repo must not lose.

A decision is worth keeping ONLY if it is one of:
- convention: "we do X this way here, because Y" (and it's repo-specific, not generic)
- constraint: "X is intentionally absent/forbidden" (e.g. a removed feature that must not return)
- incident: "X caused a bug/outage/regression before" (revert PRs are gold)
- tradeoff: "we chose X over Y because Z" (with a real why)

NOT a decision: style nits, one-off typo fixes, generic best practices ("add tests"),
anything a linter enforces, pure descriptions of what the PR does.

Rules:
- Return ZERO decisions for most routine PRs. Precision beats recall.
- `decision` must be one self-contained sentence a reviewer can act on.
- `rationale` carries the why (quote/paraphrase the review thread if that's the source).
- `files` lists the repo paths the decision is anchored to (from the changed-files list).
- `confidence`: your estimate this will still matter in 6 months."""

_EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "decision": {"type": "string"},
                    "rationale": {"type": "string"},
                    "kind": {
                        "type": "string",
                        "enum": ["convention", "constraint", "incident", "tradeoff", "other"],
                    },
                    "files": {"type": "array", "items": {"type": "string"}},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["decision", "rationale", "kind", "files", "confidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["decisions"],
    "additionalProperties": False,
}


class _DecisionOut(BaseModel):
    decision: str
    rationale: str = ""
    kind: str = "other"
    files: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)


class _ExtractOut(BaseModel):
    decisions: list[_DecisionOut]


@dataclass
class HarvestedPR:
    """Raw material for extraction, fetched from GitHub."""

    repo: str
    number: int
    title: str
    body: str
    url: str
    merged_at: str
    files: list[str] = field(default_factory=list)
    comments: list[dict] = field(default_factory=list)  # {author, path, body}


def _render_pr(pr: HarvestedPR) -> str:
    files = "\n".join(f"- {p}" for p in pr.files[:50]) or "(none listed)"
    if pr.comments:
        comments = "\n".join(
            f"- {c['author']} on `{c['path']}`: {c['body']}" for c in pr.comments
        )
    else:
        comments = "(no inline review comments)"
    return (
        f"Merged PR #{pr.number}: {pr.title}\n"
        f"Merged at: {pr.merged_at}\n\n"
        f"Description:\n{(pr.body or '(empty)')[:3000]}\n\n"
        f"Changed files:\n{files}\n\n"
        f"Review comments:\n{comments}"
    )


def extract_decisions(
    llm: LLMClient, settings: Settings, pr: HarvestedPR
) -> list[Decision] | None:
    """Extract durable decisions from one harvested PR (possibly empty).
    None means the model call failed, so the PR should be tried again later."""
    try:
        out = llm.structured(
            model=settings.extraction_model,
            system=EXTRACT_SYSTEM,
            user_content=_render_pr(pr),
            schema=_EXTRACT_SCHEMA,
            output_model=_ExtractOut,
            effort="medium",
            max_tokens=8000,
        )
    except SentinelLLMError as e:
        log.warning("Extraction failed for PR #%d: %s", pr.number, e)
        return None

    decisions: list[Decision] = []
    for d in out.decisions:
        if d.confidence < settings.min_decision_confidence:
            continue
        try:
            kind = DecisionKind(d.kind)
        except ValueError:
            kind = DecisionKind.OTHER
        decisions.append(
            Decision(
                repo=pr.repo,
                pr_number=pr.number,
                pr_title=pr.title,
                pr_url=pr.url,
                merged_at=pr.merged_at,
                kind=kind,
                decision=d.decision.strip(),
                rationale=d.rationale.strip(),
                files=[f for f in d.files if f][:20],
                confidence=d.confidence,
            )
        )
    return decisions

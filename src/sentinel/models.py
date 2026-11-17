"""Domain models shared across the pipeline."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class FileStatus(StrEnum):
    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"
    BINARY = "binary"


class RiskArea(StrEnum):
    """Coarse code-area categories used as a static risk prior."""

    AUTH = "auth"
    PAYMENTS = "payments"
    DATABASE = "database"
    SECURITY = "security"
    INFRA = "infra"
    CONFIG = "config"
    API = "api"
    LOGIC = "logic"
    TESTS = "tests"
    DOCS = "docs"
    OTHER = "other"


class Hunk(BaseModel):
    """One contiguous change block inside a file diff."""

    hunk_id: str  # "<path>#<index>"
    file_path: str
    header: str
    old_start: int
    old_lines: int
    new_start: int
    new_lines: int
    content: str  # raw hunk text incl. header line
    added: int = 0
    removed: int = 0


class FileDiff(BaseModel):
    path: str
    old_path: str | None = None
    status: FileStatus = FileStatus.MODIFIED
    hunks: list[Hunk] = Field(default_factory=list)
    is_test: bool = False
    is_lockfile: bool = False
    is_generated: bool = False
    is_docs: bool = False


class PRInfo(BaseModel):
    owner: str
    repo: str
    number: int
    title: str = ""
    body: str = ""
    author: str = ""
    base_ref: str = ""
    head_ref: str = ""
    head_sha: str = ""  # commit inline review comments are anchored to
    url: str = ""
    additions: int = 0
    deletions: int = 0
    changed_files: int = 0


class StaticSignals(BaseModel):
    """Deterministic, zero-cost risk signals computed per hunk."""

    hunk_id: str
    area: RiskArea
    size_score: float  # 0-1, from lines changed
    prior_score: float  # 0-10 heuristic prior
    touches_tests: bool
    file_status: FileStatus
    skip_reason: str | None = None  # set => never sent to any model


class TriageVerdict(BaseModel):
    """Merged verdict for one hunk (LLM risk + static prior)."""

    hunk_id: str
    risk: int = Field(ge=0, le=10)
    category: str = "other"
    reason: str = ""
    source: Literal["llm", "static", "skip"] = "llm"
    needs_deep_review: bool = False


class Finding(BaseModel):
    severity: Literal["high", "medium", "low"]
    title: str
    detail: str
    suggestion: str | None = None
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    line: int | None = None  # new-file line the finding points at, when known


class HunkReview(BaseModel):
    hunk_id: str
    file_path: str
    risk_score: int = Field(ge=0, le=10)
    summary: str = ""
    findings: list[Finding] = Field(default_factory=list)


class DecisionKind(StrEnum):
    """What kind of durable knowledge a mined decision carries."""

    CONVENTION = "convention"  # "we always do X here because Y"
    CONSTRAINT = "constraint"  # "X must never happen / is intentionally absent"
    INCIDENT = "incident"      # "X caused an outage/bug before"
    TRADEOFF = "tradeoff"      # "we chose X over Y because Z"
    OTHER = "other"


class Decision(BaseModel):
    """One durable team decision mined from PR history."""

    id: int | None = None
    repo: str  # "owner/name"
    pr_number: int
    pr_title: str = ""
    pr_url: str = ""
    merged_at: str = ""
    kind: DecisionKind = DecisionKind.OTHER
    decision: str
    rationale: str = ""
    files: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)


class RetrievedDecision(BaseModel):
    decision: Decision
    score: float
    matched_on: str = ""  # e.g. "same file", "keyword: retry"


class CostLine(BaseModel):
    model: str
    calls: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost_usd: float


class ReviewReport(BaseModel):
    pr: PRInfo
    total_hunks: int
    skipped_hunks: int
    triaged_hunks: int
    deep_reviewed_hunks: int
    verdicts: list[TriageVerdict]
    reviews: list[HunkReview]
    cost_lines: list[CostLine]
    total_cost_usd: float
    naive_cost_estimate_usd: float  # counterfactual: every hunk deep-reviewed by the strong model

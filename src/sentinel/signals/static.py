"""Deterministic, zero-cost risk signals.

These run before any model call: they skip no-signal hunks entirely (lockfiles,
generated code, docs) and give risky areas (auth, payments, ...) a floor score so
a bad triage call can't silently bury them.
"""

from __future__ import annotations

import re

from sentinel.models import FileDiff, FileStatus, Hunk, RiskArea, StaticSignals

# Path fragments -> area. First match wins (ordered by severity).
_AREA_PATTERNS: list[tuple[RiskArea, re.Pattern[str]]] = [
    (RiskArea.AUTH, re.compile(r"auth|login|session|oauth|sso|password|jwt|token", re.I)),
    (
        RiskArea.PAYMENTS,
        re.compile(r"payment|billing|invoice|stripe|razorpay|checkout|wallet|refund", re.I),
    ),
    (
        RiskArea.SECURITY,
        re.compile(r"secur|crypt|secret|sanitiz|permission|rbac|acl|csrf|cors", re.I),
    ),
    (RiskArea.DATABASE, re.compile(r"migration|schema|/models|/db/|\.sql$|database", re.I)),
    (
        RiskArea.INFRA,
        re.compile(
            r"dockerfile|docker-compose|\.github/|terraform|helm|k8s|kubernetes|deploy|\.ci\b",
            re.I,
        ),
    ),
    (RiskArea.CONFIG, re.compile(r"settings|config|\.env|\.ya?ml$|\.toml$|\.ini$", re.I)),
    (RiskArea.API, re.compile(r"/api/|routes|endpoint|handler|controller|views", re.I)),
]

# How much a hunk in this area is worth before any model sees it (0-10 prior).
_AREA_WEIGHT: dict[RiskArea, float] = {
    RiskArea.AUTH: 7.0,
    RiskArea.PAYMENTS: 7.0,
    RiskArea.SECURITY: 7.0,
    RiskArea.DATABASE: 6.0,
    RiskArea.INFRA: 5.0,
    RiskArea.API: 4.5,
    RiskArea.CONFIG: 4.0,
    RiskArea.LOGIC: 3.0,
    RiskArea.TESTS: 1.5,
    RiskArea.DOCS: 0.5,
    RiskArea.OTHER: 2.5,
}

# Areas where the static prior alone should force a deep review even if triage is mild.
CRITICAL_AREAS = {RiskArea.AUTH, RiskArea.PAYMENTS, RiskArea.SECURITY, RiskArea.DATABASE}


def classify_area(file: FileDiff) -> RiskArea:
    if file.is_docs:
        return RiskArea.DOCS
    if file.is_test:
        return RiskArea.TESTS
    for area, pattern in _AREA_PATTERNS:
        if pattern.search(file.path):
            return area
    return RiskArea.LOGIC


def _size_score(hunk: Hunk) -> float:
    """0-1: bigger changes carry more risk, saturating around ~200 changed lines."""
    changed = hunk.added + hunk.removed
    return min(changed / 200.0, 1.0)


def skip_reason(file: FileDiff) -> str | None:
    if file.is_lockfile:
        return "lockfile"
    if file.is_generated:
        return "generated"
    if file.is_docs:
        return "docs-only"
    if file.status == FileStatus.BINARY:
        return "binary"
    if file.status == FileStatus.DELETED:
        return "file deleted"
    return None


def compute_signals(files: list[FileDiff]) -> list[StaticSignals]:
    pr_touches_tests = any(f.is_test for f in files)
    signals: list[StaticSignals] = []
    for file in files:
        reason = skip_reason(file)
        area = classify_area(file)
        for hunk in file.hunks:
            size = _size_score(hunk)
            prior = _AREA_WEIGHT[area] * (0.6 + 0.4 * size)
            # Risky area touched with zero test changes anywhere in the PR -> bump.
            if area in CRITICAL_AREAS and not pr_touches_tests:
                prior += 1.0
            signals.append(
                StaticSignals(
                    hunk_id=hunk.hunk_id,
                    area=area,
                    size_score=round(size, 3),
                    prior_score=round(min(prior, 10.0), 2),
                    touches_tests=pr_touches_tests,
                    file_status=file.status,
                    skip_reason=reason,
                )
            )
    return signals

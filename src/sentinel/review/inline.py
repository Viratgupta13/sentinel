"""Inline PR comments: one review comment per finding, on the line it is about.

GitHub only accepts a review comment on a line that is part of the diff, so
each finding is anchored to the line the model named when that line is on the
new side of its hunk, else to the hunk's first added line. Every comment
carries an invisible marker with a stable key (file + title), which keeps
re-reviews from posting the same finding twice and lets feedback sync map a
comment's 👍/👎 reactions back to the finding.
"""

from __future__ import annotations

import hashlib
import re

from sentinel.models import Hunk, ReviewReport

MAX_INLINE_COMMENTS = 10
MARKER_RE = re.compile(r"<!-- sentinel-finding:([0-9a-f]{12}) -->")

_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
_SEVERITY_ICON = {"high": "🔴", "medium": "🟡", "low": "🔵"}


def new_side_lines(hunk: Hunk) -> tuple[list[int], list[int]]:
    """(added lines, all new-side lines) of a hunk, as new-file line numbers."""
    added: list[int] = []
    right: list[int] = []
    n = hunk.new_start
    for line in hunk.content.split("\n")[1:]:  # skip the @@ header
        if line.startswith("-") or line.startswith("\\"):
            continue
        if line.startswith("+"):
            added.append(n)
        right.append(n)
        n += 1
    return added, right


def anchor_line(hunk: Hunk, line: int | None) -> int | None:
    """The line to attach a comment to, or None when the hunk has no new side."""
    added, right = new_side_lines(hunk)
    if line is not None and line in right:
        return line
    if added:
        return added[0]
    return right[-1] if right else None


def finding_key(path: str, title: str) -> str:
    norm = " ".join(title.lower().split())
    return hashlib.sha1(f"{path}\0{norm}".encode()).hexdigest()[:12]


_FILLER = {
    "a", "an", "the", "of", "in", "on", "for", "to", "via", "by", "with", "and", "or",
    "potential", "possible", "likely", "vulnerability", "issue", "risk", "bug",
}


def _title_words(title: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", title.lower())
    return {w for w in words if w not in _FILLER}


def similar_titles(a: str, b: str) -> bool:
    """Same finding in other words: most of the shorter title's words recur
    ("SQL injection vulnerability" ~ "Potential SQL injection via search query")."""
    wa, wb = _title_words(a), _title_words(b)
    if not wa or not wb:
        return False
    return len(wa & wb) / min(len(wa), len(wb)) >= 0.6


def parse_marker(body: str) -> str | None:
    m = MARKER_RE.search(body or "")
    return m[1] if m else None


def comment_body(finding, key: str) -> str:
    icon = _SEVERITY_ICON[finding.severity]
    parts = [f"{icon} **{finding.severity.upper()} · {finding.title}**", "", finding.detail]
    if finding.suggestion:
        parts += ["", f"**Suggestion:** {finding.suggestion}"]
    parts += [
        "",
        f"<sub>Sentinel · confidence {finding.confidence:.0%} · "
        "react 👍 if this was useful, 👎 if not</sub>",
        f"<!-- sentinel-finding:{key} -->",
    ]
    return "\n".join(parts)


def build_inline_comments(
    report: ReviewReport, hunks_by_id: dict[str, Hunk], cap: int = MAX_INLINE_COMMENTS,
    min_confidence: float = 0.0,
) -> list[dict]:
    """[{key, path, line, body, severity, title}] - most severe first, one per key.
    Low-severity and low-confidence findings stay in the summary comment only."""
    candidates = [
        (review, f) for review in report.reviews for f in review.findings
        if f.severity != "low" and f.confidence >= min_confidence
    ]
    candidates.sort(key=lambda rf: (_SEVERITY_ORDER[rf[1].severity], -rf[1].confidence))
    out: list[dict] = []
    seen: set[str] = set()
    for review, f in candidates:
        hunk = hunks_by_id.get(review.hunk_id)
        line = anchor_line(hunk, f.line) if hunk else None
        key = finding_key(review.file_path, f.title)
        if line is None or key in seen:
            continue
        seen.add(key)
        out.append({
            "key": key, "path": review.file_path, "line": line,
            "body": comment_body(f, key), "severity": f.severity, "title": f.title,
        })
        if len(out) >= cap:
            break
    return out

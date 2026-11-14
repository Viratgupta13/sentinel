"""Per-hunk retrieval: hunk -> keyword/path query -> ranked, cited decisions."""

from __future__ import annotations

import re
from collections import Counter

from sentinel.memory.store import MemoryStore
from sentinel.models import Hunk, RetrievedDecision

_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")

_STOPWORDS = {
    # language keywords / noise common in diffs
    "def", "class", "return", "import", "from", "self", "const", "function", "public",
    "private", "static", "void", "int", "str", "string", "bool", "true", "false", "null",
    "none", "this", "with", "async", "await", "for", "while", "else", "elif", "try",
    "except", "catch", "raise", "throw", "new", "let", "var", "print", "log", "the",
    "and", "not", "type", "value", "name", "data", "args", "kwargs", "list", "dict",
}


def hunk_query_tokens(hunk: Hunk, max_tokens: int = 15) -> list[str]:
    """Identifiers from CHANGED lines only, by frequency, plus file-path stems."""
    changed_lines = [
        line[1:]
        for line in hunk.content.splitlines()
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
    ]
    counts: Counter[str] = Counter()
    for line in changed_lines:
        for token in _IDENT_RE.findall(line):
            lower = token.lower()
            if lower not in _STOPWORDS:
                counts[lower] += 1

    path_parts = re.split(r"[/.]", hunk.file_path)
    path_tokens = [p.lower() for p in path_parts if len(p) > 2 and p.lower() not in _STOPWORDS]

    tokens = [t for t, _n in counts.most_common(max_tokens)]
    for pt in path_tokens:
        if pt not in tokens:
            tokens.append(pt)
    return tokens[: max_tokens + 5]


def _path_overlap(hunk_path: str, decision_files: list[str]) -> float:
    """2.0 same file, 1.0 same directory, 0.5 same basename, else 0."""
    if hunk_path in decision_files:
        return 2.0
    hunk_dir = hunk_path.rsplit("/", 1)[0] if "/" in hunk_path else ""
    hunk_base = hunk_path.rsplit("/", 1)[-1]
    score = 0.0
    for f in decision_files:
        f_dir = f.rsplit("/", 1)[0] if "/" in f else ""
        if hunk_dir and f_dir == hunk_dir:
            score = max(score, 1.0)
        if f.rsplit("/", 1)[-1] == hunk_base:
            score = max(score, 0.5)
    return score


def retrieve_for_hunk(
    store: MemoryStore, hunk: Hunk, top_k: int = 3
) -> list[RetrievedDecision]:
    tokens = hunk_query_tokens(hunk)
    if not tokens:
        return []
    candidates = store.search(tokens, limit=50)

    ranked: list[RetrievedDecision] = []
    for position, decision in enumerate(candidates):
        fts_score = 1.0 / (1.0 + position)  # rank position, deterministic
        path_score = _path_overlap(hunk.file_path, decision.files)
        total = 2.0 * path_score + fts_score + 0.5 * decision.confidence
        matched = "same file/dir" if path_score > 0 else f"keywords: {', '.join(tokens[:3])}"
        ranked.append(
            RetrievedDecision(decision=decision, score=round(total, 3), matched_on=matched)
        )

    ranked.sort(key=lambda r: -r.score)
    return ranked[:top_k]


def render_memory_block(retrieved: list[RetrievedDecision]) -> str:
    """Markdown block injected into the deep-review user prompt."""
    if not retrieved:
        return ""
    lines = [
        "Team memory - past decisions that may apply to this hunk "
        "(cite the PR number if one grounds a finding; flag it if the code "
        "visibly supersedes a memory):"
    ]
    for i, r in enumerate(retrieved, 1):
        d = r.decision
        rationale = f" Rationale: {d.rationale}" if d.rationale else ""
        lines.append(
            f"{i}. [PR #{d.pr_number}, {d.kind.value}, confidence {d.confidence:.0%}] "
            f"{d.decision}{rationale} (files: {', '.join(d.files[:4]) or 'n/a'}; "
            f"matched: {r.matched_on})"
        )
    return "\n".join(lines)

"""Answer a question about a repo from retrieved code + decision memory.

Context budget is deliberately small (~4k tokens) so one question fits a
free-tier rate limit (Groq ~8k TPM). The model must cite numbered sources;
the citations are mapped back to GitHub blob links with line anchors (code)
or PR links (decisions), so every claim is one click from its evidence.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from sentinel.ask.index import Chunk, RepoIndex, query_tokens
from sentinel.llm import LLMClient
from sentinel.memory.store import MemoryStore

log = logging.getLogger("sentinel.ask")

MAX_CONTEXT_CHARS = 14_000
MAX_CHUNK_CHARS = 1_800
MAX_TREE_PATHS = 150

_SYSTEM = """You answer questions about one software repository for a developer.

You get: the repo's file list, numbered SOURCES (code excerpts with path and
line range, and possibly team DECISIONS mined from past pull requests), and a
question.

Rules:
- Ground every claim in the sources or the file list. Cite sources inline as
  [1], [2] right after the claim they support.
- If the sources don't contain the answer, say what you can infer from the
  file list, clearly label it as inference, and say which files would answer
  it. Never invent functions, files, or behavior.
- Explain architecture and design intent, not just what a line does: how the
  pieces connect, why a decision was made (decisions carry rationale).
- Be concise and structured: short paragraphs or bullet points, file paths in
  backticks. No preamble.
- Answer in the same language AND script as the question. Hinglish (Hindi
  words typed in Latin letters, e.g. "kaise chalta hai") gets a Hinglish
  answer in Latin letters - never Devanagari. Keep code identifiers and
  technical terms in English."""

_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "cited": {"type": "array", "items": {"type": "integer"}},
    },
    "required": ["answer", "cited"],
    "additionalProperties": False,
}


class _AskOut(BaseModel):
    answer: str
    cited: list[int] = Field(default_factory=list)


def _blob_url(repo: str, ref: str, c: Chunk) -> str:
    return f"https://github.com/{repo}/blob/{ref or 'HEAD'}/{c.path}#L{c.start_line}-L{c.end_line}"


def build_sources(
    repo: str,
    index: RepoIndex,
    question: str,
    memory: MemoryStore | None = None,
    k: int = 6,
) -> tuple[str, list[dict]]:
    """(prompt context, source records). Source n in the prompt = records[n-1]."""
    ref = index.meta("ref")
    chunks = index.search(question, k=k)
    readme = index.readme()
    # Overview questions rarely keyword-match code: the README anchors them.
    if readme and all(c.id != readme.id for c in chunks):
        chunks = [readme, *chunks[: k - 1]] if len(chunks) < 3 else [*chunks, readme]

    decisions = []
    if memory is not None:
        try:
            decisions = memory.search(query_tokens(question), limit=3)
        except Exception:
            log.exception("decision memory search failed")

    records: list[dict] = []
    parts: list[str] = []
    budget = MAX_CONTEXT_CHARS
    for c in chunks:
        body = c.text[:MAX_CHUNK_CHARS]
        block = f"[{len(records) + 1}] {c.path} (lines {c.start_line}-{c.end_line})\n{body}"
        if len(block) > budget:
            break
        budget -= len(block)
        parts.append(block)
        records.append({
            "kind": "code", "label": f"{c.path}:{c.start_line}-{c.end_line}",
            "url": _blob_url(repo, ref, c),
        })
    for d in decisions:
        block = (
            f"[{len(records) + 1}] DECISION from PR #{d.pr_number} ({d.kind.value}): "
            f"{d.decision}\nRationale: {d.rationale}\nFiles: {', '.join(d.files[:6])}"
        )
        if len(block) > budget:
            break
        budget -= len(block)
        parts.append(block)
        records.append({
            "kind": "decision", "label": f"PR #{d.pr_number}: {d.decision[:80]}",
            "url": d.pr_url or f"https://github.com/{repo}/pull/{d.pr_number}",
        })

    tree = index.tree()
    tree_txt = "\n".join(tree[:MAX_TREE_PATHS])
    if len(tree) > MAX_TREE_PATHS:
        tree_txt += f"\n... and {len(tree) - MAX_TREE_PATHS} more files"
    context = (
        f"REPOSITORY: {repo}\n\nFILES:\n{tree_txt}\n\nSOURCES:\n\n"
        + ("\n\n".join(parts) if parts else "(no matching excerpts)")
    )
    return context, records


def answer_question(
    repo: str,
    index: RepoIndex,
    question: str,
    settings,
    memory: MemoryStore | None = None,
    llm: LLMClient | None = None,
) -> dict:
    context, records = build_sources(repo, index, question, memory)
    llm = llm or LLMClient(settings=settings)
    out = llm.structured(
        model=settings.review_model,
        system=_SYSTEM,
        user_content=f"{context}\n\nQUESTION: {question}",
        schema=_SCHEMA,
        output_model=_AskOut,
        effort="medium",
        max_tokens=3_000,
    )
    cited = [records[i - 1] | {"n": i} for i in out.cited if 1 <= i <= len(records)]
    seen: set[int] = set()
    sources = [s for s in cited if not (s["n"] in seen or seen.add(s["n"]))]
    return {"answer": out.answer.strip(), "sources": sources}

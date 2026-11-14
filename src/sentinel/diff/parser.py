"""Unified diff parser: raw `git diff` text -> FileDiff/Hunk domain objects."""

from __future__ import annotations

import re

from sentinel.models import FileDiff, FileStatus, Hunk

DIFF_HEADER_RE = re.compile(r'^diff --git (?:"?a/(?P<a>.*?)"?) (?:"?b/(?P<b>.*?)"?)$')
HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$")

_LOCKFILES = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "uv.lock",
    "Pipfile.lock",
    "Cargo.lock",
    "go.sum",
    "composer.lock",
    "Gemfile.lock",
}

_DOCS_SUFFIXES = (".md", ".rst", ".txt", ".adoc")
_GENERATED_MARKERS = (".min.js", ".min.css", ".map", ".pb.go", "_pb2.py", ".snap")
_GENERATED_DIRS = ("dist/", "build/", "vendor/", "node_modules/", ".next/", "__generated__/")
_TEST_MARKERS = ("test_", "_test.", ".test.", ".spec.", "spec_")
_TEST_DIRS = ("tests/", "test/", "__tests__/", "spec/")


def _classify_path(path: str) -> dict[str, bool]:
    lower = path.lower()
    name = lower.rsplit("/", 1)[-1]
    return {
        "is_test": any(d in lower for d in _TEST_DIRS) or any(m in name for m in _TEST_MARKERS),
        "is_lockfile": path.rsplit("/", 1)[-1] in _LOCKFILES,
        "is_generated": any(m in lower for m in _GENERATED_MARKERS)
        or any(lower.startswith(d) or f"/{d}" in lower for d in _GENERATED_DIRS),
        "is_docs": lower.endswith(_DOCS_SUFFIXES),
    }


def parse_diff(diff_text: str) -> list[FileDiff]:
    """Parse a unified diff into FileDiff objects with per-hunk content."""
    files: list[FileDiff] = []
    current: FileDiff | None = None
    hunk_lines: list[str] = []
    hunk_meta: tuple[int, int, int, int, str] | None = None

    def flush_hunk() -> None:
        nonlocal hunk_lines, hunk_meta
        if current is None or hunk_meta is None:
            hunk_lines, hunk_meta = [], None
            return
        old_start, old_len, new_start, new_len, header = hunk_meta
        body = hunk_lines[1:]  # first line is the @@ header itself
        added = sum(1 for line in body if line.startswith("+"))
        removed = sum(1 for line in body if line.startswith("-"))
        idx = len(current.hunks)
        current.hunks.append(
            Hunk(
                hunk_id=f"{current.path}#{idx}",
                file_path=current.path,
                header=header.strip(),
                old_start=old_start,
                old_lines=old_len,
                new_start=new_start,
                new_lines=new_len,
                content="\n".join(hunk_lines),
                added=added,
                removed=removed,
            )
        )
        hunk_lines, hunk_meta = [], None

    def flush_file() -> None:
        nonlocal current
        flush_hunk()
        if current is not None:
            files.append(current)
            current = None

    for line in diff_text.splitlines():
        header_match = DIFF_HEADER_RE.match(line)
        if header_match:
            flush_file()
            a_path, b_path = header_match["a"], header_match["b"]
            path = b_path if b_path != "/dev/null" else a_path
            current = FileDiff(path=path, old_path=a_path if a_path != b_path else None)
            for key, value in _classify_path(path).items():
                setattr(current, key, value)
            continue

        if current is None:
            continue  # preamble before first file header

        if line.startswith("new file mode"):
            current.status = FileStatus.ADDED
            continue
        if line.startswith("deleted file mode"):
            current.status = FileStatus.DELETED
            continue
        if line.startswith("rename from"):
            current.status = FileStatus.RENAMED
            continue
        if line.startswith("Binary files") or line.startswith("GIT binary patch"):
            current.status = FileStatus.BINARY
            continue
        if line.startswith(("index ", "--- ", "+++ ", "similarity index", "rename to",
                            "old mode", "new mode")):
            continue

        hunk_match = HUNK_HEADER_RE.match(line)
        if hunk_match:
            flush_hunk()
            hunk_meta = (
                int(hunk_match.group(1)),
                int(hunk_match.group(2) or 1),
                int(hunk_match.group(3)),
                int(hunk_match.group(4) or 1),
                hunk_match.group(5) or "",
            )
            hunk_lines = [line]
            continue

        if hunk_meta is not None:
            hunk_lines.append(line)

    flush_file()
    return files

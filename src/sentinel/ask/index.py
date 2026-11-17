"""Per-repo code index: one tarball -> line-ranged text chunks in SQLite FTS5.

Same retrieval philosophy as the decision memory: deterministic BM25 keyword
search, no embedding service, nothing to pay for. File paths are indexed
alongside content so "where is auth handled?" can hit `src/auth/...` even when
the word "auth" barely appears in the code.

One DB per repo at `<memory_home>/index/<owner>__<repo>.db`.
"""

from __future__ import annotations

import io
import re
import sqlite3
import tarfile
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

SKIP_DIRS = {
    ".git", "node_modules", "vendor", "dist", "build", "out", ".next", ".nuxt",
    "target", "__pycache__", ".venv", "venv", "env", ".tox", "coverage",
    ".idea", ".vscode", "bower_components", ".gradle", "Pods", ".cache",
}
SKIP_FILES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock",
    "Cargo.lock", "composer.lock", "Gemfile.lock", "go.sum", "uv.lock",
}
SKIP_EXT = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".svg", ".pdf", ".zip",
    ".gz", ".tar", ".jar", ".woff", ".woff2", ".ttf", ".eot", ".mp3", ".mp4",
    ".mov", ".bin", ".exe", ".dll", ".so", ".dylib", ".pyc", ".class", ".lock",
    ".min.js", ".map", ".db", ".sqlite", ".pkl", ".pt", ".h5", ".onnx", ".npy",
    ".ipynb",
}
MAX_FILE_BYTES = 150_000
MAX_FILES = 600
MAX_TOTAL_BYTES = 6_000_000
CHUNK_LINES = 50

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    text TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    path_words, text, tokenize='porter unicode61'
);
"""

_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]{1,}")
_STOP = {
    "the", "a", "an", "is", "are", "was", "were", "be", "to", "of", "in", "on",
    "and", "or", "for", "with", "how", "what", "why", "where", "when", "which",
    "does", "do", "did", "this", "that", "it", "its", "can", "i", "me", "my",
    "we", "our", "you", "your", "repo", "repository", "project", "code", "about",
    "explain", "tell", "kya", "hai", "kaise", "kyun", "kahan", "ka", "ki", "ke",
    "mein", "isme", "yeh", "ye", "batao", "bata", "kar", "karta", "hota",
}


def index_db_path(memory_home: str, repo: str) -> Path:
    return Path(memory_home).expanduser() / "index" / f"{repo.replace('/', '__')}.db"


def _path_words(path: str) -> str:
    """'src/authService/login_handler.py' -> 'src auth service login handler py'."""
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", path)
    return " ".join(re.split(r"[^A-Za-z0-9]+", spaced)).lower()


def _skip(rel: str) -> bool:
    p = PurePosixPath(rel)
    if any(part in SKIP_DIRS for part in p.parts[:-1]):
        return True
    name = p.name
    if name in SKIP_FILES:
        return True
    low = name.lower()
    return any(low.endswith(ext) for ext in SKIP_EXT)


def _is_test_path(row: tuple) -> bool:
    parts = PurePosixPath(row[1]).parts
    name = parts[-1].lower()
    return (
        any(p in {"test", "tests", "__tests__", "spec", "specs"} for p in parts[:-1])
        or name.startswith("test_")
        or ".test." in name
        or ".spec." in name
        or name.endswith("_test.py")
        or name.endswith("_test.go")
    )


def query_tokens(question: str, limit: int = 12) -> list[str]:
    seen: list[str] = []
    for raw in _WORD.findall(question):
        for t in [raw.lower(), *_path_words(raw).split()]:
            if len(t) >= 3 and t not in _STOP and t not in seen:
                seen.append(t)
    return seen[:limit]


@dataclass
class Chunk:
    id: int
    path: str
    start_line: int
    end_line: int
    text: str


class RepoIndex:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(self.path), check_same_thread=False)
        self._db.executescript(_SCHEMA)

    def close(self) -> None:
        self._db.close()

    # --- meta ---

    def meta(self, key: str, default: str = "") -> str:
        row = self._db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else default

    def _set_meta(self, **kv: str) -> None:
        self._db.executemany(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", list(kv.items())
        )

    @property
    def built(self) -> bool:
        return bool(self.meta("built_ts"))

    def tree(self) -> list[str]:
        return [p for p in self.meta("tree").split("\n") if p]

    def file_texts(self) -> dict[str, str]:
        """path -> text, reassembled from the indexed chunks (all-blank chunks
        were never stored, so line numbers can drift; fine for import parsing)."""
        out: dict[str, list[str]] = {}
        for path, text in self._db.execute(
            "SELECT path, text FROM chunks ORDER BY path, start_line"
        ):
            out.setdefault(path, []).append(text)
        return {path: "\n".join(parts) for path, parts in out.items()}

    # --- build ---

    def build_from_tarball(self, data: bytes) -> dict:
        """Replace the index with the snapshot's text files. Returns build stats."""
        self._db.execute("DELETE FROM chunks")
        self._db.execute("DELETE FROM chunks_fts")
        paths: list[str] = []
        ref = ""
        files = total = 0
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            for member in tar:
                if not member.isfile():
                    continue
                top, _, rel = member.name.partition("/")
                if not rel:
                    continue
                # GitHub names the root dir "<owner>-<repo>-<sha>".
                ref = ref or top.rsplit("-", 1)[-1]
                if _skip(rel) or member.size > MAX_FILE_BYTES:
                    continue
                if files >= MAX_FILES or total + member.size > MAX_TOTAL_BYTES:
                    break
                fh = tar.extractfile(member)
                if fh is None:
                    continue
                raw = fh.read()
                if b"\x00" in raw[:4096]:
                    continue  # binary
                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError:
                    continue
                files += 1
                total += len(raw)
                paths.append(rel)
                self._add_file(rel, text)
        self._set_meta(
            built_ts=str(time.time()), ref=ref, tree="\n".join(sorted(paths)),
            files=str(files),
        )
        self._db.commit()
        return {"files": files, "bytes": total, "ref": ref}

    def _add_file(self, rel: str, text: str) -> None:
        lines = text.splitlines()
        pw = _path_words(rel)
        for start in range(0, max(len(lines), 1), CHUNK_LINES):
            body = "\n".join(lines[start : start + CHUNK_LINES])
            if not body.strip():
                continue
            cur = self._db.execute(
                "INSERT INTO chunks (path, start_line, end_line, text) VALUES (?,?,?,?)",
                (rel, start + 1, min(start + CHUNK_LINES, len(lines)), body),
            )
            self._db.execute(
                "INSERT INTO chunks_fts (rowid, path_words, text) VALUES (?,?,?)",
                (cur.lastrowid, pw, body),
            )

    # --- query ---

    def search(self, question: str, k: int = 6) -> list[Chunk]:
        tokens = query_tokens(question)
        if not tokens:
            return []
        match = " OR ".join(f'"{t}"' for t in tokens)
        # Path hits weigh 4x content hits: file names are dense signal.
        rows = self._db.execute(
            "SELECT c.id, c.path, c.start_line, c.end_line, c.text"
            " FROM chunks_fts f JOIN chunks c ON c.id = f.rowid"
            " WHERE chunks_fts MATCH ? ORDER BY bm25(chunks_fts, 4.0, 1.0) LIMIT ?",
            (match, k * 3),
        ).fetchall()
        # Tests restate the code they test; prefer the implementation itself.
        rows.sort(key=_is_test_path)  # stable: BM25 order kept within each group
        out: list[Chunk] = []
        per_file: dict[str, int] = {}
        for r in rows:  # at most 2 chunks per file -> broader coverage
            if per_file.get(r[1], 0) >= 2:
                continue
            per_file[r[1]] = per_file.get(r[1], 0) + 1
            out.append(Chunk(*r))
            if len(out) >= k:
                break
        return out

    def readme(self) -> Chunk | None:
        row = self._db.execute(
            "SELECT id, path, start_line, end_line, text FROM chunks"
            " WHERE lower(path) LIKE 'readme%' ORDER BY length(path), start_line LIMIT 1"
        ).fetchone()
        return Chunk(*row) if row else None

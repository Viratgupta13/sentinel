"""Codebase risk graph: files as nodes, imports as edges, review findings as risk.

Built from the per-repo code index (the "Ask this repo" snapshot already holds
every text file), so no extra download. Python imports are read with `ast`,
JS/TS imports with a regex; both are resolved to files in the snapshot and
anything that does not resolve (third-party packages) is dropped.

The layout is computed here, deterministically: one cluster per directory,
clusters shelf-packed in rows, files inside a cluster on a sunflower spiral
with the riskiest at the centre. The page only draws it.
"""

from __future__ import annotations

import ast
import math
import re
from collections import defaultdict, deque
from pathlib import PurePosixPath

CODE_EXT = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
JS_EXT = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
MAX_NODES = 400
SEVERITY_WEIGHT = {"high": 3, "medium": 2, "low": 1}

_JS_IMPORT = re.compile(
    r"""(?:import\s[^'"]*?from\s*|import\s*\(\s*|require\s*\(\s*|export\s[^'"]*?from\s*|import\s+)['"]([^'"]+)['"]"""
)


def is_code(path: str) -> bool:
    return PurePosixPath(path).suffix in CODE_EXT


# --- import extraction -------------------------------------------------------


def _python_imports(path: str, text: str) -> list[tuple[str, int]]:
    """(module, level) pairs; level > 0 for relative imports."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return []
    out: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [(a.name, 0) for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            out.append((base, node.level))
            # `from pkg import mod` may name a submodule rather than a symbol
            out += [(f"{base}.{a.name}" if base else a.name, node.level) for a in node.names]
    return out


def _resolve_python(
    importer: str, module: str, level: int, files: set[str], roots: list[str]
) -> str | None:
    parts = [p for p in module.split(".") if p]
    if level:
        base = list(PurePosixPath(importer).parent.parts)
        if level > 1:
            base = base[: len(base) - (level - 1)]
        candidates = ["/".join(base + parts)]
    else:
        candidates = [f"{root}{'/'.join(parts)}" for root in roots]
    for stem in candidates:
        stem = stem.strip("/")
        for path in (f"{stem}.py", f"{stem}/__init__.py"):
            if path in files:
                return path
    return None


def _resolve_js(importer: str, spec: str, files: set[str], roots: list[str]) -> str | None:
    if spec.startswith("."):
        stems = [str(PurePosixPath(importer).parent / spec)]
    elif spec.startswith(("@/", "~/")):
        stems = [f"{root}{spec[2:]}" for root in roots]
    else:
        return None  # a package, not a file in this repo
    for stem in stems:
        stem = _normalise(stem)
        if stem in files:
            return stem
        for ext in JS_EXT:
            if f"{stem}{ext}" in files:
                return f"{stem}{ext}"
        for ext in JS_EXT:
            if f"{stem}/index{ext}" in files:
                return f"{stem}/index{ext}"
    return None


def _normalise(path: str) -> str:
    out: list[str] = []
    for part in path.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if out:
                out.pop()
            continue
        out.append(part)
    return "/".join(out)


def _source_roots(files: set[str]) -> list[str]:
    """Prefixes absolute imports may be relative to: repo root, src/, and any
    directory holding a top-level Python package or a JS app/lib folder."""
    roots = ["", "src/"]
    for path in files:
        parts = PurePosixPath(path).parts
        if len(parts) >= 3 and parts[-1] == "__init__.py":
            root = "/".join(parts[:-2])
            roots.append(f"{root}/" if root else "")
    return list(dict.fromkeys(roots))


def import_edges(texts: dict[str, str]) -> set[tuple[str, str]]:
    """{(importer, imported)} between code files in the snapshot."""
    files = {p for p in texts if is_code(p)}
    roots = _source_roots(files)
    edges: set[tuple[str, str]] = set()
    for path in files:
        text = texts[path]
        if path.endswith(".py"):
            targets = [
                _resolve_python(path, mod, level, files, roots)
                for mod, level in _python_imports(path, text)
            ]
        else:
            targets = [_resolve_js(path, s, files, roots) for s in _JS_IMPORT.findall(text)]
        edges |= {(path, t) for t in targets if t and t != path}
    return edges


# --- risk, decisions, blast radius -------------------------------------------


def file_risk(review_rows: list) -> dict[str, dict]:
    """Per-file risk from the latest review of each PR (re-reviews replace,
    not add). review_rows: RunRow-like objects, newest first."""
    latest: dict[int, object] = {}
    for row in review_rows:
        if row.pr_number and row.pr_number not in latest:
            latest[row.pr_number] = row
    risk: dict[str, dict] = {}
    for number, row in latest.items():
        for f in row.findings or []:
            path = f.get("file")
            if not path:
                continue
            r = risk.setdefault(path, {"score": 0, "findings": [], "prs": set()})
            r["score"] += SEVERITY_WEIGHT.get(f.get("severity"), 1)
            r["findings"].append(
                {"severity": f.get("severity"), "title": f.get("title", ""), "pr": number}
            )
            r["prs"].add(number)
    return risk


def risk_band(score: int) -> str:
    if score >= 6:
        return "crit"
    if score >= 3:
        return "warn"
    if score > 0:
        return "low"
    return "none"


def blast_radius(
    changed: set[str], edges: set[tuple[str, str]], depth: int = 2
) -> dict[str, int]:
    """Files that (transitively) import a changed file -> hops away (1..depth)."""
    importers: dict[str, set[str]] = defaultdict(set)
    for src, dst in edges:
        importers[dst].add(src)
    hops: dict[str, int] = {}
    queue = deque((path, 0) for path in changed)
    seen = set(changed)
    while queue:
        path, d = queue.popleft()
        if d >= depth:
            continue
        for parent in importers.get(path, ()):
            if parent not in seen:
                seen.add(parent)
                hops[parent] = d + 1
                queue.append((parent, d + 1))
    return hops


# --- assembly + layout -------------------------------------------------------


def build_graph(
    texts: dict[str, str], review_rows: list, decisions: list | None = None
) -> dict:
    """The JSON the page draws: nodes (with layout + risk), edges, clusters."""
    edges = import_edges(texts)
    risk = file_risk(review_rows)
    pinned: dict[str, list[dict]] = defaultdict(list)
    for d in decisions or []:
        for path in d.files:
            pinned[path].append({
                "decision": d.decision, "kind": d.kind.value, "pr": d.pr_number,
                "url": d.pr_url,
            })

    code = [p for p in texts if is_code(p)]
    degree: dict[str, int] = defaultdict(int)
    for src, dst in edges:
        degree[src] += 1
        degree[dst] += 1
    # Over the cap: keep risky, connected and pinned files first.
    code.sort(key=lambda p: (-risk.get(p, {}).get("score", 0), -len(pinned.get(p, [])),
                             -degree[p], p))
    kept = set(code[:MAX_NODES])
    edges = {(a, b) for a, b in edges if a in kept and b in kept}

    nodes = []
    for path in kept:
        r = risk.get(path, {})
        nodes.append({
            "id": path,
            "dir": str(PurePosixPath(path).parent) if "/" in path else ".",
            "lines": texts[path].count("\n") + 1,
            "risk": r.get("score", 0),
            "band": risk_band(r.get("score", 0)),
            "findings": r.get("findings", [])[:8],
            "prs": sorted(r.get("prs", ())),
            "decisions": pinned.get(path, [])[:5],
            "imports": sum(1 for a, _ in edges if a == path),
            "imported_by": sum(1 for _, b in edges if b == path),
        })
    clusters = layout(nodes)
    return {
        "nodes": nodes,
        "edges": sorted(edges),
        "clusters": clusters,
        "truncated": len(code) > MAX_NODES,
        "total_files": len(code),
    }


def layout(nodes: list[dict], gap: float = 40.0, aspect: float = 1.3) -> list[dict]:
    """Assign node x/y in place; return cluster boxes {dir, x, y, r, n, risk}.
    Rows are as wide as a roughly `aspect`-shaped block of all clusters needs,
    so the map fills a screen instead of becoming one long strip."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for n in nodes:
        groups[n["dir"]].append(n)
    spacing = 20.0
    order = sorted(groups, key=lambda d: (-len(groups[d]), d))
    sizes = [2 * (spacing * math.sqrt(len(groups[d])) + 22) for d in order]
    area = sum((s + gap) * (s + gap + 18) for s in sizes)
    width = max(max(sizes, default=0), math.sqrt(area * aspect))
    clusters = []
    x = y = row_h = 0.0
    for d in order:
        members = sorted(groups[d], key=lambda n: (-n["risk"], -n["imported_by"], n["id"]))
        r = spacing * math.sqrt(len(members)) + 22
        if x and x + 2 * r > width:
            x, y, row_h = 0.0, y + row_h + gap, 0.0
        cx, cy = x + r, y + r + 18  # room for the label above the circle
        golden = math.pi * (3 - math.sqrt(5))
        for i, n in enumerate(members):
            dist = spacing * math.sqrt(i + 0.5)
            n["x"] = round(cx + dist * math.cos(i * golden), 1)
            n["y"] = round(cy + dist * math.sin(i * golden), 1)
        clusters.append({
            "dir": d, "x": round(cx, 1), "y": round(cy, 1), "r": round(r, 1),
            "n": len(members), "risk": sum(n["risk"] for n in members),
        })
        x += 2 * r + gap
        row_h = max(row_h, 2 * r + 18)
    return clusters

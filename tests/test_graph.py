"""Risk map: import graph, per-file risk, blast radius, layout and the API."""

import io
import tarfile

from fastapi.testclient import TestClient

import sentinel.server as server_mod
from sentinel.ask.index import RepoIndex, index_db_path
from sentinel.config import Settings
from sentinel.costs import CostHistory, RunRow
from sentinel.graph import blast_radius, build_graph, file_risk, import_edges, risk_band
from sentinel.models import Decision, DecisionKind, HunkReview, PRInfo, ReviewReport

PY = {
    "src/app/__init__.py": "",
    "src/app/api.py": "from app import db\nfrom .auth import check\nimport requests\n",
    "src/app/auth.py": "from app.db import connect\n",
    "src/app/db.py": "import sqlite3\n",
    "src/app/jobs/run.py": "from ..api import handler\n",
    "tests/test_api.py": "from app.api import handler\n",
}
JS = {
    "lib/data.js": "export const x = 1;\n",
    "components/Card.tsx": "import { x } from '@/lib/data';\nimport React from 'react';\n",
    "app/page.js": "import Card from '../components/Card';\nconst u = require('./util');\n",
    "app/util/index.js": "module.exports = {};\n",
}


def test_python_imports_resolve_relative_absolute_and_src_root():
    edges = import_edges(PY)
    assert ("src/app/api.py", "src/app/db.py") in edges          # from app import db
    assert ("src/app/api.py", "src/app/auth.py") in edges        # from .auth import
    assert ("src/app/auth.py", "src/app/db.py") in edges         # from app.db import
    assert ("src/app/jobs/run.py", "src/app/api.py") in edges    # from ..api import
    assert ("tests/test_api.py", "src/app/api.py") in edges
    assert not any("requests" in b or "sqlite3" in b for _, b in edges)


def test_js_imports_resolve_alias_extension_and_index():
    edges = import_edges(JS)
    assert edges == {
        ("components/Card.tsx", "lib/data.js"),
        ("app/page.js", "components/Card.tsx"),
        ("app/page.js", "app/util/index.js"),
    }


def _row(pr, findings, ts):
    return RunRow(ts=ts, command="review", repo="acme/app", pr_number=pr, total_hunks=1,
                  skipped_hunks=0, deep_reviewed_hunks=1, cost_usd=0, naive_cost_usd=0,
                  models=[], findings=findings)


def test_file_risk_uses_only_the_latest_review_of_each_pr():
    rows = [  # newest first
        _row(1, [{"severity": "high", "title": "SQLi", "file": "src/app/db.py"}], 3),
        _row(2, [{"severity": "medium", "title": "Leak", "file": "src/app/db.py"},
                 {"severity": "low", "title": "Nit", "file": "src/app/api.py"}], 2),
        _row(1, [{"severity": "high", "title": "old", "file": "src/app/auth.py"}], 1),
    ]
    risk = file_risk(rows)
    assert risk["src/app/db.py"]["score"] == 5 and risk["src/app/db.py"]["prs"] == {1, 2}
    assert risk["src/app/api.py"]["score"] == 1
    assert "src/app/auth.py" not in risk  # superseded by PR 1's re-review
    assert [risk_band(s) for s in (0, 1, 3, 6)] == ["none", "low", "warn", "crit"]


def test_blast_radius_walks_importers_up_to_depth():
    edges = import_edges(PY)
    hops = blast_radius({"src/app/db.py"}, edges)
    assert hops["src/app/api.py"] == 1 and hops["src/app/auth.py"] == 1
    assert hops["src/app/jobs/run.py"] == 2 and hops["tests/test_api.py"] == 2
    assert "src/app/db.py" not in hops
    assert blast_radius({"src/app/db.py"}, edges, depth=1).keys() == {
        "src/app/api.py", "src/app/auth.py"
    }


def test_build_graph_layout_pins_and_cap(monkeypatch):
    decision = Decision(repo="acme/app", pr_number=4, pr_url="u", kind=DecisionKind.CONSTRAINT,
                        decision="Never parse money with float", files=["src/app/db.py"])
    g = build_graph(PY, [_row(1, [{"severity": "high", "title": "SQLi",
                                   "file": "src/app/db.py"}], 1)], [decision])
    nodes = {n["id"]: n for n in g["nodes"]}
    assert len(nodes) == len(PY) and not g["truncated"]
    db = nodes["src/app/db.py"]
    assert db["band"] == "warn" and db["decisions"][0]["pr"] == 4
    assert db["imported_by"] == 2
    assert all("x" in n and "y" in n for n in g["nodes"])
    assert {c["dir"] for c in g["clusters"]} == {"src/app", "src/app/jobs", "tests"}
    # the riskiest file of a cluster sits at its centre
    cl = next(c for c in g["clusters"] if c["dir"] == "src/app")
    closest = min((n for n in g["nodes"] if n["dir"] == "src/app"),
                  key=lambda n: (n["x"] - cl["x"]) ** 2 + (n["y"] - cl["y"]) ** 2)
    assert closest["id"] == "src/app/db.py"

    import sentinel.graph as graph_mod
    monkeypatch.setattr(graph_mod, "MAX_NODES", 2)
    small = build_graph(PY, [], [decision])
    assert small["truncated"] and small["total_files"] == len(PY)
    assert "src/app/db.py" in {n["id"] for n in small["nodes"]}  # pinned files kept first


def _tarball(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for path, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(f"acme-app-abc1234/{path}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_graph_api_and_page(tmp_path, monkeypatch):
    settings = Settings(memory_home=str(tmp_path), post_comments=False, _env_file=None)
    index = RepoIndex(index_db_path(str(tmp_path), "acme/app"))
    index.build_from_tarball(_tarball(PY))
    index.close()
    history = CostHistory(tmp_path / "costs.db")
    history.record_report(ReviewReport(
        pr=PRInfo(owner="acme", repo="app", number=9), total_hunks=1, skipped_hunks=0,
        triaged_hunks=1, deep_reviewed_hunks=1, verdicts=[], cost_lines=[],
        total_cost_usd=0, naive_cost_estimate_usd=0,
        reviews=[HunkReview(hunk_id="h", file_path="src/app/db.py", risk_score=9, findings=[
            {"severity": "high", "title": "SQLi", "detail": "d"},
            {"severity": "high", "title": "Auth", "detail": "d"}])],
    ))
    history.close()

    class FakeGH:
        def __init__(self, *_a, **_k):
            pass

        def fetch_pr_files(self, owner, name, number):
            return ["src/app/db.py", "README.md"]

        def list_open_prs(self, owner, name):
            return [{"number": 9, "title": "Speed up queries"}]

    monkeypatch.setattr(server_mod, "GitHubClient", FakeGH)
    client = TestClient(server_mod.create_app(settings))

    g = client.get("/api/repo/acme/app/graph").json()
    nodes = {n["id"]: n for n in g["nodes"]}
    assert nodes["src/app/db.py"]["band"] == "crit" and g["ref"] == "abc1234"
    assert "pr" not in g

    g = client.get("/api/repo/acme/app/graph?pr=9").json()
    assert g["pr"]["changed"] == ["src/app/db.py"] and g["pr"]["unmapped"] == ["README.md"]
    assert g["pr"]["impacted"]["src/app/api.py"] == 1

    page = client.get("/repo/acme/app/graph").text
    assert 'id="risk-map"' in page and "PR #9: Speed up queries" in page

"""Repo-page actions: Review now, Build decision memory, live status."""

import time

import pytest
from fastapi.testclient import TestClient

import sentinel.server as server_mod
from sentinel.config import Settings
from sentinel.costs import CostHistory
from sentinel.hub import sessions
from sentinel.hub.store import HubStore
from sentinel.models import Decision, DecisionKind
from sentinel.server import SESSION_COOKIE, create_app

SECRET = "hub-secret"


@pytest.fixture
def env(tmp_path):
    server_mod._jobs.clear()
    settings = Settings(
        memory_home=str(tmp_path), post_comments=False, github_token="tok",
        github_client_id="cid", github_client_secret="csec", session_secret=SECRET,
        _env_file=None,
    )
    store = HubStore(tmp_path / "hub.db")
    store.upsert_user({"github_id": 1, "login": "virat", "avatar_url": ""})
    store.record_installation(10, "virat")
    store.set_repos(10, ["virat/app"])
    store.link_user(1, [10])
    store.close()
    client = TestClient(create_app(settings), follow_redirects=False)
    client.cookies.set(
        SESSION_COOKIE, sessions.sign({"uid": 1, "login": "virat", "avatar": ""}, SECRET)
    )
    return client, settings


def _wait(client, path, key, pred, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        d = client.get(path).json()
        if pred(d):
            return d
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting on {key}: {d}")


def test_review_now_runs_in_background(env, monkeypatch):
    client, _ = env
    calls = []

    def fake_review(pr_url, settings):
        calls.append((pr_url, settings.github_token))
        return object()

    monkeypatch.setattr(server_mod, "_run_review", fake_review)
    resp = client.post("/api/repo/virat/app/review", json={"number": 5})
    assert resp.status_code == 202 and resp.json()["started"] is True
    d = _wait(client, "/api/repo/virat/app/status", "review",
              lambda d: d["reviews"].get("5", {}).get("state") == "done")
    assert d["reviews"]["5"]["state"] == "done"
    assert calls == [("https://github.com/virat/app/pull/5", "tok")]


def test_review_now_failure_is_reported(env, monkeypatch):
    client, _ = env
    monkeypatch.setattr(server_mod, "_run_review", lambda url, s: None)
    client.post("/api/repo/virat/app/review", json={"number": 6})
    d = _wait(client, "/api/repo/virat/app/status", "review",
              lambda d: d["reviews"].get("6", {}).get("state") == "error")
    assert "failed" in d["reviews"]["6"]["msg"]


def test_review_now_dedupes_running_job(env, monkeypatch):
    client, _ = env
    gate = __import__("threading").Event()
    monkeypatch.setattr(server_mod, "_run_review", lambda url, s: gate.wait(5) or object())
    first = client.post("/api/repo/virat/app/review", json={"number": 7}).json()
    second = client.post("/api/repo/virat/app/review", json={"number": 7}).json()
    gate.set()
    assert first["started"] is True and second["started"] is False


def test_actions_validate_and_authorize(env):
    client, _ = env
    assert client.post("/api/repo/virat/app/review", json={"number": "x"}).status_code == 400
    assert client.post("/api/repo/other/repo/review", json={"number": 1}).status_code == 404
    assert client.post("/api/repo/other/repo/memory").status_code == 404
    assert client.get("/api/repo/other/repo/status").status_code == 404
    client.cookies.clear()
    assert client.post("/api/repo/virat/app/review", json={"number": 1}).status_code == 401
    assert client.post("/api/repo/virat/app/memory").status_code == 401
    assert client.get("/api/repo/virat/app/status").status_code == 401


def test_build_memory_job_stores_decisions_and_cost(env, monkeypatch):
    client, settings = env
    import sentinel.memory.harvest as harvest

    def fake_build(repo, store, s, llm, limit=None, on_progress=None, **kw):
        assert limit == server_mod.MEMORY_BUTTON_PRS and s.github_token == "tok"
        on_progress("found 2 merged PRs")
        store.add_decisions([Decision(
            repo=repo, pr_number=3, pr_title="t", pr_url="u", merged_at="",
            kind=DecisionKind.CONSTRAINT, decision="Never retry charges",
            rationale="double billing incident", files=["pay.py"], confidence=0.9,
        )])
        store.mark_harvested(3, 1)
        return {"prs_seen": 2, "prs_processed": 1, "new_decisions": 1, "cost_usd": 0.0}

    monkeypatch.setattr(harvest, "build_memory", fake_build)
    assert client.post("/api/repo/virat/app/memory").status_code == 202
    d = _wait(client, "/api/repo/virat/app/status", "memory",
              lambda d: (d["memory"] or {}).get("state") == "done")
    assert "1 new decisions" in d["memory"]["msg"]
    assert d["latest_ts"] > 0  # the harvest run is recorded -> page refreshes

    history = CostHistory(settings.memory_home + "/costs.db")
    assert [r.command for r in history.rows()] == ["memory-build"]
    history.close()


def test_repo_page_has_action_buttons(env, monkeypatch):
    client, _ = env
    monkeypatch.setattr(
        server_mod.GitHubClient, "list_open_prs",
        lambda self, o, n, cap=30: [
            {"number": 8, "title": "Fresh PR", "author": "virat", "draft": False,
             "updated_at": "2026-11-15T11:00:00Z", "html_url": "https://x/8"},
        ],
    )
    monkeypatch.setattr(server_mod.GitHubClient, "list_open_issues", lambda *a, **k: [])
    page = client.get("/repo/virat/app").text
    assert 'data-review="8"' in page and "Review now" in page
    assert 'id="mem-build"' in page and "Build decision memory" in page
    assert 'data-api="/api/repo/virat/app"' in page

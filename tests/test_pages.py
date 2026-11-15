"""Phase 7: repo-centric hub pages - home grid, repo page, routing + auth."""

import time

import pytest
from fastapi.testclient import TestClient

import sentinel.server as server_mod
from sentinel.config import Settings
from sentinel.costs import CostHistory, costs_db_path
from sentinel.hub import sessions
from sentinel.hub.store import HubStore, hub_db_path
from sentinel.models import CostLine, Finding, HunkReview, PRInfo, ReviewReport
from sentinel.server import SESSION_COOKIE, create_app

SECRET = "hub-secret"


def _report(repo: str, number: int, risk: int) -> ReviewReport:
    owner, name = repo.split("/")
    return ReviewReport(
        pr=PRInfo(owner=owner, repo=name, number=number, title="t", url="u"),
        total_hunks=1, skipped_hunks=0, triaged_hunks=1, deep_reviewed_hunks=1,
        verdicts=[],
        reviews=[HunkReview(hunk_id="a.py#0", file_path="a.py", risk_score=risk,
                            findings=[Finding(severity="high", title="boom", detail="d")])],
        cost_lines=[CostLine(model="m", calls=1, input_tokens=10, output_tokens=5,
                             cache_read_tokens=0, cache_write_tokens=0, cost_usd=0.0)],
        total_cost_usd=0.0, naive_cost_estimate_usd=0.0,
    )


@pytest.fixture
def env(tmp_path):
    settings = Settings(
        memory_home=str(tmp_path), post_comments=False,
        github_client_id="cid", github_client_secret="csec", session_secret=SECRET,
        _env_file=None,
    )
    store = HubStore(hub_db_path(str(tmp_path)))
    store.upsert_user({"github_id": 1, "login": "virat", "avatar_url": ""})
    store.record_installation(10, "virat")
    store.set_repos(10, ["virat/app", "virat/lib"])
    store.link_user(1, [10])
    store.close()

    history = CostHistory(costs_db_path(str(tmp_path)))
    history.record_report(_report("virat/app", 7, 9))
    history.close()

    client = TestClient(create_app(settings), follow_redirects=False)
    client.cookies.set(
        SESSION_COOKIE, sessions.sign({"uid": 1, "login": "virat", "avatar": ""}, SECRET)
    )
    return client


def test_home_shows_repo_cards(env):
    resp = env.get("/dashboard")
    assert resp.status_code == 200
    assert "virat/app" in resp.text and "virat/lib" in resp.text
    assert "/repo/virat/app" in resp.text
    assert "risk 9/10" in resp.text          # last review badge
    assert "no reviews yet" in resp.text     # the un-reviewed repo
    assert "/overview" in resp.text


def test_repo_page_lists_prs_with_risk_badges(env, monkeypatch):
    monkeypatch.setattr(
        server_mod.GitHubClient, "list_open_prs",
        lambda self, o, n, cap=30: [
            {"number": 7, "title": "Reviewed PR", "author": "virat", "draft": False,
             "updated_at": "2026-11-15T10:00:00Z", "html_url": "https://x/7"},
            {"number": 8, "title": "Fresh PR", "author": "virat", "draft": False,
             "updated_at": "2026-11-15T11:00:00Z", "html_url": "https://x/8"},
        ],
    )
    monkeypatch.setattr(
        server_mod.GitHubClient, "list_open_issues",
        lambda self, o, n, cap=30: [
            {"number": 3, "title": "Bug report", "author": "u",
             "updated_at": "2026-11-15T09:00:00Z", "html_url": "https://x/3"},
        ],
    )
    resp = env.get("/repo/virat/app")
    assert resp.status_code == 200
    assert "Reviewed PR" in resp.text and "risk 9/10" in resp.text
    assert "Fresh PR" in resp.text and "no review yet" in resp.text
    assert "Bug report" in resp.text
    assert "boom" in resp.text  # review history card


def test_repo_page_survives_github_outage(env, monkeypatch):
    def _boom(self, o, n, cap=30):
        raise RuntimeError("github down")

    monkeypatch.setattr(server_mod.GitHubClient, "list_open_prs", _boom)
    monkeypatch.setattr(server_mod.GitHubClient, "list_open_issues", _boom)
    resp = env.get("/repo/virat/app")
    assert resp.status_code == 200
    assert "Live GitHub data unavailable" in resp.text


def test_repo_page_denies_foreign_repo(env):
    assert env.get("/repo/other/secret").status_code == 404


def test_signed_out_redirects(env):
    env.cookies.clear()
    for path in ("/dashboard", "/overview", "/repo/virat/app"):
        assert env.get(path).status_code == 307


def test_local_mode_keeps_unified_dashboard(tmp_path):
    settings = Settings(memory_home=str(tmp_path), post_comments=False, _env_file=None)
    client = TestClient(create_app(settings))
    resp = client.get("/dashboard")
    assert "Sentinel dashboard" in resp.text  # old unified page, no login


def test_empty_store_resyncs_from_github(tmp_path, monkeypatch):
    """Ephemeral-disk recovery: store wiped => installations refetched via app JWT."""
    settings = Settings(
        memory_home=str(tmp_path), post_comments=False,
        github_client_id="cid", github_client_secret="csec", session_secret=SECRET,
        github_app_id="77", github_app_private_key="pem",
        _env_file=None,
    )
    monkeypatch.setattr(server_mod, "load_private_key", lambda s: "pem")

    class FakeTokens:
        def __init__(self, app_id, key):
            pass

        def list_installations(self):
            return [{"installation_id": 10, "account_login": "virat"}]

        def token(self, iid):
            return f"t-{iid}"

    monkeypatch.setattr(server_mod, "InstallationTokens", FakeTokens)
    monkeypatch.setattr(
        server_mod.GitHubClient, "list_installation_repos",
        lambda self, cap=100: ["virat/app"],
    )

    client = TestClient(create_app(settings), follow_redirects=False)
    client.cookies.set(
        SESSION_COOKIE, sessions.sign({"uid": 1, "login": "virat", "avatar": ""}, SECRET)
    )
    resp = client.get("/dashboard")  # store is empty -> resync kicks in
    assert "virat/app" in resp.text

    store = HubStore(hub_db_path(str(tmp_path)))
    assert store.repos_for_user(1) == {"virat/app"}
    store.close()


def test_home_sorted_by_recent_activity(env, tmp_path):
    time.sleep(0.01)  # ensure a strictly newer timestamp
    history = CostHistory(costs_db_path(str(tmp_path)))
    history.record_report(_report("virat/lib", 2, 3))
    history.close()
    text = env.get("/dashboard").text
    # virat/lib reviewed most recently => its card comes first
    assert text.index('href="/repo/virat/lib"') < text.index('href="/repo/virat/app"')

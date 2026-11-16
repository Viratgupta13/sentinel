"""Durable stores on both backends: SQLite (always) and Postgres (when
SENTINEL_TEST_DATABASE_URL points at a disposable database)."""

import os
import time

import pytest
from fastapi.testclient import TestClient

from sentinel import db as db_mod
from sentinel.config import Settings
from sentinel.costs import CostHistory
from sentinel.db import DB, location
from sentinel.hub import sessions
from sentinel.hub.store import HubStore
from sentinel.models import CostLine, Finding, HunkReview, PRInfo, ReviewReport
from sentinel.server import SESSION_COOKIE, create_app

PG_URL = os.environ.get("SENTINEL_TEST_DATABASE_URL", "")
TABLES = (
    "runs", "users", "installations", "user_installations", "installation_repos",
    "memory_snapshots",
)


def _report(repo: str, number: int, risk: int) -> ReviewReport:
    owner, name = repo.split("/")
    return ReviewReport(
        pr=PRInfo(owner=owner, repo=name, number=number, title="t", url="u"),
        total_hunks=1, skipped_hunks=0, triaged_hunks=1, deep_reviewed_hunks=1,
        verdicts=[],
        reviews=[HunkReview(hunk_id="a.py#0", file_path="a.py", risk_score=risk,
                            findings=[Finding(severity="high", title="boom", detail="d")])],
        cost_lines=[CostLine(model="m", calls=1, input_tokens=10, output_tokens=5,
                             cache_read_tokens=0, cache_write_tokens=0, cost_usd=0.001)],
        total_cost_usd=0.001, naive_cost_estimate_usd=0.01,
    )


@pytest.fixture(params=["sqlite", "postgres"])
def target(request, tmp_path):
    if request.param == "sqlite":
        return {"costs": tmp_path / "costs.db", "hub": tmp_path / "hub.db"}
    if not PG_URL:
        pytest.skip("SENTINEL_TEST_DATABASE_URL not set")
    conn = DB(PG_URL)
    conn.script("".join(f"DROP TABLE IF EXISTS {t};" for t in TABLES))
    return {"costs": PG_URL, "hub": PG_URL}


def test_location_prefers_database_url(tmp_path):
    s = Settings(memory_home=str(tmp_path), _env_file=None)
    assert location(s, "costs.db") == tmp_path / "costs.db"
    s = Settings(memory_home=str(tmp_path), database_url="postgresql://u@h/d", _env_file=None)
    assert location(s, "costs.db") == "postgresql://u@h/d"
    assert db_mod.is_postgres("postgres://x") and not db_mod.is_postgres(tmp_path / "x.db")


def test_cost_history_round_trip(target):
    h = CostHistory(target["costs"])
    before = time.time()
    h.record_report(_report("acme/app", 7, 9))
    h.record_harvest("acme/app", 0.02, [
        {"model": "m", "calls": 2, "in": 1, "out": 1, "cache_read": 0, "usd": 0.02},
    ])
    rows = h.rows()
    h.close()
    assert [r.command for r in rows] == ["memory-build", "review"]
    review = rows[1]
    assert (review.repo, review.pr_number, review.max_risk) == ("acme/app", 7, 9)
    assert review.findings[0]["title"] == "boom"
    # Timestamps must keep sub-second precision (Postgres REAL would not).
    assert abs(review.ts - before) < 5
    assert rows[0].ts > review.ts

    # Reopening (a new process after a redeploy) sees the same history.
    again = CostHistory(target["costs"])
    assert again.summary()["runs"] == 2
    again.close()


def test_hub_store_on_both_backends(target):
    store = HubStore(target["hub"])
    big = 3_000_000_000  # GitHub ids outgrow 32-bit ints
    store.upsert_user({"github_id": big, "login": "virat", "avatar_url": "a"})
    store.upsert_user({"github_id": big, "login": "virat2", "avatar_url": "b"})
    store.record_installation(big + 1, "virat")
    store.set_repos(big + 1, ["virat/app", "virat/lib"])
    store.add_repos(big + 1, ["virat/app", "virat/new"])     # duplicate ignored
    store.link_user(big, [big + 1])
    store.link_user(big, [big + 1])                           # idempotent
    store.remove_repos(big + 1, ["virat/lib"])
    store.link_user(big, [])                                  # empty batch is a no-op

    assert store.user(big)["login"] == "virat2"
    assert store.repos_for_user(big) == {"virat/app", "virat/new"}
    assert store.installation_for_repo("virat/new") == big + 1

    store.remove_installation(big + 1)
    assert store.repos_for_user(big) == set()
    assert store.installation_for_repo("virat/app") is None
    store.close()


@pytest.mark.skipif(not PG_URL, reason="SENTINEL_TEST_DATABASE_URL not set")
def test_postgres_reconnects_after_dropped_connection():
    conn = DB(PG_URL)
    conn.script("DROP TABLE IF EXISTS runs;")
    h = CostHistory(PG_URL)
    h.record_report(_report("acme/app", 1, 3))
    db_mod._pg_conns[PG_URL].close()  # what an idle-timeout disconnect looks like
    h.record_report(_report("acme/app", 2, 4))
    assert len(h.rows()) == 2


def test_history_survives_redeploy(target, tmp_path):
    """Fresh empty disk + same DATABASE_URL => the dashboard still has everything."""
    if not db_mod.is_postgres(target["costs"]):
        pytest.skip("only a database URL survives a wiped disk")
    secret = "s"

    def app_on(disk):
        settings = Settings(
            memory_home=str(disk), database_url=target["costs"], post_comments=False,
            github_client_id="cid", github_client_secret="csec", session_secret=secret,
            _env_file=None,
        )
        client = TestClient(create_app(settings), follow_redirects=False)
        client.cookies.set(
            SESSION_COOKIE, sessions.sign({"uid": 1, "login": "virat", "avatar": ""}, secret)
        )
        return settings, client

    settings, _ = app_on(tmp_path / "disk1")
    store = HubStore(location(settings, "hub.db"))
    store.upsert_user({"github_id": 1, "login": "virat", "avatar_url": ""})
    store.record_installation(10, "virat")
    store.set_repos(10, ["virat/app"])
    store.link_user(1, [10])
    history = CostHistory(location(settings, "costs.db"))
    history.record_report(_report("virat/app", 7, 9))
    history.close()

    _, client = app_on(tmp_path / "disk2")  # the "redeployed" instance
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    assert "virat/app" in resp.text and "risk 9/10" in resp.text
    assert not (tmp_path / "disk2" / "costs.db").exists()


def test_memory_snapshot_round_trip(target, tmp_path):
    from sentinel.memory import snapshots
    from sentinel.memory.store import MemoryStore, db_path_for

    url = target["costs"] if db_mod.is_postgres(target["costs"]) else ""
    s = Settings(memory_home=str(tmp_path / "disk1"), database_url=url, _env_file=None)
    store = MemoryStore(db_path_for(s.memory_home, "virat/app"))
    store.mark_harvested(4, 0)
    store.close()
    if not url:
        assert snapshots.save(s, "virat/app") is False   # local file is the durable copy
        assert snapshots.restore_all(s) == 0
        return
    assert snapshots.save(s, "virat/app") is True
    fresh = s.model_copy(update={"memory_home": str(tmp_path / "disk2")})
    assert snapshots.restore_all(fresh) == 1
    assert snapshots.restore_all(fresh) == 0              # existing files are kept
    again = MemoryStore(db_path_for(fresh.memory_home, "virat/app"))
    assert again.is_harvested(4)
    again.close()

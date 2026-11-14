"""Phase 5: webhook server - signature checks, event filtering, review wiring."""

import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

import sentinel.server as server_mod
from sentinel.config import Settings
from sentinel.server import create_app

SECRET = "s3cret"


def _signed(payload: dict) -> tuple[bytes, dict]:
    body = json.dumps(payload).encode()
    sig = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    return body, {
        "X-Hub-Signature-256": f"sha256={sig}",
        "X-GitHub-Event": "pull_request",
        "Content-Type": "application/json",
    }


@pytest.fixture
def client(tmp_path):
    settings = Settings(
        webhook_secret=SECRET, memory_home=str(tmp_path), post_comments=False,
        _env_file=None,
    )
    return TestClient(create_app(settings))


def _pr_payload(action="opened", draft=False):
    return {
        "action": action,
        "pull_request": {
            "html_url": "https://github.com/acme/app/pull/7",
            "draft": draft,
        },
    }


def test_bad_signature_rejected(client):
    body = json.dumps(_pr_payload()).encode()
    resp = client.post(
        "/webhook/github", content=body,
        headers={"X-Hub-Signature-256": "sha256=deadbeef", "X-GitHub-Event": "pull_request"},
    )
    assert resp.status_code == 401


def test_missing_signature_rejected(client):
    resp = client.post(
        "/webhook/github", content=b"{}", headers={"X-GitHub-Event": "pull_request"}
    )
    assert resp.status_code == 401


def test_non_pr_event_skipped(client):
    body = json.dumps({"zen": "ok"}).encode()
    sig = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    resp = client.post(
        "/webhook/github", content=body,
        headers={"X-Hub-Signature-256": f"sha256={sig}", "X-GitHub-Event": "push"},
    )
    assert resp.status_code == 200
    assert "skipped" in resp.json()


def test_draft_and_closed_skipped(client, monkeypatch):
    ran = []
    monkeypatch.setattr(server_mod, "_run_review", lambda url, s: ran.append(url))
    for payload in (_pr_payload(draft=True), _pr_payload(action="closed")):
        body, headers = _signed(payload)
        resp = client.post("/webhook/github", content=body, headers=headers)
        assert resp.status_code == 200
        assert "skipped" in resp.json()
    assert ran == []


def test_opened_pr_queues_review(client, monkeypatch):
    ran = []
    monkeypatch.setattr(server_mod, "_run_review", lambda url, s: ran.append(url))
    body, headers = _signed(_pr_payload())
    resp = client.post("/webhook/github", content=body, headers=headers)
    assert resp.status_code == 202
    assert resp.json()["queued"] == "https://github.com/acme/app/pull/7"
    # TestClient runs BackgroundTasks synchronously before returning.
    assert ran == ["https://github.com/acme/app/pull/7"]


def test_dashboard_and_healthz(client):
    assert client.get("/healthz").json() == {"ok": True}
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    assert "Sentinel dashboard" in resp.text


def test_run_review_never_raises(monkeypatch, tmp_path):
    settings = Settings(memory_home=str(tmp_path), _env_file=None)

    def boom(*a, **k):
        raise RuntimeError("github down")

    monkeypatch.setattr(server_mod, "load_pr", boom)
    assert server_mod._run_review("https://github.com/a/b/pull/1", settings) is None

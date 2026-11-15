"""Phase 6: hub - sessions, tenant store, login flow, installation webhooks."""

import hashlib
import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient

from sentinel.config import Settings
from sentinel.hub import oauth, sessions
from sentinel.hub.store import HubStore, hub_db_path
from sentinel.server import SESSION_COOKIE, create_app

SECRET = "hub-secret"
WEBHOOK_SECRET = "hook-secret"


# --- sessions ---

def test_session_sign_verify_roundtrip():
    tok = sessions.sign({"uid": 42, "login": "virat"}, SECRET)
    data = sessions.verify(tok, SECRET)
    assert data["uid"] == 42 and data["login"] == "virat"


def test_session_tamper_and_expiry_rejected():
    tok = sessions.sign({"uid": 42}, SECRET)
    assert sessions.verify(tok + "0", SECRET) is None
    assert sessions.verify(tok, "other-secret") is None
    assert sessions.verify(tok, SECRET, max_age_s=-1) is None
    assert sessions.verify(None, SECRET) is None
    assert sessions.verify("garbage", SECRET) is None


# --- store ---

def test_store_installations_and_user_repos(tmp_path):
    store = HubStore(hub_db_path(str(tmp_path)))
    store.upsert_user({"github_id": 1, "login": "virat", "avatar_url": "a"})
    store.record_installation(10, "virat")
    store.set_repos(10, ["virat/app", "virat/lib"])
    store.link_user(1, [10])
    assert store.repos_for_user(1) == {"virat/app", "virat/lib"}

    store.add_repos(10, ["virat/new"])
    store.remove_repos(10, ["virat/lib"])
    assert store.repos_for_user(1) == {"virat/app", "virat/new"}

    store.remove_installation(10)
    assert store.repos_for_user(1) == set()
    assert store.user(1)["login"] == "virat"
    store.close()


# --- app wiring ---

@pytest.fixture
def hub_settings(tmp_path):
    return Settings(
        webhook_secret=WEBHOOK_SECRET, memory_home=str(tmp_path), post_comments=False,
        github_client_id="cid", github_client_secret="csec", session_secret=SECRET,
        base_url="http://testserver", _env_file=None,
    )


@pytest.fixture
def client(hub_settings):
    return TestClient(create_app(hub_settings), follow_redirects=False)


def _signed(payload: dict, event: str) -> tuple[bytes, dict]:
    body = json.dumps(payload).encode()
    sig = hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return body, {
        "X-Hub-Signature-256": f"sha256={sig}",
        "X-GitHub-Event": event,
        "Content-Type": "application/json",
    }


def test_landing_when_signed_out(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Sign in with GitHub" in resp.text
    assert client.get("/dashboard").status_code == 307  # redirected to landing
    assert client.get("/api/latest").status_code == 401


def test_login_redirects_to_github(client):
    resp = client.get("/login")
    assert resp.status_code == 307
    assert resp.headers["location"].startswith("https://github.com/login/oauth/authorize")
    assert "client_id=cid" in resp.headers["location"]


def test_oauth_callback_sets_cookie_and_filters_dashboard(client, monkeypatch, tmp_path):
    monkeypatch.setattr(oauth, "exchange_code", lambda *a: "user-token")
    monkeypatch.setattr(
        oauth, "fetch_user",
        lambda t: {"github_id": 1, "login": "virat", "name": "V", "avatar_url": ""},
    )
    monkeypatch.setattr(
        oauth, "fetch_user_installations",
        lambda t: [{"installation_id": 10, "account_login": "virat"}],
    )
    monkeypatch.setattr(
        oauth, "fetch_installation_repos", lambda t, iid: ["virat/app"]
    )

    state = sessions.sign({"n": "x"}, SECRET)
    resp = client.get("/auth/callback", params={"code": "c", "state": state})
    assert resp.status_code == 307 and resp.headers["location"] == "/dashboard"
    cookie = resp.cookies[SESSION_COOKIE]
    assert sessions.verify(cookie, SECRET)["login"] == "virat"

    client.cookies.set(SESSION_COOKIE, cookie)
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    assert "virat" in resp.text and "sign out" in resp.text
    assert "/api/latest" in resp.text  # live polling enabled
    assert client.get("/api/latest").json() == {"ts": 0}


def test_callback_rejects_bad_state(client):
    resp = client.get("/auth/callback", params={"code": "c", "state": "forged"})
    assert resp.status_code == 400


def test_installation_webhook_updates_store(client, hub_settings):
    body, headers = _signed(
        {
            "action": "created",
            "installation": {"id": 10, "account": {"login": "virat"}},
            "repositories": [{"full_name": "virat/app"}],
        },
        "installation",
    )
    assert client.post("/webhook/github", content=body, headers=headers).status_code == 200

    body, headers = _signed(
        {
            "installation": {"id": 10, "account": {"login": "virat"}},
            "repositories_added": [{"full_name": "virat/lib"}],
            "repositories_removed": [{"full_name": "virat/app"}],
        },
        "installation_repositories",
    )
    assert client.post("/webhook/github", content=body, headers=headers).status_code == 200

    store = HubStore(hub_db_path(hub_settings.memory_home))
    store.link_user(1, [10])
    assert store.repos_for_user(1) == {"virat/lib"}
    store.close()

    body, headers = _signed(
        {"action": "deleted", "installation": {"id": 10}}, "installation"
    )
    assert client.post("/webhook/github", content=body, headers=headers).status_code == 200
    store = HubStore(hub_db_path(hub_settings.memory_home))
    assert store.repos_for_user(1) == set()
    store.close()


def test_pr_webhook_uses_installation_token(hub_settings, monkeypatch, tmp_path):
    import sentinel.server as server_mod

    settings = hub_settings.model_copy(
        update={"github_app_id": "77", "github_app_private_key": "unused"}
    )
    monkeypatch.setattr(server_mod, "load_private_key", lambda s: "pem")

    class FakeTokens:
        def __init__(self, app_id, key):
            assert app_id == "77"

        def token(self, iid):
            return f"inst-token-{iid}"

    monkeypatch.setattr(server_mod, "InstallationTokens", FakeTokens)
    seen = {}
    monkeypatch.setattr(
        server_mod, "_run_review", lambda url, s: seen.update(url=url, token=s.github_token)
    )

    client = TestClient(create_app(settings), follow_redirects=False)
    body, headers = _signed(
        {
            "action": "opened",
            "pull_request": {"html_url": "https://github.com/v/app/pull/3", "draft": False},
            "installation": {"id": 55},
        },
        "pull_request",
    )
    resp = client.post("/webhook/github", content=body, headers=headers)
    assert resp.status_code == 202
    assert seen == {"url": "https://github.com/v/app/pull/3", "token": "inst-token-55"}


def test_app_jwt_claims():
    jwt_mod = pytest.importorskip("jwt")
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()

    from sentinel.hub.appauth import app_jwt

    now = time.time()
    token = app_jwt("1234", pem, now=now)
    claims = jwt_mod.decode(
        token, key.public_key(), algorithms=["RS256"], options={"verify_exp": False}
    )
    assert claims["iss"] == "1234"
    assert claims["exp"] - claims["iat"] == 600

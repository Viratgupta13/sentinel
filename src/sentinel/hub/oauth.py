"""'Sign in with GitHub' - the web OAuth flow of the GitHub App.

No scopes are requested: the user token only identifies the user and lists
which installations of *this app* they can access (GET /user/installations).
Repo access for reviews comes from installation tokens, never from the user.
"""

from __future__ import annotations

import httpx

API = "https://api.github.com"
AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
TOKEN_URL = "https://github.com/login/oauth/access_token"

_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "sentinel-review",
}


class OAuthError(RuntimeError):
    pass


def login_url(client_id: str, redirect_uri: str, state: str) -> str:
    q = httpx.QueryParams(
        {"client_id": client_id, "redirect_uri": redirect_uri, "state": state}
    )
    return f"{AUTHORIZE_URL}?{q}"


def exchange_code(client_id: str, client_secret: str, code: str) -> str:
    resp = httpx.post(
        TOKEN_URL,
        data={"client_id": client_id, "client_secret": client_secret, "code": code},
        headers={"Accept": "application/json"},
        timeout=20.0,
    )
    resp.raise_for_status()
    data = resp.json()
    token = data.get("access_token")
    if not token:
        raise OAuthError(f"token exchange failed: {data.get('error', 'no access_token')}")
    return token


def fetch_user(user_token: str) -> dict:
    resp = httpx.get(
        f"{API}/user",
        headers={**_HEADERS, "Authorization": f"Bearer {user_token}"},
        timeout=20.0,
    )
    resp.raise_for_status()
    u = resp.json()
    return {
        "github_id": u["id"],
        "login": u.get("login", ""),
        "name": u.get("name") or u.get("login", ""),
        "avatar_url": u.get("avatar_url", ""),
    }


def fetch_user_installations(user_token: str) -> list[dict]:
    """Installations of this app the signed-in user can access."""
    resp = httpx.get(
        f"{API}/user/installations",
        headers={**_HEADERS, "Authorization": f"Bearer {user_token}"},
        params={"per_page": 100},
        timeout=20.0,
    )
    resp.raise_for_status()
    return [
        {"installation_id": i["id"], "account_login": (i.get("account") or {}).get("login", "")}
        for i in resp.json().get("installations", [])
    ]


def fetch_installation_repos(user_token: str, installation_id: int) -> list[str]:
    """'owner/name' repos that installation granted (first 100 - plenty here)."""
    resp = httpx.get(
        f"{API}/user/installations/{installation_id}/repositories",
        headers={**_HEADERS, "Authorization": f"Bearer {user_token}"},
        params={"per_page": 100},
        timeout=20.0,
    )
    resp.raise_for_status()
    return [r["full_name"] for r in resp.json().get("repositories", [])]

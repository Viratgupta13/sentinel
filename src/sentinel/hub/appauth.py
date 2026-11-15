"""GitHub App authentication: app JWT -> short-lived installation tokens.

A GitHub App never uses a personal token. It signs a JWT with its private key
(proves "I am app X"), then exchanges it per installation for a token scoped to
exactly the repos that installation granted - the right model for a multi-tenant
service: each customer's reviews run with their own installation's token.
"""

from __future__ import annotations

import time

import httpx
import jwt

from sentinel.config import Settings

API = "https://api.github.com"


def load_private_key(settings: Settings) -> str | None:
    """PEM from SENTINEL_GITHUB_APP_PRIVATE_KEY (inline, '\\n' escapes ok) or _PATH."""
    if settings.github_app_private_key:
        return settings.github_app_private_key.replace("\\n", "\n")
    if settings.github_app_private_key_path:
        from pathlib import Path

        return Path(settings.github_app_private_key_path).expanduser().read_text()
    return None


def app_jwt(app_id: str, private_key: str, now: float | None = None) -> str:
    now = now or time.time()
    payload = {"iat": int(now) - 60, "exp": int(now) + 540, "iss": app_id}
    return jwt.encode(payload, private_key, algorithm="RS256")


class InstallationTokens:
    """Mints and caches installation access tokens (valid ~1h; refresh at <60s)."""

    def __init__(self, app_id: str, private_key: str) -> None:
        self._app_id = app_id
        self._key = private_key
        self._cache: dict[int, tuple[str, float]] = {}

    def token(self, installation_id: int) -> str:
        cached = self._cache.get(installation_id)
        if cached and cached[1] - time.time() > 60:
            return cached[0]
        resp = httpx.post(
            f"{API}/app/installations/{installation_id}/access_tokens",
            headers={
                "Authorization": f"Bearer {app_jwt(self._app_id, self._key)}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=20.0,
        )
        resp.raise_for_status()
        data = resp.json()
        # expires_at is ISO8601; parse cheaply via time.strptime (always UTC "Z").
        expires = time.mktime(time.strptime(data["expires_at"], "%Y-%m-%dT%H:%M:%SZ"))
        expires -= time.timezone  # strptime read it as local; shift back to UTC
        self._cache[installation_id] = (data["token"], expires)
        return data["token"]

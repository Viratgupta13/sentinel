"""Signed session cookies - stdlib HMAC, no server-side session storage.

Cookie value: base64url(json payload) + "." + hex hmac-sha256. Tamper-proof
(signature covers the payload) but not encrypted - nothing secret goes in it,
just the GitHub user id/login for display and lookup.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

MAX_AGE_S = 30 * 24 * 3600  # 30 days


def sign(payload: dict, secret: str) -> str:
    body = dict(payload, iat=int(time.time()))
    raw = base64.urlsafe_b64encode(json.dumps(body, separators=(",", ":")).encode())
    mac = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return f"{raw.decode()}.{mac}"


def verify(token: str | None, secret: str, max_age_s: int = MAX_AGE_S) -> dict | None:
    if not token or "." not in token:
        return None
    raw, _, mac = token.rpartition(".")
    expected = hmac.new(secret.encode(), raw.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(mac, expected):
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(raw.encode()))
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict) or time.time() - payload.get("iat", 0) > max_age_s:
        return None
    return payload

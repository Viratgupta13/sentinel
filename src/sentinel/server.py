"""Phase 5: webhook server - PR opened on GitHub => review runs => comment posted.

FastAPI app with three endpoints:

  POST /webhook/github   GitHub `pull_request` events (HMAC-verified); queues a
                         review in the background and returns 202 immediately
  GET  /dashboard        the live unified dashboard (reviews + memory + costs)
  GET  /healthz          liveness probe

Run it with `sentinel serve` (requires `pip install 'sentinel-review[server]'`).
Point a GitHub webhook (content type application/json, events: pull requests)
at /webhook/github and set SENTINEL_WEBHOOK_SECRET to the webhook's secret.
"""

from __future__ import annotations

import hashlib
import hmac
import logging

from fastapi import BackgroundTasks, FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse

from sentinel.config import Settings, load_settings
from sentinel.costs import CostHistory, costs_db_path
from sentinel.github.client import GitHubClient
from sentinel.memory.store import all_repo_stats
from sentinel.models import ReviewReport
from sentinel.pipeline import load_pr, open_memory_if_exists, review_pr
from sentinel.report.dashboard import render_dashboard
from sentinel.report.render import to_markdown

log = logging.getLogger("sentinel.server")

# PR actions that trigger a (re-)review. "synchronize" = new commits pushed.
REVIEW_ACTIONS = {"opened", "reopened", "synchronize", "ready_for_review"}


def _signature_ok(secret: str, payload: bytes, header: str | None) -> bool:
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(header.removeprefix("sha256="), expected)


def _run_review(pr_url: str, settings: Settings) -> ReviewReport | None:
    """The background job: fetch, review, record, comment. Never raises."""
    try:
        pr, files = load_pr(pr_url, settings)
        memory_store = open_memory_if_exists(pr, settings)
        report = review_pr(pr, files, settings, memory_store=memory_store)
    except Exception:
        log.exception("webhook review failed for %s", pr_url)
        return None

    try:
        history = CostHistory(costs_db_path(settings.memory_home))
        try:
            history.record_report(report)
        finally:
            history.close()
    except Exception:
        log.exception("recording run failed for %s", pr_url)

    if settings.post_comments:
        try:
            gh = GitHubClient(settings.github_token)
            url = gh.upsert_pr_comment(
                pr.owner, pr.repo, pr.number, to_markdown(report)
            )
            log.info("review comment posted: %s", url)
        except Exception:
            log.exception("posting comment failed for %s", pr_url)
    return report


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    app = FastAPI(title="sentinel", docs_url=None, redoc_url=None)

    @app.get("/healthz")
    def healthz() -> dict:
        return {"ok": True}

    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard() -> str:
        history = CostHistory(costs_db_path(settings.memory_home))
        try:
            rows, summary = history.rows(), history.summary()
        finally:
            history.close()
        return render_dashboard(rows, summary, memory=all_repo_stats(settings.memory_home))

    @app.post("/webhook/github")
    async def github_webhook(request: Request, background: BackgroundTasks) -> Response:
        payload = await request.body()
        if settings.webhook_secret:
            if not _signature_ok(
                settings.webhook_secret, payload, request.headers.get("X-Hub-Signature-256")
            ):
                return JSONResponse({"error": "bad signature"}, status_code=401)
        else:
            log.warning("SENTINEL_WEBHOOK_SECRET unset - accepting unsigned payload")

        event = request.headers.get("X-GitHub-Event", "")
        if event == "ping":
            return JSONResponse({"ok": True, "pong": True})
        if event != "pull_request":
            return JSONResponse({"ok": True, "skipped": f"event {event!r}"})

        body = await request.json()
        action = body.get("action", "")
        pr = body.get("pull_request") or {}
        if action not in REVIEW_ACTIONS:
            return JSONResponse({"ok": True, "skipped": f"action {action!r}"})
        if pr.get("draft"):
            return JSONResponse({"ok": True, "skipped": "draft PR"})
        pr_url = pr.get("html_url")
        if not pr_url:
            return JSONResponse({"error": "no pull_request.html_url"}, status_code=400)

        background.add_task(_run_review, pr_url, settings)
        return JSONResponse({"ok": True, "queued": pr_url}, status_code=202)

    return app

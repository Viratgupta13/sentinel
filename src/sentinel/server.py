"""Phases 5+6: webhook server and hosted hub.

Local mode (no hub env vars): exactly the Phase 5 behavior - open dashboard,
HMAC-verified `pull_request` webhooks, reviews posted with your own token.

Hub mode (GitHub App + login configured): a multi-tenant hosted product -
  * "Sign in with GitHub" (OAuth, no scopes) with signed session cookies
  * `installation` webhook events keep a tenant store of who installed the
    app and which repos it covers
  * each review runs with that installation's short-lived token (private
    repos work, comments post as the app)
  * /dashboard shows each user only their installations' repos, live-updating

Run with `sentinel serve` (requires `pip install 'sentinel-review[server]'`).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets as pysecrets

from fastapi import BackgroundTasks, FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from sentinel.config import Settings, load_settings
from sentinel.costs import CostHistory, costs_db_path, summarize
from sentinel.github.client import GitHubClient
from sentinel.hub import oauth, sessions
from sentinel.hub.appauth import InstallationTokens, load_private_key
from sentinel.hub.store import HubStore, hub_db_path
from sentinel.memory.store import all_repo_stats
from sentinel.models import ReviewReport
from sentinel.pipeline import load_pr, open_memory_if_exists, review_pr
from sentinel.report.dashboard import render_dashboard, render_landing
from sentinel.report.pages import render_home, render_repo_page
from sentinel.report.render import to_markdown

log = logging.getLogger("sentinel.server")

# PR actions that trigger a (re-)review. "synchronize" = new commits pushed.
REVIEW_ACTIONS = {"opened", "reopened", "synchronize", "ready_for_review"}
SESSION_COOKIE = "sentinel_session"


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

    private_key = load_private_key(settings)
    inst_tokens = (
        InstallationTokens(settings.github_app_id, private_key)
        if settings.github_app_id and private_key
        else None
    )

    def _store() -> HubStore:
        return HubStore(hub_db_path(settings.memory_home))

    def _current_user(request: Request) -> dict | None:
        if not settings.login_enabled:
            return None
        return sessions.verify(request.cookies.get(SESSION_COOKIE), settings.session_secret)

    def _dashboard_data(user: dict | None) -> str:
        history = CostHistory(costs_db_path(settings.memory_home))
        try:
            rows = history.rows()
        finally:
            history.close()
        memory = all_repo_stats(settings.memory_home)
        if settings.login_enabled and user:
            store = _store()
            try:
                repos = store.repos_for_user(user["uid"])
            finally:
                store.close()
            rows = [r for r in rows if r.repo in repos]
            memory = [m for m in memory if m["repo"] in repos]
        return render_dashboard(
            rows, summarize(rows), memory=memory, user=user,
            live=settings.login_enabled,
        )

    # --- pages ---

    @app.get("/healthz")
    def healthz() -> dict:
        return {"ok": True}

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> Response:
        if settings.login_enabled and not _current_user(request):
            return HTMLResponse(render_landing())
        return RedirectResponse("/dashboard")

    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard(request: Request) -> Response:
        user = _current_user(request)
        if settings.login_enabled and not user:
            return RedirectResponse("/")
        if not settings.login_enabled:
            # Local single-user mode keeps the unified Phase 5 dashboard.
            return HTMLResponse(_dashboard_data(user))

        store = _store()
        try:
            repos = sorted(store.repos_for_user(user["uid"]))
        finally:
            store.close()
        history = CostHistory(costs_db_path(settings.memory_home))
        try:
            rows = [r for r in history.rows() if r.command == "review"]
        finally:
            history.close()
        decisions = {m["repo"]: m["decisions"] for m in all_repo_stats(settings.memory_home)}
        cards = []
        for repo in repos:
            mine = [r for r in rows if r.repo == repo]
            cards.append({
                "repo": repo,
                "reviews": len(mine),
                "last_ts": mine[0].ts if mine else 0,
                "last_risk": mine[0].max_risk if mine else 0,
                "decisions": decisions.get(repo, 0),
            })
        cards.sort(key=lambda c: -c["last_ts"])
        return HTMLResponse(render_home(cards, user))

    @app.get("/overview", response_class=HTMLResponse)
    def overview(request: Request) -> Response:
        user = _current_user(request)
        if settings.login_enabled and not user:
            return RedirectResponse("/")
        return HTMLResponse(_dashboard_data(user))

    @app.get("/repo/{owner}/{name}", response_class=HTMLResponse)
    def repo_page(owner: str, name: str, request: Request) -> Response:
        user = _current_user(request)
        if settings.login_enabled and not user:
            return RedirectResponse("/")
        repo = f"{owner}/{name}"

        token = settings.github_token
        if settings.login_enabled:
            store = _store()
            try:
                if repo not in store.repos_for_user(user["uid"]):
                    return JSONResponse({"error": "unknown repo"}, status_code=404)
                installation_id = store.installation_for_repo(repo)
            finally:
                store.close()
            if inst_tokens and installation_id:
                try:
                    token = inst_tokens.token(installation_id)
                except Exception:
                    log.exception("installation token mint failed for %s", repo)

        prs: list[dict] | None = None
        issues: list[dict] | None = None
        fetch_error = None
        try:
            gh = GitHubClient(token)
            prs = gh.list_open_prs(owner, name)
            issues = gh.list_open_issues(owner, name)
        except Exception as e:
            fetch_error = str(e)[:200]
            log.warning("live fetch failed for %s: %s", repo, e)

        history = CostHistory(costs_db_path(settings.memory_home))
        try:
            reviews = [r for r in history.rows() if r.command == "review" and r.repo == repo]
        finally:
            history.close()
        mem = next((m for m in all_repo_stats(settings.memory_home) if m["repo"] == repo), None)
        return HTMLResponse(
            render_repo_page(repo, prs, issues, reviews, mem, user, fetch_error)
        )

    @app.get("/api/latest")
    def api_latest(request: Request) -> Response:
        if settings.login_enabled and not _current_user(request):
            return JSONResponse({"error": "not signed in"}, status_code=401)
        history = CostHistory(costs_db_path(settings.memory_home))
        try:
            rows = history.rows(limit=1)
        finally:
            history.close()
        return JSONResponse({"ts": rows[0].ts if rows else 0})

    # --- login ---

    @app.get("/login")
    def login() -> Response:
        if not settings.login_enabled:
            return JSONResponse({"error": "login not configured"}, status_code=404)
        state = sessions.sign({"n": pysecrets.token_hex(8)}, settings.session_secret)
        url = oauth.login_url(
            settings.github_client_id, f"{settings.base_url}/auth/callback", state
        )
        return RedirectResponse(url)

    @app.get("/auth/callback")
    def auth_callback(code: str = "", state: str = "") -> Response:
        if not settings.login_enabled:
            return JSONResponse({"error": "login not configured"}, status_code=404)
        if not code or not sessions.verify(state, settings.session_secret, max_age_s=600):
            return JSONResponse({"error": "bad state"}, status_code=400)
        try:
            token = oauth.exchange_code(
                settings.github_client_id, settings.github_client_secret, code
            )
            user = oauth.fetch_user(token)
            installations = oauth.fetch_user_installations(token)
            store = _store()
            try:
                store.upsert_user(user)
                for inst in installations:
                    store.record_installation(
                        inst["installation_id"], inst["account_login"]
                    )
                    store.set_repos(
                        inst["installation_id"],
                        oauth.fetch_installation_repos(token, inst["installation_id"]),
                    )
                store.link_user(
                    user["github_id"], [i["installation_id"] for i in installations]
                )
            finally:
                store.close()
        except Exception:
            log.exception("OAuth callback failed")
            return JSONResponse({"error": "login failed"}, status_code=502)

        resp = RedirectResponse("/dashboard")
        resp.set_cookie(
            SESSION_COOKIE,
            sessions.sign(
                {"uid": user["github_id"], "login": user["login"],
                 "avatar": user["avatar_url"]},
                settings.session_secret,
            ),
            max_age=sessions.MAX_AGE_S, httponly=True, samesite="lax",
            secure=settings.base_url.startswith("https"),
        )
        return resp

    @app.get("/logout")
    def logout() -> Response:
        resp = RedirectResponse("/")
        resp.delete_cookie(SESSION_COOKIE)
        return resp

    # --- webhook ---

    def _handle_installation_event(event: str, body: dict) -> dict:
        inst = body.get("installation") or {}
        iid = inst.get("id")
        if not iid:
            return {"ok": True, "skipped": "no installation id"}
        store = _store()
        try:
            if event == "installation":
                action = body.get("action", "")
                if action == "deleted":
                    store.remove_installation(iid)
                    return {"ok": True, "installation": "removed"}
                store.record_installation(
                    iid, (inst.get("account") or {}).get("login", "")
                )
                store.set_repos(
                    iid, [r["full_name"] for r in body.get("repositories", [])]
                )
                return {"ok": True, "installation": "recorded"}
            # installation_repositories: repos added/removed to an existing install
            store.record_installation(iid, (inst.get("account") or {}).get("login", ""))
            store.add_repos(
                iid, [r["full_name"] for r in body.get("repositories_added", [])]
            )
            store.remove_repos(
                iid, [r["full_name"] for r in body.get("repositories_removed", [])]
            )
            return {"ok": True, "installation": "repos updated"}
        finally:
            store.close()

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
        if event in {"installation", "installation_repositories"}:
            return JSONResponse(_handle_installation_event(event, await request.json()))
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

        # Hub mode: run this review with the sender installation's own token.
        review_settings = settings
        installation_id = (body.get("installation") or {}).get("id")
        if inst_tokens and installation_id:
            try:
                review_settings = settings.model_copy(
                    update={"github_token": inst_tokens.token(installation_id)}
                )
            except Exception:
                log.exception("installation token mint failed for %s", installation_id)

        background.add_task(_run_review, pr_url, review_settings)
        return JSONResponse({"ok": True, "queued": pr_url}, status_code=202)

    return app

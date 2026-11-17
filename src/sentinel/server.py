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
import threading
import time

from fastapi import BackgroundTasks, FastAPI, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from sentinel.ask.answer import answer_question
from sentinel.ask.index import RepoIndex, index_db_path
from sentinel.config import Settings, load_settings
from sentinel.costs import CostHistory, summarize
from sentinel.db import location as db_location
from sentinel.feedback import FeedbackStore, reaction_counts, summarize_feedback
from sentinel.github.client import GitHubClient
from sentinel.hub import oauth, sessions
from sentinel.hub.appauth import InstallationTokens, load_private_key
from sentinel.hub.store import HubStore
from sentinel.llm import SentinelLLMError
from sentinel.memory import snapshots
from sentinel.memory.store import MemoryStore, all_repo_stats, db_path_for
from sentinel.models import ReviewReport
from sentinel.pipeline import load_pr, open_memory_if_exists, review_pr
from sentinel.report.dashboard import render_dashboard, render_landing
from sentinel.report.pages import render_home, render_repo_page
from sentinel.report.render import to_markdown
from sentinel.review.inline import build_inline_comments, parse_marker

log = logging.getLogger("sentinel.server")

# PR actions that trigger a (re-)review. "synchronize" = new commits pushed.
REVIEW_ACTIONS = {"opened", "reopened", "synchronize", "ready_for_review"}
SESSION_COOKIE = "sentinel_session"
MAX_QUESTION_CHARS = 600
FEEDBACK_SYNC_S = 300  # re-read 👍/👎 reactions for a repo at most every 5 min
INDEX_TTL_S = 6 * 3600  # re-snapshot the repo at most every 6h unless asked
MEMORY_BUTTON_PRS = 30  # merged PRs mined per "Build memory" click (free-tier friendly)
_index_locks: dict[str, threading.Lock] = {}

# On-demand jobs started from the UI, keyed "review:<repo>#<n>" / "memory:<repo>".
# In-process only: a restart forgets running jobs, never their results.
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()
_feedback_synced: dict[str, float] = {}


def _start_job(key: str, fn) -> bool:
    """Run fn(job) in a daemon thread unless that job is already running."""
    with _jobs_lock:
        if _jobs.get(key, {}).get("state") == "running":
            return False
        job = {"state": "running", "msg": "starting…", "started": time.time()}
        _jobs[key] = job

    def run() -> None:
        try:
            fn(job)
            if job["state"] == "running":
                job["state"] = "done"
        except Exception as e:
            log.exception("job %s failed", key)
            job.update(state="error", msg=str(e)[:200])

    threading.Thread(target=run, name=key, daemon=True).start()
    return True


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
        history = CostHistory(db_location(settings, "costs.db"))
        try:
            history.record_report(report)
        finally:
            history.close()
    except Exception:
        log.exception("recording run failed for %s", pr_url)

    if settings.post_comments:
        gh = GitHubClient(settings.github_token)
        inline_note = ""
        if settings.inline_comments and pr.head_sha:
            try:
                posted = _post_inline(gh, pr, report, files, settings)
                if posted:
                    inline_note = (
                        f"\n\n_{posted} finding{'s' if posted != 1 else ''} posted "
                        "inline on the changed lines. React 👍 or 👎 on them so "
                        "Sentinel learns which findings are useful._\n"
                    )
            except Exception:
                log.exception("posting inline comments failed for %s", pr_url)
        try:
            url = gh.upsert_pr_comment(
                pr.owner, pr.repo, pr.number, to_markdown(report) + inline_note
            )
            log.info("review comment posted: %s", url)
        except Exception:
            log.exception("posting comment failed for %s", pr_url)
    return report


def _sync_pr_feedback(
    gh: GitHubClient, store: FeedbackStore, repo: str, number: int
) -> set:
    """Read the PR's Sentinel inline comments from GitHub: store their 👍/👎
    counts (re-adopting any the store lost) and return what they cover - each
    finding key and each (path, line), since a re-review may word a finding
    differently."""
    owner, name = repo.split("/", 1)
    ours = []
    for c in gh.list_pr_review_comments(owner, name, number):
        key = parse_marker(c.get("body") or "")
        if key and not c.get("in_reply_to_id"):
            ours.append((key, c))
    store.record_posted(repo, number, [
        {"id": c["id"], "html_url": c.get("html_url"), "path": c.get("path", ""),
         "line": c.get("line") or c.get("original_line"), "key": key,
         "severity": _severity_from_body(c.get("body") or ""),
         "title": _title_from_body(c.get("body") or "")}
        for key, c in ours
    ])
    store.update_reactions(reaction_counts([c for _, c in ours]))
    covered: set = {key for key, _ in ours}
    covered |= {(c.get("path"), c.get("line") or c.get("original_line")) for _, c in ours}
    return covered


def _severity_from_body(body: str) -> str:
    head = body.split("\n", 1)[0].upper()
    return next((s.lower() for s in ("HIGH", "MEDIUM", "LOW") if f"**{s} ·" in head), "low")


def _title_from_body(body: str) -> str:
    head = body.split("\n", 1)[0]
    return head.split("·", 1)[-1].strip(" *") if "·" in head else head[:120]


def _post_inline(gh: GitHubClient, pr, report: ReviewReport, files, settings: Settings) -> int:
    """Post findings not already on the PR as inline comments; returns how many
    Sentinel inline comments the PR has afterwards."""
    repo = f"{pr.owner}/{pr.repo}"
    hunks = {h.hunk_id: h for f in files for h in f.hunks}
    store = FeedbackStore(db_location(settings, "costs.db"))
    try:
        existing = _sync_pr_feedback(gh, store, repo, pr.number)
        fresh = [
            c for c in build_inline_comments(report, hunks)
            if c["key"] not in existing and (c["path"], c["line"]) not in existing
        ]
        already = sum(1 for k in existing if isinstance(k, str))
        if not fresh:
            return already
        created = gh.post_inline_review(pr.owner, pr.repo, pr.number, pr.head_sha, fresh)
        by_key = {c["key"]: c for c in fresh}
        rows = []
        for c in created:
            key = parse_marker(c.get("body") or "")
            if key in by_key:
                rows.append({**by_key[key], "id": c["id"], "html_url": c.get("html_url"),
                             "line": c.get("line") or by_key[key]["line"]})
        store.record_posted(repo, pr.number, rows)
        log.info("posted %d inline comments on %s#%d", len(rows), repo, pr.number)
        return already + len(rows)
    finally:
        store.close()


def _sync_repo_feedback(repo: str, settings: Settings) -> None:
    """Refresh 👍/👎 counts for every PR Sentinel commented on. Never raises."""
    try:
        gh = GitHubClient(settings.github_token)
        store = FeedbackStore(db_location(settings, "costs.db"))
        try:
            for number in store.prs_for_repo(repo):
                _sync_pr_feedback(gh, store, repo, number)
        finally:
            store.close()
    except Exception:
        log.exception("feedback sync failed for %s", repo)


def _build_memory_job(repo: str, settings: Settings, job: dict) -> None:
    """Mine the repo's recent merged PRs into decision memory (idempotent per PR)."""
    from sentinel.llm import LLMClient
    from sentinel.memory.harvest import build_memory

    llm = LLMClient(settings=settings)
    store = MemoryStore(db_path_for(settings.memory_home, repo))
    try:
        result = build_memory(
            repo, store, settings, llm, limit=MEMORY_BUTTON_PRS,
            on_progress=lambda msg: job.update(msg=msg),
        )
    finally:
        store.close()
        try:  # partial progress is still worth keeping
            snapshots.save(settings, repo)
        except Exception:
            log.exception("saving decision memory snapshot failed for %s", repo)

    history = CostHistory(db_location(settings, "costs.db"))
    try:
        history.record_harvest(repo, result["cost_usd"], [
            {"model": c.model, "calls": c.calls, "in": c.input_tokens,
             "out": c.output_tokens, "cache_read": c.cache_read_tokens, "usd": c.cost_usd}
            for c in llm.ledger.cost_lines()
        ])
    finally:
        history.close()
    job["msg"] = (
        f"{result['new_decisions']} new decisions from "
        f"{result['prs_processed']} PRs ({result['prs_seen']} merged PRs checked)"
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    app = FastAPI(title="sentinel", docs_url=None, redoc_url=None)

    private_key = load_private_key(settings)
    inst_tokens = (
        InstallationTokens(settings.github_app_id, private_key)
        if settings.github_app_id and private_key
        else None
    )

    try:
        snapshots.restore_all(settings)
    except Exception:
        log.exception("restoring decision memories failed")

    def _store() -> HubStore:
        return HubStore(db_location(settings, "hub.db"))

    def _current_user(request: Request) -> dict | None:
        if not settings.login_enabled:
            return None
        return sessions.verify(request.cookies.get(SESSION_COOKIE), settings.session_secret)

    def _user_repos(user: dict) -> set[str]:
        """The user's installed repos - resynced from GitHub if the local
        tenant store is empty (ephemeral disks lose it on redeploy)."""
        store = _store()
        try:
            repos = store.repos_for_user(user["uid"])
            if repos or not inst_tokens:
                return repos
            try:
                for inst in inst_tokens.list_installations():
                    iid = inst["installation_id"]
                    store.record_installation(iid, inst["account_login"])
                    store.set_repos(
                        iid, GitHubClient(inst_tokens.token(iid)).list_installation_repos()
                    )
                    if inst["account_login"].lower() == user.get("login", "").lower():
                        store.link_user(user["uid"], [iid])
            except Exception:
                log.exception("installation resync failed")
            return store.repos_for_user(user["uid"])
        finally:
            store.close()

    def _feedback_rows(repos: set[str]) -> list[dict]:
        store = FeedbackStore(db_location(settings, "costs.db"))
        try:
            return store.rows(repos)
        finally:
            store.close()

    def _dashboard_data(user: dict | None) -> str:
        history = CostHistory(db_location(settings, "costs.db"))
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

        repos = sorted(_user_repos(user))
        history = CostHistory(db_location(settings, "costs.db"))
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
        mine = [r for r in rows if r.repo in set(repos)]
        latest_per_pr: dict[tuple, object] = {}
        for r in mine:  # rows are newest first
            latest_per_pr.setdefault((r.repo, r.pr_number), r)
        stats = {
            "reviews": len(mine),
            "high": sum(
                1 for r in latest_per_pr.values()
                for f in (r.findings or []) if f.get("severity") == "high"
            ),
            "cost": sum(r.cost_usd for r in mine),
        }
        attention = [r for r in latest_per_pr.values() if r.max_risk >= 7]
        open_findings = [f for r in latest_per_pr.values() for f in (r.findings or [])]
        return HTMLResponse(
            render_home(
                cards, user, stats, attention, activity=mine, open_findings=open_findings,
                feedback=summarize_feedback(_feedback_rows(set(repos))),
            )
        )

    @app.get("/overview", response_class=HTMLResponse)
    def overview(request: Request) -> Response:
        user = _current_user(request)
        if settings.login_enabled and not user:
            return RedirectResponse("/")
        return HTMLResponse(_dashboard_data(user))

    def _repo_access(user: dict | None, repo: str) -> tuple[bool, str | None]:
        """(allowed, GitHub token to read it with). Hub mode: the user must have
        the repo through an installation; reads use that installation's token."""
        token = settings.github_token
        if not settings.login_enabled:
            return True, token
        if repo not in _user_repos(user):
            return False, None
        store = _store()
        try:
            installation_id = store.installation_for_repo(repo)
        finally:
            store.close()
        if inst_tokens and installation_id:
            try:
                token = inst_tokens.token(installation_id)
            except Exception:
                log.exception("installation token mint failed for %s", repo)
        return True, token

    @app.get("/repo/{owner}/{name}", response_class=HTMLResponse)
    def repo_page(owner: str, name: str, request: Request) -> Response:
        user = _current_user(request)
        if settings.login_enabled and not user:
            return RedirectResponse("/")
        repo = f"{owner}/{name}"
        allowed, token = _repo_access(user, repo)
        if not allowed:
            return JSONResponse({"error": "unknown repo"}, status_code=404)

        prs: list[dict] | None = None
        issues: list[dict] | None = None
        fetch_error = None
        gh = GitHubClient(token)
        try:
            prs = gh.list_open_prs(owner, name)
        except Exception as e:
            fetch_error = str(e)[:200]
            log.warning("live PR fetch failed for %s: %s", repo, e)
        try:
            issues = gh.list_open_issues(owner, name)
        except Exception as e:
            # Most common cause: the GitHub App was not granted Issues read.
            if "not accessible" in str(e).lower():
                issues = None
            else:
                fetch_error = fetch_error or str(e)[:200]
            log.warning("live issue fetch failed for %s: %s", repo, e)

        history = CostHistory(db_location(settings, "costs.db"))
        try:
            mine = [r for r in history.rows() if r.repo == repo]
        finally:
            history.close()
        reviews = [r for r in mine if r.command == "review"]
        mem = next((m for m in all_repo_stats(settings.memory_home) if m["repo"] == repo), None)
        if time.time() - _feedback_synced.get(repo, 0) > FEEDBACK_SYNC_S:
            _feedback_synced[repo] = time.time()
            threading.Thread(
                target=_sync_repo_feedback, args=(repo, _job_settings(token)),
                name=f"feedback:{repo}", daemon=True,
            ).start()
        return HTMLResponse(
            render_repo_page(
                repo, prs, issues, reviews, mem, user, fetch_error,
                latest_ts=mine[0].ts if mine else 0.0,
                feedback=_feedback_rows({repo}),
            )
        )

    # --- on-demand actions (repo page buttons) ---

    def _job_settings(token: str | None) -> Settings:
        return settings.model_copy(update={"github_token": token}) if token else settings

    @app.post("/api/repo/{owner}/{name}/review")
    async def review_now(owner: str, name: str, request: Request) -> Response:
        user = _current_user(request)
        if settings.login_enabled and not user:
            return JSONResponse({"error": "not signed in"}, status_code=401)
        try:
            number = int((await request.json()).get("number", 0))
        except (ValueError, TypeError, AttributeError):
            number = 0
        if number <= 0:
            return JSONResponse({"error": "bad PR number"}, status_code=400)
        repo = f"{owner}/{name}"
        allowed, token = await run_in_threadpool(_repo_access, user, repo)
        if not allowed:
            return JSONResponse({"error": "unknown repo"}, status_code=404)
        job_settings = _job_settings(token)
        pr_url = f"https://github.com/{repo}/pull/{number}"

        def work(job: dict) -> None:
            job["msg"] = "reviewing…"
            if _run_review(pr_url, job_settings) is None:
                job.update(state="error", msg="review failed - see server logs")

        started = _start_job(f"review:{repo}#{number}", work)
        return JSONResponse({"ok": True, "started": started}, status_code=202)

    @app.post("/api/repo/{owner}/{name}/memory")
    async def build_memory_now(owner: str, name: str, request: Request) -> Response:
        user = _current_user(request)
        if settings.login_enabled and not user:
            return JSONResponse({"error": "not signed in"}, status_code=401)
        repo = f"{owner}/{name}"
        allowed, token = await run_in_threadpool(_repo_access, user, repo)
        if not allowed:
            return JSONResponse({"error": "unknown repo"}, status_code=404)
        job_settings = _job_settings(token)
        started = _start_job(
            f"memory:{repo}", lambda job: _build_memory_job(repo, job_settings, job)
        )
        return JSONResponse({"ok": True, "started": started}, status_code=202)

    @app.get("/api/repo/{owner}/{name}/status")
    def repo_status(owner: str, name: str, request: Request) -> Response:
        user = _current_user(request)
        if settings.login_enabled and not user:
            return JSONResponse({"error": "not signed in"}, status_code=401)
        repo = f"{owner}/{name}"
        if settings.login_enabled and repo not in _user_repos(user):
            return JSONResponse({"error": "unknown repo"}, status_code=404)
        history = CostHistory(db_location(settings, "costs.db"))
        try:
            latest = next((r.ts for r in history.rows() if r.repo == repo), 0.0)
        finally:
            history.close()
        prefix = f"review:{repo}#"
        with _jobs_lock:
            reviews = {
                k.removeprefix(prefix): dict(v) for k, v in _jobs.items()
                if k.startswith(prefix)
            }
            memory = dict(_jobs[f"memory:{repo}"]) if f"memory:{repo}" in _jobs else None
        return JSONResponse({"latest_ts": latest, "reviews": reviews, "memory": memory})

    @app.post("/api/repo/{owner}/{name}/ask")
    async def ask_repo(owner: str, name: str, request: Request) -> Response:
        user = _current_user(request)
        if settings.login_enabled and not user:
            return JSONResponse({"error": "not signed in"}, status_code=401)
        try:
            body = await request.json()
        except ValueError:
            body = {}
        question = str(body.get("question", "")).strip()
        if not question:
            return JSONResponse({"error": "empty question"}, status_code=400)
        if len(question) > MAX_QUESTION_CHARS:
            return JSONResponse({"error": "question too long"}, status_code=400)
        # Index build + LLM call are blocking; keep them off the event loop.
        return await run_in_threadpool(
            _ask_blocking, user, f"{owner}/{name}", question, bool(body.get("reindex"))
        )

    def _ask_blocking(user: dict | None, repo: str, question: str, reindex: bool) -> Response:
        allowed, token = _repo_access(user, repo)
        if not allowed:
            return JSONResponse({"error": "unknown repo"}, status_code=404)

        lock = _index_locks.setdefault(repo, threading.Lock())
        with lock:  # one build per repo at a time; concurrent askers wait for it
            index = RepoIndex(index_db_path(settings.memory_home, repo))
            try:
                stale = time.time() - float(index.meta("built_ts") or 0) > INDEX_TTL_S
                if reindex or not index.built or stale:
                    owner, name = repo.split("/", 1)
                    try:
                        data = GitHubClient(token).download_tarball(owner, name)
                        stats = index.build_from_tarball(data)
                        log.info("indexed %s: %s", repo, stats)
                    except Exception as e:
                        log.exception("indexing %s failed", repo)
                        if not index.built:
                            return JSONResponse(
                                {"error": f"could not index repo: {str(e)[:200]}"},
                                status_code=502,
                            )
                memory = None
                mem_path = db_path_for(settings.memory_home, repo)
                if mem_path.exists():
                    memory = MemoryStore(mem_path)
                try:
                    result = answer_question(repo, index, question, settings, memory)
                except SentinelLLMError as e:
                    return JSONResponse({"error": str(e)[:300]}, status_code=502)
                finally:
                    if memory is not None:
                        memory.close()
                result["indexed_files"] = int(index.meta("files") or 0)
                return JSONResponse(result)
            finally:
                index.close()

    @app.get("/api/latest")
    def api_latest(request: Request) -> Response:
        if settings.login_enabled and not _current_user(request):
            return JSONResponse({"error": "not signed in"}, status_code=401)
        history = CostHistory(db_location(settings, "costs.db"))
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

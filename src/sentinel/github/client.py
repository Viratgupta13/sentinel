"""Minimal GitHub REST client: PR metadata + unified diff.

Token resolution order: explicit setting -> GITHUB_TOKEN env -> `gh auth token` -> anonymous.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess

import httpx

from sentinel.models import PRInfo

log = logging.getLogger("sentinel.github")

PR_URL_RE = re.compile(
    r"^https?://github\.com/(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+)/pull/(?P<number>\d+)"
)

API = "https://api.github.com"


class GitHubError(RuntimeError):
    pass


def parse_pr_url(url: str) -> tuple[str, str, int]:
    m = PR_URL_RE.match(url.strip())
    if not m:
        raise GitHubError(
            f"Not a GitHub PR URL: {url!r} (expected https://github.com/<owner>/<repo>/pull/<n>)"
        )
    return m["owner"], m["repo"], int(m["number"])


def resolve_token(explicit: str | None = None) -> str | None:
    if explicit:
        return explicit
    env = os.environ.get("GITHUB_TOKEN")
    if env:
        return env
    try:
        proc = subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True, timeout=5, check=False
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


class GitHubClient:
    def __init__(self, token: str | None = None) -> None:
        self.token = resolve_token(token)
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "sentinel-review",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        else:
            log.warning("No GitHub token found; using anonymous API (60 req/h rate limit).")
        self._http = httpx.Client(base_url=API, headers=headers, timeout=30.0)

    def fetch_pr(self, owner: str, repo: str, number: int) -> PRInfo:
        resp = self._http.get(f"/repos/{owner}/{repo}/pulls/{number}")
        self._raise_for_status(resp, f"PR {owner}/{repo}#{number}")
        data = resp.json()
        return PRInfo(
            owner=owner,
            repo=repo,
            number=number,
            title=data.get("title") or "",
            body=(data.get("body") or "")[:4000],
            author=(data.get("user") or {}).get("login", ""),
            base_ref=(data.get("base") or {}).get("ref", ""),
            head_ref=(data.get("head") or {}).get("ref", ""),
            url=data.get("html_url") or f"https://github.com/{owner}/{repo}/pull/{number}",
            additions=data.get("additions") or 0,
            deletions=data.get("deletions") or 0,
            changed_files=data.get("changed_files") or 0,
        )

    def fetch_diff(self, owner: str, repo: str, number: int) -> str:
        resp = self._http.get(
            f"/repos/{owner}/{repo}/pulls/{number}",
            headers={"Accept": "application/vnd.github.v3.diff"},
        )
        if resp.status_code == 406:
            raise GitHubError(
                "GitHub refused to render this diff (too large). "
                "Fetch per-file patches instead (planned: paginated /files endpoint)."
            )
        self._raise_for_status(resp, f"diff for {owner}/{repo}#{number}")
        return resp.text

    # --- Phase 5: webhook server ---

    def upsert_pr_comment(
        self, owner: str, repo: str, number: int, body: str,
        marker: str = "<!-- sentinel-review -->",
    ) -> str:
        """Post a PR comment, or update the existing Sentinel comment in place.

        The invisible marker keeps one comment per PR instead of a new one per
        push. Returns the comment's html_url. Requires a token with write access.
        """
        body = f"{marker}\n{body}"
        resp = self._http.get(
            f"/repos/{owner}/{repo}/issues/{number}/comments", params={"per_page": 100}
        )
        self._raise_for_status(resp, f"comments for {owner}/{repo}#{number}")
        for comment in resp.json():
            if marker in (comment.get("body") or ""):
                upd = self._http.patch(
                    f"/repos/{owner}/{repo}/issues/comments/{comment['id']}",
                    json={"body": body},
                )
                self._raise_for_status(upd, "updating review comment")
                return upd.json().get("html_url", "")
        new = self._http.post(
            f"/repos/{owner}/{repo}/issues/{number}/comments", json={"body": body}
        )
        self._raise_for_status(new, "posting review comment")
        return new.json().get("html_url", "")

    # --- Phase 2: history harvesting ---

    def list_merged_prs(self, owner: str, repo: str, limit: int = 200) -> list[dict]:
        """Most recently updated merged PRs (metadata dicts), newest first."""
        merged: list[dict] = []
        page = 1
        while len(merged) < limit and page <= 20:
            resp = self._http.get(
                f"/repos/{owner}/{repo}/pulls",
                params={
                    "state": "closed",
                    "sort": "updated",
                    "direction": "desc",
                    "per_page": 50,
                    "page": page,
                },
            )
            self._raise_for_status(resp, f"PR list for {owner}/{repo}")
            batch = resp.json()
            if not batch:
                break
            merged.extend(pr for pr in batch if pr.get("merged_at"))
            page += 1
        return merged[:limit]

    def search_merged_prs(self, owner: str, repo: str, query: str, limit: int = 50) -> list[dict]:
        """Search merged PRs repo-wide (not window-limited like list_merged_prs)."""
        items: list[dict] = []
        page = 1
        while len(items) < limit and page <= 5:
            resp = self._http.get(
                "/search/issues",
                params={
                    "q": f"repo:{owner}/{repo} is:pr is:merged {query}",
                    "per_page": min(limit, 100),
                    "page": page,
                    "sort": "created",
                    "order": "desc",
                },
            )
            self._raise_for_status(resp, f"PR search for {owner}/{repo}")
            batch = resp.json().get("items", [])
            if not batch:
                break
            items.extend(batch)
            page += 1
        return items[:limit]

    def fetch_pr_json(self, owner: str, repo: str, number: int) -> dict:
        """Raw PR metadata dict (includes merged_at, which PRInfo omits)."""
        resp = self._http.get(f"/repos/{owner}/{repo}/pulls/{number}")
        self._raise_for_status(resp, f"PR {owner}/{repo}#{number}")
        return resp.json()

    def fetch_pr_files(self, owner: str, repo: str, number: int, cap: int = 100) -> list[str]:
        resp = self._http.get(
            f"/repos/{owner}/{repo}/pulls/{number}/files", params={"per_page": cap}
        )
        self._raise_for_status(resp, f"files for {owner}/{repo}#{number}")
        return [f.get("filename", "") for f in resp.json() if f.get("filename")]

    def fetch_review_comments(
        self, owner: str, repo: str, number: int, cap: int = 30
    ) -> list[dict]:
        """Inline review comments: [{author, path, body}], oldest first."""
        resp = self._http.get(
            f"/repos/{owner}/{repo}/pulls/{number}/comments", params={"per_page": cap}
        )
        self._raise_for_status(resp, f"review comments for {owner}/{repo}#{number}")
        return [
            {
                "author": (c.get("user") or {}).get("login", ""),
                "path": c.get("path", ""),
                "body": (c.get("body") or "")[:500],
            }
            for c in resp.json()
        ]

    @staticmethod
    def _raise_for_status(resp: httpx.Response, what: str) -> None:
        if resp.status_code == 404:
            raise GitHubError(f"Not found: {what} (private repo without a token?)")
        if resp.status_code == 403 and "rate limit" in resp.text.lower():
            raise GitHubError("GitHub rate limit exceeded; set GITHUB_TOKEN or `gh auth login`.")
        if resp.status_code >= 400:
            raise GitHubError(f"GitHub API {resp.status_code} for {what}: {resp.text[:300]}")

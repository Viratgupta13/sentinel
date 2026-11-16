"""Phase 7: repo-centric hub pages - the signed-in product UI.

Home ("/dashboard") is a grid of the user's installed repos; each repo gets
its own page with live open PRs (risk-badged when Sentinel reviewed them),
open issues, review history, and decision-memory stats. The old unified
cost view stays at /overview.
"""

from __future__ import annotations

import html
import time

from sentinel.costs import RunRow
from sentinel.report.dashboard import (
    _CSS,
    _LIVE_SCRIPT,
    _review_card,
    _risk_badge,
    _user_chip,
)

_EXTRA_CSS = """
.crumbs { font-size:13px; margin-bottom:14px; }
.crumbs a { color:var(--ink-3); text-decoration:none; }
.crumbs a:hover { color:var(--ink); }
.repo-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(260px,1fr));
             gap:12px; }
a.repo-card { display:block; padding:16px; text-decoration:none; color:var(--ink);
              background:var(--surface); border:1px solid var(--border);
              border-radius:12px; transition:border-color .15s; }
a.repo-card:hover { border-color:var(--ink-3); }
.repo-card .rname { font-weight:650; font-size:15px; word-break:break-all; }
.repo-card .rmeta { color:var(--ink-2); font-size:12.5px; margin-top:8px;
                    display:flex; gap:10px; flex-wrap:wrap; align-items:center; }
.list { padding:2px 16px; }
.list-row { display:flex; align-items:center; gap:10px; padding:9px 0;
            font-size:13.5px; }
.list-row + .list-row { border-top:1px solid var(--grid); }
.list-row a.t { color:var(--ink); text-decoration:none; font-weight:550;
                overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.list-row a.t:hover { text-decoration:underline; }
.list-row .meta { color:var(--ink-3); font-size:12.5px; margin-left:auto;
                  flex:none; }
.pill { border:1px solid var(--border); color:var(--ink-2); border-radius:999px;
        padding:1px 9px; font-size:11.5px; flex:none; }
.note { color:var(--ink-3); font-size:12.5px; margin:6px 0 0; }
h1 a { color:inherit; text-decoration:none; }

/* --- ask the repo --- */
.ask { padding:14px 16px; }
.ask form { display:flex; gap:8px; }
.ask input { flex:1; min-width:0; font:inherit; font-size:14px; color:var(--ink);
             background:var(--plane); border:1px solid var(--border);
             border-radius:8px; padding:9px 12px; }
.ask input:focus { outline:2px solid var(--bar); outline-offset:-1px; }
.ask button { font:inherit; font-size:14px; font-weight:600; border:0;
              border-radius:8px; padding:0 16px; cursor:pointer;
              background:var(--ink); color:var(--plane); }
.ask button:disabled { opacity:.5; cursor:default; }
.ask .hint { color:var(--ink-3); font-size:12.5px; margin-top:8px; }
.ask .hint a { color:var(--ink-2); cursor:pointer; text-decoration:underline dotted; }
.qa { border-top:1px solid var(--grid); margin-top:14px; padding-top:12px; }
.qa .q { font-weight:600; font-size:14px; }
.qa .a { font-size:14px; line-height:1.6; margin-top:6px; white-space:pre-wrap; }
.qa .a code { background:var(--plane); border:1px solid var(--border);
              border-radius:4px; padding:0 4px; }
.qa .a sup a { color:var(--bar); text-decoration:none; font-weight:600; }
.qa .src { margin-top:8px; font-size:12.5px; color:var(--ink-3); }
.qa .src a { color:var(--ink-2); font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
             text-decoration:none; }
.qa .src a:hover { text-decoration:underline; }
.qa .err { color:var(--crit); font-size:13.5px; margin-top:6px; }
.thinking { color:var(--ink-3); font-size:13.5px; margin-top:6px; }
"""

_ASK_SCRIPT = """<script>
(function () {
  var form = document.getElementById("ask-form");
  var input = document.getElementById("ask-input");
  var btn = form.querySelector("button");
  var log = document.getElementById("ask-log");
  var api = form.getAttribute("data-api");
  var first = true;

  function esc(s) {
    return s.replace(/[&<>"']/g, function (c) {
      return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c];
    });
  }
  function render(text, sources) {
    var byN = {};
    (sources || []).forEach(function (s) { byN[s.n] = s; });
    return esc(text)
      .replace(/`([^`\\n]+)`/g, "<code>$1</code>")
      .replace(/\\*\\*([^*\\n]+)\\*\\*/g, "<b>$1</b>")
      .replace(/\\[(\\d+)\\]/g, function (m, n) {
        var s = byN[n];
        return s ? '<sup><a href="' + esc(s.url) + '" target="_blank" rel="noopener">[' +
          n + "]</a></sup>" : m;
      });
  }
  function ask(q, reindex) {
    var box = document.createElement("div");
    box.className = "qa";
    box.innerHTML = '<div class="q">' + esc(q) + '</div><div class="thinking">' +
      (first ? "Reading the repo (first question indexes it, ~10-30s)…" : "Thinking…") +
      "</div>";
    log.insertBefore(box, log.firstChild);
    btn.disabled = true;
    fetch(api, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({question: q, reindex: !!reindex})
    }).then(function (r) { return r.json(); }).then(function (d) {
      first = false;
      if (d.error) {
        box.innerHTML = '<div class="q">' + esc(q) + '</div><div class="err">' +
          esc(d.error) + "</div>";
        return;
      }
      var src = (d.sources || []).map(function (s) {
        return '<a href="' + esc(s.url) + '" target="_blank" rel="noopener">[' + s.n +
          "] " + esc(s.label) + "</a>";
      }).join(" · ");
      box.innerHTML = '<div class="q">' + esc(q) + '</div><div class="a">' +
        render(d.answer, d.sources) + "</div>" +
        (src ? '<div class="src">Sources: ' + src + "</div>" : "");
    }).catch(function () {
      box.innerHTML = '<div class="q">' + esc(q) + '</div><div class="err">' +
        "Request failed - the server may be waking up; try again.</div>";
    }).finally(function () { btn.disabled = false; input.focus(); });
  }
  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var q = input.value.trim();
    if (!q || btn.disabled) return;
    input.value = "";
    ask(q, false);
  });
  document.querySelectorAll("[data-q]").forEach(function (a) {
    a.addEventListener("click", function () { ask(a.getAttribute("data-q"), false); });
  });
  var re = document.getElementById("ask-reindex");
  if (re) re.addEventListener("click", function () {
    ask("Give me a short overview of this repository.", true);
  });
})();
</script>"""

_SUGGESTIONS = (
    "What does this repo do and how is it structured?",
    "How does data flow from a request to the database?",
    "Which parts are riskiest to change, and why?",
)


def _ask_panel(repo: str) -> str:
    chips = " · ".join(
        f'<a data-q="{html.escape(q)}">{html.escape(q)}</a>' for q in _SUGGESTIONS
    )
    return f"""<h2>Ask this repo</h2>
<div class="card ask">
  <form id="ask-form" data-api="/api/repo/{html.escape(repo)}/ask">
    <input id="ask-input" maxlength="600" autocomplete="off"
           placeholder="Architecture, design decisions, where something lives…">
    <button type="submit">Ask</button>
  </form>
  <div class="hint">Try: {chips} · <a id="ask-reindex">re-read latest code</a></div>
  <div id="ask-log"></div>
</div>"""


def _page(title: str, body: str, user: dict | None, live_ts: float | None = None) -> str:
    live = _LIVE_SCRIPT % live_ts if live_ts is not None else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title><style>{_CSS}{_EXTRA_CSS}</style></head>
<body>
<header>
  <div class="lead">{body_header(title)}</div>
  {_user_chip(user)}
</header>
{body}
{live}
</body></html>"""


def body_header(title: str) -> str:
    return f'<h1><a href="/dashboard">{html.escape(title)}</a></h1>'


def _when(iso: str) -> str:
    try:
        t = time.strptime(iso, "%Y-%m-%dT%H:%M:%SZ")
        return time.strftime("%b %d", t)
    except ValueError:
        return ""


def _repo_card(c: dict) -> str:
    badge = (
        _risk_badge(c["last_risk"])
        if c["reviews"]
        else '<span class="pill">no reviews yet</span>'
    )
    decisions = f'<span>{c["decisions"]} decisions</span>' if c.get("decisions") else ""
    last = (
        f'<span>last {time.strftime("%b %d", time.localtime(c["last_ts"]))}</span>'
        if c.get("last_ts")
        else ""
    )
    return (
        f'<a class="repo-card" href="/repo/{html.escape(c["repo"])}">'
        f'<div class="rname">{html.escape(c["repo"])}</div>'
        f'<div class="rmeta">{badge}'
        f'<span>{c["reviews"]} review{"s" if c["reviews"] != 1 else ""}</span>'
        f"{decisions}{last}</div></a>"
    )


def render_home(repo_cards: list[dict], user: dict | None) -> str:
    """repo_cards: [{repo, reviews, last_ts, last_risk, decisions}]"""
    cards = "".join(_repo_card(c) for c in repo_cards)
    empty = (
        '<div class="card empty">No repos yet - install the GitHub App on a '
        "repository and it will show up here.</div>"
    )
    body = f"""
<div class="sub" style="margin:-14px 0 18px">Your repositories - every PR gets an
automatic risk review. Pick a repo to see its pull requests, issues and history.</div>
<div class="repo-grid">{cards}</div>
{"" if repo_cards else empty}
<div class="note" style="margin-top:22px"><a href="/overview"
  style="color:var(--ink-3)">Usage &amp; costs &rarr;</a></div>
"""
    return _page(
        "Sentinel", body, user,
        live_ts=max((c["last_ts"] for c in repo_cards), default=0.0),
    )


def render_repo_page(
    repo: str,
    prs: list[dict] | None,
    issues: list[dict] | None,
    reviews: list[RunRow],
    mem: dict | None,
    user: dict | None,
    fetch_error: str | None = None,
) -> str:
    latest_review: dict[int, RunRow] = {}
    for r in reviews:
        if r.pr_number and r.pr_number not in latest_review:
            latest_review[r.pr_number] = r

    def _pr_row(pr: dict) -> str:
        badge = ""
        row = latest_review.get(pr["number"])
        if row is not None:
            badge = _risk_badge(row.max_risk)
        elif pr["draft"]:
            badge = '<span class="pill">draft</span>'
        else:
            badge = '<span class="pill">no review yet</span>'
        return (
            f'<div class="list-row">{badge}'
            f'<a class="t" href="{html.escape(pr["html_url"])}">#{pr["number"]} '
            f"{html.escape(pr['title'])}</a>"
            f'<span class="meta">{html.escape(pr["author"])} · '
            f'{_when(pr["updated_at"])}</span></div>'
        )

    pr_rows = "".join(_pr_row(pr) for pr in (prs or []))
    prs_block = (
        f'<div class="card list">{pr_rows}</div>'
        if pr_rows
        else '<div class="card empty">No open pull requests.</div>'
    )

    issue_rows = "".join(
        f'<div class="list-row">'
        f'<a class="t" href="{html.escape(i["html_url"])}">#{i["number"]} '
        f"{html.escape(i['title'])}</a>"
        f'<span class="meta">{html.escape(i["author"])} · {_when(i["updated_at"])}</span></div>'
        for i in (issues or [])
    )
    if issue_rows:
        issues_block = f'<div class="card list">{issue_rows}</div>'
    elif issues is None:
        issues_block = (
            '<div class="card empty">Issues not visible - grant the GitHub App '
            '"Issues: Read-only" permission to list them here.</div>'
        )
    else:
        issues_block = '<div class="card empty">No open issues.</div>'

    review_cards = "".join(_review_card(r) for r in reviews[:8]) or (
        '<div class="card empty">No reviews yet - open a pull request and '
        "Sentinel will review it automatically.</div>"
    )

    error_note = (
        f'<div class="note">Live GitHub data unavailable: {html.escape(fetch_error)}</div>'
        if fetch_error
        else ""
    )
    mem_note = ""
    if mem:
        kinds = ", ".join(f"{k} {v}" for k, v in sorted(mem["by_kind"].items()))
        mem_note = (
            f'<h2>Decision memory</h2><div class="card empty">'
            f"{mem['decisions']} decisions mined from {mem['harvested_prs']} PRs"
            f"{' · ' + html.escape(kinds) if kinds else ''}</div>"
        )

    body = f"""
<div class="crumbs"><a href="/dashboard">&larr; All repositories</a> ·
  <a href="https://github.com/{html.escape(repo)}">view on GitHub</a></div>
{error_note}
{_ask_panel(repo)}
<h2>Open pull requests</h2>
{prs_block}
<h2>Recent reviews</h2>
{review_cards}
<h2>Open issues</h2>
{issues_block}
{mem_note}
{_ASK_SCRIPT}
"""
    # No live auto-reload here: it would wipe an in-progress conversation.
    return _page(repo, body, user)

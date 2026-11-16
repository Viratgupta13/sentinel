"""Phase 7: repo-centric hub pages - the signed-in product UI.

Home ("/dashboard") is the user's repo grid with headline numbers and the
reviews that need attention; each repo page puts open PRs (with their latest
findings inline), issues, "Ask this repo" and decision memory side by side.
The unified cost view lives at /overview.
"""

from __future__ import annotations

import html
import time

from sentinel.costs import RunRow
from sentinel.report import ui
from sentinel.report.dashboard import _LIVE_SCRIPT, _review_card, _risk_badge

_EXTRA_CSS = """
/* --- home --- */
.toolbar { display:flex; gap:10px; align-items:center; margin:34px 0 10px; }
.toolbar h2 { flex:1; }
.toolbar input { width:240px; font-size:13px; padding:6px 11px; }
.repo-grid { border:1px solid var(--border); border-radius:6px; background:var(--surface); }
.repo-head, a.repo-card { display:grid; align-items:center; gap:16px;
                          grid-template-columns:minmax(0,1fr) 150px 90px 90px 80px;
                          padding:11px 18px; }
.repo-head { font-family:var(--mono); font-size:11px; letter-spacing:.07em;
             text-transform:uppercase; color:var(--ink-3); padding-top:9px;
             padding-bottom:9px; border-bottom:1px solid var(--border); }
a.repo-card { text-decoration:none; min-width:0; }
a.repo-card + a.repo-card { border-top:1px solid var(--border); }
a.repo-card:hover { background:var(--hover); }
a.repo-card:hover .rc-name b { text-decoration:underline; text-underline-offset:3px; }
.rc-name { min-width:0; display:flex; align-items:baseline; gap:8px; }
.rc-name b { font-size:14.5px; font-weight:500; overflow:hidden; text-overflow:ellipsis;
             white-space:nowrap; }
.rc-name span { color:var(--ink-3); font-size:12px; font-family:var(--mono);
                white-space:nowrap; }
.rc-col { font-family:var(--mono); font-size:12.5px; color:var(--ink-2);
          font-variant-numeric:tabular-nums; white-space:nowrap; }
.rc-col.dim { color:var(--ink-3); }
.r-right { text-align:right; }
.attn .row .t { font-size:14px; }

/* --- repo page --- */
.layout { display:grid; grid-template-columns:minmax(0,1fr) 300px; gap:28px;
          align-items:start; margin-top:30px; }
.layout > div { min-width:0; }
.layout .section:first-child { margin-top:0; }
.side { position:sticky; top:78px; }
.side .card + .card { margin-top:12px; }
.side h3 { font-family:var(--mono); font-size:11px; font-weight:600; letter-spacing:.08em;
           text-transform:uppercase; color:var(--ink-2); margin:0 0 8px; }
.side p { margin:0; color:var(--ink-2); font-size:13.5px; }
.side .actions { display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin-top:14px; }
.side .status { color:var(--ink-3); font-size:12.5px; }
.kv { display:flex; justify-content:space-between; font-size:13.5px; padding:7px 0; }
.kv + .kv { border-top:1px solid var(--border); }
.kv span:first-child { color:var(--ink-2); }
.kv b { font-family:var(--mono); font-weight:500; font-size:13px; }
.sub .findings { padding-top:0; padding-left:136px; }
.rows > .row > .risk, .rows > .row > .pill { min-width:108px; }

/* --- ask --- */
.ask { padding:16px 18px 14px; }
.ask-head { display:flex; align-items:baseline; gap:12px; margin-bottom:10px;
            flex-wrap:wrap; }
.ask-head p { margin:0; color:var(--ink-3); font-size:13px; }
.ask form { display:flex; gap:8px; }
.ask input { flex:1; font-family:var(--mono); font-size:13.5px; }
.chips { display:flex; flex-wrap:wrap; gap:4px 16px; margin-top:10px; }
.chips a { font-size:12.5px; color:var(--ink-3); cursor:pointer; text-decoration:none; }
.chips a::before { content:"→ "; }
.chips a:hover { color:var(--ink); }
.chips a.ghost::before { content:""; }
.qa { border-top:1px solid var(--border); margin-top:14px; padding-top:14px; }
.qa .q { font-weight:600; font-size:14px; }
.qa .q::before { content:"Q  "; font-family:var(--mono); color:var(--ink-3); }
.qa .a { font-size:14px; line-height:1.7; margin-top:8px; white-space:pre-wrap;
         max-width:72ch; }
.qa .a code { background:var(--surface-2); border-radius:3px; padding:0 4px; }
.qa .a sup a { color:var(--link); text-decoration:none; font-weight:600; }
.qa .src { margin-top:10px; font-size:12.5px; color:var(--ink-3); line-height:1.9; }
.qa .src a { color:var(--link); font-family:var(--mono); font-size:12px;
             text-decoration:none; }
.qa .src a:hover { text-decoration:underline; }
.qa .err { color:var(--crit); font-size:13.5px; margin-top:6px; }
.thinking { color:var(--ink-3); font-size:13.5px; margin-top:6px; font-family:var(--mono); }

.fresh { position:fixed; left:50%; bottom:20px; transform:translateX(-50%); z-index:30;
         background:var(--ink); color:var(--bg); border-radius:5px; padding:9px 16px;
         font-size:13px; box-shadow:var(--shadow-lg); }
.fresh a { color:inherit; font-weight:600; }

@media (max-width: 900px) {
  .layout { grid-template-columns:1fr; } .side { position:static; }
  .repo-head, a.repo-card { grid-template-columns:minmax(0,1fr) 130px 70px; }
  .c-dec, .c-when { display:none; }
}
@media (max-width: 760px) {
  .toolbar input { width:100%; } .toolbar { flex-wrap:wrap; }
  .sub .findings { padding-left:14px; }
  .rows > .row > .risk, .rows > .row > .pill { min-width:0; }
  .rows > .row:has(> .risk, > .pill) { flex-wrap:wrap; row-gap:6px; }
  .rows > .row:has(> .risk, > .pill) > .grow { order:3; flex-basis:100%; }
  .repo-head { display:none; }
  a.repo-card { grid-template-columns:minmax(0,1fr) auto; padding:12px 14px; }
  .c-rev { display:none; }
  .rc-name { flex-direction:column; gap:0; }
}
"""

_REPO_SCRIPT = """<script>
(function () {
  var root = document.getElementById("repo-actions");
  if (!root) return;
  var api = root.getAttribute("data-api");
  var seen = parseFloat(root.getAttribute("data-latest")) || 0;
  var memBtn = document.getElementById("mem-build");
  var memStatus = document.getElementById("mem-status");
  var memWasRunning = false;

  function post(path, body) {
    return fetch(api + path, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify(body || {})
    }).then(function (r) { return r.json(); });
  }
  function fresh() {
    var log = document.getElementById("ask-log");
    if (!log || !log.children.length) { location.reload(); return; }
    if (document.querySelector(".fresh")) return;
    var b = document.createElement("div");
    b.className = "fresh";
    b.innerHTML = 'New results for this repo · <a href="">refresh</a>';
    document.body.appendChild(b);
  }
  function poll() {
    fetch(api + "/status").then(function (r) { return r.json(); }).then(function (d) {
      if (d.error) return;
      document.querySelectorAll("[data-review]").forEach(function (btn) {
        var j = (d.reviews || {})[btn.getAttribute("data-review")];
        if (!j) return;
        btn.disabled = j.state === "running";
        btn.textContent = {running: "Reviewing…", error: "Failed - retry"}[j.state] ||
          "Reviewed ✓";
      });
      var m = d.memory;
      if (m && memBtn) {
        memBtn.disabled = m.state === "running";
        if (memStatus) memStatus.textContent =
          (m.state === "running" ? "Building… " : m.state === "error" ? "Failed: " : "Done: ") +
          (m.msg || "");
        if (memWasRunning && m.state !== "running") fresh();
        memWasRunning = m.state === "running";
      }
      if (d.latest_ts > seen) { seen = d.latest_ts; fresh(); }
    }).catch(function () {});
  }
  document.querySelectorAll("[data-review]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      btn.disabled = true; btn.textContent = "Reviewing…";
      post("/review", {number: parseInt(btn.getAttribute("data-review"), 10)})
        .then(poll).catch(function () { btn.disabled = false; btn.textContent = "Retry"; });
    });
  });
  if (memBtn) memBtn.addEventListener("click", function () {
    memBtn.disabled = true;
    if (memStatus) memStatus.textContent = "Starting… (reads up to 30 merged PRs, a few minutes)";
    memWasRunning = true;
    post("/memory").then(poll).catch(function () { memBtn.disabled = false; });
  });
  poll();
  setInterval(poll, 8000);
})();
</script>"""

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

_HOME_SCRIPT = """<script>
(function () {
  var f = document.getElementById("repo-filter");
  if (!f) return;
  f.addEventListener("input", function () {
    var q = f.value.toLowerCase().trim();
    document.querySelectorAll(".repo-card").forEach(function (c) {
      c.style.display = c.getAttribute("data-name").indexOf(q) === -1 ? "none" : "";
    });
  });
})();
</script>"""

_SUGGESTIONS = (
    "What does this repo do and how is it structured?",
    "How does data flow from a request to the database?",
    "Which parts are riskiest to change, and why?",
)


def _ask_panel(repo: str) -> str:
    chips = "".join(
        f'<a data-q="{html.escape(q)}">{html.escape(q)}</a>' for q in _SUGGESTIONS
    )
    return f"""<div class="card ask">
  <div class="ask-head"><h2>Ask this repo</h2>
    <p>Architecture, design decisions, where something lives. Answers cite exact lines.</p>
  </div>
  <form id="ask-form" data-api="/api/repo/{html.escape(repo)}/ask">
    <input id="ask-input" class="field" maxlength="600" autocomplete="off"
           placeholder="How is authentication handled?">
    <button class="btn primary" type="submit">Ask</button>
  </form>
  <div class="chips">{chips}<a id="ask-reindex" class="ghost">↻ re-read latest code</a></div>
  <div id="ask-log"></div>
</div>"""


def _page(
    title: str, body: str, user: dict | None, live_ts: float | None = None, active: str = ""
) -> str:
    live = _LIVE_SCRIPT % live_ts if live_ts is not None else ""
    return ui.shell(title, f"<style>{_EXTRA_CSS}</style>{body}", user, active, live)


def _when(iso: str) -> str:
    try:
        t = time.strptime(iso, "%Y-%m-%dT%H:%M:%SZ")
        return time.strftime("%b %d", t)
    except ValueError:
        return ""


def _split(repo: str) -> tuple[str, str]:
    owner, _, name = repo.partition("/")
    return owner, name or owner


def _repo_card(c: dict) -> str:
    owner, name = _split(c["repo"])
    risk = (
        _risk_badge(c["last_risk"])
        if c["reviews"]
        else '<span class="pill">no reviews yet</span>'
    )
    n, d = c["reviews"], c.get("decisions", 0)
    return (
        f'<a class="repo-card" href="/repo/{html.escape(c["repo"])}" '
        f'data-name="{html.escape(c["repo"].lower())}" title="{html.escape(c["repo"])}">'
        f'<span class="rc-name"><b>{html.escape(name)}</b>'
        f"<span>{html.escape(owner)}</span></span>"
        f"<span>{risk}</span>"
        f'<span class="rc-col c-rev{" dim" if not n else ""}">'
        f"{n} review{'s' if n != 1 else ''}</span>"
        f'<span class="rc-col c-dec dim">{d or "-"}</span>'
        f'<span class="rc-col c-when dim r-right">{ui.ago(c.get("last_ts", 0)) or "-"}</span>'
        f"</a>"
    )


def render_home(
    repo_cards: list[dict],
    user: dict | None,
    stats: dict | None = None,
    attention: list[RunRow] | None = None,
) -> str:
    """repo_cards: [{repo, reviews, last_ts, last_risk, decisions}];
    stats: {reviews, high, cost}; attention: recent high-risk reviews."""
    stats = stats or {}
    first = (user or {}).get("login", "")
    cards = "".join(_repo_card(c) for c in repo_cards)
    grid = (
        '<div class="repo-grid"><div class="repo-head"><span>Repository</span>'
        '<span>Last review</span><span class="c-rev">Reviews</span>'
        '<span class="c-dec">Decisions</span><span class="c-when r-right">Activity</span>'
        f"</div>{cards}</div>"
    )
    tiles = f"""<div class="stats">
  <div class="stat"><div class="k">Repositories</div><div class="v">{len(repo_cards)}</div>
    <div class="s">connected through the GitHub App</div></div>
  <div class="stat"><div class="k">PRs reviewed</div><div class="v">{stats.get("reviews", 0)}</div>
    <div class="s">automatic + on demand</div></div>
  <div class="stat hot"><div class="k">High-severity findings</div>
    <div class="v">{stats.get("high", 0)}</div><div class="s">across all reviews</div></div>
  <div class="stat"><div class="k">Spend</div><div class="v">${stats.get("cost", 0.0):.2f}</div>
    <div class="s"><a href="/overview">usage details →</a></div></div>
</div>"""

    attn = ""
    if attention:
        rows = []
        for r in attention[:5]:
            _, name = _split(r.repo)
            top = (r.findings or [{}])[0].get("title", "")
            rows.append(
                f'<div class="row">{_risk_badge(r.max_risk)}<div class="grow">'
                f'<a class="t" href="/repo/{html.escape(r.repo)}">{html.escape(name)}'
                f' <span class="num">#{r.pr_number}</span></a>'
                f'<span class="meta">{html.escape(top)}</span></div>'
                f'<span class="end meta">{ui.ago(r.ts)}</span></div>'
            )
        attn = f"""<div class="section"><div class="section-head"><h2>Needs attention</h2>
<span class="count">risk ≥ 7 · latest review per PR</span></div>
<div class="card rows attn">{"".join(rows)}</div></div>"""

    empty = (
        '<div class="card empty"><b>No repositories yet</b>Install the Sentinel GitHub App '
        "on a repository and it will show up here.</div>"
    )
    body = f"""
<div class="page-head"><div class="grow">
  <h1>Welcome back{", " + html.escape(first) if first else ""}</h1>
  <p class="lede">Every pull request on these repositories gets an automatic risk review.</p>
</div></div>
{tiles}
{attn}
<div class="toolbar"><h2>Repositories</h2>
  <input id="repo-filter" class="field" placeholder="Filter repositories…" autocomplete="off">
</div>
{grid if repo_cards else empty}
{_HOME_SCRIPT}
"""
    return _page(
        "Sentinel", body, user,
        live_ts=max((c["last_ts"] for c in repo_cards), default=0.0), active="repos",
    )


def render_repo_page(
    repo: str,
    prs: list[dict] | None,
    issues: list[dict] | None,
    reviews: list[RunRow],
    mem: dict | None,
    user: dict | None,
    fetch_error: str | None = None,
    latest_ts: float = 0.0,
) -> str:
    owner, name = _split(repo)
    latest_review: dict[int, RunRow] = {}
    for r in reviews:
        if r.pr_number and r.pr_number not in latest_review:
            latest_review[r.pr_number] = r
    open_numbers = {pr["number"] for pr in (prs or [])}

    def _pr_row(pr: dict) -> str:
        row = latest_review.get(pr["number"])
        if row is not None:
            badge = _risk_badge(row.max_risk)
        elif pr["draft"]:
            badge = '<span class="pill">draft</span>'
        else:
            badge = '<span class="pill">no review yet</span>'
        label = "Re-review" if row is not None else "Review now"
        head = (
            f'<div class="row">{badge}<div class="grow">'
            f'<a class="t" href="{html.escape(pr["html_url"])}">{html.escape(pr["title"])}</a>'
            f'<span class="meta"><span class="num">#{pr["number"]}</span> · '
            f'{html.escape(pr["author"])} · '
            f'{_when(pr["updated_at"])}</span></div>'
            f'<div class="end"><button class="btn sm" data-review="{pr["number"]}">'
            f"{label}</button></div></div>"
        )
        if row is None:
            return head
        return (
            f'{head}<div class="sub"><ul class="findings">'
            f"{ui.finding_items(row.findings or [])}</ul></div>"
        )

    pr_rows = "".join(_pr_row(pr) for pr in (prs or []))
    prs_block = (
        f'<div class="card rows">{pr_rows}</div>'
        if pr_rows
        else '<div class="card empty"><b>No open pull requests</b>'
        "Open one and Sentinel reviews it automatically.</div>"
    )

    issue_rows = "".join(
        f'<div class="row"><div class="grow">'
        f'<a class="t" href="{html.escape(i["html_url"])}">{html.escape(i["title"])}</a>'
        f'<span class="meta">#{i["number"]} · {html.escape(i["author"])} · '
        f'{_when(i["updated_at"])}</span></div></div>'
        for i in (issues or [])
    )
    if issue_rows:
        issues_block = f'<div class="card rows">{issue_rows}</div>'
    elif issues is None:
        issues_block = (
            '<div class="card empty">Issues not visible - grant the GitHub App '
            '"Issues: Read-only" permission to list them here.</div>'
        )
    else:
        issues_block = '<div class="card empty">No open issues.</div>'

    # Open PRs already show their latest findings; history keeps the rest.
    history = [
        r for r in reviews
        if r.pr_number not in open_numbers or r is not latest_review.get(r.pr_number)
    ]
    history_block = (
        f"""<div class="section"><div class="section-head"><h2>Review history</h2>
<span class="count">{len(history)}</span></div>
{"".join(_review_card(r, link=True) for r in history[:8])}</div>"""
        if history
        else ""
    )

    error_note = (
        f'<div class="alert">Live GitHub data unavailable: {html.escape(fetch_error)}</div>'
        if fetch_error
        else ""
    )

    if mem:
        kinds = ", ".join(f"{k} {v}" for k, v in sorted(mem["by_kind"].items()))
        mem_text = (
            f"<b>{mem['decisions']} decision{'s' if mem['decisions'] != 1 else ''}</b> "
            f"mined from {mem['harvested_prs']} "
            f"merged PR{'s' if mem['harvested_prs'] != 1 else ''}"
            f"{' · ' + html.escape(kinds) if kinds else ''}. Reviews cite them "
            "when a change touches the same code, and Ask uses them to explain why."
        )
        mem_label = "Update memory"
    else:
        mem_text = (
            "Not built yet. Sentinel can read this repo's merged pull requests and "
            "remember the team's design decisions and their reasons - reviews then "
            "flag changes that undo them, and Ask can answer <i>why</i> questions."
        )
        mem_label = "Build decision memory"

    top_risk = max((r.max_risk for r in latest_review.values()), default=0)
    facts = "".join(
        f'<div class="kv"><span>{k}</span><b>{v}</b></div>'
        for k, v in (
            ("Open pull requests", len(prs or [])),
            ("Reviews", len(reviews)),
            ("Highest open risk", f"{top_risk}/10" if latest_review else "-"),
            ("Last activity", ui.ago(latest_ts) or "-"),
        )
    )

    body = f"""
<div id="repo-actions" data-api="/api/repo/{html.escape(repo)}"
     data-latest="{latest_ts}"></div>
<div class="crumbs"><a href="/dashboard">repositories</a> / {html.escape(owner)}</div>
<div class="page-head"><div class="grow">
  <h1><span class="owner">{html.escape(owner)} / </span>{html.escape(name)}</h1>
  <p class="lede">Automatic risk review is on for every pull request.</p></div>
  <a class="btn" href="https://github.com/{html.escape(repo)}">{ui.GITHUB_ICON}View on GitHub</a>
</div>
{error_note}
{_ask_panel(repo)}
<div class="layout">
  <div>
    <div class="section"><div class="section-head"><h2>Open pull requests</h2>
      <span class="count">{len(prs or [])}</span></div>{prs_block}</div>
    {history_block}
    <div class="section"><div class="section-head"><h2>Open issues</h2>
      <span class="count">{len(issues or [])}</span></div>{issues_block}</div>
  </div>
  <aside class="side">
    <div class="card pad"><h3>Overview</h3>{facts}</div>
    <div class="card pad"><h3>Decision memory</h3><p>{mem_text}</p>
      <div class="actions"><button class="btn sm" id="mem-build">{mem_label}</button>
      <span class="status" id="mem-status"></span></div></div>
  </aside>
</div>
{_ASK_SCRIPT}
{_REPO_SCRIPT}
"""
    return _page(repo, body, user, active="repos")

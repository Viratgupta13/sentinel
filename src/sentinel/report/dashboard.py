"""Usage dashboard: reviews, memory, and costs on one page.

Light/dark aware, styled by the shared shell in `report.ui`. Rendered by
`sentinel costs --html` and served at /overview (and /dashboard in local mode).

Colors follow a validated data-viz palette: a single sequential blue for
magnitude (token bars), a reserved status trio for risk/severity (always
paired with an icon + label, never color alone), and ink/surface tokens that
re-step for dark mode rather than inverting.
"""

from __future__ import annotations

import html
import time

from sentinel.costs import RunRow
from sentinel.report import ui

_CSS = ui.CSS
_risk_badge = ui.risk_badge


def _review_card(r: RunRow, link: bool = False) -> str:
    target = f"{r.repo}#{r.pr_number}" if r.pr_number else r.repo
    when = time.strftime("%b %d, %H:%M", time.localtime(r.ts))
    findings = r.findings or []
    href = f"https://github.com/{r.repo}/pull/{r.pr_number}" if r.pr_number else ""
    name = (
        f'<a class="target" href="{html.escape(href)}">{html.escape(target)}</a>'
        if link and href
        else f'<span class="target">{html.escape(target)}</span>'
    )
    return f"""<div class="card review">
  <div class="review-head">{name}{_risk_badge(r.max_risk)}
    <span class="meta">{len(findings)} finding{"s" if len(findings) != 1 else ""} ·
      {r.total_hunks} hunks · {r.deep_reviewed_hunks} deep · ${r.cost_usd:.4f} · {when}</span>
  </div>
  <ul class="findings">{ui.finding_items(findings)}</ul>
</div>"""


def _memory_section(memory: list[dict]) -> str:
    if not memory:
        return ""

    def _kinds(m: dict) -> str:
        return html.escape(", ".join(f"{k} {v}" for k, v in sorted(m["by_kind"].items())))

    rows = "".join(
        f"<tr><td>{html.escape(m['repo'])}</td>"
        f'<td class="num">{m["decisions"]}</td>'
        f'<td class="num">{m["harvested_prs"]}</td>'
        f'<td class="muted">{_kinds(m)}</td></tr>'
        for m in memory
    )
    return f"""<div class="section"><div class="section-head"><h2>Decision memory</h2></div>
<div class="card tablecard">
<table><tr><th>repo</th><th class="num">decisions</th><th class="num">PRs mined</th>
<th>by kind</th></tr>{rows}</table></div></div>"""


def _user_chip(user: dict | None) -> str:
    return ui._who(user)


_LIVE_SCRIPT = """<script>
(function () {
  var latest = %f;
  setInterval(function () {
    fetch("/api/latest").then(function (r) { return r.json(); }).then(function (d) {
      if (d.ts && d.ts > latest + 0.001) location.reload();
    }).catch(function () {});
  }, 8000);
})();
</script>"""

_LANDING_CSS = """
.land { max-width:1040px; margin:0 auto; padding:0 20px; }
.land-top { display:flex; align-items:center; height:64px; }
.land-top .brand { flex:1; }
.hero { text-align:center; padding:72px 0 40px; }
.eyebrow { display:inline-flex; align-items:center; gap:8px; font-size:12.5px;
           font-weight:600; color:var(--accent); background:var(--accent-soft);
           border-radius:999px; padding:4px 12px; }
.hero h1 { font-size:clamp(32px,5.4vw,54px); letter-spacing:-.04em; line-height:1.06;
           margin:20px auto 0; max-width:780px; }
.hero h1 em { font-style:normal; background:linear-gradient(90deg,var(--accent),#c45cf2);
              -webkit-background-clip:text; background-clip:text; color:transparent; }
.hero p { color:var(--ink-2); font-size:17px; max-width:600px; margin:18px auto 0; }
.cta { margin-top:30px; display:flex; gap:12px; justify-content:center; flex-wrap:wrap; }
.cta .btn { font-size:15px; padding:11px 20px; border-radius:11px; }
.feats { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:14px;
         margin:36px 0 22px; }
.feat { padding:22px; }
.feat .ic { width:38px; height:38px; border-radius:10px; display:grid; place-items:center;
            background:var(--accent-soft); color:var(--accent); font-size:18px; }
.feat h3 { font-size:15.5px; margin:14px 0 6px; letter-spacing:-.01em; }
.feat p { margin:0; color:var(--ink-2); font-size:14px; }
.steps { display:flex; gap:10px; justify-content:center; flex-wrap:wrap; color:var(--ink-2);
         font-size:13.5px; padding-bottom:56px; }
.steps span { background:var(--surface); border:1px solid var(--border); border-radius:999px;
              padding:6px 14px; }
.steps b { color:var(--accent); margin-right:6px; }
@media (max-width:760px) { .feats { grid-template-columns:1fr; } .hero { padding-top:40px; } }
"""


def render_landing() -> str:
    """Signed-out home page."""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sentinel - PR risk review for your GitHub repos</title>{ui.FONTS}
<style>{ui.CSS}{_LANDING_CSS}</style></head>
<body>
<div class="land">
  <div class="land-top"><span class="brand">{ui.LOGO}Sentinel</span>
    <a class="btn sm" href="/login">Sign in</a></div>
  <section class="hero">
    <span class="eyebrow">AI code review · free to try</span>
    <h1>Know which pull requests can <em>hurt you</em> before you merge</h1>
    <p>Connect your GitHub account. Sentinel risk-scores every pull request,
       remembers your team's design decisions, and answers questions about any
       of your repos - with links to the exact lines.</p>
    <div class="cta"><a class="btn primary" href="/login">{ui.GITHUB_ICON}Sign in with GitHub</a>
    </div>
  </section>
  <div class="feats">
    <div class="card feat"><div class="ic">▲</div><h3>Risk-scored reviews</h3>
      <p>Cheap triage on every change, a deep review only where it matters. Findings land
      as a PR comment and on your dashboard.</p></div>
    <div class="card feat"><div class="ic">?</div><h3>Ask any repo</h3>
      <p>"How does auth work?" "Why is this built this way?" Cited answers that open the
      exact file and lines on GitHub.</p></div>
    <div class="card feat"><div class="ic">◆</div><h3>Remembers decisions</h3>
      <p>Mines merged PRs for the team's decisions and flags changes that quietly undo
      them.</p></div>
  </div>
  <div class="steps"><span><b>1</b>Sign in with GitHub</span>
    <span><b>2</b>Install the app on your repos</span>
    <span><b>3</b>Open a PR - the review appears</span></div>
</div>
</body></html>"""


def render_dashboard(
    rows: list[RunRow],
    summary: dict,
    memory: list[dict] | None = None,
    user: dict | None = None,
    live: bool = False,
) -> str:
    saved = summary["naive_usd"] - summary["total_usd"]
    pct = (saved / summary["naive_usd"] * 100) if summary["naive_usd"] > 0 else 0.0

    tiles = f"""
    <div class="stats">
      <div class="stat"><div class="k">Runs recorded</div><div class="v">{summary["runs"]}</div>
        <div class="s">reviews + memory builds</div></div>
      <div class="stat"><div class="k">Total spend</div>
        <div class="v">${summary["total_usd"]:.4f}</div><div class="s">all models</div></div>
      <div class="stat"><div class="k">Naive baseline</div>
        <div class="v">${summary["naive_usd"]:.4f}</div>
        <div class="s">strong model on everything</div></div>
      <div class="stat hero"><div class="k">Saved vs naive</div><div class="v">${saved:.4f}</div>
        <div class="s">{pct:.0f}% below baseline</div></div>
    </div>"""

    reviews = [r for r in rows if r.command == "review"][:10]
    review_cards = "".join(_review_card(r) for r in reviews) or (
        '<div class="card empty"><b>No reviews yet</b>Run <code>sentinel review</code> '
        "or open a PR on a connected repo.</div>"
    )

    by_model = summary["by_model"]
    max_tokens = max((m["in"] + m["out"] for m in by_model.values()), default=1) or 1
    bars = "".join(
        f'<div class="bar-row"><div class="bar-label">{html.escape(name)}</div>'
        f'<div class="bar-track"><div class="bar-fill" '
        f'style="width:{(m["in"] + m["out"]) / max_tokens * 100:.1f}%"></div></div>'
        f'<div class="bar-val">{m["in"] + m["out"]:,} tok · ${m["usd"]:.4f}</div></div>'
        for name, m in sorted(by_model.items(), key=lambda kv: -(kv[1]["in"] + kv[1]["out"]))
    )
    bars_block = (
        f'<div class="card bars">{bars}</div>'
        if bars
        else '<div class="card empty"><b>No model usage yet</b>'
        "Token use appears after the first review.</div>"
    )

    run_rows = "".join(
        f"<tr><td>{time.strftime('%b %d, %H:%M', time.localtime(r.ts))}</td>"
        f"<td>{html.escape(r.command)}</td>"
        f"<td>{html.escape(r.repo)}{f'#{r.pr_number}' if r.pr_number else ''}</td>"
        f'<td class="num">{r.total_hunks or ""}</td>'
        f'<td class="num">{r.deep_reviewed_hunks or ""}</td>'
        f'<td class="num">${r.cost_usd:.4f}</td>'
        f'<td class="num muted">${r.naive_cost_usd:.4f}</td></tr>'
        for r in rows[:50]
    )

    generated = time.strftime("%b %d %Y, %H:%M", time.localtime())
    body = f"""
<div class="page-head"><div class="grow"><h1>Usage &amp; costs</h1>
  <p class="lede">Tiered reviews · decision memory · cost ledger - updated {generated}</p>
</div></div>
{tiles}
<div class="section"><div class="section-head"><h2>Recent reviews</h2></div>
{review_cards}</div>
{_memory_section(memory or [])}
<div class="section"><div class="section-head"><h2>Tokens by model</h2></div>
{bars_block}</div>
<div class="section"><div class="section-head"><h2>Recent runs</h2></div>
<div class="card tablecard">
<table><tr><th>when</th><th>command</th><th>target</th><th class="num">hunks</th>
<th class="num">deep</th><th class="num">cost</th><th class="num">naive est.</th></tr>
{run_rows or '<tr><td colspan="7" class="muted">No runs yet.</td></tr>'}
</table></div></div>
<footer class="foot">Free-tier models price at $0; token columns carry the cost story.</footer>
"""
    live_js = _LIVE_SCRIPT % (rows[0].ts if rows else 0.0) if live else ""
    return ui.shell("Sentinel dashboard", body, user, active="usage", extra=live_js)

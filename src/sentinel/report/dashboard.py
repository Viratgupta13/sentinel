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
from sentinel.report import charts, ui

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
.land { max-width:1120px; margin:0 auto; padding:0 24px; }
.land-top { display:flex; align-items:center; height:60px; border-bottom:1px solid var(--border); }
.land-top .brand { flex:1; }
.land-top .theme-btn { margin-right:10px; }
.hero { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,520px); gap:56px;
        align-items:center; padding:72px 0 64px; }
.kicker { font-family:var(--mono); font-size:12px; color:var(--ink-3); letter-spacing:.06em;
          text-transform:uppercase; }
.hero h1 { font-size:clamp(34px,4.6vw,50px); letter-spacing:-.035em; line-height:1.05;
           font-weight:600; margin:16px 0 0; }
.hero p { color:var(--ink-2); font-size:16.5px; line-height:1.6; max-width:470px;
          margin:20px 0 0; }
.cta { margin-top:30px; display:flex; gap:16px; align-items:center; flex-wrap:wrap; }
.cta .btn { font-size:14.5px; padding:10px 18px; }
.cta span { color:var(--ink-3); font-size:13px; }
.sample { font-size:13.5px; overflow:hidden; }
.sample-top { display:flex; align-items:center; gap:10px; padding:10px 16px;
              border-bottom:1px solid var(--border); font-family:var(--mono);
              font-size:12px; color:var(--ink-3); }
.sample-top b { color:var(--ink); font-weight:500; }
.sample-body { padding:16px; }
.sample-body .line { display:flex; align-items:center; gap:12px; }
.sample-body .line + .line { margin-top:10px; }
.sample .findings { padding:12px 0 0; }
.sample .findings li { align-items:flex-start; }
.sample .findings li .ft { white-space:normal; }
.scan-live { margin-left:auto; }
.diff { position:relative; overflow:hidden; border-bottom:1px solid var(--border);
        background:var(--surface-2); padding:6px 0 8px; font-size:12.5px; }
.dfile { font-family:var(--mono); font-size:11.5px; color:var(--ink-3); padding:2px 14px 6px; }
.dl { display:flex; gap:10px; padding:0 14px; line-height:1.75; white-space:pre;
      border-left:2px solid transparent; }
.dl code { font-size:12px; overflow:hidden; text-overflow:ellipsis; }
.dl .ln { width:18px; text-align:right; color:var(--ink-3); font-family:var(--mono);
          font-size:11px; user-select:none; }
.dl .sg { width:8px; color:var(--ink-3); font-family:var(--mono); }
.dl.add { background:color-mix(in srgb, var(--good) 9%, transparent); }
.dl.add .sg { color:var(--good); }
.dl.del { background:color-mix(in srgb, var(--crit) 7%, transparent); color:var(--ink-3); }
.dl.del .sg { color:var(--crit); }
.dl.risk { border-left-color:var(--crit); animation:flag 4s ease-in-out infinite; }
@keyframes flag { 0%, 30% { background:color-mix(in srgb, var(--good) 9%, transparent); }
  45%, 85% { background:color-mix(in srgb, var(--crit) 16%, transparent); }
  100% { background:color-mix(in srgb, var(--good) 9%, transparent); } }
.beam { position:absolute; left:0; right:0; top:0; height:42px; pointer-events:none; z-index:1;
  background:linear-gradient(180deg, transparent,
    color-mix(in srgb, var(--good) 22%, transparent) 85%, var(--good) 100%);
  opacity:.55; animation:beam 4s cubic-bezier(.45,0,.55,1) infinite; }
@keyframes beam { 0% { transform:translateY(-44px); } 60%, 100% { transform:translateY(190px); } }
.hero > div:first-child > * { animation:rise .6s cubic-bezier(.2,.7,.2,1) both; }
.hero > div:first-child > :nth-child(2) { animation-delay:.06s; }
.hero > div:first-child > :nth-child(3) { animation-delay:.12s; }
.hero > div:first-child > :nth-child(4) { animation-delay:.18s; }
.hero .sample { animation:rise .7s .15s cubic-bezier(.2,.7,.2,1) both; }
.sample .why { margin:14px 0 0; padding:10px 12px; border-left:2px solid var(--border-strong);
               background:var(--surface-2); color:var(--ink-2); font-size:13px; }
.sample .why b { color:var(--ink); font-weight:600; }
.how { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,560px); gap:56px;
       align-items:center; padding:56px 0; border-top:1px solid var(--border); }
.how h2.big { font-family:inherit; text-transform:none; letter-spacing:-.025em;
              font-size:26px; line-height:1.15; color:var(--ink); font-weight:600;
              margin:12px 0 0; }
.how p { color:var(--ink-2); font-size:15px; margin:14px 0 0; max-width:420px; }
.feats { display:grid; grid-template-columns:repeat(3,minmax(0,1fr));
         border-top:1px solid var(--border); }
.feat { padding:28px 28px 32px 0; }
.feat + .feat { padding-left:28px; border-left:1px solid var(--border); }
.feat .n { font-family:var(--mono); font-size:12px; color:var(--ink-3); }
.feat h3 { font-size:16px; margin:10px 0 6px; font-weight:600; letter-spacing:-.01em; }
.feat p { margin:0; color:var(--ink-2); font-size:14px; }
.land-foot { border-top:1px solid var(--border); padding:20px 0 40px; color:var(--ink-3);
             font-size:12.5px; font-family:var(--mono); }
@media (max-width:860px) {
  .hero { grid-template-columns:1fr; gap:36px; padding:44px 0; }
  .how { grid-template-columns:1fr; gap:24px; padding:40px 0; }
  .feats { grid-template-columns:1fr; }
  .feat, .feat + .feat { padding:22px 0; border-left:none; }
  .feat + .feat { border-top:1px solid var(--border); }
}
@media (max-width:760px) { .land { padding:0 16px; } }
"""


def render_landing() -> str:
    """Signed-out home page."""
    diff = (
        (" ", "def charge(order, card):", ""),
        ("-", "    return gateway.capture(order.total, card)", ""),
        ("+", "    for attempt in range(3):", "risk"),
        ("+", "        try:", ""),
        ("+", "            return gateway.capture(order.total, card)", "risk"),
        ("+", "        except Timeout:", "risk"),
        ("+", "            time.sleep(2 ** attempt)", ""),
    )
    code = "".join(
        f'<div class="dl {"add" if sign == "+" else "del" if sign == "-" else ""} {flag}">'
        f'<span class="ln">{i + 41}</span><span class="sg">{sign}</span>'
        f"<code>{html.escape(text)}</code></div>"
        for i, (sign, text, flag) in enumerate(diff)
    )
    sample = f"""<div class="card sample" aria-label="Example Sentinel review">
  <div class="sample-top"><b>acme/payments</b> #482 · Retry failed charges automatically
    <span class="live scan-live"><i></i>SCANNING</span></div>
  <div class="diff"><div class="beam"></div>
    <div class="dfile">billing/charge.py</div>{code}</div>
  <div class="sample-body">
    <div class="line">{ui.risk_badge(9)}<span class="muted">2 of 14 hunks needed a deep
      review</span></div>
    <ul class="findings">
      <li><span class="sev high">HIGH</span><span class="ft">Retry loop can charge a
        card twice if the provider times out after capture</span></li>
      <li><span class="sev medium">MED</span><span class="ft">Idempotency key is built from
        the timestamp, not the order id</span></li>
    </ul>
    <div class="why"><b>Undoes a past decision.</b> PR #311 removed charge retries after
      the March double-billing incident.</div>
  </div>
</div>"""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sentinel - PR risk review for your GitHub repos</title>{ui.THEME_HEAD}{ui.FONTS}
<style>{ui.CSS}{charts.CSS}{_LANDING_CSS}</style></head>
<body>
<div class="land">
  <div class="land-top"><span class="brand">{ui.LOGO}Sentinel</span>
    {ui.THEME_BUTTON}<a class="btn sm" href="/login">Sign in</a></div>
  <section class="hero">
    <div>
      <div class="kicker">Pull request risk review</div>
      <h1>Know which pull requests can hurt you before you merge.</h1>
      <p>Sentinel scores every pull request on your GitHub repos, remembers why your
         team made past decisions, and tells you when a change quietly undoes one.</p>
      <div class="cta"><a class="btn primary" href="/login">{ui.GITHUB_ICON}Sign in with
        GitHub</a><span>Free · installs as a GitHub App</span></div>
    </div>
    {sample}
  </section>
  <section class="how">
    <div><div class="kicker">How a review works</div>
      <h2 class="big">Only risky code gets the expensive review.</h2>
      <p>A fast model scores every changed hunk. Only the few that look dangerous go to
         the strong model, so reviews stay quick and cheap without skipping what
         matters.</p></div>
    {charts.funnel(14, 3, 2, title="Example: PR #482")}
  </section>
  <div class="feats">
    <div class="feat"><div class="n">01</div><h3>Risk-scored reviews</h3>
      <p>A cheap pass over every change, and a deep review only where it matters. The
      result lands as a PR comment and on your dashboard.</p></div>
    <div class="feat"><div class="n">02</div><h3>Ask any repo</h3>
      <p>"How does auth work?" "Why is this built this way?" Answers link to the exact
      file and lines on GitHub.</p></div>
    <div class="feat"><div class="n">03</div><h3>Remembers decisions</h3>
      <p>Reads merged PRs for the team's decisions and their reasons, then flags changes
      that go against them.</p></div>
  </div>
  <div class="land-foot">Sign in with GitHub → install the app on your repos → open a PR</div>
</div>
{charts.TIP_SCRIPT}
{ui.THEME_SCRIPT}
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

    all_reviews = [r for r in rows if r.command == "review"]
    hunk_funnel = charts.funnel(
        sum(r.total_hunks for r in all_reviews),
        sum(r.skipped_hunks for r in all_reviews),
        sum(r.deep_reviewed_hunks for r in all_reviews),
    )
    reviews = all_reviews[:10]
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
<div class="section">{hunk_funnel}</div>
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
    body = f"<style>{charts.CSS}</style>{body}"
    return ui.shell(
        "Sentinel dashboard", body, user, active="usage", extra=live_js + charts.TIP_SCRIPT
    )

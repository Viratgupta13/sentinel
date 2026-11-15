"""Self-contained HTML dashboard: reviews, memory, and costs on one page.

No external assets, light/dark aware. Rendered by `sentinel costs --html`
and served live by the Phase 5 webhook server at GET /dashboard.

Colors follow a validated data-viz palette: a single sequential blue for
magnitude (token bars), a reserved status trio for risk/severity (always
paired with an icon + label, never color alone), and ink/surface tokens that
re-step for dark mode rather than inverting.
"""

from __future__ import annotations

import html
import time

from sentinel.costs import RunRow

_CSS = """
:root {
  color-scheme: light;
  --plane:#f9f9f7; --surface:#fcfcfb; --border:#e1e0d9; --grid:#e1e0d9;
  --ink:#0b0b0b; --ink-2:#52514e; --ink-3:#898781;
  --bar:#2a78d6; --bar-track:#cde2fb;
  --good:#0ca30c; --warn:#fab219; --crit:#d03b3b;
  --accent:#0a7d4f;
}
@media (prefers-color-scheme: dark) {
  :root {
    color-scheme: dark;
    --plane:#0d0d0d; --surface:#1a1a19; --border:#2c2c2a; --grid:#2c2c2a;
    --ink:#f0efec; --ink-2:#c3c2b7; --ink-3:#898781;
    --bar:#3987e5; --bar-track:#0d366b;
    --accent:#3ecf8e;
  }
}
* { box-sizing:border-box; }
body { background:var(--plane); color:var(--ink);
       font:15px/1.5 -apple-system,'Segoe UI',system-ui,sans-serif;
       margin:0; padding:32px 16px 48px; max-width:960px; margin-inline:auto; }
header { margin-bottom:24px; display:flex; align-items:center; gap:12px; }
header .lead { flex:1; }
h1 { font-size:21px; font-weight:650; margin:0; letter-spacing:-0.01em; }
.userchip { display:flex; align-items:center; gap:8px; font-size:13px;
            color:var(--ink-2); }
.userchip img { width:26px; height:26px; border-radius:50%;
                border:1px solid var(--border); }
.userchip a { color:var(--ink-3); text-decoration:none; }
.userchip a:hover { color:var(--ink); }
.sub { color:var(--ink-2); font-size:13.5px; margin-top:2px; }
h2 { font-size:13px; font-weight:600; color:var(--ink-2); margin:32px 0 10px;
     text-transform:uppercase; letter-spacing:0.06em; }
.card { background:var(--surface); border:1px solid var(--border);
        border-radius:12px; }

/* --- stat tiles --- */
.tiles { display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr));
         gap:12px; }
.tile { background:var(--surface); border:1px solid var(--border);
        border-radius:12px; padding:14px 16px; }
.tile span { display:block; color:var(--ink-2); font-size:12.5px; }
.tile b { display:block; font-size:26px; font-weight:600; margin-top:2px;
          letter-spacing:-0.01em; }
.tile.hero b { color:var(--accent); }
.tile small { color:var(--ink-3); font-size:12px; }

/* --- review cards --- */
.review { background:var(--surface); border:1px solid var(--border);
          border-radius:12px; padding:14px 16px; margin:10px 0; }
.review-head { display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
.review-head .target { font-weight:600; font-size:14.5px; }
.review-head .meta { color:var(--ink-3); font-size:12.5px; margin-left:auto; }
.badge { border-radius:999px; padding:2px 10px; font-size:12px; font-weight:600;
         color:#fff; display:inline-flex; align-items:center; gap:5px; }
.badge.crit { background:var(--crit); }
.badge.warn { background:var(--warn); color:#0b0b0b; }
.badge.good { background:var(--good); }
.findings { margin:10px 0 0; padding:0; list-style:none; }
.findings li { font-size:13.5px; padding:5px 0; display:flex; gap:8px;
               align-items:baseline; border-top:1px solid var(--grid); }
.dot { width:8px; height:8px; border-radius:50%; flex:none;
       position:relative; top:-1px; align-self:center; }
.dot.high { background:var(--crit); } .dot.medium { background:var(--warn); }
.dot.low { background:var(--bar); }
.findings .sev { font-weight:600; font-size:11.5px; color:var(--ink-2);
                 letter-spacing:0.04em; flex:none; }
.findings .file { color:var(--ink-3); font-size:12.5px;
                  font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }
.findings li.ok { color:var(--ink-2); border-top:1px solid var(--grid); }
.findings li.more { color:var(--ink-3); font-size:12.5px; }

/* --- token bars (meter spec: track = lighter step of the same ramp) --- */
.bars { padding:6px 16px; }
.bar-row { display:flex; align-items:center; gap:12px; padding:8px 0; }
.bar-row + .bar-row { border-top:1px solid var(--grid); }
.bar-label { width:230px; font-size:13px; overflow:hidden; text-overflow:ellipsis;
             white-space:nowrap;
             font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }
.bar-track { flex:1; background:var(--bar-track); border-radius:4px; height:10px; }
.bar-fill { background:var(--bar); height:100%; border-radius:4px; min-width:2px; }
.bar-val { width:150px; font-size:12.5px; color:var(--ink-2); text-align:right;
           font-variant-numeric:tabular-nums; }

/* --- tables --- */
.tablecard { padding:4px 16px 8px; overflow-x:auto; }
table { border-collapse:collapse; width:100%; font-size:13.5px; }
th, td { text-align:left; padding:7px 8px; border-bottom:1px solid var(--grid); }
tr:last-child td { border-bottom:none; }
th { color:var(--ink-3); font-weight:600; font-size:12px;
     text-transform:uppercase; letter-spacing:0.05em; }
.tablecard td:first-child { white-space:nowrap; }
td.num, th.num { text-align:right; font-variant-numeric:tabular-nums; }
.muted { color:var(--ink-3); }
.empty { color:var(--ink-2); font-size:13.5px; padding:14px 16px; }
footer { color:var(--ink-3); font-size:12.5px; margin-top:28px; }
code { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:12.5px; }
"""

_SEV_LABEL = {"high": "HIGH", "medium": "MED", "low": "LOW"}


def _risk_badge(risk: int) -> str:
    cls, icon = ("crit", "▲") if risk >= 7 else ("warn", "◆") if risk >= 4 else ("good", "✓")
    return f'<span class="badge {cls}">{icon} risk {risk}/10</span>'


def _review_card(r: RunRow) -> str:
    target = f"{r.repo}#{r.pr_number}" if r.pr_number else r.repo
    when = time.strftime("%b %d, %H:%M", time.localtime(r.ts))
    findings = r.findings or []
    items = "".join(
        f'<li><span class="dot {html.escape(f["severity"])}"></span>'
        f'<span class="sev">{_SEV_LABEL.get(f["severity"], "?")}</span>'
        f"<span>{html.escape(f['title'])}</span>"
        f'<span class="file">{html.escape(f.get("file", ""))}</span></li>'
        for f in findings[:3]
    )
    if len(findings) > 3:
        items += f'<li class="more">… and {len(findings) - 3} more</li>'
    if not findings:
        items = '<li class="ok">No blocking findings ✓</li>'
    return f"""<div class="review">
  <div class="review-head"><span class="target">{html.escape(target)}</span>
    {_risk_badge(r.max_risk)}
    <span class="meta">{len(findings)} finding{"s" if len(findings) != 1 else ""} ·
      {r.total_hunks} hunks · {r.deep_reviewed_hunks} deep · ${r.cost_usd:.4f} · {when}</span>
  </div>
  <ul class="findings">{items}</ul>
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
    return f"""<h2>Decision memory</h2>
<div class="card tablecard">
<table><tr><th>repo</th><th class="num">decisions</th><th class="num">PRs mined</th>
<th>by kind</th></tr>{rows}</table></div>"""


def _user_chip(user: dict | None) -> str:
    if not user:
        return ""
    avatar = (
        f'<img src="{html.escape(user.get("avatar", ""))}" alt="">'
        if user.get("avatar")
        else ""
    )
    return (
        f'<div class="userchip">{avatar}<span>{html.escape(user.get("login", ""))}</span>'
        f'<a href="/logout">sign out</a></div>'
    )


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


def render_landing() -> str:
    """Signed-out home page: one card, one button."""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sentinel</title><style>{_CSS}
.hero-card {{ max-width:420px; margin:12vh auto 0; text-align:center;
             padding:40px 32px; }}
.hero-card p {{ color:var(--ink-2); font-size:14.5px; }}
.signin {{ display:inline-block; margin-top:16px; background:var(--ink);
          color:var(--plane); border-radius:8px; padding:10px 20px;
          font-weight:600; font-size:14.5px; text-decoration:none; }}
</style></head>
<body>
<div class="card hero-card">
  <h1>Sentinel</h1>
  <p>Context-aware PR risk review. Install the GitHub App on your repos and
     every pull request gets an automatic risk-scored review - findings on the
     PR, history on your dashboard.</p>
  <a class="signin" href="/login">Sign in with GitHub</a>
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
    <div class="tiles">
      <div class="tile"><span>Runs recorded</span><b>{summary["runs"]}</b></div>
      <div class="tile"><span>Total spend</span><b>${summary["total_usd"]:.4f}</b></div>
      <div class="tile"><span>Naive baseline</span><b>${summary["naive_usd"]:.4f}</b>
        <small>strong model on everything</small></div>
      <div class="tile hero"><span>Saved vs naive</span><b>${saved:.4f}</b>
        <small>{pct:.0f}% below baseline</small></div>
    </div>"""

    reviews = [r for r in rows if r.command == "review"][:10]
    review_cards = "".join(_review_card(r) for r in reviews) or (
        '<div class="card empty">No reviews yet - run <code>sentinel review</code> '
        "or point a webhook at <code>sentinel serve</code>.</div>"
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
        else '<div class="card empty">No model usage recorded yet.</div>'
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
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sentinel dashboard</title><style>{_CSS}</style></head>
<body>
<header>
  <div class="lead">
    <h1>Sentinel dashboard</h1>
    <div class="sub">Tiered PR reviews · decision memory · cost ledger — {generated}</div>
  </div>
  {_user_chip(user)}
</header>
{tiles}
<h2>Recent reviews</h2>
{review_cards}
{_memory_section(memory or [])}
<h2>Tokens by model</h2>
{bars_block}
<h2>Recent runs</h2>
<div class="card tablecard">
<table><tr><th>when</th><th>command</th><th>target</th><th class="num">hunks</th>
<th class="num">deep</th><th class="num">cost</th><th class="num">naive est.</th></tr>
{run_rows or '<tr><td colspan="7" class="muted">No runs yet.</td></tr>'}
</table></div>
<footer>Free-tier models price at $0; token columns carry the cost story.</footer>
{_LIVE_SCRIPT % (rows[0].ts if rows else 0.0) if live else ""}
</body></html>"""

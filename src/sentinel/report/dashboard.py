"""Self-contained HTML dashboard: reviews, memory, and costs on one page.

No external assets, light/dark aware. Rendered by `sentinel costs --html`
and served live by the Phase 5 webhook server at GET /dashboard.
"""

from __future__ import annotations

import html
import time

from sentinel.costs import RunRow

_CSS = """
:root { --bg:#fff; --fg:#1a1a1a; --muted:#667; --card:#f4f5f7; --bar:#4f7cff;
        --accent:#0a7d4f; --hi:#c0392b; --med:#b26a00; --low:#3a6ea5; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#14161a; --fg:#e8eaed; --muted:#9aa; --card:#1e2127; --bar:#6b93ff;
          --accent:#3ecf8e; --hi:#ff6b5e; --med:#f0a848; --low:#7fb3ff; } }
body { background:var(--bg); color:var(--fg);
       font:15px/1.5 -apple-system,'Segoe UI',sans-serif; margin:0; padding:24px 16px;
       max-width:880px; margin-inline:auto; }
h1 { font-size:22px; } h2 { font-size:16px; margin-top:28px; }
.tiles { display:flex; gap:12px; flex-wrap:wrap; }
.tile { background:var(--card); border-radius:10px; padding:14px 18px; flex:1 1 150px; }
.tile b { display:block; font-size:22px; }
.tile span { color:var(--muted); font-size:13px; }
.savings b { color:var(--accent); }
.review { background:var(--card); border-radius:10px; padding:12px 16px; margin:10px 0; }
.review-head { display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
.review-head a { color:var(--fg); font-weight:600; text-decoration:none; }
.badge { border-radius:6px; padding:1px 9px; font-size:12.5px; font-weight:600;
         color:#fff; }
.badge.hi { background:var(--hi); } .badge.med { background:var(--med); }
.badge.low { background:var(--accent); }
.chip { font-size:12px; color:var(--muted); }
.finding { font-size:13.5px; margin:4px 0 0 2px; }
.finding .sev { font-weight:600; }
.sev.high { color:var(--hi); } .sev.medium { color:var(--med); }
.sev.low { color:var(--low); }
.bar-row { display:flex; align-items:center; gap:10px; margin:6px 0; }
.bar-label { width:220px; font-size:13px; overflow:hidden; text-overflow:ellipsis;
             white-space:nowrap; }
.bar-track { flex:1; background:var(--card); border-radius:6px; height:18px; }
.bar-fill { background:var(--bar); height:100%; border-radius:6px; min-width:2px; }
.bar-val { width:120px; font-size:12.5px; color:var(--muted); text-align:right; }
table { border-collapse:collapse; width:100%; font-size:13.5px; }
th, td { text-align:left; padding:6px 8px; border-bottom:1px solid var(--card); }
th { color:var(--muted); font-weight:600; }
td.num, th.num { text-align:right; font-variant-numeric:tabular-nums; }
.muted { color:var(--muted); }
"""


def _risk_badge(risk: int) -> str:
    cls = "hi" if risk >= 7 else "med" if risk >= 4 else "low"
    return f'<span class="badge {cls}">risk {risk}/10</span>'


def _review_card(r: RunRow) -> str:
    target = f"{r.repo}#{r.pr_number}" if r.pr_number else r.repo
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(r.ts))
    findings = r.findings or []
    shown = "".join(
        f'<div class="finding"><span class="sev {html.escape(f["severity"])}">'
        f"{html.escape(f['severity'].upper())}</span> {html.escape(f['title'])} "
        f'<span class="chip">{html.escape(f.get("file", ""))}</span></div>'
        for f in findings[:3]
    )
    more = len(findings) - 3
    if more > 0:
        shown += f'<div class="finding muted">… and {more} more</div>'
    if not findings:
        shown = '<div class="finding muted">No blocking findings ✅</div>'
    return f"""<div class="review">
  <div class="review-head"><a>{html.escape(target)}</a> {_risk_badge(r.max_risk)}
    <span class="chip">{len(findings)} finding{"s" if len(findings) != 1 else ""}</span>
    <span class="chip">{r.total_hunks} hunks · {r.deep_reviewed_hunks} deep</span>
    <span class="chip">${r.cost_usd:.4f}</span>
    <span class="chip">{when}</span></div>
  {shown}
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
<table><tr><th>repo</th><th class="num">decisions</th><th class="num">PRs mined</th>
<th>by kind</th></tr>{rows}</table>"""


def render_dashboard(
    rows: list[RunRow], summary: dict, memory: list[dict] | None = None
) -> str:
    saved = summary["naive_usd"] - summary["total_usd"]
    pct = (saved / summary["naive_usd"] * 100) if summary["naive_usd"] > 0 else 0.0

    tiles = f"""
    <div class="tiles">
      <div class="tile"><b>{summary["runs"]}</b><span>runs recorded</span></div>
      <div class="tile"><b>${summary["total_usd"]:.4f}</b><span>total spend</span></div>
      <div class="tile"><b>${summary["naive_usd"]:.4f}</b>
        <span>naive strong-model-everything estimate</span></div>
      <div class="tile savings"><b>${saved:.4f} ({pct:.0f}%)</b>
        <span>saved vs naive</span></div>
    </div>"""

    reviews = [r for r in rows if r.command == "review"][:10]
    review_cards = "".join(_review_card(r) for r in reviews) or (
        '<p class="muted">No reviews yet - run <code>sentinel review</code> '
        "or point a webhook at <code>sentinel serve</code>.</p>"
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

    run_rows = "".join(
        f"<tr><td>{time.strftime('%Y-%m-%d %H:%M', time.localtime(r.ts))}</td>"
        f"<td>{html.escape(r.command)}</td>"
        f"<td>{html.escape(r.repo)}{f'#{r.pr_number}' if r.pr_number else ''}</td>"
        f'<td class="num">{r.total_hunks or ""}</td>'
        f'<td class="num">{r.deep_reviewed_hunks or ""}</td>'
        f'<td class="num">${r.cost_usd:.4f}</td>'
        f'<td class="num muted">${r.naive_cost_usd:.4f}</td></tr>'
        for r in rows[:50]
    )

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sentinel</title><style>{_CSS}</style></head>
<body>
<h1>Sentinel dashboard</h1>
{tiles}
<h2>Recent reviews</h2>
{review_cards}
{_memory_section(memory or [])}
<h2>Tokens by model</h2>
{bars or '<p class="muted">No model usage recorded yet.</p>'}
<h2>Recent runs</h2>
<table><tr><th>when</th><th>command</th><th>target</th><th class="num">hunks</th>
<th class="num">deep</th><th class="num">cost</th><th class="num">naive est.</th></tr>
{run_rows or '<tr><td colspan="7" class="muted">No runs yet.</td></tr>'}
</table>
<p class="muted">Free-tier models price at $0; token columns carry the cost story.</p>
</body></html>"""

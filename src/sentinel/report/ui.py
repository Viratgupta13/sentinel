"""Shared look for every Sentinel page: design tokens, app shell, small parts.

Light and dark are each designed (not inverted). Status colors are reserved
for risk/severity and always travel with an icon + text label. Pages degrade
to system fonts when the Inter webfont can't load (offline `--html` exports).
"""

from __future__ import annotations

import html
import time

FONTS = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
    'family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap">'
)

CSS = """
:root {
  color-scheme: light;
  --bg:#f6f6f8; --surface:#ffffff; --surface-2:#f1f1f4; --hover:#f7f7f9;
  --border:#e3e3e8; --border-strong:#d0d0d8;
  --ink:#121217; --ink-2:#4b4b57; --ink-3:#868693;
  --accent:#5546f0; --accent-2:#7a6ff7; --accent-ink:#ffffff; --accent-soft:#efedff;
  --crit:#c4321f; --crit-soft:#fdeeec; --crit-line:#f6c9c3;
  --warn:#a35a00; --warn-soft:#fff4e0; --warn-line:#f8d9a6;
  --good:#127a43; --good-soft:#e8f6ee; --good-line:#bfe5cf;
  --bar:#2a78d6; --bar-track:#d7e7fb;
  --shadow:0 1px 2px rgba(18,18,23,.04), 0 1px 3px rgba(18,18,23,.06);
  --shadow-lg:0 10px 30px rgba(18,18,23,.10);
  --mono:'JetBrains Mono',ui-monospace,SFMono-Regular,Menlo,monospace;
}
@media (prefers-color-scheme: dark) {
  :root {
    color-scheme: dark;
    --bg:#0c0c10; --surface:#15151b; --surface-2:#1c1c24; --hover:#1a1a21;
    --border:#25252e; --border-strong:#34343f;
    --ink:#ececf1; --ink-2:#b0b0bd; --ink-3:#7c7c8a;
    --accent:#8a7fff; --accent-2:#a49cff; --accent-ink:#0c0c10; --accent-soft:#1e1a3d;
    --crit:#ff7b6b; --crit-soft:#331512; --crit-line:#5c231d;
    --warn:#ffb547; --warn-soft:#30220b; --warn-line:#5a3f12;
    --good:#4fd18b; --good-soft:#0e2a1b; --good-line:#1c4d33;
    --bar:#3987e5; --bar-track:#12305a;
    --shadow:0 1px 2px rgba(0,0,0,.4);
    --shadow-lg:0 10px 30px rgba(0,0,0,.5);
  }
}
* { box-sizing:border-box; }
html { -webkit-text-size-adjust:100%; }
body { margin:0; background:var(--bg); color:var(--ink);
       font:14.5px/1.55 Inter,-apple-system,'Segoe UI',system-ui,sans-serif;
       -webkit-font-smoothing:antialiased; font-feature-settings:'cv11','ss01'; }
a { color:inherit; }
code, .mono { font-family:var(--mono); font-size:.86em; }
.wrap { max-width:1140px; margin:0 auto; padding:0 20px; }

/* --- top bar --- */
.topbar { position:sticky; top:0; z-index:20; border-bottom:1px solid var(--border);
          background:color-mix(in srgb, var(--bg) 82%, transparent);
          backdrop-filter:saturate(1.4) blur(12px); -webkit-backdrop-filter:blur(12px); }
.topbar .wrap { display:flex; align-items:center; gap:28px; height:58px; }
.brand { display:flex; align-items:center; gap:9px; text-decoration:none;
         font-weight:700; font-size:16px; letter-spacing:-.02em; }
.brand svg { width:26px; height:26px; flex:none; }
.nav { display:flex; gap:4px; flex:1; }
.nav a { text-decoration:none; color:var(--ink-2); font-weight:500; font-size:13.5px;
         padding:6px 11px; border-radius:7px; }
.nav a:hover { color:var(--ink); background:var(--surface-2); }
.nav a.on { color:var(--ink); background:var(--surface-2); }
.who { display:flex; align-items:center; gap:10px; font-size:13px; color:var(--ink-2); }
.who img { width:28px; height:28px; border-radius:50%; border:1px solid var(--border); }
.who a { color:var(--ink-3); text-decoration:none; white-space:nowrap; }
.who a:hover { color:var(--ink); }
main.wrap { padding-top:30px; padding-bottom:64px; }

/* --- page header --- */
.crumbs { font-size:13px; color:var(--ink-3); margin-bottom:10px; }
.crumbs a { color:var(--ink-3); text-decoration:none; }
.crumbs a:hover { color:var(--ink); }
.page-head { display:flex; align-items:flex-end; gap:16px; flex-wrap:wrap;
             margin-bottom:24px; }
.page-head .grow { flex:1; min-width:240px; }
h1 { font-size:26px; line-height:1.2; font-weight:700; letter-spacing:-.025em; margin:0; }
h1 .owner { color:var(--ink-3); font-weight:500; }
.lede { color:var(--ink-2); margin:6px 0 0; font-size:14.5px; }
h2 { font-size:15px; font-weight:650; letter-spacing:-.01em; margin:0; }
.section { margin-top:28px; }
.section-head { display:flex; align-items:baseline; gap:10px; margin-bottom:12px; }
.section-head .count { color:var(--ink-3); font-size:13px; }
.section-head .right { margin-left:auto; font-size:13px; }
.section-head .right a { color:var(--ink-3); text-decoration:none; }
.section-head .right a:hover { color:var(--ink); }

/* --- surfaces --- */
.card { background:var(--surface); border:1px solid var(--border); border-radius:14px;
        box-shadow:var(--shadow); }
.pad { padding:18px 20px; }
.empty { color:var(--ink-2); font-size:14px; padding:26px 20px; text-align:center; }
.empty b { display:block; color:var(--ink); font-weight:600; margin-bottom:4px; }
.muted { color:var(--ink-3); }
.note { color:var(--ink-3); font-size:13px; margin:8px 0 0; }
.alert { border:1px solid var(--warn-line); background:var(--warn-soft); color:var(--warn);
         border-radius:10px; padding:10px 14px; font-size:13.5px; margin-bottom:18px; }

/* --- buttons --- */
.btn { display:inline-flex; align-items:center; gap:7px; font:inherit; font-size:13.5px;
       font-weight:600; border-radius:9px; padding:8px 14px; cursor:pointer;
       text-decoration:none; border:1px solid var(--border-strong);
       background:var(--surface); color:var(--ink); white-space:nowrap;
       transition:background .12s, border-color .12s; }
.btn:hover { background:var(--hover); border-color:var(--ink-3); }
.btn.primary { background:var(--accent); border-color:var(--accent); color:var(--accent-ink); }
.btn.primary:hover { background:var(--accent-2); border-color:var(--accent-2); }
.btn.sm { font-size:12.5px; padding:5px 11px; border-radius:8px; }
.btn:disabled { opacity:.55; cursor:default; }
.btn svg { width:16px; height:16px; }
input.field { font:inherit; font-size:14px; color:var(--ink); background:var(--surface);
              border:1px solid var(--border-strong); border-radius:10px; padding:9px 13px;
              min-width:0; }
input.field:focus { outline:none; border-color:var(--accent);
                    box-shadow:0 0 0 3px var(--accent-soft); }

/* --- stat tiles --- */
.stats { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; }
.stat { background:var(--surface); border:1px solid var(--border); border-radius:14px;
        padding:16px 18px; box-shadow:var(--shadow); }
.stat .k { color:var(--ink-2); font-size:13px; font-weight:500; }
.stat .v { font-size:28px; font-weight:700; letter-spacing:-.03em; margin-top:4px;
           font-variant-numeric:tabular-nums; line-height:1.15; }
.stat .s { color:var(--ink-3); font-size:12.5px; margin-top:2px; }
.stat.hot .v { color:var(--crit); }
.stat.hero .v { color:var(--good); }

/* --- status: badges, pills, severity --- */
.badge { display:inline-flex; align-items:center; gap:5px; border-radius:999px;
         padding:2px 9px; font-size:12px; font-weight:600; white-space:nowrap;
         border:1px solid; flex:none; }
.badge.crit { color:var(--crit); background:var(--crit-soft); border-color:var(--crit-line); }
.badge.warn { color:var(--warn); background:var(--warn-soft); border-color:var(--warn-line); }
.badge.good { color:var(--good); background:var(--good-soft); border-color:var(--good-line); }
.pill { display:inline-flex; align-items:center; border:1px solid var(--border);
        color:var(--ink-3); background:var(--surface-2); border-radius:999px;
        padding:1px 9px; font-size:12px; font-weight:500; white-space:nowrap; flex:none; }
.sev { font-size:10.5px; font-weight:700; letter-spacing:.05em; border-radius:5px;
       padding:1px 6px; flex:none; border:1px solid; }
.sev.high { color:var(--crit); background:var(--crit-soft); border-color:var(--crit-line); }
.sev.medium { color:var(--warn); background:var(--warn-soft); border-color:var(--warn-line); }
.sev.low { color:var(--ink-2); background:var(--surface-2); border-color:var(--border); }

/* --- rows --- */
.rows > .row { display:flex; align-items:center; gap:12px; padding:13px 20px; }
.rows > .row + .row, .rows > .sub + .row { border-top:1px solid var(--border); }
.rows > .row:has(+ .sub) { padding-bottom:8px; }
.row .t { font-weight:600; text-decoration:none; overflow:hidden; text-overflow:ellipsis;
          white-space:nowrap; min-width:0; }
a.t:hover { color:var(--accent); }
.row .meta { color:var(--ink-3); font-size:12.5px; white-space:nowrap; }
.row .grow { flex:1; min-width:0; display:flex; flex-direction:column; gap:2px; }
.row .grow .meta { overflow:hidden; text-overflow:ellipsis; }
.row .end { margin-left:auto; display:flex; align-items:center; gap:10px; flex:none; }
.findings { list-style:none; margin:0; padding:0 20px 14px 20px; }
.findings li { display:flex; align-items:center; gap:9px; font-size:13.5px; padding:4px 0;
               min-width:0; }
.findings li .ft { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.findings li .file { color:var(--ink-3); font-family:var(--mono); font-size:12px;
                     margin-left:auto; flex:none; }
.findings li.ok { color:var(--good); }
.findings li.more { color:var(--ink-3); font-size:12.5px; }

/* --- review cards (history, overview) --- */
.review { padding:0; margin:0 0 12px; }
.review-head { display:flex; align-items:center; gap:10px; flex-wrap:wrap; padding:14px 20px; }
.review-head .target { font-weight:650; text-decoration:none; }
.review-head .meta { color:var(--ink-3); font-size:12.5px; margin-left:auto; }

/* --- token bars (overview) --- */
.bars { padding:8px 20px; }
.bar-row { display:flex; align-items:center; gap:12px; padding:9px 0; }
.bar-row + .bar-row { border-top:1px solid var(--border); }
.bar-label { width:230px; font-size:12.5px; overflow:hidden; text-overflow:ellipsis;
             white-space:nowrap; font-family:var(--mono); }
.bar-track { flex:1; background:var(--bar-track); border-radius:4px; height:10px; }
.bar-fill { background:var(--bar); height:100%; border-radius:4px; min-width:2px; }
.bar-val { width:160px; font-size:12.5px; color:var(--ink-2); text-align:right;
           font-variant-numeric:tabular-nums; }

/* --- tables --- */
.tablecard { padding:6px 20px 10px; overflow-x:auto; }
table { border-collapse:collapse; width:100%; font-size:13.5px; }
th, td { text-align:left; padding:9px 8px; border-bottom:1px solid var(--border); }
tr:last-child td { border-bottom:none; }
th { color:var(--ink-3); font-weight:600; font-size:11.5px; text-transform:uppercase;
     letter-spacing:.06em; }
td.num, th.num { text-align:right; font-variant-numeric:tabular-nums; }
.tablecard td:first-child { white-space:nowrap; }

footer.foot { color:var(--ink-3); font-size:12.5px; margin-top:36px; }

@media (max-width: 760px) {
  .stats { grid-template-columns:repeat(2,minmax(0,1fr)); }
  .topbar .wrap { gap:14px; }
  .who span { display:none; }
  h1 { font-size:22px; }
  .rows > .row { padding:12px 16px; gap:10px; }
  .attn .end { display:none; }
  .rows .row a.t { white-space:normal; }
  .nav a { padding:6px 8px; }
  .findings { padding:0 16px 12px; }
  .bar-label { width:120px; } .bar-val { width:110px; }
}
"""

LOGO = (
    '<svg viewBox="0 0 32 32" aria-hidden="true"><defs><linearGradient id="lg" x1="0" '
    'y1="0" x2="1" y2="1"><stop offset="0" stop-color="#7a6ff7"/><stop offset="1" '
    'stop-color="#4b3be8"/></linearGradient></defs><path d="M16 2.5 4.5 6.8v8.4c0 7.2 '
    '4.9 12.4 11.5 14.3 6.6-1.9 11.5-7.1 11.5-14.3V6.8Z" fill="url(#lg)"/><path '
    'd="m10.6 16.2 3.7 3.7 7.2-7.6" fill="none" stroke="#fff" stroke-width="2.6" '
    'stroke-linecap="round" stroke-linejoin="round"/></svg>'
)

GITHUB_ICON = (
    '<svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="M8 0C3.58 '
    "0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49"
    "-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 "
    "1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64"
    "-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-"
    ".27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56"
    ".82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 "
    '2.2 0 .21.15.46.55.38A8.013 8.013 0 0 0 16 8c0-4.42-3.58-8-8-8Z"/></svg>'
)

SEV_LABEL = {"high": "HIGH", "medium": "MED", "low": "LOW"}


def esc(s) -> str:
    return html.escape(str(s))


def risk_badge(risk: int) -> str:
    cls, icon = ("crit", "▲") if risk >= 7 else ("warn", "◆") if risk >= 4 else ("good", "✓")
    return f'<span class="badge {cls}">{icon} risk {risk}/10</span>'


def ago(ts: float, now: float | None = None) -> str:
    if not ts:
        return ""
    d = max(0, (now or time.time()) - ts)
    if d < 60:
        return "just now"
    if d < 3600:
        return f"{int(d // 60)}m ago"
    if d < 86400:
        return f"{int(d // 3600)}h ago"
    if d < 7 * 86400:
        return f"{int(d // 86400)}d ago"
    return time.strftime("%b %d", time.localtime(ts))


def finding_items(findings: list[dict], limit: int = 3) -> str:
    items = "".join(
        f'<li><span class="sev {esc(f["severity"])}">'
        f'{SEV_LABEL.get(f["severity"], "?")}</span>'
        f'<span class="ft">{esc(f["title"])}</span>'
        f'<span class="file">{esc(f.get("file", ""))}</span></li>'
        for f in findings[:limit]
    )
    if len(findings) > limit:
        items += f'<li class="more">+ {len(findings) - limit} more</li>'
    return items or '<li class="ok">✓ No blocking findings</li>'


def _who(user: dict | None) -> str:
    if not user:
        return ""
    avatar = f'<img src="{esc(user["avatar"])}" alt="">' if user.get("avatar") else ""
    return (
        f'<div class="who">{avatar}<span>{esc(user.get("login", ""))}</span>'
        f'<a href="/logout">sign out</a></div>'
    )


def shell(
    title: str, body: str, user: dict | None = None, active: str = "", extra: str = ""
) -> str:
    """Full HTML document: top bar + main column. `active`: repos | usage."""
    def link(href: str, label: str, key: str) -> str:
        on = ' class="on"' if key == active else ""
        return f'<a href="{href}"{on}>{label}</a>'

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>{FONTS}<style>{CSS}</style></head>
<body>
<nav class="topbar"><div class="wrap">
  <a class="brand" href="/dashboard">{LOGO}Sentinel</a>
  <div class="nav">{link("/dashboard", "Repositories", "repos")}
    {link("/overview", "Usage", "usage")}</div>
  {_who(user)}
</div></nav>
<main class="wrap">
{body}
</main>
{extra}
</body></html>"""

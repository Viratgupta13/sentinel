"""Shared look for every Sentinel page: design tokens, app shell, small parts.

Light and dark are each designed (not inverted). Status colors are reserved
for risk/severity and always travel with an icon + text label. Pages degrade
to system fonts when the IBM Plex webfont can't load (offline `--html` exports).
"""

from __future__ import annotations

import html
import time

FONTS = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
    'family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600'
    '&display=swap">'
)

_DARK = """
    color-scheme: dark;
    --bg:#111110; --surface:#181816; --surface-2:#21211e; --hover:#1d1d1a;
    --border:#2b2a26; --border-strong:#3c3b35;
    --ink:#ecebe5; --ink-2:#aeaca2; --ink-3:#7d7b72;
    --accent:#ecebe5; --accent-2:#ffffff; --accent-ink:#111110; --accent-soft:#2a2925;
    --link:#7fb0ff;
    --crit:#ff7a62; --crit-soft:#2e1712; --crit-line:#5a2a20;
    --warn:#f0b04a; --warn-soft:#2b210f; --warn-line:#54401b;
    --good:#5fcf8c; --good-soft:#132619; --good-line:#24472f;
    --tick:#34332e;
    --bar:#3987e5; --bar-track:#1b2a3d;
    --shadow-lg:0 8px 24px rgba(0,0,0,.5);
"""

CSS = """
:root {
  color-scheme: light;
  --bg:#f5f4f0; --surface:#fdfcfa; --surface-2:#efeee9; --hover:#f3f2ed;
  --border:#e0ded6; --border-strong:#c9c6bb;
  --ink:#16150f; --ink-2:#55534a; --ink-3:#8a877c;
  --accent:#16150f; --accent-2:#3a382f; --accent-ink:#fdfcfa; --accent-soft:#e9e7df;
  --link:#1f5fbf;
  --crit:#c2361f; --crit-soft:#fbebe7; --crit-line:#efc4bb;
  --warn:#9a5b00; --warn-soft:#fbf1de; --warn-line:#ecd39f;
  --good:#1d7a45; --good-soft:#e6f3ea; --good-line:#bcdcc7;
  --tick:#dcd9cf;
  --bar:#2a78d6; --bar-track:#dfe8f3;
  --shadow:none; --shadow-lg:0 8px 24px rgba(22,21,15,.12);
  --mono:'IBM Plex Mono',ui-monospace,SFMono-Regular,Menlo,monospace;
}
/*DARK*/
* { box-sizing:border-box; }
html { -webkit-text-size-adjust:100%; }
body { margin:0; background:var(--bg); color:var(--ink);
       font:14.5px/1.55 'IBM Plex Sans',-apple-system,'Segoe UI',system-ui,sans-serif;
       -webkit-font-smoothing:antialiased; }
a { color:inherit; }
code, .mono { font-family:var(--mono); font-size:.88em; }
.wrap { max-width:1120px; margin:0 auto; padding:0 24px; }

/* --- top bar --- */
.topbar { position:sticky; top:0; z-index:20; border-bottom:1px solid var(--border);
          background:var(--bg); }
.topbar .wrap { display:flex; align-items:center; gap:32px; height:54px; }
.brand { display:flex; align-items:center; gap:9px; text-decoration:none;
         font-weight:600; font-size:15px; letter-spacing:-.01em; }
.brand svg { width:22px; height:22px; flex:none; color:var(--ink); }
.nav { display:flex; gap:22px; flex:1; align-self:stretch; }
.nav a { text-decoration:none; color:var(--ink-3); font-weight:500; font-size:13.5px;
         display:flex; align-items:center; border-bottom:2px solid transparent;
         margin-bottom:-1px; }
.nav a:hover { color:var(--ink); }
.nav a.on { color:var(--ink); border-bottom-color:var(--ink); }
.who { display:flex; align-items:center; gap:10px; font-size:13px; color:var(--ink-2); }
.who img { width:24px; height:24px; border-radius:4px; }
.who span { font-family:var(--mono); font-size:12.5px; }
.who a { color:var(--ink-3); text-decoration:none; white-space:nowrap; }
.who a:hover { color:var(--ink); }
main.wrap { padding-top:34px; padding-bottom:72px; }

/* --- page header --- */
.crumbs { font-size:12.5px; color:var(--ink-3); margin-bottom:12px; font-family:var(--mono); }
.crumbs a { color:var(--ink-3); text-decoration:none; }
.crumbs a:hover { color:var(--ink); }
.page-head { display:flex; align-items:flex-end; gap:16px; flex-wrap:wrap;
             margin-bottom:26px; }
.page-head .grow { flex:1; min-width:240px; }
h1 { font-size:28px; line-height:1.15; font-weight:600; letter-spacing:-.025em; margin:0; }
h1 .owner { color:var(--ink-3); font-weight:400; }
.lede { color:var(--ink-2); margin:8px 0 0; font-size:14.5px; }
h2 { font-family:var(--mono); font-size:11.5px; font-weight:600; letter-spacing:.08em;
     text-transform:uppercase; color:var(--ink-2); margin:0; }
.section { margin-top:34px; }
.section-head { display:flex; align-items:baseline; gap:10px; margin-bottom:10px; }
.section-head .count { color:var(--ink-3); font-size:11.5px; font-family:var(--mono); }
.section-head .right { margin-left:auto; font-size:13px; }
.section-head .right a { color:var(--ink-3); text-decoration:none; }
.section-head .right a:hover { color:var(--ink); }

/* --- surfaces --- */
.card { background:var(--surface); border:1px solid var(--border); border-radius:6px; }
.pad { padding:18px 20px; }
.empty { color:var(--ink-2); font-size:14px; padding:28px 20px; text-align:left; }
.empty b { display:block; color:var(--ink); font-weight:600; margin-bottom:2px; }
.muted { color:var(--ink-3); }
.note { color:var(--ink-3); font-size:13px; margin:8px 0 0; }
.alert { border:1px solid var(--warn-line); background:var(--warn-soft); color:var(--warn);
         border-radius:6px; padding:10px 14px; font-size:13.5px; margin-bottom:18px; }

/* --- buttons --- */
.btn { display:inline-flex; align-items:center; gap:7px; font:inherit; font-size:13.5px;
       font-weight:500; border-radius:5px; padding:7px 13px; cursor:pointer;
       text-decoration:none; border:1px solid var(--border-strong);
       background:var(--surface); color:var(--ink); white-space:nowrap;
       transition:background .1s, border-color .1s; }
.btn:hover { background:var(--hover); border-color:var(--ink-3); }
.btn.primary { background:var(--accent); border-color:var(--accent); color:var(--accent-ink); }
.btn.primary:hover { background:var(--accent-2); border-color:var(--accent-2); }
.btn.sm { font-size:12.5px; padding:4px 10px; }
.btn:disabled { opacity:.5; cursor:default; }
.btn svg { width:15px; height:15px; }
input.field { font:inherit; font-size:14px; color:var(--ink); background:var(--surface);
              border:1px solid var(--border-strong); border-radius:5px; padding:8px 12px;
              min-width:0; }
input.field::placeholder { color:var(--ink-3); }
input.field:focus { outline:none; border-color:var(--ink); }

/* --- stat strip --- */
.stats { display:grid; grid-template-columns:repeat(4,minmax(0,1fr));
         border:1px solid var(--border); border-radius:6px; background:var(--surface); }
.stat { padding:16px 20px 18px; min-width:0; }
.stat + .stat { border-left:1px solid var(--border); }
.stat .k { font-family:var(--mono); color:var(--ink-3); font-size:11px; font-weight:500;
           letter-spacing:.07em; text-transform:uppercase; }
.stat .v { font-size:32px; font-weight:500; letter-spacing:-.03em; margin-top:8px;
           font-variant-numeric:tabular-nums; line-height:1; }
.stat .s { color:var(--ink-3); font-size:12.5px; margin-top:8px; }
.stat .s a { color:var(--ink-2); }
.stat.hot .v { color:var(--crit); }
.stat.hero .v { color:var(--good); }

/* --- status: risk meter, pills, severity --- */
.risk { display:inline-flex; align-items:center; gap:8px; white-space:nowrap; flex:none;
        font-family:var(--mono); font-size:12.5px; font-weight:600; color:var(--ink); }
.risk small { color:var(--ink-3); font-weight:400; font-size:11.5px; }
.meter { display:inline-flex; gap:2px; }
.meter i { width:4px; height:12px; border-radius:1px; background:var(--tick); }
.risk.crit .meter i.on { background:var(--crit); }
.risk.warn .meter i.on { background:var(--warn); }
.risk.good .meter i.on { background:var(--good); }
.risk.crit b { color:var(--crit); } .risk.warn b { color:var(--warn); }
.risk.good b { color:var(--good); }
.badge { display:inline-flex; align-items:center; gap:5px; border-radius:4px;
         padding:1px 7px; font-size:12px; font-weight:600; white-space:nowrap;
         border:1px solid; flex:none; }
.badge.crit { color:var(--crit); background:var(--crit-soft); border-color:var(--crit-line); }
.badge.warn { color:var(--warn); background:var(--warn-soft); border-color:var(--warn-line); }
.badge.good { color:var(--good); background:var(--good-soft); border-color:var(--good-line); }
.pill { display:inline-flex; align-items:center; color:var(--ink-3); white-space:nowrap;
        flex:none; font-family:var(--mono); font-size:11.5px; }
.sev { font-family:var(--mono); font-size:10.5px; font-weight:600; letter-spacing:.04em;
       border-radius:3px; padding:0 5px; flex:none; width:40px; text-align:center; }
.sev.high { color:var(--crit); background:var(--crit-soft); }
.sev.medium { color:var(--warn); background:var(--warn-soft); }
.sev.low { color:var(--ink-2); background:var(--surface-2); }

/* --- rows --- */
.rows > .row { display:flex; align-items:center; gap:14px; padding:12px 18px; }
.rows > .row + .row, .rows > .sub + .row { border-top:1px solid var(--border); }
.rows > .row:has(+ .sub) { padding-bottom:6px; }
.rows > a.row { text-decoration:none; }
.rows > a.row:hover, .rows > .row.hl:hover { background:var(--hover); }
.row .t { font-weight:500; text-decoration:none; overflow:hidden; text-overflow:ellipsis;
          white-space:nowrap; min-width:0; }
a.t:hover { text-decoration:underline; text-underline-offset:3px; }
.row .meta { color:var(--ink-3); font-size:12.5px; white-space:nowrap; }
.row .grow { flex:1; min-width:0; display:flex; flex-direction:column; gap:1px; }
.row .grow .meta { overflow:hidden; text-overflow:ellipsis; }
.row .num { font-family:var(--mono); color:var(--ink-3); font-size:12.5px; }
.row .end { margin-left:auto; display:flex; align-items:center; gap:10px; flex:none; }
.findings { list-style:none; margin:0; padding:0 18px 12px 18px; }
.findings li { display:flex; align-items:center; gap:10px; font-size:13.5px; padding:3px 0;
               min-width:0; color:var(--ink-2); }
.findings li .ft { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.findings li .file { color:var(--ink-3); font-family:var(--mono); font-size:11.5px;
                     margin-left:auto; flex:none; }
.findings li.ok { color:var(--good); }
.findings li.more { color:var(--ink-3); font-size:12.5px; padding-left:50px; }

/* --- review cards (history, overview) --- */
.review { padding:0; margin:0 0 10px; }
.review-head { display:flex; align-items:center; gap:12px; flex-wrap:wrap; padding:12px 18px; }
.review-head .target { font-weight:500; font-family:var(--mono); font-size:13.5px;
                       text-decoration:none; }
.review-head .meta { color:var(--ink-3); font-size:12px; margin-left:auto;
                     font-family:var(--mono); }

/* --- token bars (overview) --- */
.bars { padding:8px 18px; }
.bar-row { display:flex; align-items:center; gap:12px; padding:9px 0; }
.bar-row + .bar-row { border-top:1px solid var(--border); }
.bar-label { width:230px; font-size:12px; overflow:hidden; text-overflow:ellipsis;
             white-space:nowrap; font-family:var(--mono); }
.bar-track { flex:1; background:var(--bar-track); border-radius:2px; height:8px; }
.bar-fill { background:var(--bar); height:100%; border-radius:2px; min-width:2px; }
.bar-val { width:170px; font-size:12px; color:var(--ink-2); text-align:right;
           font-family:var(--mono); font-variant-numeric:tabular-nums; }

/* --- tables --- */
.tablecard { padding:4px 18px 8px; overflow-x:auto; }
table { border-collapse:collapse; width:100%; font-size:13.5px; }
th, td { text-align:left; padding:9px 8px; border-bottom:1px solid var(--border); }
tr:last-child td { border-bottom:none; }
th { color:var(--ink-3); font-family:var(--mono); font-weight:500; font-size:11px;
     text-transform:uppercase; letter-spacing:.07em; }
td.num, th.num { text-align:right; font-variant-numeric:tabular-nums; }
td.num { font-family:var(--mono); font-size:12.5px; }
.tablecard td:first-child { white-space:nowrap; }

footer.foot { color:var(--ink-3); font-size:12.5px; margin-top:40px; }


/* --- texture + motion --- */
body::before { content:""; position:absolute; inset:0 0 auto 0; height:420px; z-index:-1;
  pointer-events:none;
  background-image:radial-gradient(var(--border-strong) 1px, transparent 1.2px);
  background-size:18px 18px;
  -webkit-mask-image:linear-gradient(180deg,#000 0%,transparent 100%);
  mask-image:linear-gradient(180deg,#000 0%,transparent 100%); opacity:.55; }
body { position:relative; isolation:isolate; }
@keyframes rise { from { opacity:0; transform:translateY(8px); } to { opacity:1; transform:none; } }
@keyframes tick { from { opacity:.15; transform:scaleY(.3); } to { opacity:1; transform:none; } }
@keyframes grow { from { transform:scaleY(0); } to { transform:none; } }
@keyframes pulse { 0% { transform:scale(1); opacity:.7; }
                   100% { transform:scale(3.2); opacity:0; } }
@keyframes spin { to { transform:rotate(360deg); } }
main > .page-head, main > .stats, main > .panels, main > .section, main > .toolbar,
main > .repo-grid, main > .card, main > .layout {
  animation:rise .5s cubic-bezier(.2,.7,.2,1) both; }
main > :nth-child(2) { animation-delay:.04s; } main > :nth-child(3) { animation-delay:.08s; }
main > :nth-child(4) { animation-delay:.12s; } main > :nth-child(5) { animation-delay:.16s; }
main > :nth-child(6) { animation-delay:.2s; } main > :nth-child(n+7) { animation-delay:.24s; }
.meter i.on { animation:tick .35s ease-out both; transform-origin:bottom; }
.meter i:nth-child(2) { animation-delay:.04s; } .meter i:nth-child(3) { animation-delay:.08s; }
.meter i:nth-child(4) { animation-delay:.12s; } .meter i:nth-child(5) { animation-delay:.16s; }
.meter i:nth-child(6) { animation-delay:.2s; } .meter i:nth-child(7) { animation-delay:.24s; }
.meter i:nth-child(8) { animation-delay:.28s; } .meter i:nth-child(9) { animation-delay:.32s; }
.meter i:nth-child(10) { animation-delay:.36s; }
.live { display:inline-flex; align-items:center; gap:7px; font-family:var(--mono);
        font-size:11.5px; color:var(--good); letter-spacing:.04em; }
.live i { position:relative; width:7px; height:7px; border-radius:50%; background:var(--good); }
.live i::after { content:""; position:absolute; inset:0; border-radius:50%;
                 background:var(--good); animation:pulse 1.8s ease-out infinite; }
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation:none !important; transition:none !important; }
}

@media (max-width: 760px) {
  .wrap { padding:0 16px; }
  .stats { grid-template-columns:repeat(2,minmax(0,1fr)); }
  .stat:nth-child(3) { border-left:none; }
  .stat:nth-child(n+3) { border-top:1px solid var(--border); }
  .stat .v { font-size:26px; }
  .topbar .wrap { gap:18px; }
  .nav { gap:16px; }
  .who span { display:none; }
  h1 { font-size:23px; }
  .rows > .row { padding:12px 14px; gap:10px; }
  .attn .end { display:none; }
  .rows .row a.t { white-space:normal; }
  .findings { padding:0 14px 12px; }
  .findings li .file { display:none; }
  .bar-label { width:110px; } .bar-val { width:110px; }
}
"""
CSS = CSS.replace(
    "/*DARK*/",
    f':root[data-theme="dark"] {{{_DARK}}}\n'
    f'@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{{_DARK}}} }}',
)
CSS += """
/* --- theme toggle --- */
.theme-btn { display:grid; place-items:center; width:30px; height:30px; padding:0;
             border:1px solid var(--border); border-radius:6px; background:var(--surface);
             color:var(--ink-2); cursor:pointer; flex:none; }
.theme-btn:hover { color:var(--ink); border-color:var(--border-strong); }
.theme-btn svg { width:15px; height:15px; }
.theme-btn .sun { display:none; }
:root[data-theme="dark"] .theme-btn .sun { display:block; }
:root[data-theme="dark"] .theme-btn .moon { display:none; }
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) .theme-btn .sun { display:block; }
  :root:not([data-theme="light"]) .theme-btn .moon { display:none; }
}
"""

# Runs in <head> so a saved choice applies before first paint (no flash).
THEME_HEAD = (
    '<script>try{var t=localStorage.getItem("sentinel-theme");'
    'if(t==="dark"||t==="light")document.documentElement.setAttribute("data-theme",t)}'
    "catch(e){}</script>"
)

THEME_BUTTON = (
    '<button class="theme-btn" id="theme-toggle" type="button" '
    'aria-label="Switch dark or light mode" title="Dark / light mode">'
    '<svg class="moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z"/></svg>'
    '<svg class="sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" '
    'r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2'
    'M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg></button>'
)

THEME_SCRIPT = """<script>
(function () {
  var b = document.getElementById("theme-toggle");
  if (!b) return;
  b.addEventListener("click", function () {
    var root = document.documentElement, cur = root.getAttribute("data-theme");
    if (!cur) cur = matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    var next = cur === "dark" ? "light" : "dark";
    root.setAttribute("data-theme", next);
    try { localStorage.setItem("sentinel-theme", next); } catch (e) {}
  });
})();
</script>"""

LOGO = (
    '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="1.5" y="1.5" width="21" '
    'height="21" rx="4" fill="currentColor"/><path d="M6 15.5h2.4l2-6 3.2 9 2-5.5H18" '
    'fill="none" stroke="var(--bg)" stroke-width="1.9" stroke-linecap="round" '
    'stroke-linejoin="round"/></svg>'
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

COUNT_SCRIPT = """<script>
(function () {
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  document.querySelectorAll(".stat .v").forEach(function (el) {
    var m = el.textContent.trim().match(/^(\\$?)([0-9]+(?:\\.[0-9]+)?)$/);
    if (!m) return;
    var end = parseFloat(m[2]), dec = (m[2].split(".")[1] || "").length, t0 = null;
    if (!end) return;
    var done = false;
    function step(t) {
      if (done) return;
      t0 = t0 || t;
      var k = Math.min(1, (t - t0) / 700), e = 1 - Math.pow(1 - k, 3);
      el.textContent = m[1] + (end * e).toFixed(dec);
      if (k < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
    // Background tabs pause animation frames; never leave a number mid-count.
    setTimeout(function () { done = true; el.textContent = m[1] + m[2]; }, 1200);
  });
})();
</script>"""

SEV_LABEL = {"high": "HIGH", "medium": "MED", "low": "LOW"}


def esc(s) -> str:
    return html.escape(str(s))


def risk_badge(risk: int) -> str:
    """10-tick meter + score; the tick count and number carry it, not color alone."""
    cls = "crit" if risk >= 7 else "warn" if risk >= 4 else "good"
    ticks = "".join(f'<i{" class=on" if i < risk else ""}></i>' for i in range(10))
    return (
        f'<span class="risk {cls}" title="risk {risk}/10">'
        f'<span class="meter">{ticks}</span><b>{risk}</b><small>/10</small></span>'
    )


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
<title>{esc(title)}</title>{THEME_HEAD}{FONTS}<style>{CSS}</style></head>
<body>
<nav class="topbar"><div class="wrap">
  <a class="brand" href="/dashboard">{LOGO}Sentinel</a>
  <div class="nav">{link("/dashboard", "Repositories", "repos")}
    {link("/overview", "Usage", "usage")}</div>
  {THEME_BUTTON}
  {_who(user)}
</div></nav>
<main class="wrap">
{body}
</main>
{COUNT_SCRIPT}
{THEME_SCRIPT}
{extra}
</body></html>"""

"""Small server-rendered charts: inline SVG/HTML, no chart library.

Risk and severity reuse the reserved status colors (always with a legend or
text label beside them). Every mark carries a `data-tip` that the shared
TIP_SCRIPT shows on hover/tap.
"""

from __future__ import annotations

import time

from sentinel.costs import RunRow
from sentinel.report.ui import esc

CSS = """
.panels { display:grid; grid-template-columns:minmax(0,1.7fr) minmax(0,1fr); gap:12px;
          margin-top:12px; }
.panel { padding:16px 20px 18px; min-width:0; }
.panel-head { display:flex; align-items:baseline; gap:10px; margin-bottom:14px; flex-wrap:wrap; }
.panel-head h2 { flex:1; }
.panel-head .count { color:var(--ink-3); font-size:11.5px; font-family:var(--mono); }
.legend { display:flex; gap:14px; font-size:12px; color:var(--ink-2); flex-wrap:wrap; }
.legend span { display:inline-flex; align-items:center; gap:6px; }
.legend i { width:9px; height:9px; border-radius:2px; display:inline-block; }
.c-crit { fill:var(--crit); background:var(--crit); }
.c-warn { fill:var(--warn); background:var(--warn); }
.c-good { fill:var(--good); background:var(--good); }
.c-low { fill:var(--ink-3); background:var(--ink-3); }
svg.chart { display:block; width:100%; height:auto; overflow:visible; }
svg.chart text { font-family:var(--mono); font-size:10.5px; fill:var(--ink-3); }
svg.chart .grid { stroke:var(--border); stroke-width:1; }
svg.chart .base { stroke:var(--border-strong); stroke-width:1; }
svg.chart .hit { fill:transparent; cursor:default; }
svg.chart .col:hover .hit { fill:var(--hover); }
.chart-note { color:var(--ink-3); font-size:12.5px; margin-top:8px; }
.sevbar { display:flex; gap:2px; height:12px; border-radius:3px; overflow:hidden;
          background:var(--tick); }
.sevbar span { display:block; height:100%; }
.sevlist { margin-top:14px; }
.sevlist .ln { display:flex; align-items:center; gap:10px; padding:7px 0; font-size:13.5px; }
.sevlist .ln + .ln { border-top:1px solid var(--border); }
.sevlist .ln b { margin-left:auto; font-family:var(--mono); font-weight:500; }
.sevlist .ln small { color:var(--ink-3); font-family:var(--mono); width:38px;
                     text-align:right; }
.funnel { display:grid; grid-template-columns:auto minmax(0,1fr) auto; gap:10px 16px;
          align-items:center; }
.funnel .lbl { font-size:13.5px; white-space:nowrap; }
.funnel .lbl small { display:block; color:var(--ink-3); font-size:12px; }
.funnel .track { height:22px; background:var(--surface-2); border-radius:3px; }
.funnel .fill { height:100%; border-radius:3px; background:var(--ink-3); min-width:3px; }
.funnel .fill.deep { background:var(--crit); }
.funnel .n { font-family:var(--mono); font-size:13px; text-align:right;
             font-variant-numeric:tabular-nums; }
#tip { position:fixed; z-index:40; pointer-events:none; background:var(--ink);
       color:var(--bg); font-size:12px; line-height:1.45; padding:6px 9px; border-radius:4px;
       font-family:var(--mono); white-space:nowrap; opacity:0; transition:opacity .08s; }
@media (max-width: 860px) { .panels { grid-template-columns:1fr; } }
@media (max-width: 760px) {
  .panel { padding:14px 14px 16px; }
  svg.chart text { font-size:17px; }  /* the SVG scales to ~0.6x here */
  .funnel { grid-template-columns:minmax(0,1fr) auto; gap:4px 12px; }
  .funnel .lbl { grid-column:1 / -1; white-space:normal; margin-top:6px; }
}
"""

TIP_SCRIPT = """<script>
(function () {
  var tip = document.createElement("div");
  tip.id = "tip";
  document.body.appendChild(tip);
  function show(e) {
    var t = e.target.closest("[data-tip]");
    if (!t) { tip.style.opacity = 0; return; }
    tip.textContent = t.getAttribute("data-tip");
    var x = e.clientX + 12, y = e.clientY - 34;
    var w = tip.offsetWidth;
    if (x + w > innerWidth - 8) x = e.clientX - w - 12;
    tip.style.left = Math.max(8, x) + "px";
    tip.style.top = Math.max(8, y) + "px";
    tip.style.opacity = 1;
  }
  document.addEventListener("mousemove", show);
  document.addEventListener("click", show);
  document.addEventListener("scroll", function () { tip.style.opacity = 0; }, true);
})();
</script>"""

_BANDS = (("crit", "high risk", 7, 10), ("warn", "medium", 4, 6), ("good", "low", 0, 3))


def _band(risk: int) -> str:
    return next(cls for cls, _, lo, hi in _BANDS if lo <= risk <= hi)


def activity(rows: list[RunRow], days: int = 14, now: float | None = None) -> str:
    """Reviews per day for the last `days` days, stacked by risk band."""
    now = now or time.time()
    today = time.localtime(now)
    midnight = time.mktime((today.tm_year, today.tm_mon, today.tm_mday, 0, 0, 0, 0, 0, -1))
    starts = [midnight - (days - 1 - i) * 86400 for i in range(days)]
    counts = [{"crit": 0, "warn": 0, "good": 0} for _ in range(days)]
    for r in rows:
        i = int((r.ts - starts[0]) // 86400)
        if 0 <= i < days:
            counts[i][_band(r.max_risk)] += 1

    top = max((sum(c.values()) for c in counts), default=0)
    ymax = max(2, top + (top % 2))  # even, so the midline lands on a whole number
    w, h, left, bottom, top_pad = 560, 150, 22, 22, 6
    plot_h = h - bottom - top_pad
    slot = (w - left) / days
    bar_w = min(26.0, slot * 0.62)

    def y(v: float) -> float:
        return top_pad + plot_h - v / ymax * plot_h

    parts = [
        f'<line class="grid" x1="{left}" x2="{w}" y1="{y(ymax):.1f}" y2="{y(ymax):.1f}"/>',
        f'<line class="grid" x1="{left}" x2="{w}" y1="{y(ymax / 2):.1f}" '
        f'y2="{y(ymax / 2):.1f}"/>',
        f'<text x="{left - 6}" y="{y(ymax) + 4:.1f}" text-anchor="end">{ymax}</text>',
        f'<text x="{left - 6}" y="{y(ymax / 2) + 4:.1f}" text-anchor="end">{ymax // 2}</text>',
        f'<text x="{left - 6}" y="{y(0) + 4:.1f}" text-anchor="end">0</text>',
    ]
    for i, (start, c) in enumerate(zip(starts, counts, strict=True)):
        x0 = left + i * slot
        cx = x0 + slot / 2
        label = time.strftime("%b %d", time.localtime(start))
        total = sum(c.values())
        detail = ", ".join(f"{c[cls]} {name}" for cls, name, _, _ in _BANDS if c[cls])
        tip = f"{label} · {total} review{'s' if total != 1 else ''}" + (
            f" ({detail})" if detail else ""
        )
        segs, level = [], 0
        for cls, _, _, _ in reversed(_BANDS):  # low at the bottom, high on top
            n = c[cls]
            if not n:
                continue
            y_top, y_bot = y(level + n), y(level)
            gap = 2 if level else 0  # surface gap between stacked segments
            segs.append(
                f'<rect class="c-{cls}" x="{cx - bar_w / 2:.1f}" y="{y_top:.1f}" '
                f'width="{bar_w:.1f}" height="{max(1.0, y_bot - y_top - gap):.1f}" rx="2"/>'
            )
            level += n
        parts.append(
            f'<g class="col" data-tip="{esc(tip)}"><rect class="hit" x="{x0:.1f}" '
            f'y="{top_pad}" width="{slot:.1f}" height="{plot_h}" rx="3"/>{"".join(segs)}</g>'
        )
        if i % 3 == (days - 1) % 3:
            parts.append(
                f'<text x="{cx:.1f}" y="{h - 5}" text-anchor="middle">{label}</text>'
            )
    parts.append(f'<line class="base" x1="{left}" x2="{w}" y1="{y(0):.1f}" y2="{y(0):.1f}"/>')

    legend = "".join(
        f'<span><i class="c-{cls}"></i>{name}</span>' for cls, name, _, _ in _BANDS
    )
    in_range = sum(sum(c.values()) for c in counts)
    note = (
        "" if in_range
        else '<div class="chart-note">No reviews in this window yet - open a PR or use '
        "Review now on a repository.</div>"
    )
    return f"""<div class="card panel">
  <div class="panel-head"><h2>Review activity</h2><div class="legend">{legend}</div></div>
  <svg class="chart" viewBox="0 0 {w} {h}" role="img"
       aria-label="{in_range} reviews in the last {days} days">{"".join(parts)}</svg>{note}
</div>"""


def severity(findings: list[dict]) -> str:
    """Open findings (latest review per PR) split by severity."""
    order = (("high", "HIGH", "c-crit"), ("medium", "MED", "c-warn"), ("low", "LOW", "c-low"))
    n = {k: sum(1 for f in findings if f.get("severity") == k) for k, _, _ in order}
    total = sum(n.values())
    bar = "".join(
        f'<span class="{cls}" style="flex:{n[k]}" data-tip="{n[k]} {label}"></span>'
        for k, label, cls in order if n[k]
    )
    lines = "".join(
        f'<div class="ln"><span class="sev {k}">{label}</span>'
        f'<span>{"High" if k == "high" else "Medium" if k == "medium" else "Low"}</span>'
        f"<b>{n[k]}</b><small>{(n[k] / total * 100) if total else 0:.0f}%</small></div>"
        for k, label, _ in order
    )
    return f"""<div class="card panel">
  <div class="panel-head"><h2>Open findings</h2>
    <span class="count">{total} total</span></div>
  <div class="sevbar">{bar}</div>
  <div class="sevlist">{lines}</div>
</div>"""


def funnel(total: int, skipped: int, deep: int, title: str = "Where the hunks went") -> str:
    """Tiered review as a funnel: every hunk -> triaged -> deep reviewed."""
    triaged = max(0, total - skipped)
    steps = (
        ("Changed hunks", "everything in the diff", total, ""),
        ("Triaged", "fast model scores each one", triaged, ""),
        ("Deep reviewed", "strong model, risky hunks only", deep, "deep"),
    )
    top = max(total, 1)
    rows = "".join(
        f'<div class="lbl">{name}<small>{sub}</small></div>'
        f'<div class="track" data-tip="{name}: {v} hunk{"s" if v != 1 else ""}">'
        f'<div class="fill {cls}" style="width:{v / top * 100:.1f}%"></div></div>'
        f'<div class="n">{v}</div>'
        for name, sub, v, cls in steps
    )
    pct = f"{deep / total * 100:.0f}%" if total else "0%"
    return f"""<div class="card panel">
  <div class="panel-head"><h2>{esc(title)}</h2>
    <span class="count">{pct} reached the strong model</span></div>
  <div class="funnel">{rows}</div>
</div>"""

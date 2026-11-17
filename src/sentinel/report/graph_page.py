"""Risk map page: the repo's import graph with review risk painted on it.

Server-rendered shell + one inline script that fetches
/api/repo/<repo>/graph (layout already computed server-side) and draws it as
SVG: zoom and pan, hover to see a file's neighbours, click for its findings and
decisions, pick an open PR to see its blast radius. A plain table of the
riskiest files sits under the map so nothing is colour-only or mouse-only.
"""

from __future__ import annotations

import html

from sentinel.report.pages import _page, _split

_CSS = """
.rm-bar { display:flex; flex-wrap:wrap; gap:10px; align-items:center; margin:18px 0 12px; }
.rm-bar select, .rm-bar input { font:inherit; font-size:13px; color:var(--ink);
  background:var(--surface); border:1px solid var(--border); border-radius:8px;
  padding:7px 10px; min-width:0; }
.rm-bar input { flex:1 1 200px; }
.rm-bar .status { font-size:12.5px; color:var(--ink-3); }
.rm { display:grid; grid-template-columns:minmax(0,1fr) 300px; gap:16px; }
.rm-stage { position:relative; background:var(--surface); border:1px solid var(--border);
  border-radius:12px; overflow:hidden; height:640px; touch-action:none; }
.rm-stage svg { width:100%; height:100%; display:block; cursor:grab; }
.rm-stage svg.drag { cursor:grabbing; }
.rm-zoom { position:absolute; right:10px; top:10px; display:flex; flex-direction:column; gap:4px; }
.rm-zoom button { width:30px; height:30px; border-radius:8px; border:1px solid var(--border);
  background:var(--surface); color:var(--ink); font:inherit; cursor:pointer; }
.rm-msg { position:absolute; inset:0; display:grid; place-items:center; text-align:center;
  color:var(--ink-3); font-size:14px; padding:24px; }
.rm-legend { display:flex; flex-wrap:wrap; gap:14px; font-size:12px; color:var(--ink-2);
  margin-top:10px; }
.rm-legend i { display:inline-block; width:10px; height:10px; border-radius:50%;
  vertical-align:-1px; margin-right:6px; }
.rm-legend .ring { background:transparent; border:2px solid var(--ink); }
.rm-legend .dash { background:transparent; border:2px dashed var(--ink-2); }
.rm-side { background:var(--surface); border:1px solid var(--border); border-radius:12px;
  padding:16px; height:640px; overflow:auto; font-size:13.5px; }
.rm-side h3 { margin:0 0 4px; font-size:12px; letter-spacing:.06em; text-transform:uppercase;
  color:var(--ink-3); font-family:var(--mono); }
.rm-side .path { font-family:var(--mono); font-size:12.5px; word-break:break-all;
  margin:2px 0 12px; }
.rm-side ul { list-style:none; margin:6px 0 14px; padding:0; }
.rm-side li { padding:5px 0; border-bottom:1px solid var(--border); }
.rm-side li:last-child { border-bottom:0; }
.rm-side .muted { color:var(--ink-3); }
.rm-side .kv { display:flex; justify-content:space-between; padding:4px 0; }
svg .cl { fill:var(--surface-2); stroke:var(--border); }
svg .cl-t { fill:var(--ink-3); font-family:var(--mono); font-size:11px; }
svg .ed { stroke:var(--ink-3); stroke-opacity:.18; stroke-width:.8; }
svg .ed.on { stroke:var(--ink); stroke-opacity:.75; stroke-width:1.4; }
svg .nd { stroke:var(--surface); stroke-width:1.5; cursor:pointer; }
svg .nd.none { fill:var(--ink-3); fill-opacity:.45; }
svg .nd.low { fill:var(--ink-2); }
svg .nd.warn { fill:var(--warn); }
svg .nd.crit { fill:var(--crit); }
svg .nd.sel, svg .nd.chg { stroke:var(--ink); stroke-width:2.6; }
svg .nd.hit { stroke:var(--ink-2); stroke-width:2; stroke-dasharray:3 2; }
svg .pin { fill:var(--ink); pointer-events:none; }
svg.dim .nd:not(.focus), svg.dim .pin:not(.focus) { opacity:.18; }
svg.dim .ed:not(.on) { stroke-opacity:.05; }
.rm-tip { position:absolute; pointer-events:none; background:var(--ink); color:var(--bg);
  font-size:12px; padding:6px 9px; border-radius:6px; max-width:320px; display:none;
  font-family:var(--mono); }
.rm-table { width:100%; border-collapse:collapse; font-size:13px; margin-top:8px; }
.rm-table th, .rm-table td { text-align:left; padding:8px 10px; border-bottom:1px solid var(--border); }
.rm-table th { font-weight:500; color:var(--ink-3); font-size:12px; }
.rm-table td.n { font-family:var(--mono); }
.rm-go { font:inherit; font-family:var(--mono); font-size:12.5px; background:none;
  border:0; padding:0; color:var(--ink); cursor:pointer; text-align:left; word-break:break-all; }
.rm-go:hover { text-decoration:underline; }
@media (max-width: 900px) {
  .rm { grid-template-columns:1fr; }
  .rm-stage { height:460px; }
  .rm-side { height:auto; max-height:420px; }
}
"""

_SCRIPT = """<script>
(function () {
  var root = document.getElementById("risk-map");
  var api = root.getAttribute("data-api");
  var repo = root.getAttribute("data-repo");
  var svg = document.getElementById("rm-svg");
  var msg = document.getElementById("rm-msg");
  var tip = document.getElementById("rm-tip");
  var side = document.getElementById("rm-side");
  var prSel = document.getElementById("rm-pr");
  var search = document.getElementById("rm-search");
  var status = document.getElementById("rm-status");
  var table = document.getElementById("rm-top");
  var NS = "http://www.w3.org/2000/svg";
  var g = null, byId = {}, out = {}, inn = {}, view = null, home = null, selected = null;
  var BAND = {crit: "high risk", warn: "medium risk", low: "low risk", none: "no findings"};

  function esc(s) { var d = document.createElement("div"); d.textContent = s == null ? "" : String(s); return d.innerHTML; }
  function el(tag, attrs, parent) {
    var n = document.createElementNS(NS, tag);
    for (var k in attrs) n.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(n);
    return n;
  }
  function setView(v) { view = v; svg.setAttribute("viewBox", v.x + " " + v.y + " " + v.w + " " + v.h); }
  function radius(n) { return Math.min(10, 4.5 + Math.sqrt(n.lines) / 6); }
  function blob(path) { return "https://github.com/" + repo + "/blob/" + (g.ref || "HEAD") + "/" + path; }

  function load(pr) {
    msg.style.display = "grid";
    msg.textContent = g ? "Loading…" : "Reading the codebase… the first map of a repo can take ~20 s.";
    status.textContent = "";
    fetch(api + (pr ? "?pr=" + pr : ""), {credentials: "same-origin"})
      .then(function (r) { return r.json().then(function (j) { return [r.ok, j]; }); })
      .then(function (res) {
        if (!res[0]) throw new Error(res[1].error || "could not build the map");
        g = res[1]; draw();
      })
      .catch(function (e) { msg.style.display = "grid"; msg.textContent = e.message; });
  }

  function draw() {
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    byId = {}; out = {}; inn = {};
    if (!g.nodes.length) { msg.textContent = "No Python or JS/TS files found in this repo."; return; }
    msg.style.display = "none";
    g.nodes.forEach(function (n) { byId[n.id] = n; out[n.id] = []; inn[n.id] = []; });
    g.edges.forEach(function (e) { out[e[0]].push(e[1]); inn[e[1]].push(e[0]); });

    var minX = 1e9, minY = 1e9, maxX = -1e9, maxY = -1e9;
    var lc = el("g", {}, svg), le = el("g", {}, svg), ln = el("g", {}, svg);
    g.clusters.forEach(function (c) {
      el("circle", {cx: c.x, cy: c.y, r: c.r, "class": "cl"}, lc);
      var t = el("text", {x: c.x, y: c.y - c.r - 6, "text-anchor": "middle", "class": "cl-t"}, lc);
      t.textContent = c.dir === "." ? "(root)" : c.dir.split("/").pop() + "/";
      el("title", {}, t).textContent = c.dir;
      minX = Math.min(minX, c.x - c.r); maxX = Math.max(maxX, c.x + c.r);
      minY = Math.min(minY, c.y - c.r - 24); maxY = Math.max(maxY, c.y + c.r);
    });
    g.edges.forEach(function (e) {
      var a = byId[e[0]], b = byId[e[1]];
      var line = el("line", {x1: a.x, y1: a.y, x2: b.x, y2: b.y, "class": "ed"}, le);
      line.__e = e;
    });
    var pr = g.pr || {}, changed = {}, hit = pr.impacted || {};
    (pr.changed || []).forEach(function (p) { changed[p] = 1; });
    g.nodes.forEach(function (n) {
      var cls = "nd " + n.band + (changed[n.id] ? " chg" : "") + (hit[n.id] ? " hit" : "");
      var c = el("circle", {cx: n.x, cy: n.y, r: radius(n), "class": cls, tabindex: 0,
        role: "button", "aria-label": n.id + ", " + BAND[n.band]}, ln);
      c.__n = n; n.__el = c;
      if (n.decisions.length) {
        var p = el("rect", {x: n.x + radius(n) - 2, y: n.y - radius(n) - 2, width: 4.5,
          height: 4.5, transform: "rotate(45 " + (n.x + radius(n)) + " " + (n.y - radius(n)) + ")",
          "class": "pin"}, ln);
        n.__pin = p;
      }
    });
    var pad = 30;
    home = {x: minX - pad, y: minY - pad, w: maxX - minX + 2 * pad, h: maxY - minY + 2 * pad};
    setView(home);

    if (g.pr) {
      var nImp = Object.keys(hit).length;
      var direct = Object.keys(hit).filter(function (k) { return hit[k] === 1; }).length;
      status.textContent = "PR #" + g.pr.number + " changes " + g.pr.changed.length +
        " mapped file" + (g.pr.changed.length === 1 ? "" : "s") + "; " + nImp +
        " more depend on them (" + direct + " directly).";
      focus(Object.keys(changed).concat(Object.keys(hit)), prEdges());
    } else {
      status.textContent = g.nodes.length + " files, " + g.edges.length + " imports" +
        (g.truncated ? " (showing the " + g.nodes.length + " most relevant of " + g.total_files + ")" : "");
    }
    renderTable();
    if (selected && byId[selected]) select(selected); else intro();
  }

  function focus(ids, edgeIds) {
    var set = {}; ids.forEach(function (i) { set[i] = 1; });
    svg.classList.toggle("dim", ids.length > 0);
    g.nodes.forEach(function (n) {
      n.__el.classList.toggle("focus", !!set[n.id]);
      if (n.__pin) n.__pin.classList.toggle("focus", !!set[n.id]);
    });
    var on = {}; edgeIds.forEach(function (e) { on[e] = 1; });
    svg.querySelectorAll(".ed").forEach(function (l) { l.classList.toggle("on", !!on[l.__e[0] + ">" + l.__e[1]]); });
  }
  function neighbours(id) {
    var ids = [id].concat(out[id], inn[id]);
    var edges = out[id].map(function (t) { return id + ">" + t; }).concat(inn[id].map(function (s) { return s + ">" + id; }));
    return [ids, edges];
  }
  function prEdges() {
    // import lines along the blast radius: an affected file -> what it imports from the PR
    var inPr = {}, hit = g.pr.impacted || {};
    g.pr.changed.forEach(function (p) { inPr[p] = 1; });
    Object.keys(hit).forEach(function (p) { inPr[p] = 1; });
    return g.edges.filter(function (e) { return hit[e[0]] && inPr[e[1]]; })
      .map(function (e) { return e[0] + ">" + e[1]; });
  }
  function restore() {
    if (selected) { var nb = neighbours(selected); focus(nb[0], nb[1]); return; }
    if (g.pr) { var hit = g.pr.impacted || {}; focus(g.pr.changed.concat(Object.keys(hit)), prEdges()); return; }
    focus([], []);
  }

  function intro() {
    if (g.pr) {
      var hit = g.pr.impacted || {};
      var near = Object.keys(hit).sort(function (a, b) { return hit[a] - hit[b] || byId[b].risk - byId[a].risk; });
      var h = "<h3>PR #" + g.pr.number + " changes</h3><ul>";
      g.pr.changed.forEach(function (p) { h += "<li><button class='rm-go' data-id='" + esc(p) + "'>" + esc(p) + "</button></li>"; });
      if (g.pr.unmapped.length) h += "<li class='muted'>+ " + g.pr.unmapped.length + " other file" + (g.pr.unmapped.length > 1 ? "s" : "") + " (docs, config, …)</li>";
      h += "</ul><h3>Could break (" + near.length + ")</h3><ul>";
      near.slice(0, 12).forEach(function (p) {
        h += "<li><button class='rm-go' data-id='" + esc(p) + "'>" + esc(p) + "</button> <span class='muted'>" + hit[p] + " hop" + (hit[p] > 1 ? "s" : "") + "</span></li>";
      });
      side.innerHTML = h + "</ul>";
      return;
    }
    var hot = g.nodes.filter(function (n) { return n.risk > 0; }).length;
    side.innerHTML = "<h3>How to read this</h3><p>Each dot is a file, grouped by folder. Lines are imports. " +
      "Colour is the risk from Sentinel's reviews; bigger dots are longer files; a small diamond means a team decision is tied to that file.</p>" +
      "<p class='muted'>" + hot + " of " + g.nodes.length + " files carry review findings. Click a dot for details, or pick an open PR above to see what it could break.</p>";
  }

  function select(id) {
    selected = id;
    var n = byId[id];
    svg.querySelectorAll(".nd.sel").forEach(function (c) { c.classList.remove("sel"); });
    n.__el.classList.add("sel");
    var nb = neighbours(id); focus(nb[0], nb[1]);
    var h = "<h3>File</h3><div class='path'><a href='" + esc(blob(n.id)) + "' target='_blank' rel='noopener'>" + esc(n.id) + " ↗</a></div>";
    h += "<div class='kv'><span>Risk</span><b>" + esc(BAND[n.band]) + (n.risk ? " · " + n.risk : "") + "</b></div>";
    h += "<div class='kv'><span>Lines</span><b>" + n.lines + "</b></div>";
    h += "<div class='kv'><span>Imports / imported by</span><b>" + n.imports + " / " + n.imported_by + "</b></div>";
    if (g.pr && (g.pr.impacted || {})[n.id]) h += "<div class='kv'><span>PR #" + g.pr.number + "</span><b>" + g.pr.impacted[n.id] + " hop" + (g.pr.impacted[n.id] > 1 ? "s" : "") + " away</b></div>";
    if (g.pr && g.pr.changed.indexOf(n.id) >= 0) h += "<div class='kv'><span>PR #" + g.pr.number + "</span><b>changed here</b></div>";
    if (n.findings.length) {
      h += "<h3 style='margin-top:14px'>Review findings</h3><ul>";
      n.findings.forEach(function (f) {
        h += "<li><span class='sev " + esc(f.severity) + "'>" + esc({high: "HIGH", medium: "MED", low: "LOW"}[f.severity] || "?") + "</span> " +
          esc(f.title) + " <a class='muted' href='https://github.com/" + esc(repo) + "/pull/" + f.pr + "' target='_blank' rel='noopener'>#" + f.pr + "</a></li>";
      });
      h += "</ul>";
    }
    if (n.decisions.length) {
      h += "<h3>Team decisions</h3><ul>";
      n.decisions.forEach(function (d) {
        h += "<li>" + esc(d.decision) + " <a class='muted' href='" + esc(d.url) + "' target='_blank' rel='noopener'>#" + d.pr + "</a></li>";
      });
      h += "</ul>";
    }
    var deps = inn[id].slice().sort(function (a, b) { return byId[b].risk - byId[a].risk; });
    if (deps.length) {
      h += "<h3>Depends on this (" + deps.length + ")</h3><ul>";
      deps.slice(0, 8).forEach(function (p) { h += "<li><button class='rm-go' data-id='" + esc(p) + "'>" + esc(p) + "</button></li>"; });
      h += "</ul>";
    }
    side.innerHTML = h;
  }

  function renderTable() {
    var top = g.nodes.filter(function (n) { return n.risk > 0; })
      .sort(function (a, b) { return b.risk - a.risk || b.imported_by - a.imported_by; }).slice(0, 10);
    if (!top.length) { table.innerHTML = "<p class='muted'>No review findings on these files yet. Reviews colour the map as PRs come in.</p>"; return; }
    var h = "<table class='rm-table'><thead><tr><th>File</th><th>Risk</th><th>Findings</th><th>Depended on by</th></tr></thead><tbody>";
    top.forEach(function (n) {
      h += "<tr><td><button class='rm-go' data-id='" + esc(n.id) + "'>" + esc(n.id) + "</button></td><td>" + esc(BAND[n.band]) +
        "</td><td class='n'>" + n.findings.length + "</td><td class='n'>" + n.imported_by + "</td></tr>";
    });
    table.innerHTML = h + "</tbody></table>";
  }

  function centerOn(n) {
    var w = Math.min(home.w, 420), h = w * (home.h / home.w);
    setView({x: n.x - w / 2, y: n.y - h / 2, w: w, h: h});
  }

  // --- interaction ---
  svg.addEventListener("mousemove", function (e) {
    var n = e.target.__n;
    if (!n) { tip.style.display = "none"; return; }
    var r = svg.parentNode.getBoundingClientRect();
    tip.innerHTML = esc(n.id) + "<br>" + esc(BAND[n.band]) + (n.findings.length ? " · " + n.findings.length + " finding" + (n.findings.length > 1 ? "s" : "") : "") +
      (n.decisions.length ? " · " + n.decisions.length + " decision" + (n.decisions.length > 1 ? "s" : "") : "");
    tip.style.display = "block";
    tip.style.left = Math.min(e.clientX - r.left + 12, r.width - 240) + "px";
    tip.style.top = (e.clientY - r.top + 12) + "px";
  });
  svg.addEventListener("mouseover", function (e) {
    if (e.target.__n && !selected) { var nb = neighbours(e.target.__n.id); focus(nb[0], nb[1]); }
  });
  svg.addEventListener("mouseout", function (e) {
    if (e.target.__n) { tip.style.display = "none"; if (!selected) restore(); }
  });
  function pick(e) {
    if (e.target.__n) { select(e.target.__n.id); }
    else if (!moved) { selected = null; svg.querySelectorAll(".nd.sel").forEach(function (c) { c.classList.remove("sel"); }); restore(); intro(); }
  }
  svg.addEventListener("click", pick);
  svg.addEventListener("keydown", function (e) { if ((e.key === "Enter" || e.key === " ") && e.target.__n) { e.preventDefault(); select(e.target.__n.id); } });
  document.addEventListener("click", function (e) {
    var b = e.target.closest && e.target.closest(".rm-go");
    if (b && byId[b.getAttribute("data-id")]) { select(b.getAttribute("data-id")); centerOn(byId[b.getAttribute("data-id")]); svg.scrollIntoView({block: "center", behavior: "smooth"}); }
  });

  function zoom(f, cx, cy) {
    if (!view) return;
    cx = cx == null ? view.x + view.w / 2 : cx; cy = cy == null ? view.y + view.h / 2 : cy;
    var w = Math.max(80, Math.min(home.w * 3, view.w * f)), h = w * (view.h / view.w);
    setView({x: cx - (cx - view.x) * (w / view.w), y: cy - (cy - view.y) * (h / view.h), w: w, h: h});
  }
  function toSvg(e) {
    var r = svg.getBoundingClientRect();
    var s = Math.max(view.w / r.width, view.h / r.height);
    var ox = (r.width * s - view.w) / 2, oy = (r.height * s - view.h) / 2;
    return [view.x - ox + (e.clientX - r.left) * s, view.y - oy + (e.clientY - r.top) * s, s];
  }
  svg.addEventListener("wheel", function (e) { e.preventDefault(); var p = toSvg(e); zoom(e.deltaY > 0 ? 1.15 : 1 / 1.15, p[0], p[1]); }, {passive: false});
  var drag = null, moved = false;
  svg.addEventListener("pointerdown", function (e) { if (e.target.__n) return; drag = {x: e.clientX, y: e.clientY, v: view}; moved = false; svg.classList.add("drag"); });
  window.addEventListener("pointermove", function (e) {
    if (!drag) return;
    var r = svg.getBoundingClientRect(), s = Math.max(drag.v.w / r.width, drag.v.h / r.height);
    var dx = (e.clientX - drag.x) * s, dy = (e.clientY - drag.y) * s;
    if (Math.abs(dx) + Math.abs(dy) > 2) moved = true;
    setView({x: drag.v.x - dx, y: drag.v.y - dy, w: drag.v.w, h: drag.v.h});
  });
  window.addEventListener("pointerup", function () { drag = null; svg.classList.remove("drag"); setTimeout(function () { moved = false; }, 0); });
  document.getElementById("rm-in").onclick = function () { zoom(1 / 1.4); };
  document.getElementById("rm-out").onclick = function () { zoom(1.4); };
  document.getElementById("rm-home").onclick = function () { if (home) setView(home); };

  prSel.addEventListener("change", function () { selected = null; load(prSel.value); });
  search.addEventListener("input", function () {
    var q = search.value.trim().toLowerCase();
    if (!g) return;
    if (!q) { restore(); return; }
    var hits = g.nodes.filter(function (n) { return n.id.toLowerCase().indexOf(q) >= 0; });
    focus(hits.map(function (n) { return n.id; }), []);
    status.textContent = hits.length + " file" + (hits.length === 1 ? "" : "s") + " match “" + search.value.trim() + "”";
  });
  search.addEventListener("keydown", function (e) {
    if (e.key !== "Enter" || !g) return;
    var q = search.value.trim().toLowerCase();
    var n = g.nodes.filter(function (n) { return n.id.toLowerCase().indexOf(q) >= 0; })[0];
    if (n) { select(n.id); centerOn(n); }
  });

  load(prSel.value);
})();
</script>"""


def render_graph_page(repo: str, user: dict | None, prs: list[dict] | None) -> str:
    owner, name = _split(repo)
    options = '<option value="">No PR: whole repo</option>' + "".join(
        f'<option value="{p["number"]}">PR #{p["number"]}: {html.escape(p["title"][:70])}</option>'
        for p in (prs or [])
    )
    body = f"""
<div class="crumbs"><a href="/dashboard">repositories</a> / {html.escape(owner)} /
  <a href="/repo/{html.escape(repo)}">{html.escape(name)}</a></div>
<div class="page-head"><div class="grow">
  <h1><span class="owner">{html.escape(owner)} / </span>{html.escape(name)} · risk map</h1>
  <p class="lede">Every file and its imports, coloured by what Sentinel's reviews found.
  Pick an open PR to see what it could break.</p></div></div>
<div id="risk-map" data-api="/api/repo/{html.escape(repo)}/graph"
     data-repo="{html.escape(repo)}">
  <div class="rm-bar">
    <select id="rm-pr" aria-label="Show the blast radius of an open pull request">{options}</select>
    <input id="rm-search" type="search" placeholder="Find a file… (Enter to jump)"
      aria-label="Find a file">
    <span class="status" id="rm-status" aria-live="polite"></span>
  </div>
  <div class="rm">
    <div>
      <div class="rm-stage">
        <svg id="rm-svg" role="img" aria-label="Import graph of {html.escape(repo)}"></svg>
        <div class="rm-zoom"><button id="rm-in" aria-label="Zoom in">+</button>
          <button id="rm-out" aria-label="Zoom out">−</button>
          <button id="rm-home" aria-label="Reset view">⤢</button></div>
        <div class="rm-msg" id="rm-msg"></div>
        <div class="rm-tip" id="rm-tip"></div>
      </div>
      <div class="rm-legend">
        <span><i style="background:var(--crit)"></i>high risk</span>
        <span><i style="background:var(--warn)"></i>medium risk</span>
        <span><i style="background:var(--ink-2)"></i>low risk</span>
        <span><i style="background:var(--ink-3);opacity:.45"></i>no findings</span>
        <span><i class="ring"></i>changed by the PR</span>
        <span><i class="dash"></i>depends on a changed file</span>
        <span>◆ team decision</span>
      </div>
    </div>
    <aside class="rm-side" id="rm-side" aria-live="polite"></aside>
  </div>
  <div class="section"><div class="section-head"><h2>Riskiest files</h2></div>
    <div id="rm-top"></div></div>
</div>
<style>{_CSS}</style>
{_SCRIPT}
"""
    return _page(f"{repo} · risk map", body, user, active="repos")

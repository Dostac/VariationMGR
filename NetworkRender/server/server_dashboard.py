import json
from pathlib import Path

_CSS_PATH = Path(__file__).with_name("server_dashboard.css")


def read_stylesheet():
    return _CSS_PATH.read_text(encoding="utf-8")


CLIENT_CONFIG = {
    "poll_ms": 3000,
    "csrf_header": "X-VB-Request",
    "csrf_value": "1",
}


def render_dashboard(state, server_address):
    host, port = server_address[0], server_address[1]
    title = f"VB Batch Server — {host}:{port}"
    bootstrap = json.dumps(CLIENT_CONFIG)

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_esc(title)}</title>
  <link rel="stylesheet" href="/static/server_dashboard.css">
</head>
<body>
  <div class="wrap">

    <header>
      <div class="hero">
        <h1>Render Server</h1>
        <span class="hero-badge" id="hero-status">Active</span>
      </div>

      <div class="statusline">
        <div class="pill" id="pill-http">HTTP: {_esc(f"http://{host}:{port}")}</div>
        <div class="pill" id="pill-workers">Workers: …</div>
        <div class="pill" id="pill-queue">Queue: <span class="status-indicator processing">…</span></div>
        <div class="pill" id="pill-eta" title="Estimated time to clear the queue">ETA: —</div>
        <div class="pill" id="pill-updated">…</div>
        <div class="pill pill-actions">
          <button class="btn btn-tonal" id="btn-pause">⏸ Pause</button>
          <label class="toggle">
            <input type="checkbox" id="chk-auto-requeue">
            <span>Auto-requeue failed</span>
          </label>
        </div>
      </div>
    </header>

    <div class="grid" id="stats-grid"></div>

    <section class="panel" id="progress-panel">
      <div class="progress-summary" id="progress-text">—</div>
      <div class="progress"><div class="bar" id="progress-bar" style="width:0%"></div></div>
    </section>

    <section class="panel">
      <h2>Workers</h2>
      <table class="t-workers">
        <thead>
          <tr><th></th><th>Name</th><th>Status</th><th>Current Job</th><th>Last Seen</th></tr>
        </thead>
        <tbody id="tbody-workers">
          <tr><td colspan="5" class="empty">Loading…</td></tr>
        </tbody>
      </table>
    </section>

    <section class="panel" id="perf-panel">
      <div class="panel-head">
        <h2>Performance</h2>
        <div class="panel-actions perf-filters">
          <div class="filter-group" id="worker-chips">
            <span class="filter-label">Workers:</span>
            <button class="chip-btn active" data-worker-all>All</button>
          </div>
          <div class="filter-group">
            <span class="filter-label">Status:</span>
            <select id="perf-status" class="select">
              <option value="done">Done only</option>
              <option value="done_failed">Done + Failed</option>
            </select>
          </div>
          <div class="filter-group">
            <span class="filter-label">Window:</span>
            <select id="perf-window" class="select">
              <option value="all">All time</option>
              <option value="24h">Last 24 h</option>
              <option value="1h">Last hour</option>
            </select>
          </div>
        </div>
      </div>

      <div class="stat-strip" id="perf-stats">
        <div class="stat"><div class="label">Count</div><div class="value" id="stat-count">—</div></div>
        <div class="stat"><div class="label">Average</div><div class="value" id="stat-avg">—</div></div>
        <div class="stat"><div class="label">Median</div><div class="value" id="stat-median">—</div></div>
        <div class="stat"><div class="label">Min</div><div class="value" id="stat-min">—</div></div>
        <div class="stat"><div class="label">Max</div><div class="value" id="stat-max">—</div></div>
      </div>

      <div class="chart-grid">
        <div class="chart-card">
          <div class="chart-title">Jobs by Worker</div>
          <div class="chart-subtitle">Completed job count · who's pulling weight</div>
          <div class="chart-body" id="chart-pie"></div>
        </div>
        <div class="chart-card">
          <div class="chart-title">Avg Duration by Worker</div>
          <div class="chart-subtitle">Mean render time · lower = faster</div>
          <div class="chart-body" id="chart-bars"></div>
        </div>
      </div>

      <div class="chart-card chart-card-full">
        <div class="chart-title">Recent Activity · Timeline</div>
        <div class="chart-subtitle">Each block = one render · width = duration · placed at start time</div>
        <div class="chart-body chart-swimlane" id="chart-swimlane"></div>
      </div>
    </section>

    <section class="panel">
      <div class="panel-head">
        <h2>Jobs</h2>
        <div class="panel-actions">
          <button class="btn" id="btn-requeue-sel" disabled>Requeue Selected</button>
          <button class="btn btn-danger" id="btn-remove-sel" disabled>Remove Selected</button>
          <span class="sep"></span>
          <button class="btn" id="btn-clear-queue">Clear Queue</button>
          <button class="btn" id="btn-remove-done">Remove Done</button>
          <button class="btn" id="btn-remove-failed">Remove Failed</button>
          <button class="btn btn-danger" id="btn-clear-all">Clear All</button>
        </div>
      </div>

      <div class="job-tabs" id="job-tabs">
        <button class="job-tab active" data-tab="all">All <span class="tab-count" id="tab-cnt-all">0</span></button>
        <button class="job-tab" data-tab="done">Done <span class="tab-count" id="tab-cnt-done">0</span></button>
        <button class="job-tab" data-tab="running">Running <span class="tab-count" id="tab-cnt-running">0</span></button>
        <button class="job-tab" data-tab="queued">Queued <span class="tab-count" id="tab-cnt-queued">0</span></button>
        <button class="job-tab" data-tab="failed">Failed <span class="tab-count" id="tab-cnt-failed">0</span></button>
      </div>

      <table class="t-jobs">
        <thead>
          <tr>
            <th class="col-check"><input type="checkbox" id="chk-all"></th>
            <th>Scene</th>
            <th>Output</th>
            <th>Status</th>
            <th>Worker</th>
            <th>Duration</th>
            <th>Att.</th>
            <th>Updated</th>
            <th>Last Error</th>
          </tr>
        </thead>
        <tbody id="tbody-jobs">
          <tr><td colspan="9" class="empty">Loading…</td></tr>
        </tbody>
      </table>
      <div class="foot" id="jobs-foot">—</div>
    </section>

    <div id="toast" class="toast" role="status" aria-live="polite"></div>
  </div>

  <script>
    const CFG = {bootstrap};
    {_DASHBOARD_JS}
  </script>
</body>
</html>"""


def _esc(value):
    import html as _html
    return _html.escape(str(value or ""))


_DASHBOARD_JS = r"""
const $ = (id) => document.getElementById(id);
const selectedJobIds = new Set();
let lastSnapshot = null;
let jobTabFilter = "all";

const perfFilter = {
  workers: new Set(),
  statusMode: "done",
  windowMode: "all",
};

// ── Colour helpers ──────────────────────────────────────────────────────────

function colorForWorker(name) {
  const s = String(name || "");
  let h = 0;
  for (let i = 0; i < s.length; i++) h = ((h * 31) + s.charCodeAt(i)) >>> 0;
  return `hsl(${h % 360}, 60%, 60%)`;
}

// ── Formatters ──────────────────────────────────────────────────────────────

function fmtDuration(secs) {
  if (!secs || secs <= 0) return "—";
  secs = Math.floor(secs);
  if (secs < 60) return secs + "s";
  const m = Math.floor(secs / 60), s = secs % 60;
  if (m < 60) return s ? `${m}m ${s}s` : `${m}m`;
  const h = Math.floor(m / 60), mm = m % 60;
  return mm ? `${h}h ${mm}m` : `${h}h`;
}

function fmtTs(ts) {
  if (!ts) return "—";
  try {
    const d = new Date(ts * 1000);
    const p = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
  } catch (e) { return "—"; }
}

function fmtTime(ts) {
  if (!ts) return "—";
  try {
    const d = new Date(ts * 1000);
    const p = (n) => String(n).padStart(2, "0");
    return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
  } catch (e) { return "—"; }
}

function esc(s) {
  const d = document.createElement("div");
  d.textContent = String(s == null ? "" : s);
  return d.innerHTML;
}

function statusChip(status) {
  const norm = String(status || "").trim().toLowerCase();
  const cls = ({queued:"queued",claimed:"running",running:"running",done:"done",success:"done",failed:"failed",idle:"idle"})[norm] || "idle";
  return `<span class="chip ${cls}">${esc(status||"-")}</span>`;
}

function workerCell(name) {
  if (!name || name === "-") return `<span class="worker-cell">—</span>`;
  return `<span class="worker-cell"><span class="worker-dot" style="background:${colorForWorker(name)}"></span>${esc(name)}</span>`;
}

function shortPath(p, parts = 3) {
  if (!p) return "";
  const norm = p.replace(/\\/g, "/").replace(/\/+/g, "/");
  const chunks = norm.split("/").filter(Boolean);
  return chunks.length <= parts ? norm : "…/" + chunks.slice(-parts).join("/");
}

// ── Network ─────────────────────────────────────────────────────────────────

async function fetchJson(url, opts) {
  const r = await fetch(url, opts);
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try { const j = await r.json(); if (j && j.error) msg = j.error; } catch {}
    throw new Error(msg);
  }
  return r.json();
}

async function postAdmin(path, body) {
  return fetchJson(path, {
    method: "POST",
    headers: {"Content-Type":"application/json",[CFG.csrf_header]:CFG.csrf_value},
    body: JSON.stringify(body || {}),
  });
}

let toastTimer = null;
function toast(msg, isError) {
  const el = $("toast");
  el.textContent = msg;
  el.classList.toggle("error", !!isError);
  el.classList.add("show");
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 3200);
}

// ── Stats / header ──────────────────────────────────────────────────────────

function renderStats(data) {
  const s = data.stats || {};
  const by = s.by_status || {};
  const running = (by.running || 0) + (by.claimed || 0);

  // Stat cards
  const cards = [
    ["Done",    by.done    || 0],
    ["Running", running],
    ["Queued",  by.queued  || 0],
    ["Failed",  by.failed  || 0],
  ];
  $("stats-grid").innerHTML = cards.map(([label, value]) =>
    `<div class="card"><div class="label">${esc(label)}</div><div class="value">${esc(value)}</div></div>`
  ).join("");

  // Progress
  const total = s.jobs_total || 0;
  const done  = by.done || 0;
  const pct   = total ? Math.round((done * 100) / total) : 0;
  $("progress-bar").style.width = pct + "%";
  $("progress-text").textContent = `${done} of ${total} jobs complete  ·  ${pct}%`;

  // Queue pill
  const paused = !!data.queue_paused;
  $("pill-queue").innerHTML = `Queue: <span class="status-indicator ${paused?"paused":"processing"}">${paused?"Paused":"Active"}</span>`;
  $("pill-workers").textContent = `Workers: ${s.workers_total || 0}`;

  // ETA
  const etaPill = $("pill-eta");
  const avgTxt = data.avg_duration_seconds ? ` · avg ${fmtDuration(data.avg_duration_seconds)}/job` : "";
  if (paused) {
    etaPill.textContent = "ETA: paused";
  } else if (data.eta_seconds && data.eta_seconds > 0) {
    etaPill.textContent = `ETA: ${fmtDuration(data.eta_seconds)}${avgTxt}`;
  } else {
    etaPill.textContent = `ETA: —${avgTxt}`;
  }

  $("pill-updated").textContent = fmtTime(data.now_ts);

  // Pause button
  const btn = $("btn-pause");
  btn.textContent = paused ? "▶ Resume" : "⏸ Pause";

  $("chk-auto-requeue").checked = !!data.auto_requeue_failed;
}

// ── Workers table ───────────────────────────────────────────────────────────

function renderWorkers(workers) {
  const tbody = $("tbody-workers");
  if (!workers.length) {
    tbody.innerHTML = '<tr><td colspan="5" class="empty">No workers connected.</td></tr>';
    return;
  }
  tbody.innerHTML = workers.map((w) => `
    <tr>
      <td style="width:24px;padding-right:0">
        <span class="worker-dot" style="background:${colorForWorker(w.name)}"></span>
      </td>
      <td style="font-weight:500">${esc(w.name)}</td>
      <td>${statusChip(w.status)}</td>
      <td style="color:var(--text-muted);font-size:0.75rem">${esc(w.current_scene || "—")}</td>
      <td style="color:var(--text-muted);font-size:0.75rem">${esc(fmtTime(w.last_seen_ts))}</td>
    </tr>
  `).join("");
}

// ── Jobs table ──────────────────────────────────────────────────────────────

function updateTabCounts(jobs) {
  const by = {all:0, done:0, running:0, queued:0, failed:0};
  for (const j of jobs) {
    by.all++;
    const st = (j.status || "").toLowerCase();
    if (st === "done" || st === "success") by.done++;
    else if (st === "running" || st === "claimed") by.running++;
    else if (st === "queued") by.queued++;
    else if (st === "failed") by.failed++;
  }
  for (const k of Object.keys(by)) {
    const el = $(`tab-cnt-${k}`);
    if (el) el.textContent = by[k];
  }
}

function visibleJobs(jobs) {
  if (jobTabFilter === "all") return jobs;
  return jobs.filter((j) => {
    const st = (j.status || "").toLowerCase();
    if (jobTabFilter === "done")    return st === "done" || st === "success";
    if (jobTabFilter === "running") return st === "running" || st === "claimed";
    if (jobTabFilter === "queued")  return st === "queued";
    if (jobTabFilter === "failed")  return st === "failed";
    return true;
  });
}

function renderJobs(jobs) {
  updateTabCounts(jobs);
  const shown = visibleJobs(jobs);
  const tbody = $("tbody-jobs");

  // Clean up stale selections
  const liveIds = new Set(jobs.map((j) => j.job_id));
  for (const id of Array.from(selectedJobIds)) {
    if (!liveIds.has(id)) selectedJobIds.delete(id);
  }

  if (!shown.length) {
    tbody.innerHTML = `<tr><td colspan="9" class="empty">No jobs${jobTabFilter !== "all" ? " in this filter" : ""}.</td></tr>`;
    updateSelectionUI(0);
    return;
  }

  tbody.innerHTML = shown.map((j) => {
    const checked = selectedJobIds.has(j.job_id) ? "checked" : "";
    const selCls  = checked ? "selected" : "";
    const tip = `Started: ${fmtTs(j.started_at_ts)}&#10;Finished: ${fmtTs(j.finished_at_ts)}`;
    return `
      <tr class="${selCls}" data-job-id="${esc(j.job_id)}">
        <td class="col-check"><input type="checkbox" class="job-check" ${checked}></td>
        <td title="${esc(j.scene_path)}">${esc(j.scene_name || "—")}</td>
        <td title="${esc(j.output_folder)}" style="color:var(--text-muted)">${esc(shortPath(j.output_folder) || "—")}</td>
        <td>${statusChip(j.status)}</td>
        <td>${workerCell(j.worker_name || null)}</td>
        <td title="${tip}" style="font-variant-numeric:tabular-nums">${esc(fmtDuration(j.duration_seconds))}</td>
        <td style="color:var(--text-muted)">${esc(j.attempts)}</td>
        <td style="color:var(--text-muted);font-size:0.75rem">${esc(fmtTime(j.updated_at_ts))}</td>
        <td title="${esc(j.last_error)}" style="color:var(--red);font-size:0.75rem;max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(j.last_error || "—")}</td>
      </tr>`;
  }).join("");

  $("jobs-foot").textContent = `${shown.length} of ${jobs.length} jobs`;
  updateSelectionUI(shown.length);
}

function updateSelectionUI(visibleCount) {
  const n = selectedJobIds.size;
  $("btn-requeue-sel").disabled = n === 0;
  $("btn-remove-sel").disabled  = n === 0;
  $("btn-requeue-sel").textContent = n > 1 ? `Requeue Selected (${n})` : "Requeue Selected";
  $("btn-remove-sel").textContent  = n > 1 ? `Remove Selected (${n})`  : "Remove Selected";
  $("chk-all").checked       = visibleCount > 0 && n >= visibleCount;
  $("chk-all").indeterminate = n > 0 && n < visibleCount;
}

// ── Main load ───────────────────────────────────────────────────────────────

async function loadData() {
  try {
    const data = await fetchJson("/dashboard_data");
    lastSnapshot = data;
    renderStats(data);
    renderWorkers(data.workers || []);
    renderJobs(data.jobs || []);
    renderPerformance(data);
  } catch (e) {
    toast("Could not refresh: " + e.message, true);
  }
}

// ── Performance panel ───────────────────────────────────────────────────────

function workerUniverse(data) {
  const seen = new Set();
  for (const w of (data.workers || [])) if (w.name) seen.add(w.name);
  for (const j of (data.jobs   || [])) if (j.worker_name) seen.add(j.worker_name);
  return Array.from(seen).sort();
}

function filterJobsForPerf(data) {
  const now = data.now_ts || (Date.now() / 1000);
  const cutoff = perfFilter.windowMode === "1h"  ? now - 3600
               : perfFilter.windowMode === "24h" ? now - 86400
               : 0;
  const statusSet = perfFilter.statusMode === "done_failed"
    ? new Set(["done","failed"]) : new Set(["done"]);
  const wantWorker = perfFilter.workers.size === 0 ? null : perfFilter.workers;

  return (data.jobs || []).filter((j) => {
    if (!statusSet.has((j.status || "").toLowerCase())) return false;
    if (!j.started_at_ts || !j.finished_at_ts) return false;
    if (j.finished_at_ts < cutoff) return false;
    if (wantWorker && !wantWorker.has(j.worker_name)) return false;
    return true;
  });
}

function median(nums) {
  if (!nums.length) return 0;
  const s = nums.slice().sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m-1] + s[m]) / 2;
}

function renderWorkerChips(data) {
  const universe = workerUniverse(data);
  const group    = $("worker-chips");
  const allBtn   = group.querySelector("[data-worker-all]");
  for (const el of Array.from(group.querySelectorAll(".chip-btn:not([data-worker-all])"))) el.remove();
  for (const name of Array.from(perfFilter.workers)) {
    if (!universe.includes(name)) perfFilter.workers.delete(name);
  }
  for (const name of universe) {
    const btn = document.createElement("button");
    btn.className = "chip-btn";
    btn.dataset.worker = name;
    btn.innerHTML = `<span class="chip-dot" style="background:${colorForWorker(name)}"></span>${esc(name)}`;
    if (perfFilter.workers.has(name)) btn.classList.add("active");
    group.appendChild(btn);
  }
  allBtn.classList.toggle("active", perfFilter.workers.size === 0);
}

function renderStatStrip(filteredJobs) {
  const n    = filteredJobs.length;
  const durs = filteredJobs.map((j) => j.duration_seconds || 0).filter((d) => d > 0);
  const sum  = durs.reduce((a, b) => a + b, 0);
  $("stat-count").textContent  = n || "—";
  $("stat-avg").textContent    = durs.length ? fmtDuration(sum / durs.length) : "—";
  $("stat-median").textContent = durs.length ? fmtDuration(median(durs)) : "—";
  $("stat-min").textContent    = durs.length ? fmtDuration(Math.min(...durs)) : "—";
  $("stat-max").textContent    = durs.length ? fmtDuration(Math.max(...durs)) : "—";
}

// ── SVG chart helpers ───────────────────────────────────────────────────────

function svgText(x, y, text, attrs = "") {
  return `<text x="${x}" y="${y}" ${attrs}>${esc(text)}</text>`;
}

// ── Pie / donut chart ───────────────────────────────────────────────────────

function describeArc(cx, cy, r, startAngle, endAngle) {
  const rad = (a) => (a - 90) * Math.PI / 180;
  const x1 = cx + r * Math.cos(rad(startAngle));
  const y1 = cy + r * Math.sin(rad(startAngle));
  const x2 = cx + r * Math.cos(rad(endAngle));
  const y2 = cy + r * Math.sin(rad(endAngle));
  const large = (endAngle - startAngle) > 180 ? 1 : 0;
  return `M ${x1} ${y1} A ${r} ${r} 0 ${large} 1 ${x2} ${y2}`;
}

function renderPieChart(el, filteredJobs) {
  if (!filteredJobs.length) {
    el.innerHTML = '<div class="chart-empty">No data for selected filters.</div>';
    return;
  }
  const byWorker = {};
  for (const j of filteredJobs) {
    const n = j.worker_name || "Unknown";
    byWorker[n] = (byWorker[n] || 0) + 1;
  }
  const workers = Object.keys(byWorker).sort((a, b) => byWorker[b] - byWorker[a]);
  const total   = filteredJobs.length;

  const W = 220, H = 180;
  const cx = 80, cy = 85, rOuter = 62, rInner = 36;
  const gap = 2;

  let angle = 0;
  const arcs = workers.map((name) => {
    const frac  = byWorker[name] / total;
    const sweep = frac * 360 - gap;
    const start = angle;
    const end   = angle + sweep;
    angle += frac * 360;
    return { name, count: byWorker[name], frac, start, end };
  });

  let paths = arcs.map(({ name, start, end }) => {
    const col = colorForWorker(name);
    const d1 = describeArc(cx, cy, rOuter, start, end);
    const d2 = describeArc(cx, cy, rInner, end, start);
    const d  = `${d1} L ${cx + rInner * Math.cos((end - 90) * Math.PI / 180)} ${cy + rInner * Math.sin((end - 90) * Math.PI / 180)} ${d2} Z`;
    return `<path d="${d}" fill="${col}" stroke="none" opacity="0.92"/>`;
  }).join("");

  // Center label
  const centerLabel = `
    <text x="${cx}" y="${cy - 6}" text-anchor="middle" font-size="20" font-weight="600" fill="var(--text)">${total}</text>
    <text x="${cx}" y="${cy + 10}" text-anchor="middle" font-size="10" fill="var(--text-muted)">jobs</text>`;

  // Legend rows
  const legendX = 156;
  let legendY = 24;
  const legendRows = arcs.map(({ name, count, frac }) => {
    const pct = Math.round(frac * 100);
    const row = `
      <circle cx="${legendX}" cy="${legendY}" r="4" fill="${colorForWorker(name)}"/>
      <text x="${legendX + 10}" y="${legendY + 4}" font-size="11" fill="var(--text)">${esc(name)}</text>
      <text x="${W - 4}" y="${legendY + 4}" text-anchor="end" font-size="10" fill="var(--text-muted)">${count} · ${pct}%</text>`;
    legendY += 20;
    return row;
  }).join("");

  // Insight
  const topWorker = arcs[0];
  let insight = "";
  if (topWorker && arcs.length > 1) {
    insight = `${topWorker.name} handled the most jobs (${Math.round(topWorker.frac * 100)}%).`;
  } else if (topWorker) {
    insight = `${topWorker.name} handled all ${total} jobs.`;
  }

  el.innerHTML = `
    <svg width="100%" viewBox="0 0 ${W} ${H}" style="max-height:200px">
      <g>${paths}</g>
      ${centerLabel}
      <g>${legendRows}</g>
    </svg>
    ${insight ? `<div class="chart-insight">${esc(insight)}</div>` : ""}`;
}

// ── Horizontal bar chart ────────────────────────────────────────────────────

function renderBarChart(el, filteredJobs) {
  if (!filteredJobs.length) {
    el.innerHTML = '<div class="chart-empty">No data for selected filters.</div>';
    return;
  }
  const dursByWorker = {};
  for (const j of filteredJobs) {
    const n = j.worker_name || "Unknown";
    if (!dursByWorker[n]) dursByWorker[n] = [];
    if ((j.duration_seconds || 0) > 0) dursByWorker[n].push(j.duration_seconds);
  }
  const workers = Object.keys(dursByWorker).sort((a, b) => {
    const aA = dursByWorker[a].reduce((s, v) => s + v, 0) / (dursByWorker[a].length || 1);
    const bA = dursByWorker[b].reduce((s, v) => s + v, 0) / (dursByWorker[b].length || 1);
    return aA - bA;
  });

  if (!workers.length) {
    el.innerHTML = '<div class="chart-empty">No duration data.</div>';
    return;
  }

  const avgs   = workers.map((n) => {
    const d = dursByWorker[n];
    return d.length ? d.reduce((a, b) => a + b, 0) / d.length : 0;
  });
  const maxAvg = Math.max(...avgs, 1);

  const W = 300, barH = 22, gap = 10, labelW = 90, barMaxW = W - labelW - 56;
  const H = workers.length * (barH + gap) + 16;

  let bars = "";
  workers.forEach((name, i) => {
    const avg  = avgs[i];
    const bw   = Math.round((avg / maxAvg) * barMaxW);
    const y    = 8 + i * (barH + gap);
    const col  = colorForWorker(name);
    bars += `
      <text x="${labelW - 6}" y="${y + barH / 2 + 4}" text-anchor="end" font-size="11" fill="var(--text)">${esc(name)}</text>
      <rect x="${labelW}" y="${y}" width="${bw}" height="${barH}" rx="3" fill="${col}" opacity="0.85"/>
      <text x="${labelW + bw + 5}" y="${y + barH / 2 + 4}" font-size="10" fill="var(--text-muted)">${fmtDuration(avg)}</text>`;
  });

  // Insight
  const minW = workers[0], maxW = workers[workers.length - 1];
  let insight = "";
  if (workers.length > 1) {
    const ratio = avgs[avgs.length - 1] / avgs[0];
    insight = `${esc(minW)} fastest · ${esc(maxW)} ~${Math.round((ratio - 1) * 100)}% slower.`;
  }

  el.innerHTML = `
    <svg width="100%" viewBox="0 0 ${W} ${H}" style="max-height:220px">
      ${bars}
    </svg>
    ${insight ? `<div class="chart-insight">${insight}</div>` : ""}`;
}

// ── Swimlane timeline ───────────────────────────────────────────────────────

function renderSwimlane(el, filteredJobs) {
  if (!filteredJobs.length) {
    el.innerHTML = '<div class="chart-empty">No data for selected filters.</div>';
    return;
  }

  // Collect workers with at least one job that has time data
  const workerMap = {};
  for (const j of filteredJobs) {
    if (!j.started_at_ts || !j.finished_at_ts) continue;
    const n = j.worker_name || "Unknown";
    if (!workerMap[n]) workerMap[n] = [];
    workerMap[n].push(j);
  }
  const workers = Object.keys(workerMap).sort();
  if (!workers.length) {
    el.innerHTML = '<div class="chart-empty">No timeline data (jobs need started/finished timestamps).</div>';
    return;
  }

  // Time window: now - window, or earliest job start
  const now = lastSnapshot ? (lastSnapshot.now_ts || Date.now() / 1000) : Date.now() / 1000;
  const allStarts    = filteredJobs.map((j) => j.started_at_ts).filter(Boolean);
  const earliestJob  = allStarts.length ? Math.min(...allStarts) : now - 3600;
  const windowStart  = Math.min(earliestJob - 60, now - 3600);
  const windowEnd    = now;
  const windowSecs   = Math.max(windowEnd - windowStart, 60);

  const W = 600, rowH = 28, gap = 8, labelW = 80, axisH = 20, paddingTop = 4;
  const barH   = 18;
  const barArea = W - labelW - 8;
  const H = workers.length * (rowH + gap) + axisH + paddingTop;

  const tx = (ts) => labelW + Math.round(((ts - windowStart) / windowSecs) * barArea);

  // Time axis ticks (5 evenly spaced)
  const ticks = [];
  for (let i = 0; i <= 4; i++) {
    const ts  = windowStart + (windowSecs * i) / 4;
    const x   = tx(ts);
    const rel = ts - now;
    let label;
    if (Math.abs(rel) < 30) label = "now";
    else {
      const mins = Math.round(Math.abs(rel) / 60);
      label = rel < 0 ? `-${mins}m` : `+${mins}m`;
    }
    ticks.push({ x, label });
  }

  let axisG = ticks.map(({ x, label }) =>
    `<line x1="${x}" y1="${paddingTop}" x2="${x}" y2="${H - axisH}" stroke="var(--border)" stroke-width="1" opacity="0.5"/>
     <text x="${x}" y="${H}" text-anchor="middle" font-size="9" fill="var(--text-muted)">${esc(label)}</text>`
  ).join("");

  let rowsG = "";
  workers.forEach((name, i) => {
    const y    = paddingTop + i * (rowH + gap);
    const jobs = workerMap[name];
    const col  = colorForWorker(name);

    rowsG += `<text x="${labelW - 6}" y="${y + rowH / 2 + 4}" text-anchor="end" font-size="10" fill="var(--text)">${esc(name)}</text>`;

    // Row background
    rowsG += `<rect x="${labelW}" y="${y + 5}" width="${barArea}" height="${rowH - 10}" rx="2" fill="var(--bg-card)" opacity="0.5"/>`;

    for (const j of jobs) {
      const x1  = tx(j.started_at_ts);
      const x2  = tx(j.finished_at_ts);
      const bw  = Math.max(x2 - x1, 3);
      const bx  = Math.max(x1, labelW);
      const clipped = Math.min(bx + bw, labelW + barArea) - bx;
      if (clipped <= 0) continue;
      const dur = fmtDuration(j.duration_seconds);
      rowsG += `<rect x="${bx}" y="${y + 6}" width="${clipped}" height="${barH - 4}" rx="2" fill="${col}" opacity="0.85">
        <title>${esc(j.scene_name || j.job_id)} · ${esc(dur)}</title>
      </rect>`;
    }
  });

  el.innerHTML = `
    <svg width="100%" viewBox="0 0 ${W} ${H}" style="min-height:120px">
      <g>${axisG}</g>
      <g>${rowsG}</g>
    </svg>`;
}

// ── Render all performance charts ───────────────────────────────────────────

function renderPerformance(data) {
  renderWorkerChips(data);
  const filtered = filterJobsForPerf(data);
  renderStatStrip(filtered);
  renderPieChart($("chart-pie"), filtered);
  renderBarChart($("chart-bars"), filtered);
  renderSwimlane($("chart-swimlane"), filtered);
}

// ── Action handlers ─────────────────────────────────────────────────────────

async function actRequeueSelected() {
  const ids = Array.from(selectedJobIds);
  if (!ids.length) return;
  if (ids.length > 1 && !confirm(`Requeue ${ids.length} job(s)?`)) return;
  try {
    const r = await postAdmin("/admin/jobs/requeue", { job_ids: ids });
    toast(`Requeued ${r.count} job(s).`);
    selectedJobIds.clear();
    await loadData();
  } catch (e) { toast("Requeue failed: " + e.message, true); }
}

async function actRemoveSelected() {
  const ids = Array.from(selectedJobIds);
  if (!ids.length) return;
  if (!confirm(`Remove ${ids.length} job(s)?`)) return;
  try {
    const r = await postAdmin("/admin/jobs/remove", { job_ids: ids });
    toast(`Removed ${r.removed} job(s).`);
    selectedJobIds.clear();
    await loadData();
  } catch (e) { toast("Remove failed: " + e.message, true); }
}

async function actClearQueue() {
  if (!confirm("Remove all queued jobs?")) return;
  try {
    const r = await postAdmin("/admin/jobs/clear_queue", {});
    toast(`Cleared ${r.removed} queued job(s).`);
    await loadData();
  } catch (e) { toast("Clear queue failed: " + e.message, true); }
}

async function actRemoveDone() {
  if (!confirm("Remove all done jobs?")) return;
  try {
    const r = await postAdmin("/admin/jobs/remove_by_status", { statuses: ["done","success"] });
    toast(`Removed ${r.removed} done job(s).`);
    await loadData();
  } catch (e) { toast("Remove done failed: " + e.message, true); }
}

async function actRemoveFailed() {
  if (!confirm("Remove all failed jobs?")) return;
  try {
    const r = await postAdmin("/admin/jobs/remove_by_status", { statuses: ["failed"] });
    toast(`Removed ${r.removed} failed job(s).`);
    await loadData();
  } catch (e) { toast("Remove failed: " + e.message, true); }
}

async function actClearAll() {
  if (!confirm("Remove ALL jobs?")) return;
  try {
    const r = await postAdmin("/admin/jobs/clear_all", {});
    toast(`Removed ${r.removed} job(s).`);
    selectedJobIds.clear();
    await loadData();
  } catch (e) { toast("Clear all failed: " + e.message, true); }
}

async function actTogglePause() {
  if (!lastSnapshot) return;
  const next = !lastSnapshot.queue_paused;
  try {
    await postAdmin("/admin/queue/pause", { paused: next });
    toast(next ? "Queue paused." : "Queue resumed.");
    await loadData();
  } catch (e) { toast("Toggle pause failed: " + e.message, true); }
}

async function actToggleAutoRequeue() {
  const enabled = $("chk-auto-requeue").checked;
  try {
    await postAdmin("/admin/auto_requeue", { enabled });
    toast(enabled ? "Auto-requeue enabled." : "Auto-requeue disabled.");
    await loadData();
  } catch (e) { toast("Toggle auto-requeue failed: " + e.message, true); }
}

// ── Event wiring ─────────────────────────────────────────────────────────────

function onRowChecked(ev) {
  const cb = ev.target;
  if (!cb.classList || !cb.classList.contains("job-check")) return;
  const tr = cb.closest("tr");
  if (!tr) return;
  const id = tr.getAttribute("data-job-id");
  if (!id) return;
  if (cb.checked) { selectedJobIds.add(id); tr.classList.add("selected"); }
  else            { selectedJobIds.delete(id); tr.classList.remove("selected"); }
  updateSelectionUI(lastSnapshot ? visibleJobs(lastSnapshot.jobs || []).length : 0);
}

function onCheckAll() {
  const checked = $("chk-all").checked;
  const jobs    = lastSnapshot ? visibleJobs(lastSnapshot.jobs || []) : [];
  if (checked) for (const j of jobs) selectedJobIds.add(j.job_id);
  else selectedJobIds.clear();
  renderJobs(lastSnapshot ? (lastSnapshot.jobs || []) : []);
}

function onWorkerChipClick(ev) {
  const btn = ev.target.closest(".chip-btn");
  if (!btn) return;
  if (btn.hasAttribute("data-worker-all")) {
    perfFilter.workers.clear();
  } else {
    const name = btn.dataset.worker;
    if (!name) return;
    if (perfFilter.workers.has(name)) perfFilter.workers.delete(name);
    else perfFilter.workers.add(name);
  }
  if (lastSnapshot) renderPerformance(lastSnapshot);
}

function onPerfFilterChange() {
  perfFilter.statusMode = $("perf-status").value;
  perfFilter.windowMode = $("perf-window").value;
  if (lastSnapshot) renderPerformance(lastSnapshot);
}

function onJobTabClick(ev) {
  const btn = ev.target.closest(".job-tab");
  if (!btn) return;
  jobTabFilter = btn.dataset.tab || "all";
  for (const t of document.querySelectorAll(".job-tab")) t.classList.toggle("active", t.dataset.tab === jobTabFilter);
  if (lastSnapshot) renderJobs(lastSnapshot.jobs || []);
}

function wire() {
  $("tbody-jobs").addEventListener("change", onRowChecked);
  $("chk-all").addEventListener("change", onCheckAll);
  $("btn-requeue-sel").addEventListener("click", actRequeueSelected);
  $("btn-remove-sel").addEventListener("click", actRemoveSelected);
  $("btn-clear-queue").addEventListener("click", actClearQueue);
  $("btn-remove-done").addEventListener("click", actRemoveDone);
  $("btn-remove-failed").addEventListener("click", actRemoveFailed);
  $("btn-clear-all").addEventListener("click", actClearAll);
  $("btn-pause").addEventListener("click", actTogglePause);
  $("chk-auto-requeue").addEventListener("change", actToggleAutoRequeue);
  $("worker-chips").addEventListener("click", onWorkerChipClick);
  $("perf-status").addEventListener("change", onPerfFilterChange);
  $("perf-window").addEventListener("change", onPerfFilterChange);
  $("job-tabs").addEventListener("click", onJobTabClick);
}

wire();
loadData();
setInterval(loadData, CFG.poll_ms);
"""

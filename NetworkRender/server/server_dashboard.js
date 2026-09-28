const $ = (id) => document.getElementById(id);
const selectedJobIds = new Set();
let lastSnapshot = null;
let jobTabFilter = "all";

// Queue drag-reorder state. While a drag is in progress we suspend polling so a
// background refresh can't rebuild the table out from under the dragged row.
let dragSrcId = null;
let dragging = false;

// Anchor row for shift-range selection (last row clicked without shift).
let selectionAnchorId = null;

// Job ids currently open in the edit modal (one for single edit, many for a
// multi-select edit). While non-empty, polling is suspended so a background
// refresh can't overwrite the form values the user is editing.
let editingJobIds = [];

// Mode of the shared job modal: "edit" (existing job(s)), "new" (compose a
// submission for POST /submit) or null when closed. Only edit mode suspends
// polling (via editingJobIds): a New Job form isn't prefilled from the
// snapshot, so a background refresh can't disturb it.
let modalMode = null;

const perfFilter = {
  workers: new Set(),
  statusMode: "done",
  windowMode: "all",
};

// ── Color helpers ────────────────────────────────────────────────────────────

// ── Worker color registry ─────────────────────────────────────────────────────
// Hues are assigned on first encounter to maximise spacing on the hue wheel.
// All workers share the same saturation and lightness for visual consistency.
// Assignments persist in localStorage so the same worker always gets the same color.

const _WS = 65, _WL = 62;  // saturation %, lightness %

const _workerHues = (() => {
  try { return JSON.parse(localStorage.getItem("vb_worker_hues") || "{}"); }
  catch { return {}; }
})();

function _saveWorkerHues() {
  try { localStorage.setItem("vb_worker_hues", JSON.stringify(_workerHues)); }
  catch {}
}

function _assignHue(name) {
  if (_workerHues[name] !== undefined) return _workerHues[name];
  const taken = Object.values(_workerHues).sort((a, b) => a - b);
  let hue;
  if (!taken.length) {
    // First worker: derive starting hue from name hash so it isn't always the same
    let h = 0;
    for (let i = 0; i < name.length; i++) h = ((h * 31) + name.charCodeAt(i)) >>> 0;
    hue = h % 360;
  } else {
    // Bisect the largest gap on the circular hue wheel
    let bestGap = 0;
    const n = taken.length;
    for (let i = 0; i < n; i++) {
      const a = taken[i];
      const b = taken[(i + 1) % n];
      const gap = (i === n - 1) ? (360 - a + b) : (b - a);
      if (gap > bestGap) {
        bestGap = gap;
        hue = (i === n - 1) ? (a + gap / 2) % 360 : a + gap / 2;
      }
    }
  }
  _workerHues[name] = Math.round(hue);
  _saveWorkerHues();
  return _workerHues[name];
}

// Worker-chosen colors sent by the server, keyed by display name. Populated
// from each snapshot and kept across snapshots so a worker keeps its color in
// the charts even after it disconnects. A worker color overrides the auto hue.
const _serverColors = {};

function normalizeHex(v) {
  if (!v) return "";
  const s = String(v).trim();
  return /^#[0-9a-fA-F]{6}$/.test(s) ? s.toLowerCase() : "";
}

function updateServerColors(workers) {
  for (const w of (workers || [])) {
    const hex = normalizeHex(w.color);
    if (w.name && hex) _serverColors[w.name] = hex;
  }
}

function _colorsFromHex(hex) {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return {
    color:  hex,
    tint:   `rgba(${r},${g},${b},0.15)`,
    faint:  `rgba(${r},${g},${b},0.10)`,
    border: `rgba(${r},${g},${b},0.35)`,
  };
}

function workerColors(name) {
  const key = String(name || "unknown");
  const custom = _serverColors[key];
  if (custom) return _colorsFromHex(custom);
  const h = _assignHue(key);
  return {
    color:  `hsl(${h},${_WS}%,${_WL}%)`,
    tint:   `hsla(${h},${_WS}%,${_WL}%,0.15)`,
    faint:  `hsla(${h},${_WS}%,${_WL}%,0.10)`,
    border: `hsla(${h},${_WS}%,${_WL}%,0.35)`,
  };
}

function colorForWorker(name) { return workerColors(name).color; }

// ── Formatters ───────────────────────────────────────────────────────────────

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
  } catch { return "—"; }
}

function fmtTime(ts) {
  if (!ts) return "—";
  try {
    const d = new Date(ts * 1000);
    const p = (n) => String(n).padStart(2, "0");
    return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
  } catch { return "—"; }
}

// HTML-escape for both element content and attribute values. Quotes must be
// escaped too: error text (which often quotes paths) is embedded in
// data-copy="…" and title="…" attributes.
function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// Clipboard glyph for the copy-output-path button.
const COPY_ICON = `<svg viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"><rect x="5.5" y="5.5" width="8.5" height="9" rx="1.5"/><path d="M3.5 10.5h-1a1 1 0 0 1-1-1v-7a1 1 0 0 1 1-1h7a1 1 0 0 1 1 1v1"/></svg>`;

// Drag-handle glyph shown on queued rows (drag to reorder the queue).
const GRIP_ICON = `<svg viewBox="0 0 16 16" width="12" height="12" fill="currentColor"><circle cx="6" cy="4" r="1.3"/><circle cx="10" cy="4" r="1.3"/><circle cx="6" cy="8" r="1.3"/><circle cx="10" cy="8" r="1.3"/><circle cx="6" cy="12" r="1.3"/><circle cx="10" cy="12" r="1.3"/></svg>`;

// Pencil glyph for the per-row edit button.
const EDIT_ICON = `<svg viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round" stroke-linecap="round"><path d="M11.5 2.5l2 2L6 12l-2.5.5L4 10z"/><path d="M10.5 3.5l2 2"/></svg>`;

// Windows-native (backslash) form so the copied value pastes straight into Explorer.
function toNativePath(p) {
  return String(p || "").replace(/\//g, "\\");
}

// Folder containing a file (either slash style). The scene copy button copies
// this instead of the full scene path: pasting a .max path into Explorer's
// address bar would launch 3ds Max, pasting the folder just opens it.
function parentDir(p) {
  const s = String(p || "");
  const i = Math.max(s.lastIndexOf("/"), s.lastIndexOf("\\"));
  return i > 0 ? s.slice(0, i) : "";
}

// Clipboard write with a fallback for non-secure contexts. The dashboard is
// reachable over plain HTTP on the LAN, where navigator.clipboard is unavailable.
async function copyText(text) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {}
  try {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(ta);
    return ok;
  } catch { return false; }
}

function statusChip(status) {
  const norm = String(status || "").trim().toLowerCase();
  const cls = ({queued:"queued",claimed:"running",running:"running",done:"done",success:"done",failed:"failed",idle:"idle"})[norm] || "idle";
  return `<span class="chip ${cls}">${esc(status||"-")}</span>`;
}

function workerCell(name) {
  if (!name || name === "-") return `<span style="color:var(--text-muted)">—</span>`;
  const { color, faint, border } = workerColors(name);
  return `<span class="worker-pill" style="color:${color};background:${faint};border-color:${border}">
    <span style="display:inline-block;width:7px;height:7px;border-radius:50%;background:${color};flex-shrink:0"></span>${esc(name)}
  </span>`;
}

function shortPath(p, parts = 3) {
  if (!p) return "";
  const norm = p.replace(/\\/g, "/").replace(/\/+/g, "/");
  const chunks = norm.split("/").filter(Boolean);
  return chunks.length <= parts ? norm : "…/" + chunks.slice(-parts).join("/");
}

// ── Network ──────────────────────────────────────────────────────────────────

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

// ── Stats / header ───────────────────────────────────────────────────────────

function renderStats(data) {
  const s  = data.stats || {};
  const by = s.by_status || {};
  const running = (by.running || 0) + (by.claimed || 0);
  const total   = s.jobs_total || 0;
  const done    = by.done || 0;
  const queued  = by.queued || 0;
  const failed  = by.failed || 0;
  const pct     = total ? Math.round((done * 100) / total) : 0;

  // Top bar
  $("pill-workers").textContent = `Workers ${s.workers_total || 0}`;
  const paused = !!data.queue_paused;
  $("pill-queue").innerHTML = `<span class="status-indicator ${paused?"paused":"processing"}">${paused?"Paused":"Active"}</span>`;
  $("pill-updated").textContent = fmtTime(data.now_ts);
  $("btn-pause").textContent = paused ? "▶ Resume" : "⏸ Pause";

  const avgTxt = data.avg_duration_seconds ? fmtDuration(data.avg_duration_seconds) : "—";
  if (paused) {
    $("pill-eta").textContent = "ETA paused";
  } else if (data.eta_seconds && data.eta_seconds > 0) {
    $("pill-eta").textContent = `ETA ${fmtDuration(data.eta_seconds)}`;
  } else {
    $("pill-eta").textContent = "ETA —";
  }

  // Progress left column
  $("progress-pct").textContent = pct + "%";
  $("progress-done").textContent = done;
  $("progress-bar").style.width = pct + "%";
  $("progress-text").textContent = `of ${total} jobs complete`;

  // Stat row
  $("si-done").textContent    = done;
  $("si-running").textContent = running;
  $("si-queued").textContent  = queued;
  $("si-failed").textContent  = failed;

  const etaPart = (data.eta_seconds && data.eta_seconds > 0) ? `eta ${fmtDuration(data.eta_seconds)}` : "eta —";
  const frozenPart = data.frozen_count > 0 ? ` · ${data.frozen_count} frozen` : "";
  $("stats-meta").textContent = `avg ${avgTxt} · ${etaPart}${frozenPart}`;

  $("chk-auto-requeue").checked = !!data.auto_requeue_failed;
}

// ── Workers ──────────────────────────────────────────────────────────────────

function renderWorkers(workers) {
  const list = $("workers-list");
  const onlineCount = workers.filter((w) => w.status !== "offline").length;
  const allIdle     = workers.every((w) => (w.status || "").toLowerCase() === "idle");
  $("workers-status").textContent = workers.length
    ? `${onlineCount} online · ${allIdle ? "all idle" : "working"}`
    : "none connected";

  if (!workers.length) {
    list.innerHTML = '<div class="worker-row"><div class="worker-item__left"><div><div class="worker-item__name" style="color:var(--text-muted)">No workers connected.</div></div></div></div>';
    return;
  }

  list.innerHTML = workers.map((w) => {
    const { color, tint } = workerColors(w.name);
    const sub = w.current_scene
      ? esc(shortPath(w.current_scene, 2))
      : `last seen ${esc(fmtTime(w.last_seen_ts))}`;
    return `
    <div class="worker-row" style="--worker-color:${color};--worker-tint:${tint}">
      <div class="worker-item__left">
        <div class="worker-item__dot"></div>
        <div>
          <div class="worker-item__name">${esc(w.name)}</div>
          <div class="worker-item__meta">${sub}</div>
        </div>
      </div>
      <div class="worker-item__right">
        ${statusChip(w.status)}
      </div>
    </div>`;
  }).join("");
}

// ── Jobs table ───────────────────────────────────────────────────────────────

function updateTabCounts(jobs) {
  const by = {all:0, done:0, running:0, queued:0, failed:0};
  for (const j of jobs) {
    by.all++;
    const st = (j.status || "").toLowerCase();
    if (st === "done" || st === "success")       by.done++;
    else if (st === "running" || st === "claimed") by.running++;
    else if (st === "queued")                      by.queued++;
    else if (st === "failed")                      by.failed++;
  }
  for (const k of Object.keys(by)) {
    const el = $(`tab-cnt-${k}`);
    if (el) el.textContent = by[k];
  }
  $("jobs-total-badge").textContent = `${jobs.length} total`;
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
  let shown = visibleJobs(jobs);
  const tbody = $("tbody-jobs");

  // On the Queued tab, show rows in true queue (claim) order so drag-reorder
  // reflects reality. Other tabs keep the default created-at order.
  const isQueuedTab = jobTabFilter === "queued";
  if (isQueuedTab) {
    shown = shown.slice().sort(
      (a, b) => (a.queue_position ?? Infinity) - (b.queue_position ?? Infinity)
    );
  }

  const liveIds = new Set(jobs.map((j) => j.job_id));
  for (const id of Array.from(selectedJobIds)) {
    if (!liveIds.has(id)) selectedJobIds.delete(id);
  }

  if (!shown.length) {
    tbody.innerHTML = `<tr><td colspan="10" class="empty">No jobs${jobTabFilter !== "all" ? " in this filter" : ""}.</td></tr>`;
    updateSelectionUI(0);
    return;
  }

  tbody.innerHTML = shown.map((j) => {
    const selCls = selectedJobIds.has(j.job_id) ? "selected" : "";
    const tip = `Started: ${fmtTs(j.started_at_ts)}\nFinished: ${fmtTs(j.finished_at_ts)}`;
    const outFolder = j.output_folder || "";
    const outCell = outFolder
      ? `<div class="out-wrap">
          <span class="out-path" title="${esc(outFolder)}">${esc(shortPath(outFolder))}</span>
          <button class="copy-btn" data-copy="${esc(outFolder)}" data-msg="Output path copied — paste into Explorer" title="Copy path for Explorer" aria-label="Copy output path">${COPY_ICON}</button>
        </div>`
      : `<span style="color:var(--text-muted)">—</span>`;
    const sceneDir = parentDir(j.scene_path);
    const sceneCell = `<div class="cell-copy">
          <span class="cell-text" title="${esc(j.scene_path)}">${esc(j.scene_name || "—")}</span>
          ${sceneDir ? `<button class="copy-btn" data-copy="${esc(sceneDir)}" data-msg="Scene folder copied — paste into Explorer" title="Copy scene folder for Explorer" aria-label="Copy scene folder">${COPY_ICON}</button>` : ""}
        </div>`;
    const errCell = j.last_error
      ? `<div class="cell-copy">
          <span class="cell-text err-text" title="${esc(j.last_error)}">${esc(j.last_error)}</span>
          <button class="copy-btn" data-copy="${esc(j.last_error)}" data-raw="1" data-msg="Error copied" title="Copy full error text" aria-label="Copy error text">${COPY_ICON}</button>
        </div>`
      : `<span style="color:var(--text-muted)">—</span>`;
    const rowCls = selCls
      + (isQueuedTab ? " draggable-row" : "")
      + (j.frozen ? " frozen-row" : "");
    const dragAttr = isQueuedTab ? ' draggable="true"' : "";
    const grip = isQueuedTab
      ? `<span class="drag-grip" title="Drag to reorder">${GRIP_ICON}</span>`
      : "";
    const statusCell = j.frozen
      ? `<span class="chip frozen" title="Frozen — skipped until unfrozen">❄ frozen</span>`
      : statusChip(j.status);
    return `<tr class="${rowCls.trim()}" data-job-id="${esc(j.job_id)}"${dragAttr}>
      <td class="col-grip">${grip}</td>
      <td class="col-scene">${sceneCell}</td>
      <td class="col-output">${outCell}</td>
      <td>${statusCell}</td>
      <td>${workerCell(j.worker_name || null)}</td>
      <td title="${esc(tip)}" style="font-variant-numeric:tabular-nums">${esc(fmtDuration(j.duration_seconds))}</td>
      <td style="color:var(--text-muted)">${esc(j.attempts)}</td>
      <td style="color:var(--text-muted);font-size:0.75rem">${esc(fmtTime(j.updated_at_ts))}</td>
      <td class="col-error">${errCell}</td>
      <td class="col-edit"><button class="edit-btn" data-edit="${esc(j.job_id)}" title="Edit render/output settings" aria-label="Edit job settings">${EDIT_ICON}</button></td>
    </tr>`;
  }).join("");

  $("jobs-foot").textContent = `${shown.length} of ${jobs.length} jobs`;
  updateSelectionUI(shown.length);
}

// What actions the current selection supports. Drives which context-menu items
// are enabled. Freeze/unfreeze only apply to queued jobs (frozen vs not).
function selectionCaps() {
  const n = selectedJobIds.size;
  let freezable = 0, unfreezable = 0;
  if (lastSnapshot) {
    const byId = new Map((lastSnapshot.jobs || []).map((j) => [j.job_id, j]));
    for (const id of selectedJobIds) {
      const j = byId.get(id);
      if (!j || (j.status || "").toLowerCase() !== "queued") continue;
      if (j.frozen) unfreezable++; else freezable++;
    }
  }
  return { count: n, freezable, unfreezable };
}

// Selection actions now live in the right-click context menu, so there are no
// per-selection buttons to toggle here. Kept as a no-op hook (renderJobs and the
// selection handlers still call it) in case bar-level selection UI returns.
function updateSelectionUI(visibleCount) {}

// ── Main load ────────────────────────────────────────────────────────────────

async function loadData() {
  if (dragging) return;   // don't rebuild the table mid-drag
  if (editingJobIds.length) return;   // don't disturb the open edit modal
  try {
    const data = await fetchJson("/dashboard_data");
    lastSnapshot = data;
    updateServerColors(data.workers || []);
    renderStats(data);
    renderWorkers(data.workers || []);
    renderJobs(data.jobs || []);
    renderPerformance(data);
  } catch (e) {
    toast("Could not refresh: " + e.message, true);
  }
}

// ── Performance panel ────────────────────────────────────────────────────────

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
    btn.innerHTML = `<span class="chip-dot" style="background:${workerColors(name).color}"></span>${esc(name)}`;
    if (perfFilter.workers.has(name)) btn.classList.add("active");
    group.appendChild(btn);
  }
  allBtn.classList.toggle("active", perfFilter.workers.size === 0);
}

function renderStatStrip(filteredJobs) {
  const n    = filteredJobs.length;
  const durs = filteredJobs.map((j) => j.duration_seconds || 0).filter((d) => d > 0);
  const sum  = durs.reduce((a, b) => a + b, 0);
  $("stat-count").textContent  = n  || "—";
  $("stat-avg").textContent    = durs.length ? fmtDuration(sum / durs.length) : "—";
  $("stat-median").textContent = durs.length ? fmtDuration(median(durs)) : "—";
  $("stat-min").textContent    = durs.length ? fmtDuration(Math.min(...durs)) : "—";
  $("stat-max").textContent    = durs.length ? fmtDuration(Math.max(...durs)) : "—";
}

// ── SVG chart helpers ─────────────────────────────────────────────────────────

// ── Pie / donut ───────────────────────────────────────────────────────────────

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

  const W = 240, H = 180;
  const cx = 80, cy = 82, rO = 60, rI = 34;
  const r  = (rO + rI) / 2;          // stroke centerline radius
  const sw = rO - rI;                // ring thickness
  const C  = 2 * Math.PI * r;        // circumference
  const gapLen = workers.length > 1 ? 2 : 0;  // gap between segments, in path units

  // Each segment is a stroked circle: draw `frac` of the circumference,
  // rotated to its start angle. No arc-flag math, so it can't fold over.
  let acc = 0;                       // accumulated fraction (0..1)
  const arcs = workers.map((name) => {
    const frac  = byWorker[name] / total;
    const start = acc;
    acc += frac;
    return { name, count: byWorker[name], frac, start };
  });

  const paths = arcs.map(({ name, frac, start }) => {
    const col    = colorForWorker(name);
    const segLen = Math.max(frac * C - gapLen, 0);
    const rot    = start * 360 - 90;   // -90 so the ring starts at 12 o'clock
    return `<circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="${col}" stroke-width="${sw}" stroke-dasharray="${segLen.toFixed(2)} ${C.toFixed(2)}" transform="rotate(${rot.toFixed(2)} ${cx} ${cy})"/>`;
  }).join("");

  const centerLabel = `
    <text x="${cx}" y="${cy - 5}" text-anchor="middle" font-size="22" font-weight="700" fill="var(--text)">${total}</text>
    <text x="${cx}" y="${cy + 11}" text-anchor="middle" font-size="9" fill="var(--text-muted)">jobs</text>`;

  const legX = 152;
  let legY = 22;
  const legend = arcs.map(({ name, count, frac }) => {
    const pct = Math.round(frac * 100);
    const col = colorForWorker(name);
    const row = `
      <circle cx="${legX}" cy="${legY}" r="4" fill="${col}"/>
      <text x="${legX + 11}" y="${legY + 4}" font-size="11" fill="var(--text)">${esc(name)}</text>
      <text x="${W - 2}" y="${legY + 4}" text-anchor="end" font-size="9.5" fill="var(--text-muted)">${count} · ${pct}%</text>`;
    legY += 21;
    return row;
  }).join("");

  const topW = arcs[0];
  const insight = (topW && arcs.length > 1)
    ? `${topW.name} handled the most jobs (${Math.round(topW.frac*100)}%).`
    : topW ? `${topW.name} handled all ${total} jobs.` : "";

  el.innerHTML = `
    <svg width="100%" viewBox="0 0 ${W} ${H}" style="max-height:190px">
      ${paths}${centerLabel}
      <g>${legend}</g>
    </svg>
    ${insight ? `<div class="chart-insight">${esc(insight)}</div>` : ""}`;
}

// ── Bar chart ─────────────────────────────────────────────────────────────────

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
    const avg = (d) => d.reduce((s, v) => s + v, 0) / (d.length || 1);
    return avg(dursByWorker[a]) - avg(dursByWorker[b]);
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

  const W = 300, barH = 20, gap = 10, labelW = 86, barMaxW = W - labelW - 54;
  const H = workers.length * (barH + gap) + 8;

  let bars = "";
  workers.forEach((name, i) => {
    const avg = avgs[i];
    const bw  = Math.round((avg / maxAvg) * barMaxW);
    const y   = 4 + i * (barH + gap);
    const col = colorForWorker(name);
    bars += `
      <text x="${labelW - 6}" y="${y + barH/2 + 4}" text-anchor="end" font-size="11" fill="var(--text)">${esc(name)}</text>
      <rect x="${labelW}" y="${y}" width="${bw}" height="${barH}" rx="3" fill="${col}"/>
      <text x="${labelW + bw + 5}" y="${y + barH/2 + 4}" font-size="9.5" fill="var(--text-muted)">${fmtDuration(avg)}</text>`;
  });

  let insight = "";
  if (workers.length > 1) {
    const ratio = avgs[avgs.length-1] / avgs[0];
    insight = `${esc(workers[0])} fastest · ${esc(workers[workers.length-1])} ~${Math.round((ratio-1)*100)}% slower.`;
  }

  el.innerHTML = `
    <svg width="100%" viewBox="0 0 ${W} ${H}" style="max-height:220px">
      ${bars}
    </svg>
    ${insight ? `<div class="chart-insight">${insight}</div>` : ""}`;
}

// ── Swimlane ──────────────────────────────────────────────────────────────────

function renderSwimlane(el, filteredJobs) {
  if (!filteredJobs.length) {
    el.innerHTML = '<div class="chart-empty">No data for selected filters.</div>';
    return;
  }
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

  const now   = lastSnapshot ? (lastSnapshot.now_ts || Date.now()/1000) : Date.now()/1000;
  const allS  = filteredJobs.map((j) => j.started_at_ts).filter(Boolean);
  const wSt   = allS.length ? Math.min(...allS) - 60 : now - 3600;
  const wEnd  = now;
  const wSecs = Math.max(wEnd - wSt, 60);

  const W = 600, rowH = 26, gap = 6, labelW = 76, axisH = 18, padT = 2;
  const barH   = 16;
  const barW   = W - labelW - 4;
  const H      = workers.length * (rowH + gap) + axisH + padT;
  const tx     = (ts) => labelW + Math.round(((ts - wSt) / wSecs) * barW);

  // axis ticks
  let axisG = "";
  for (let i = 0; i <= 4; i++) {
    const ts  = wSt + (wSecs * i) / 4;
    const x   = tx(ts);
    const rel = ts - now;
    const lbl = Math.abs(rel) < 30 ? "now"
              : rel < 0 ? `-${Math.round(Math.abs(rel)/60)}m`
              : `+${Math.round(rel/60)}m`;
    axisG += `<line x1="${x}" y1="${padT}" x2="${x}" y2="${H-axisH}" stroke="var(--border)" stroke-width="1" opacity="0.5"/>
      <text x="${x}" y="${H}" text-anchor="middle" font-size="9" fill="var(--text-muted)">${esc(lbl)}</text>`;
  }

  // worker rows
  let rowsG = "";
  workers.forEach((name, i) => {
    const y   = padT + i * (rowH + gap);
    const col = colorForWorker(name);
    rowsG += `<text x="${labelW-5}" y="${y+rowH/2+4}" text-anchor="end" font-size="10" fill="var(--text)">${esc(name)}</text>`;
    rowsG += `<rect x="${labelW}" y="${y+5}" width="${barW}" height="${rowH-10}" rx="2" fill="var(--bg-card)" opacity="0.6"/>`;
    for (const j of workerMap[name]) {
      const x1 = tx(j.started_at_ts);
      const x2 = tx(j.finished_at_ts);
      const bw = Math.max(x2 - x1, 2);
      const bx = Math.max(x1, labelW);
      const cl = Math.min(bx + bw, labelW + barW) - bx;
      if (cl <= 0) continue;
      rowsG += `<rect x="${bx}" y="${y+6}" width="${cl}" height="${barH-4}" rx="2" fill="${col}">
        <title>${esc(j.scene_name || j.job_id)} · ${fmtDuration(j.duration_seconds)}</title>
      </rect>`;
    }
  });

  el.innerHTML = `<svg width="100%" viewBox="0 0 ${W} ${H}" style="min-height:100px">
    <g>${axisG}</g><g>${rowsG}</g>
  </svg>`;
}

// ── Render all performance ───────────────────────────────────────────────────

function renderPerformance(data) {
  renderWorkerChips(data);
  const filtered = filterJobsForPerf(data);
  renderStatStrip(filtered);
  renderPieChart($("chart-pie"), filtered);
  renderBarChart($("chart-bars"), filtered);
  renderSwimlane($("chart-swimlane"), filtered);
}

// ── Actions ───────────────────────────────────────────────────────────────────

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

async function actSetFrozenSelected(frozen) {
  const ids = Array.from(selectedJobIds);
  if (!ids.length) return;
  try {
    const r = await postAdmin("/admin/jobs/freeze", { job_ids: ids, frozen });
    toast(`${frozen ? "Froze" : "Unfroze"} ${r.count} job(s).`);
    await loadData();
  } catch (e) {
    toast(`${frozen ? "Freeze" : "Unfreeze"} failed: ` + e.message, true);
  }
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

// ── Job modal (Edit Job / New Job share one form) ─────────────────────────────

// Per-format Bit Depth options, mirroring on_format_changed() in
// batchrenderer_UI.py. The stored output.depth_index is an index into the
// list for the current format. jpg is fixed 8-bit (disabled) and hides alpha.
const DEPTH_OPTS = {
  jpg: ["8-bit (Fixed)"],
  png: ["8-bit", "16-bit"],
  tif: ["8-bit", "16-bit"],
  exr: ["16-bit (Half)", "32-bit (Float)", "32-bit (Integer)"],
};

const MIXED = "__mixed__";   // synthetic <select> value for differing selections

// Field ids the user has touched since the modal opened. Only touched fields
// (plus fields that started non-mixed) are written on save, so untouched
// "mixed" fields preserve each job's own value. See computeSave().
const editTouched = new Set();

// Defaults for a fresh New Job form: the render/output halves of
// _DEFAULT_JOB_REQUEST in NetworkRender/shared/job_schema.py.
const NEW_JOB_DEFAULTS = {
  render: {
    override_settings: false, resolution: 4000, pass_limit: 75, noise_limit: 6.0,
    use_variations: true, fallback_camera_mode: "all", fallback_camera_name: "",
  },
  output: {
    folder: "", version: null, format: "jpg", depth_index: 0,
    save_alpha: false, save_render_elements: false,
  },
};

// localStorage key under which the last submitted render/output settings are
// remembered (per browser), so the next New Job starts from them.
const NEW_JOB_MEMORY_KEY = "vb_new_job_form";

function findJob(jobId) {
  if (!lastSnapshot) return null;
  return (lastSnapshot.jobs || []).find((j) => j.job_id === jobId) || null;
}

// Are all values in `arr` equal (by ===)? Empty/one-element arrays are "same".
function allSame(arr) {
  return arr.every((v) => v === arr[0]);
}

// Show the resolution/pass/noise block only when "Override scene render
// settings" is on, matching widget_settings visibility in the batch renderer.
// While the override checkbox is in the mixed (indeterminate) state we keep the
// block expanded so its sub-fields remain reachable.
function syncOverrideBlock() {
  const c = $("f-override-settings");
  $("f-settings-block").hidden = !(c.checked || c.indeterminate);
}

// Show the Camera Name row only when it applies: mode is "by_name", or the
// selection is mixed (so the field stays reachable, like the override block).
function syncCameraNameRow() {
  const v = $("f-camera-mode").value;
  $("f-camera-name-row").hidden = !(v === "by_name" || v === MIXED);
}

// Repopulate the Bit Depth dropdown for the chosen format and toggle the alpha
// row (hidden for jpg). Keeps the previously selected index when still valid.
// When `desiredDepthIndex` is MIXED, a synthetic mixed option is shown instead.
function syncFormatDependents(desiredDepthIndex) {
  const fmt  = $("f-output-format").value;
  const sel  = $("f-depth-index");
  if (fmt === MIXED) {
    // Format itself differs across the selection — we can't know which depth
    // list applies, so just show a single mixed entry until a format is picked.
    sel.innerHTML = `<option value="${MIXED}">— mixed —</option>`;
    sel.value = MIXED;
    sel.disabled = false;
    $("f-alpha-row").hidden = false;
    markMixed(sel, true);
    syncRenderElementsAvailability(MIXED);
    return;
  }
  syncRenderElementsAvailability(fmt);
  const opts = DEPTH_OPTS[fmt] || DEPTH_OPTS.jpg;
  const prevMixed = desiredDepthIndex === MIXED;
  // No arg → user just changed format; keep the current index if it's a real
  // number, else fall back to 0 (e.g. when leaving the mixed state).
  let prev;
  if (prevMixed) prev = 0;
  else if (desiredDepthIndex != null) prev = desiredDepthIndex;
  else { const cur = Number(sel.value); prev = Number.isFinite(cur) ? cur : 0; }
  let html = opts.map((label, i) => `<option value="${i}">${esc(label)}</option>`).join("");
  if (prevMixed) html = `<option value="${MIXED}">— mixed —</option>` + html;
  sel.innerHTML = html;
  sel.value = prevMixed ? MIXED : String(Math.min(Math.max(prev, 0), opts.length - 1));
  sel.disabled = (fmt === "jpg") && !prevMixed;    // jpg depth is fixed
  $("f-alpha-row").hidden = (fmt === "jpg");        // jpg has no alpha channel
  markMixed(sel, prevMixed);
}

// Visually flag a control as holding mixed values (a dashed/idle look via CSS).
function markMixed(el, isMixed) { el.classList.toggle("mixed", !!isMixed); }

// Max's pngio writes render-element PNGs with an invalid IHDR ("PNG Library
// Internal Error" per element, 0-byte files) regardless of bit depth, so
// render elements are unavailable for PNG. Force the checkbox off and disable
// it — clearing its indeterminate/mixed state so the false is actually written
// on save. For any other (or mixed) format, re-enable it and leave its value.
function syncRenderElementsAvailability(fmt) {
  const el = $("f-save-re");
  if (!el) return;
  if (fmt === "png") {
    el.checked = false;
    el.indeterminate = false;
    el.dataset.mixed = "";
    el.disabled = true;
    el.parentElement.title =
      "Render elements aren't supported for PNG output. Use EXR or TIFF to save passes.";
  } else {
    el.disabled = false;
    el.parentElement.title = "";
  }
}

// Prefill one checkbox from N job values: checked/unchecked if all agree,
// else indeterminate (the "dash"). Records mixedness on the element.
function fillCheck(id, values) {
  const el = $(id);
  const same = allSame(values);
  el.indeterminate = !same;
  el.checked = same ? !!values[0] : false;
  el.dataset.mixed = same ? "" : "1";
}

// Prefill a text/number input: the shared value if all agree, else blank with a
// "— mixed —" placeholder and the .mixed flag.
function fillInput(id, values, toStr) {
  const el = $(id);
  const same = allSame(values.map(String));
  if (same) {
    el.value = toStr ? toStr(values[0]) : (values[0] ?? "");
    el.placeholder = "";
    el.dataset.mixed = "";
    markMixed(el, false);
  } else {
    el.value = "";
    el.placeholder = "— mixed —";
    el.dataset.mixed = "1";
    markMixed(el, true);
  }
}

// Prefill a <select>: select the shared value if all agree, else prepend a
// synthetic "— mixed —" option and select it.
function fillSelect(id, values) {
  const el = $(id);
  // Drop any stale mixed option from a previous open.
  const stale = el.querySelector(`option[value="${MIXED}"]`);
  if (stale) stale.remove();
  const same = allSame(values.map(String));
  if (same) {
    el.value = String(values[0]);
    el.dataset.mixed = "";
    markMixed(el, false);
  } else {
    el.insertBefore(new Option("— mixed —", MIXED), el.firstChild);
    el.value = MIXED;
    el.dataset.mixed = "1";
    markMixed(el, true);
  }
}

// Open the editor for the entire current selection (the "Edit Selected" button).
function actEditSelected() {
  const ids = Array.from(selectedJobIds);
  if (!ids.length) return;
  openEditModal(ids[0]);   // primaryId is in the selection → edits all of it
}

// Switch the shared modal between "edit" and "new": title, the submit-only
// sections (scene list, row range), the footer button and the notice banner.
// Field values are filled separately by fillJobForm().
function setModalMode(mode, title) {
  modalMode = mode;
  const isNew = (mode === "new");
  editTouched.clear();
  $("edit-title").textContent = title;
  const warn = $("edit-warn");
  warn.textContent = "";
  warn.hidden = true;
  $("f-scene-section").hidden = !isNew;
  $("f-row-range-row").hidden = !isNew;
  const btn = $("edit-save");
  btn.textContent = isNew ? "Submit" : "Save";
  btn.classList.toggle("btn-success", isNew);
  btn.classList.toggle("btn-primary", !isNew);
  btn.disabled = false;
}

// Show a message in the modal's banner (orange, above the form). Used for the
// non-queued warning in edit mode and for validation/submit errors in new mode.
function showModalNotice(msg) {
  const warn = $("edit-warn");
  warn.textContent = msg;
  warn.hidden = false;
}

function openEditModal(primaryId) {
  // Edit the whole current selection if the clicked row is part of it;
  // otherwise edit just the clicked row.
  let ids = Array.from(selectedJobIds);
  if (!ids.includes(primaryId)) ids = [primaryId];

  const jobs = ids.map(findJob).filter(Boolean);
  if (!jobs.length) { toast("Job no longer exists.", true); return; }
  ids = jobs.map((j) => j.job_id);
  const multi = jobs.length > 1;

  setModalMode("edit", multi
    ? `Edit ${jobs.length} Jobs`
    : `Edit Job · ${jobs[0].scene_name || ids[0]}`);
  editingJobIds = ids;   // suspends polling via loadData()'s guard

  // Warn (but don't block) about non-queued jobs: edits only take effect on
  // requeue. With a mixed selection, count how many are affected.
  const nonQueued = jobs.filter((j) => (j.status || "").toLowerCase() !== "queued");
  if (nonQueued.length) {
    showModalNotice(multi
      ? `${nonQueued.length} of ${jobs.length} selected job(s) are not queued. Changes are saved but only take effect for those once you requeue them.`
      : `This job is "${jobs[0].status}". Changes are saved but only take effect if you requeue it.`);
  }

  fillJobForm(jobs);
  $("edit-overlay").hidden = false;
  $("f-output-folder").focus();
}

// Prefill every render/output control from one or more {render, output}
// records. With several records, fields that differ show the mixed
// affordance; with one (a single job, or the New Job defaults) every field
// simply takes that value.
function fillJobForm(jobs) {
  const R = (k) => jobs.map((j) => (j.render || {})[k]);
  const O = (k) => jobs.map((j) => (j.output || {})[k]);

  // Render fields.
  fillInput("f-resolution",  R("resolution"));
  fillInput("f-pass-limit",  R("pass_limit"));
  fillInput("f-noise-limit", R("noise_limit"));
  fillSelect("f-camera-mode", R("fallback_camera_mode").map((v) =>
    (v === "active" || v === "by_name") ? v : "all"));
  fillInput("f-camera-name", R("fallback_camera_name").map((v) => v || ""));
  fillCheck("f-use-variations",    R("use_variations").map(Boolean));
  fillCheck("f-override-settings", R("override_settings").map(Boolean));
  syncOverrideBlock();
  syncCameraNameRow();

  // Output fields. version null → "" (the "None" option).
  fillInput("f-output-folder", O("folder").map((v) => v || ""));
  const versionSel = $("f-output-version");
  const versions = O("version").map((v) => (v == null) ? "" : String(v));
  // Add any custom version labels not already listed so they can be shown.
  for (const v of versions) {
    if (v && !Array.from(versionSel.options).some((opt) => opt.value === v)) {
      versionSel.add(new Option(v, v));
    }
  }
  fillSelect("f-output-version", versions);

  const formats = O("format").map((v) => v || "jpg");
  fillSelect("f-output-format", formats);
  // Depth list depends on format; pass MIXED through when either differs.
  const depthVals = O("depth_index").map((v) => v ?? 0);
  const depthArg = !allSame(formats) ? MIXED
                 : !allSame(depthVals.map(String)) ? MIXED
                 : depthVals[0];
  syncFormatDependents(depthArg);

  fillCheck("f-save-alpha", O("save_alpha").map(Boolean));
  fillCheck("f-save-re",    O("save_render_elements").map(Boolean));
  // fillCheck reset the render-elements box from stored values; re-apply the
  // PNG guard so a PNG job can't show it checked/enabled.
  syncRenderElementsAvailability(allSame(formats) ? formats[0] : MIXED);
}

// Close the modal in either mode and resume polling (edit mode had it
// suspended; pulling a fresh snapshot right away also shows the rows a New
// Job submit just queued).
function closeJobModal() {
  if (!modalMode) return;
  modalMode = null;
  editingJobIds = [];
  $("edit-overlay").hidden = true;
  loadData();
}

// ── New Job (submit straight from the dashboard) ─────────────────────────────

// Open the shared modal in "new" mode: an empty scene list plus render/output
// settings prefilled from the last submission made in this browser, falling
// back to the schema defaults. Scene list and row range are never remembered:
// they belong to one submission.
function openNewJobModal() {
  setModalMode("new", "New Job");
  editingJobIds = [];
  const remembered = loadNewJobMemory();
  fillJobForm([{
    render: { ...NEW_JOB_DEFAULTS.render, ...(remembered.render || {}) },
    output: { ...NEW_JOB_DEFAULTS.output, ...(remembered.output || {}) },
  }]);
  // fillInput() clears placeholders; restore the ones that help a blank form.
  $("f-output-folder").placeholder = "\\\\vb_nas\\nas\\…\\renders";
  $("f-camera-name").placeholder = "e.g. Detail";
  const scenes = $("f-scene-files");
  scenes.value = "";
  updateSceneHint();
  $("f-row-range").value = "";
  syncRowRangeValidity();
  $("edit-overlay").hidden = false;
  scenes.focus();
}

// Explorer's "Copy as path" wraps the path in double quotes, and PowerShell
// users paste single-quoted ones. Strip whitespace and one matching pair of
// surrounding quotes so a pasted path is usable as-is. Used wherever a path
// enters the form: the scene list, the output folder, and their paste handlers.
function cleanPathText(text) {
  let t = String(text || "").trim();
  const m = t.match(/^(["'])(.*)\1$/);
  if (m) t = m[2].trim();
  return t;
}

// Split the textarea into scene paths: one per line, cleaned by
// cleanPathText(), blank lines and duplicates dropped, backslashes normalised
// to "/" (the schema does the same server-side). Also returns the lines that
// don't look like 3ds Max scenes for the hint.
function parseScenePaths(text) {
  const files = [];
  const seen = new Set();
  const suspicious = [];
  for (const rawLine of String(text || "").split(/\r?\n/)) {
    const line = cleanPathText(rawLine);
    if (!line) continue;
    const norm = line.replace(/\\/g, "/");
    const key = norm.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    files.push(norm);
    if (!/\.max$/i.test(norm)) suspicious.push(line);
  }
  return { files, suspicious };
}

// Live count under the scene list, flagging lines that don't end in .max.
function updateSceneHint() {
  const { files, suspicious } = parseScenePaths($("f-scene-files").value);
  const hint = $("f-scene-hint");
  if (!files.length) {
    hint.textContent = "No scenes yet. Paste one .max path per line (Explorer's Copy as path, quotes and all, works); each becomes its own queued job.";
    hint.classList.remove("warn");
    return;
  }
  let text = `${files.length} scene(s), one job each.`;
  if (suspicious.length) text += ` ${suspicious.length} line(s) don't end in .max.`;
  hint.textContent = text;
  hint.classList.toggle("warn", suspicious.length > 0);
}

// Mirror of variation_core.is_valid_row_range_expr(): comma-separated table
// row numbers or ranges ("2,4-7,10"); open ends ("5-", "-9") are allowed;
// row 1 is the header so every number must be >= 2; empty = all rows.
function isValidRowRangeExpr(expr) {
  const text = String(expr || "").trim();
  if (!text) return true;
  for (let part of text.split(",")) {
    part = part.trim();
    if (!part) continue;
    const dash = part.indexOf("-");
    if (dash >= 0) {
      const a = part.slice(0, dash).trim();
      const b = part.slice(dash + 1).trim();
      if (a && !/^\d+$/.test(a)) return false;
      if (b && !/^\d+$/.test(b)) return false;
      const start = a ? Number(a) : 2;
      if (start < 2) return false;
      if (b && Number(b) < start) return false;
    } else {
      if (!/^\d+$/.test(part) || Number(part) < 2) return false;
    }
  }
  return true;
}

function syncRowRangeValidity() {
  const el = $("f-row-range");
  el.classList.toggle("invalid", !isValidRowRangeExpr(el.value));
}

function loadNewJobMemory() {
  try {
    const raw = localStorage.getItem(NEW_JOB_MEMORY_KEY);
    const obj = raw ? JSON.parse(raw) : null;
    return (obj && typeof obj === "object") ? obj : {};
  } catch { return {}; }
}

function saveNewJobMemory(settings) {
  try { localStorage.setItem(NEW_JOB_MEMORY_KEY, JSON.stringify(settings)); } catch {}
}

// ── Native pickers (only inside the pywebview server window) ─────────────────
// A browser file input never reveals a full path, so "Browse…" exists only
// where the page runs inside `server.py --ui`: pywebview injects
// window.pywebview.api (see _DashboardNativeApi in server.py) and fires
// "pywebviewready" once it's callable. Elsewhere the buttons stay hidden and
// paths are pasted. The API returns native Windows paths (backslashes, mapped
// drives resolved to UNC); parseScenePaths()/the schema normalise them later.

function nativeApi() {
  return (window.pywebview && window.pywebview.api) ? window.pywebview.api : null;
}

function revealNativePickers() {
  const on = !!nativeApi();
  $("f-scene-browse").hidden = !on;
  $("f-folder-browse").hidden = !on;
}

// Parent folder of a path in backslash form (what the native dialog wants as
// its start directory), or "" when there is none.
function dirOf(path) {
  const p = String(path || "").trim().replace(/\//g, "\\");
  const i = p.lastIndexOf("\\");
  return i > 1 ? p.slice(0, i) : "";
}

async function browseScenes() {
  const api = nativeApi();
  if (!api) return;
  const ta = $("f-scene-files");
  const { files } = parseScenePaths(ta.value);
  const startDir = files.length
    ? dirOf(files[files.length - 1])
    : dirOf($("f-output-folder").value);
  try {
    const picked = await api.pick_scene_files(startDir);
    if (!picked || !picked.length) return;
    const existing = ta.value.replace(/\s+$/, "");
    ta.value = (existing ? existing + "\n" : "") + picked.join("\n") + "\n";
    ta.dispatchEvent(new Event("input", { bubbles: true }));   // hint + touched
  } catch (e) {
    toast("Browse failed: " + e.message, true);
  }
}

async function browseOutputFolder() {
  const api = nativeApi();
  if (!api) return;
  const input = $("f-output-folder");
  try {
    const picked = await api.pick_output_folder(cleanPathText(input.value).replace(/\//g, "\\"));
    if (!picked) return;
    input.value = picked;
    input.dispatchEvent(new Event("input", { bubbles: true }));   // marks touched (multi-edit)
  } catch (e) {
    toast("Browse failed: " + e.message, true);
  }
}

// ── Paste normalisation ───────────────────────────────────────────────────────
// The parse/save steps cope with quotes anyway, but the field should show what
// will be sent, so pasted text is cleaned in place: one cleaned path per line
// in the scene list, the first path only in the single-line folder field.
// setRangeText() keeps the caret/selection semantics of a normal paste.

function pastedLines(ev) {
  const dt = ev.clipboardData || window.clipboardData;
  const raw = dt ? dt.getData("text") : "";
  return raw ? raw.split(/\r?\n/).map(cleanPathText).filter(Boolean) : [];
}

function onScenePaste(ev) {
  const lines = pastedLines(ev);
  if (!lines.length) return;
  ev.preventDefault();
  const el = ev.target;
  el.setRangeText(lines.join("\n") + "\n", el.selectionStart, el.selectionEnd, "end");
  el.dispatchEvent(new Event("input", { bubbles: true }));
}

function onFolderPaste(ev) {
  const lines = pastedLines(ev);
  if (!lines.length) return;
  ev.preventDefault();
  const el = ev.target;
  el.setRangeText(lines[0], el.selectionStart, el.selectionEnd, "end");
  el.dispatchEvent(new Event("input", { bubbles: true }));
}

// Typed (not pasted) quotes: tidy the folder field when it loses focus.
function onFolderChange(ev) {
  const el = ev.target;
  const cleaned = cleanPathText(el.value);
  if (cleaned !== el.value) el.value = cleaned;
}

// A checkbox should be written only when it holds a definite value: either it
// was never mixed, or the user clicked it (clearing indeterminate). A still-
// indeterminate box means "leave each job's own value alone".
function checkVal(id) {
  const el = $(id);
  return el.indeterminate ? undefined : el.checked;
}

// A select/input value to write, or undefined to skip. Skips the synthetic
// mixed option and untouched mixed inputs.
function pickVal(id, transform) {
  const el = $(id);
  const wasMixed = el.dataset.mixed === "1";
  // Mixed + untouched → skip (preserve per-job values).
  if (wasMixed && !editTouched.has(id)) return undefined;
  const raw = el.value;
  if (raw === MIXED) return undefined;
  return transform ? transform(raw) : raw;
}

// Build the sparse {render, output} body: omit any field we must not write.
function computeSave() {
  const render = {};
  const output = {};
  const set = (obj, key, val) => { if (val !== undefined) obj[key] = val; };

  set(render, "resolution",  pickVal("f-resolution",  (v) => v.trim() === "" ? undefined : Number(v)));
  set(render, "pass_limit",  pickVal("f-pass-limit",  (v) => v.trim() === "" ? undefined : Number(v)));
  set(render, "noise_limit", pickVal("f-noise-limit", (v) => v.trim() === "" ? undefined : Number(v)));
  set(render, "fallback_camera_mode", pickVal("f-camera-mode"));
  set(render, "fallback_camera_name", pickVal("f-camera-name", (v) => v.trim()));
  set(render, "use_variations",    checkVal("f-use-variations"));
  set(render, "override_settings", checkVal("f-override-settings"));

  set(output, "folder",  pickVal("f-output-folder", cleanPathText));
  set(output, "version", pickVal("f-output-version", (v) => v === "" ? null : v));
  set(output, "format",  pickVal("f-output-format"));
  set(output, "depth_index", pickVal("f-depth-index", (v) => Number(v)));
  set(output, "save_alpha",           checkVal("f-save-alpha"));
  set(output, "save_render_elements", checkVal("f-save-re"));

  const body = {};
  if (Object.keys(render).length) body.render = render;
  if (Object.keys(output).length) body.output = output;
  return body;
}

async function saveEditModal() {
  if (!editingJobIds.length) return;
  const ids = editingJobIds;
  const changes = computeSave();

  if (!changes.render && !changes.output) {
    toast("No changes to apply.");
    closeJobModal();
    return;
  }

  const body = (ids.length === 1)
    ? { job_id: ids[0], ...changes }
    : { job_ids: ids, ...changes };

  const saveBtn = $("edit-save");
  saveBtn.disabled = true;
  try {
    const r = await postAdmin("/admin/jobs/update", body);
    // Drop the polling guard *before* the refresh so loadData() runs.
    modalMode = null;
    editingJobIds = [];
    $("edit-overlay").hidden = true;
    const n = (r && r.count != null) ? r.count : ids.length;
    toast(n > 1 ? `Updated ${n} jobs.` : "Job updated.");
    await loadData();
  } catch (e) {
    toast("Update failed: " + e.message, true);
  } finally {
    saveBtn.disabled = false;
  }
}

// Footer button: "Save" posts an edit, "Submit" posts a new submission.
function onSaveClick() {
  if (modalMode === "new") submitNewJob();
  else if (modalMode === "edit") saveEditModal();
}

// Validate the New Job form, build a full job request (the same shape the
// Batch Renderer's build_job_request() POSTs) and submit it. The server fans
// max_files out into one queued job per scene and mints the request id. On
// failure the modal stays open with the error in the banner so nothing typed
// is lost.
async function submitNewJob() {
  const fail = (msg, focusId) => {
    showModalNotice(msg);
    if (focusId) $(focusId).focus();
  };

  const { files, suspicious } = parseScenePaths($("f-scene-files").value);
  if (!files.length) return fail("Add at least one scene file (one .max path per line).", "f-scene-files");
  if (!cleanPathText($("f-output-folder").value)) return fail("Output folder is required.", "f-output-folder");
  const rangeExpr = $("f-row-range").value.trim();
  if (!isValidRowRangeExpr(rangeExpr)) {
    return fail('Row Range must look like "2,4-7,10" (row 1 is the header, so numbers start at 2).', "f-row-range");
  }
  if ($("f-camera-mode").value === "by_name" && !$("f-camera-name").value.trim()) {
    return fail('Camera Name is required for "Render Camera By Name".', "f-camera-name");
  }
  if (suspicious.length) {
    const shown = suspicious.slice(0, 5).join("\n") + (suspicious.length > 5 ? "\n…" : "");
    if (!confirm(`${suspicious.length} line(s) don't end in .max:\n\n${shown}\n\nSubmit anyway?`)) return;
  }

  // No field is ever "mixed" in new mode, so computeSave() yields the full
  // render/output dicts (blank number inputs are omitted → schema defaults).
  const settings = computeSave();
  const body = {
    schema_version: 1,
    request_id: "",            // server mints a uuid
    max_files: files,
    load_scene: true,
    render: settings.render || {},
    output: settings.output || {},
    render_range_expr: rangeExpr,
  };

  const btn = $("edit-save");
  btn.disabled = true;
  try {
    const r = await postAdmin("/submit", body);
    saveNewJobMemory({ render: body.render, output: body.output });
    const n = (r && r.count != null) ? r.count : files.length;
    closeJobModal();   // also triggers the refresh that shows the new rows
    toast(`Submitted ${n} job(s).`);
  } catch (e) {
    showModalNotice("Submit failed: " + e.message);
  } finally {
    btn.disabled = false;
  }
}

// Mark a control as user-touched (so a previously-mixed field gets written) and
// drop its mixed styling.
function onEditFieldInput(ev) {
  const el = ev.target;
  if (!el.id || !el.id.startsWith("f-")) return;
  editTouched.add(el.id);
  el.dataset.mixed = "";
  markMixed(el, false);
}

function onEditOverlayClick(ev) {
  // Click on the dimmed backdrop (not the modal card itself) closes the modal.
  if (ev.target === $("edit-overlay")) closeJobModal();
}

function onKeydown(ev) {
  if (ev.key !== "Escape") return;
  if (!ctxMenuEl().hidden) { closeCtxMenu(); return; }
  if (modalMode) closeJobModal();
}

// ── Job row context menu (right-click) ─────────────────────────────────────────

// The job id the menu currently targets (for the single-row "Copy output path").
let ctxRowId = null;

function ctxMenuEl() { return $("ctx-menu"); }

function closeCtxMenu() {
  const m = ctxMenuEl();
  if (!m.hidden) m.hidden = true;
  ctxRowId = null;
}

// Right-click on a job row. Smart selection: if the row is already selected the
// menu acts on the whole selection; otherwise select just this row first.
function onTbodyContextMenu(ev) {
  const tr = ev.target.closest("tr[data-job-id]");
  if (!tr) return;                 // not a job row → leave native menu alone
  const id = tr.getAttribute("data-job-id");
  if (!id) return;
  ev.preventDefault();             // suppress the WebView2/browser native menu

  if (!selectedJobIds.has(id)) {
    selectedJobIds.clear();
    selectedJobIds.add(id);
    selectionAnchorId = id;
    applySelectionClasses();
  }
  ctxRowId = id;
  openCtxMenu(ev.clientX, ev.clientY);
}

function openCtxMenu(x, y) {
  const m = ctxMenuEl();
  const caps = selectionCaps();
  const multi = caps.count > 1;

  // Enable/disable items by what the selection supports (greyed, not hidden,
  // so the menu shape stays stable).
  const setEnabled = (action, on) => {
    const el = m.querySelector(`[data-action="${action}"]`);
    if (el) el.disabled = !on;
  };
  setEnabled("edit",     caps.count > 0);
  setEnabled("requeue",  caps.count > 0);
  setEnabled("freeze",   caps.freezable > 0);
  setEnabled("unfreeze", caps.unfreezable > 0);
  setEnabled("remove",   caps.count > 0);
  // Copy output path is single-row only and needs an output folder to copy.
  setEnabled("copy", !multi && !!ctxCopyPath());

  // Show first (so we can measure), then clamp inside the viewport.
  m.hidden = false;
  const rect = m.getBoundingClientRect();
  const pad = 6;
  const left = Math.min(x, window.innerWidth  - rect.width  - pad);
  const top  = Math.min(y, window.innerHeight - rect.height - pad);
  m.style.left = Math.max(pad, left) + "px";
  m.style.top  = Math.max(pad, top) + "px";
}

// Output path (Windows-native) for the menu's target row, or "" if none.
// Read from the snapshot, not the DOM: rows now hold several copy buttons
// (scene folder, output, error), so scraping the first one would be wrong.
function ctxCopyPath() {
  if (!ctxRowId) return "";
  const j = findJob(ctxRowId);
  return j ? toNativePath(j.output_folder || "") : "";
}

function onCtxMenuClick(ev) {
  const item = ev.target.closest(".ctx-item");
  if (!item || item.disabled) return;
  const action = item.getAttribute("data-action");
  const targetRow = ctxRowId;     // capture before close clears it
  closeCtxMenu();
  switch (action) {
    case "edit":     actEditSelected(); break;
    case "requeue":  actRequeueSelected(); break;
    case "freeze":   actSetFrozenSelected(true); break;
    case "unfreeze": actSetFrozenSelected(false); break;
    case "remove":   actRemoveSelected(); break;
    case "copy": {
      const j = findJob(targetRow);
      const native = j ? toNativePath(j.output_folder || "") : "";
      if (native) {
        copyText(native).then((ok) =>
          toast(ok ? "Output path copied — paste into Explorer" : "Copy failed", !ok));
      }
      break;
    }
  }
}

// ── Event wiring ──────────────────────────────────────────────────────────────

function rowIdOrder() {
  return Array.from($("tbody-jobs").querySelectorAll("tr[data-job-id]"))
    .map((r) => r.getAttribute("data-job-id"));
}

function applySelectionClasses() {
  const rows = $("tbody-jobs").querySelectorAll("tr[data-job-id]");
  for (const tr of rows) {
    tr.classList.toggle("selected", selectedJobIds.has(tr.getAttribute("data-job-id")));
  }
  updateSelectionUI(rows.length);
}

function onTbodyClick(ev) {
  // Copy button: act and bail, never affects row selection. Paths are copied
  // in Windows-native form for Explorer; data-raw payloads (error text) are
  // copied verbatim.
  const copyBtn = ev.target.closest(".copy-btn");
  if (copyBtn) {
    const raw = copyBtn.getAttribute("data-copy") || "";
    const text = copyBtn.dataset.raw === "1" ? raw : toNativePath(raw);
    if (text) {
      copyText(text).then((ok) =>
        toast(ok ? (copyBtn.dataset.msg || "Copied.") : "Copy failed", !ok)
      );
    }
    return;
  }

  // Edit button: open the modal and bail, never affects row selection.
  const editBtn = ev.target.closest(".edit-btn");
  if (editBtn) {
    openEditModal(editBtn.getAttribute("data-edit") || "");
    return;
  }

  const tr = ev.target.closest("tr[data-job-id]");
  if (!tr) return;
  const id = tr.getAttribute("data-job-id");
  if (!id) return;

  const ids = rowIdOrder();
  const additive = ev.ctrlKey || ev.metaKey;

  if (ev.shiftKey && selectionAnchorId && ids.includes(selectionAnchorId)) {
    // Range from the anchor to the clicked row. Ctrl+Shift extends the existing
    // selection; plain Shift replaces it. The anchor stays put (standard).
    const a = ids.indexOf(selectionAnchorId);
    const b = ids.indexOf(id);
    const [lo, hi] = a < b ? [a, b] : [b, a];
    if (!additive) selectedJobIds.clear();
    for (let i = lo; i <= hi; i++) selectedJobIds.add(ids[i]);
  } else if (additive) {
    // Ctrl/Cmd+click toggles a single row and moves the anchor.
    if (selectedJobIds.has(id)) selectedJobIds.delete(id);
    else selectedJobIds.add(id);
    selectionAnchorId = id;
  } else {
    // Plain click selects only this row.
    selectedJobIds.clear();
    selectedJobIds.add(id);
    selectionAnchorId = id;
  }
  applySelectionClasses();
}

// ── Queue drag-reorder (Queued tab only) ──────────────────────────────────────

function clearDropMarkers() {
  for (const el of document.querySelectorAll(".drop-before, .drop-after")) {
    el.classList.remove("drop-before", "drop-after");
  }
}

function onDragStart(ev) {
  const tr = ev.target.closest("tr.draggable-row");
  if (!tr) return;
  dragSrcId = tr.getAttribute("data-job-id");
  dragging = true;
  tr.classList.add("dragging");
  ev.dataTransfer.effectAllowed = "move";
  try { ev.dataTransfer.setData("text/plain", dragSrcId || ""); } catch {}
}

function onDragOver(ev) {
  if (!dragSrcId) return;
  const tr = ev.target.closest("tr.draggable-row");
  if (!tr || tr.getAttribute("data-job-id") === dragSrcId) return;
  ev.preventDefault();              // required to allow a drop
  ev.dataTransfer.dropEffect = "move";
  const rect = tr.getBoundingClientRect();
  const after = (ev.clientY - rect.top) > rect.height / 2;
  clearDropMarkers();
  tr.classList.add(after ? "drop-after" : "drop-before");
}

function onDrop(ev) {
  if (!dragSrcId) return;
  const tr = ev.target.closest("tr.draggable-row");
  if (!tr) return;
  ev.preventDefault();
  const tbody = $("tbody-jobs");
  const srcRow = tbody.querySelector("tr.dragging");
  if (srcRow && tr !== srcRow) {
    const rect = tr.getBoundingClientRect();
    const after = (ev.clientY - rect.top) > rect.height / 2;
    if (after) tr.after(srcRow); else tr.before(srcRow);
    commitReorder();
  }
  clearDropMarkers();
}

function onDragEnd() {
  clearDropMarkers();
  const el = $("tbody-jobs").querySelector("tr.dragging");
  if (el) el.classList.remove("dragging");
  dragSrcId = null;
  dragging = false;
}

async function commitReorder() {
  const ids = Array.from($("tbody-jobs").querySelectorAll("tr.draggable-row"))
    .map((tr) => tr.getAttribute("data-job-id"))
    .filter(Boolean);
  try {
    await postAdmin("/admin/queue/reorder", { job_ids: ids });
    toast("Queue reordered.");
  } catch (e) {
    toast("Reorder failed: " + e.message, true);
  } finally {
    dragging = false;   // allow the refresh below (and future polls) to proceed
    await loadData();
  }
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
  for (const t of document.querySelectorAll(".job-tab")) {
    t.classList.toggle("active", t.dataset.tab === jobTabFilter);
  }
  if (lastSnapshot) renderJobs(lastSnapshot.jobs || []);
}

function wire() {
  $("tbody-jobs").addEventListener("click", onTbodyClick);
  $("tbody-jobs").addEventListener("contextmenu", onTbodyContextMenu);
  $("tbody-jobs").addEventListener("dragstart", onDragStart);
  $("tbody-jobs").addEventListener("dragover", onDragOver);
  $("tbody-jobs").addEventListener("drop", onDrop);
  $("tbody-jobs").addEventListener("dragend", onDragEnd);
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
  // Context menu: act on item click; dismiss on any click-away, scroll,
  // resize, another right-click outside it, or Escape.
  $("ctx-menu").addEventListener("click", onCtxMenuClick);
  document.addEventListener("mousedown", (ev) => {
    if (!ev.target.closest("#ctx-menu")) closeCtxMenu();
  });
  document.addEventListener("scroll", closeCtxMenu, true);
  window.addEventListener("resize", closeCtxMenu);
  $("btn-new-job").addEventListener("click", openNewJobModal);
  $("edit-close").addEventListener("click", closeJobModal);
  $("edit-cancel").addEventListener("click", closeJobModal);
  $("edit-save").addEventListener("click", onSaveClick);
  $("f-scene-files").addEventListener("input", updateSceneHint);
  $("f-row-range").addEventListener("input", syncRowRangeValidity);
  $("f-scene-browse").addEventListener("click", browseScenes);
  $("f-folder-browse").addEventListener("click", browseOutputFolder);
  $("f-scene-files").addEventListener("paste", onScenePaste);
  $("f-output-folder").addEventListener("paste", onFolderPaste);
  $("f-output-folder").addEventListener("change", onFolderChange);
  window.addEventListener("pywebviewready", revealNativePickers);
  revealNativePickers();   // in case the API was injected before wire() ran
  $("edit-overlay").addEventListener("click", onEditOverlayClick);
  // Any field interaction marks it touched (so a previously-mixed field is
  // written on save). Delegated so it covers every f-* control. input fires
  // for text/number; change fires for checkbox/select.
  $("edit-overlay").addEventListener("input", onEditFieldInput);
  $("edit-overlay").addEventListener("change", onEditFieldInput);
  $("f-override-settings").addEventListener("change", syncOverrideBlock);
  $("f-camera-mode").addEventListener("change", syncCameraNameRow);
  $("f-output-format").addEventListener("change", () => syncFormatDependents());
  document.addEventListener("keydown", onKeydown);
}

wire();
loadData();
setInterval(loadData, CFG.poll_ms);

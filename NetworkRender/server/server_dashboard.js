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

function workerColors(name) {
  const h = _assignHue(String(name || "unknown"));
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

function esc(s) {
  const d = document.createElement("div");
  d.textContent = String(s == null ? "" : s);
  return d.innerHTML;
}

// Clipboard glyph for the copy-output-path button.
const COPY_ICON = `<svg viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"><rect x="5.5" y="5.5" width="8.5" height="9" rx="1.5"/><path d="M3.5 10.5h-1a1 1 0 0 1-1-1v-7a1 1 0 0 1 1-1h7a1 1 0 0 1 1 1v1"/></svg>`;

// Drag-handle glyph shown on queued rows (drag to reorder the queue).
const GRIP_ICON = `<svg viewBox="0 0 16 16" width="12" height="12" fill="currentColor"><circle cx="6" cy="4" r="1.3"/><circle cx="10" cy="4" r="1.3"/><circle cx="6" cy="8" r="1.3"/><circle cx="10" cy="8" r="1.3"/><circle cx="6" cy="12" r="1.3"/><circle cx="10" cy="12" r="1.3"/></svg>`;

// Windows-native (backslash) form so the copied value pastes straight into Explorer.
function toNativePath(p) {
  return String(p || "").replace(/\//g, "\\");
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
    tbody.innerHTML = `<tr><td colspan="9" class="empty">No jobs${jobTabFilter !== "all" ? " in this filter" : ""}.</td></tr>`;
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
          <button class="copy-btn" data-copy="${esc(outFolder)}" title="Copy path for Explorer" aria-label="Copy output path">${COPY_ICON}</button>
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
      <td title="${esc(j.scene_path)}">${esc(j.scene_name || "—")}</td>
      <td class="col-output">${outCell}</td>
      <td>${statusCell}</td>
      <td>${workerCell(j.worker_name || null)}</td>
      <td title="${esc(tip)}" style="font-variant-numeric:tabular-nums">${esc(fmtDuration(j.duration_seconds))}</td>
      <td style="color:var(--text-muted)">${esc(j.attempts)}</td>
      <td style="color:var(--text-muted);font-size:0.75rem">${esc(fmtTime(j.updated_at_ts))}</td>
      <td title="${esc(j.last_error)}" style="color:var(--red);font-size:0.75rem;max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(j.last_error || "—")}</td>
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

  // Freeze/unfreeze only apply to queued jobs; enable each only when the
  // selection contains a job it can actually act on.
  let freezable = 0, unfreezable = 0;
  if (lastSnapshot) {
    const byId = new Map((lastSnapshot.jobs || []).map((j) => [j.job_id, j]));
    for (const id of selectedJobIds) {
      const j = byId.get(id);
      if (!j || (j.status || "").toLowerCase() !== "queued") continue;
      if (j.frozen) unfreezable++; else freezable++;
    }
  }
  $("btn-freeze-sel").disabled   = freezable === 0;
  $("btn-unfreeze-sel").disabled = unfreezable === 0;
  $("btn-freeze-sel").textContent   = freezable   > 1 ? `Freeze Selected (${freezable})`     : "Freeze Selected";
  $("btn-unfreeze-sel").textContent = unfreezable > 1 ? `Unfreeze Selected (${unfreezable})` : "Unfreeze Selected";
}

// ── Main load ────────────────────────────────────────────────────────────────

async function loadData() {
  if (dragging) return;   // don't rebuild the table mid-drag
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
  // Copy-output-path button: act and bail, never affects row selection.
  const copyBtn = ev.target.closest(".copy-btn");
  if (copyBtn) {
    const native = toNativePath(copyBtn.getAttribute("data-copy") || "");
    if (native) {
      copyText(native).then((ok) =>
        toast(ok ? "Output path copied — paste into Explorer" : "Copy failed", !ok)
      );
    }
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
  $("tbody-jobs").addEventListener("dragstart", onDragStart);
  $("tbody-jobs").addEventListener("dragover", onDragOver);
  $("tbody-jobs").addEventListener("drop", onDrop);
  $("tbody-jobs").addEventListener("dragend", onDragEnd);
  $("btn-requeue-sel").addEventListener("click", actRequeueSelected);
  $("btn-freeze-sel").addEventListener("click", () => actSetFrozenSelected(true));
  $("btn-unfreeze-sel").addEventListener("click", () => actSetFrozenSelected(false));
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

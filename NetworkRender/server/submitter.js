// Recipe submitter page (/submitter). See NetworkRender/server/submitter.py for
// the pipeline and docs/SUBMITTER_RECIPES.md for the recipe contract.
//
// Flow: pick a recipe -> fill the grid (Load CSV / Scan folder / + Row, edit
// cells) -> set recipe options and output/render settings -> the preview
// re-runs the recipe server-side on every change -> Submit queues every job
// under one request id. Grid, options and settings are saved per recipe on
// the server (<recipe>.state.json), so everyone sees the same working copy.

const $ = (id) => document.getElementById(id);
const API = "/submitter/api";
const LAST_RECIPE_KEY = "vb_submitter_recipe";
const RECIPE_ID_RE = /^[A-Za-z0-9][A-Za-z0-9_\-]{0,63}$/;

// Bit depth options per format, as in the dashboard job modal / batch renderer.
const DEPTH_OPTS = {
  jpg: ["8-bit (Fixed)"],
  png: ["8-bit", "16-bit"],
  tif: ["8-bit", "16-bit"],
  exr: ["16-bit (Half)", "32-bit (Float)", "32-bit (Integer)"],
};
const VERSIONS = ["", "V1", "V2", "V3", "V4", "V5", "V6", "V7", "V8", "V9", "V10"];

const S = {
  folder: "",
  recipes: [],
  id: "",
  meta: null,         // columns, options, scenes, settings defaults (null = recipe fails to load)
  loadError: "",
  rows: [],           // [{_on: bool, <column key>: string, ...}]
  options: {},
  settings: null,     // {render, output, ocio, chunk_rows}
  sourceName: "",
  inputWarnings: [],
  preview: null,
};

let previewSeq = 0;
let previewTimer = null;
let saveTimer = null;
let editor = { id: "", mtime: 0, loaded: "" };

// ── Helpers ──────────────────────────────────────────────────────────────────

function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

async function api(method, path, body, opts = {}) {
  const init = { method, headers: {} };
  if (method !== "GET") {
    init.headers["Content-Type"] = "application/json";
    init.headers[CFG.csrf_header] = CFG.csrf_value;
    init.body = JSON.stringify(body || {});
    if (opts.keepalive) init.keepalive = true;
  }
  const r = await fetch(API + path, init);
  let data = null;
  try { data = await r.json(); } catch {}
  if (!r.ok) {
    const err = new Error((data && (data.message || data.error)) || `${r.status} ${r.statusText}`);
    err.status = r.status;
    err.data = data;
    throw err;
  }
  return data || {};
}

let toastTimer = null;
function toast(msg, isError) {
  const el = $("toast");
  el.textContent = msg;
  el.classList.toggle("error", !!isError);
  el.classList.add("show");
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 3600);
}

// Explorer's "Copy as path" adds double quotes, PowerShell single ones.
function cleanPathText(text) {
  let t = String(text || "").trim();
  const m = t.match(/^(["'])(.*)\1$/);
  if (m) t = m[2].trim();
  return t;
}

function baseName(p) {
  const s = String(p || "");
  return s.slice(Math.max(s.lastIndexOf("/"), s.lastIndexOf("\\")) + 1);
}

function hexColor(v) {
  const m = String(v || "").trim().match(/^#?([0-9a-fA-F]{6})$/);
  return m ? "#" + m[1] : "";
}

function banner(el, items, asList) {
  const list = (items || []).filter(Boolean);
  if (!list.length) { el.hidden = true; el.innerHTML = ""; return; }
  el.hidden = false;
  if (asList && list.length > 1) {
    const shown = list.slice(0, 40);
    el.innerHTML = "<ul>" + shown.map((t) => `<li>${esc(t)}</li>`).join("") + "</ul>" +
      (list.length > shown.length ? `<div>… and ${list.length - shown.length} more.</div>` : "");
  } else {
    el.textContent = list.join("\n");
  }
}

function arrayBufferToBase64(buf) {
  const bytes = new Uint8Array(buf);
  let bin = "";
  for (let i = 0; i < bytes.length; i += 0x8000) {
    bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  }
  return btoa(bin);
}

function fmtWhen(iso) {
  const d = new Date(iso);
  if (isNaN(d)) return iso || "";
  return d.toLocaleString([], { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

function nativeApi() {
  return (window.pywebview && window.pywebview.api) ? window.pywebview.api : null;
}

function revealNativePickers() {
  const on = !!(nativeApi() && nativeApi().pick_output_folder);
  document.querySelectorAll(".native-only").forEach((b) => { b.hidden = !on; });
}

async function browseFolderInto(input) {
  const a = nativeApi();
  if (!a) return;
  try {
    const picked = await a.pick_output_folder(cleanPathText(input.value).replace(/\//g, "\\"));
    if (!picked) return;
    input.value = picked;
    input.dispatchEvent(new Event("change", { bubbles: true }));
  } catch (e) {
    toast("Browse failed: " + e.message, true);
  }
}

// ── Recipes ──────────────────────────────────────────────────────────────────

async function loadRecipeList(selectId) {
  const data = await api("GET", "/recipes");
  S.recipes = data.recipes || [];
  S.folder = data.folder || "";
  $("pill-folder").textContent = "Recipes: " + (S.folder || "—");
  $("pill-folder").title = "Recipes folder on the server: " + S.folder;
  const sel = $("recipe-select");
  sel.innerHTML = S.recipes.length
    ? S.recipes.map((r) => `<option value="${esc(r.id)}">${esc(r.title)}${r.error ? "  (error)" : ""}</option>`).join("")
    : `<option value="">No recipes</option>`;
  let want = selectId;
  if (!want) { try { want = localStorage.getItem(LAST_RECIPE_KEY) || ""; } catch {} }
  if (!S.recipes.some((r) => r.id === want)) want = S.recipes.length ? S.recipes[0].id : "";
  sel.value = want;
  return want;
}

function mergeSettings(defaults, saved) {
  const d = defaults || { render: {}, output: {}, ocio: {}, chunk_rows: 0 };
  const s = saved || {};
  return {
    render: { ...d.render, ...(s.render || {}) },
    output: { ...d.output, ...(s.output || {}) },
    ocio: { ...d.ocio, ...(s.ocio || {}) },
    chunk_rows: (s.chunk_rows != null) ? s.chunk_rows : d.chunk_rows,
  };
}

function optionDefaults(meta) {
  const out = {};
  for (const o of (meta ? meta.options : [])) out[o.key] = o.default;
  return out;
}

async function selectRecipe(id) {
  await flushSave();
  S.id = id;
  S.preview = null;
  try { localStorage.setItem(LAST_RECIPE_KEY, id); } catch {}
  if (!id) { S.meta = null; S.loadError = ""; renderAll(); return; }
  let detail;
  try {
    detail = await api("GET", `/recipes/${encodeURIComponent(id)}`);
  } catch (e) {
    S.meta = null;
    S.loadError = "Could not open recipe: " + e.message;
    renderAll();
    return;
  }
  const state = detail.state || {};
  S.meta = detail.meta;
  S.loadError = detail.load_error || "";
  S.rows = Array.isArray(state.rows) ? state.rows : [];
  S.options = { ...optionDefaults(S.meta), ...(state.options || {}) };
  S.settings = mergeSettings(S.meta && S.meta.settings, state.settings);
  S.sourceName = state.source_name || "";
  S.inputWarnings = [];
  $("pill-saved").textContent = state.saved_at ? "Saved " + fmtWhen(state.saved_at) : "Not saved yet";
  renderAll();
  schedulePreview(0);
  loadHistory();
}

// Re-read the recipe after an edit, keeping the working grid/options/settings.
async function refreshRecipeMeta() {
  if (!S.id) return;
  try {
    const detail = await api("GET", `/recipes/${encodeURIComponent(S.id)}`);
    const hadMeta = !!S.meta;
    S.meta = detail.meta;
    S.loadError = detail.load_error || "";
    if (S.meta) {
      S.options = { ...optionDefaults(S.meta), ...S.options };
      if (!hadMeta || !S.settings) S.settings = mergeSettings(S.meta.settings, (detail.state || {}).settings);
    }
  } catch (e) {
    S.loadError = e.message;
  }
  renderAll();
  schedulePreview(0);
}

// ── Rendering ────────────────────────────────────────────────────────────────

function renderAll() {
  const r = S.recipes.find((x) => x.id === S.id);
  $("recipe-desc").textContent = S.meta ? (S.meta.description || "") : (r ? r.description || "" : "");
  banner($("recipe-error"), S.loadError ? ["This recipe fails to load. Fix it with Edit recipe.\n\n" + S.loadError] : []);
  const usable = !!S.meta;
  ["btn-load-csv", "btn-add-row", "btn-tick-all", "btn-tick-none", "btn-bulk",
   "btn-delete-ticked", "btn-download", "btn-reset-settings"].forEach((id) => { $(id).disabled = !usable; });
  $("btn-edit-recipe").disabled = !S.id;
  $("btn-scan").hidden = !(usable && S.meta.folder_scan);
  if (usable && S.meta.folder_scan) {
    const opt = S.meta.options.find((o) => o.key === S.meta.folder_scan.option);
    $("btn-scan").title = `Fill the grid from the ${S.meta.folder_scan.files ? "files" : "subfolders"} of "${opt ? opt.label : S.meta.folder_scan.option}"`;
  }
  renderGrid();
  renderOptions();
  renderSettings();
  renderPreview();
  banner($("input-warnings"), S.inputWarnings, true);
  $("input-source").textContent = S.sourceName ? "Source: " + S.sourceName : "";
}

function cellHtml(col, value, ticked) {
  const v = value == null ? "" : String(value);
  const bad = col.choices && v && !col.choices.includes(v);
  const emptyReq = ticked && col.required && !v;
  const cls = (bad ? " cell-bad" : "") + (emptyReq ? " cell-empty-req" : "");
  const title = bad ? ` title="Not one of: ${esc(col.choices.join(", "))}"` : (col.help ? ` title="${esc(col.help)}"` : "");
  let control;
  if (col.readonly) {
    control = `<span class="cell-readonly${cls}"${title}>${esc(v)}</span>`;
  } else if (col.choices) {
    let opts = "";
    if (!col.required || !v) opts += `<option value=""${v ? "" : " selected"}>—</option>`;
    if (bad) opts += `<option value="${esc(v)}" selected>${esc(v)} (?)</option>`;
    opts += col.choices.map((c) => `<option value="${esc(c)}"${c === v ? " selected" : ""}>${esc(c)}</option>`).join("");
    control = `<select class="cell-select${cls}" data-k="${esc(col.key)}"${title}>${opts}</select>`;
  } else {
    control = `<input class="cell-input${cls}" data-k="${esc(col.key)}" value="${esc(v)}" spellcheck="false"${title}>`;
  }
  if (col.swatch) {
    const hex = hexColor(v);
    control = `<div class="cell-swatch"><span class="swatch" style="${hex ? "background:" + hex : ""}"></span>${control}</div>`;
  }
  return control;
}

function renderGrid() {
  const head = $("grid-head");
  const body = $("grid-body");
  if (!S.meta) {
    head.innerHTML = "";
    body.innerHTML = `<tr><td class="grid-empty">No recipe loaded.</td></tr>`;
    updateRowCount();
    return;
  }
  const cols = S.meta.columns;
  head.innerHTML = "<tr><th class=\"col-tick\"></th><th class=\"col-num\">#</th>" +
    cols.map((c) => `<th title="${esc(c.help || (c.aliases.length ? "Also accepts: " + c.aliases.join(", ") : ""))}">${esc(c.name)}${c.required ? '<span class="req">*</span>' : ""}</th>`).join("") +
    "<th class=\"col-del\"></th></tr>";
  if (!S.rows.length) {
    const how = S.meta.folder_scan ? "Load a CSV, Scan folder or add rows." : "Load a CSV or add rows.";
    body.innerHTML = `<tr><td class="grid-empty" colspan="${cols.length + 3}">No rows yet. ${how}</td></tr>`;
    updateRowCount();
    return;
  }
  body.innerHTML = S.rows.map((row, i) => {
    const on = row._on !== false;
    return `<tr data-i="${i}" class="${on ? "" : "off"}">` +
      `<td class="col-tick"><input type="checkbox" class="row-tick"${on ? " checked" : ""} aria-label="Render row ${i + 1}"></td>` +
      `<td class="col-num">${i + 1}</td>` +
      cols.map((c) => `<td>${cellHtml(c, row[c.key], on)}</td>`).join("") +
      `<td class="col-del"><button class="row-del" title="Delete row" aria-label="Delete row ${i + 1}">&times;</button></td></tr>`;
  }).join("");
  updateRowCount();
}

function refreshRowCells(tr) {
  const i = Number(tr.dataset.i);
  const row = S.rows[i];
  const on = row._on !== false;
  tr.classList.toggle("off", !on);
  const cols = S.meta.columns;
  const tds = tr.querySelectorAll("td");
  cols.forEach((c, ci) => {
    const td = tds[ci + 2];
    const active = document.activeElement;
    const focusedHere = active && td.contains(active);
    const v = row[c.key] == null ? "" : String(row[c.key]);
    const bad = c.choices && v && !c.choices.includes(v);
    const ctrl = td.querySelector(".cell-input, .cell-select, .cell-readonly");
    if (focusedHere && ctrl && ctrl.tagName === "INPUT") {
      ctrl.classList.toggle("cell-bad", !!bad);
      ctrl.classList.toggle("cell-empty-req", on && c.required && !v);
    } else {
      td.innerHTML = cellHtml(c, v, on);
      if (focusedHere) {
        const again = td.querySelector(".cell-input, .cell-select");
        if (again) again.focus();
      }
    }
  });
}

function updateRowCount() {
  const total = S.rows.length;
  const ticked = S.rows.filter((r) => r._on !== false).length;
  $("rows-count").textContent = total ? `${ticked} / ${total} ticked` : "0";
}

function renderOptions() {
  const panel = $("panel-options");
  const form = $("options-form");
  const opts = S.meta ? S.meta.options : [];
  panel.hidden = !opts.length;
  form.innerHTML = opts.map((o) => {
    const id = "o-" + o.key;
    const v = S.options[o.key];
    const hint = o.help ? `<div class="field-hint option-hint">${esc(o.help)}</div>` : "";
    if (o.kind === "toggle") {
      return `<div class="form-block"><label class="toggle"><input type="checkbox" id="${esc(id)}" data-opt="${esc(o.key)}"${v ? " checked" : ""}> ${esc(o.label)}</label>${hint}</div>`;
    }
    let control;
    if (o.kind === "choice") {
      control = `<select id="${esc(id)}" class="select" data-opt="${esc(o.key)}">` +
        o.choices.map((c, ci) => `<option value="${esc(c)}"${c === v ? " selected" : ""}>${esc(o.labels[ci])}</option>`).join("") + "</select>";
    } else if (o.kind === "number") {
      const attrs = (o.min != null ? ` min="${o.min}"` : "") + (o.max != null ? ` max="${o.max}"` : "") + ` step="${o.step || 1}"`;
      control = `<input type="number" id="${esc(id)}" class="input" data-opt="${esc(o.key)}" value="${esc(v)}"${attrs}>`;
    } else if (o.kind === "folder") {
      control = `<div class="input-with-btn"><input type="text" id="${esc(id)}" class="input" data-opt="${esc(o.key)}" value="${esc(v)}" spellcheck="false">` +
        `<button type="button" class="btn native-only" data-browse="${esc(id)}" hidden>Browse…</button></div>`;
    } else {
      control = `<input type="text" id="${esc(id)}" class="input" data-opt="${esc(o.key)}" value="${esc(v)}" spellcheck="false">`;
    }
    return `<div class="form-block"><label class="field-label" for="${esc(id)}">${esc(o.label)}</label>${control}${hint}</div>`;
  }).join("");
  revealNativePickers();
}

function renderSettings() {
  const s = S.settings;
  if (!s) return;
  $("s-folder").value = (s.output.folder || "").replace(/\//g, "\\");
  const ver = s.output.version || "";
  const versions = VERSIONS.includes(ver) ? VERSIONS : VERSIONS.concat([ver]);
  $("s-version").innerHTML = versions.map((v) => `<option value="${esc(v)}">${v ? esc(v) : "None"}</option>`).join("");
  $("s-version").value = ver;
  $("s-format").value = DEPTH_OPTS[s.output.format] ? s.output.format : "jpg";
  syncFormatDependents(s.output.depth_index || 0);
  $("s-alpha").checked = !!s.output.save_alpha;
  $("s-re").checked = !!s.output.save_render_elements && s.output.format !== "png";
  $("s-override").checked = !!s.render.override_settings;
  $("s-resolution").value = s.render.resolution;
  $("s-pass").value = s.render.pass_limit;
  $("s-noise").value = s.render.noise_limit;
  $("s-chunk").value = s.chunk_rows || 0;
  $("s-override-block").hidden = !s.render.override_settings;
}

function syncFormatDependents(depthIndex) {
  const fmt = $("s-format").value;
  const opts = DEPTH_OPTS[fmt] || DEPTH_OPTS.jpg;
  const sel = $("s-depth");
  const prev = depthIndex != null ? depthIndex : Number(sel.value) || 0;
  sel.innerHTML = opts.map((l, i) => `<option value="${i}">${esc(l)}</option>`).join("");
  sel.value = String(Math.min(Math.max(prev, 0), opts.length - 1));
  sel.disabled = fmt === "jpg";
  $("s-alpha-row").hidden = fmt === "jpg";
  const re = $("s-re");
  re.disabled = fmt === "png";
  if (fmt === "png") re.checked = false;
  $("s-re-row").title = fmt === "png" ? "Render elements aren't supported for PNG output. Use EXR or TIFF to save passes." : "";
}

function readSettings() {
  const s = S.settings;
  const num = (id, fallback) => {
    const v = $(id).value.trim();
    const n = Number(v);
    return v === "" || !Number.isFinite(n) ? fallback : n;
  };
  s.output.folder = cleanPathText($("s-folder").value);
  s.output.version = $("s-version").value || null;
  s.output.format = $("s-format").value;
  s.output.depth_index = Number($("s-depth").value) || 0;
  s.output.save_alpha = s.output.format !== "jpg" && $("s-alpha").checked;
  s.output.save_render_elements = $("s-re").checked && s.output.format !== "png";
  s.render.override_settings = $("s-override").checked;
  s.render.resolution = num("s-resolution", s.render.resolution);
  s.render.pass_limit = num("s-pass", s.render.pass_limit);
  s.render.noise_limit = num("s-noise", s.render.noise_limit);
  s.chunk_rows = Math.max(0, Math.floor(num("s-chunk", 0)));
  $("s-override-block").hidden = !s.render.override_settings;
}

// ── Preview ──────────────────────────────────────────────────────────────────

function schedulePreview(delay = 450) {
  if (previewTimer) clearTimeout(previewTimer);
  previewTimer = setTimeout(runPreview, delay);
}

function requestBody() {
  return { rows: S.rows, options: S.options, settings: S.settings };
}

async function runPreview() {
  previewTimer = null;
  if (!S.meta) { S.preview = null; renderPreview(); return; }
  const seq = ++previewSeq;
  const status = $("preview-status");
  status.textContent = "Updating…";
  status.className = "preview-status busy";
  try {
    const res = await api("POST", `/recipes/${encodeURIComponent(S.id)}/preview`, requestBody());
    if (seq !== previewSeq) return;
    S.preview = res;
  } catch (e) {
    if (seq !== previewSeq) return;
    S.preview = { ok: false, errors: [e.message], warnings: [], scenes: [], totals: { jobs: 0, rows: 0 }, log: [] };
    if (e.status === 422) refreshRecipeMeta();
  }
  renderPreview();
}

function renderPreview() {
  const p = S.preview;
  const status = $("preview-status");
  const body = $("preview-body");
  const submit = $("btn-submit");
  if (!p || !S.meta) {
    status.textContent = S.meta ? "—" : "";
    status.className = "preview-status";
    body.innerHTML = `<tr><td colspan="6" class="empty">Load rows to see the jobs this recipe creates.</td></tr>`;
    banner($("preview-errors"), []);
    banner($("preview-warnings"), []);
    $("preview-log").hidden = true;
    submit.disabled = true;
    submit.textContent = "Submit";
    return;
  }
  banner($("preview-errors"), p.errors, true);
  banner($("preview-warnings"), p.warnings, true);
  const t = p.totals || {};
  if (p.ok) {
    status.textContent = `${t.input_rows} input row(s) → ${t.scenes} scene(s), ${t.jobs} job(s), ${t.rows} variation row(s)`;
    status.className = "preview-status";
  } else {
    status.textContent = `${p.errors.length} problem(s) to fix before submitting`;
    status.className = "preview-status bad";
  }
  const scenes = p.scenes || [];
  if (!scenes.length) {
    body.innerHTML = `<tr><td colspan="6" class="empty">${p.ok ? "No jobs." : "No jobs until the problems above are fixed."}</td></tr>`;
  } else {
    body.innerHTML = scenes.map((sc) => {
      const missing = sc.exists === false;
      const split = sc.ranges.length
        ? esc(sc.ranges.slice(0, 8).join(", ") + (sc.ranges.length > 8 ? `, … (${sc.ranges.length})` : ""))
        : "—";
      const render = (sc.resolution ? `${sc.resolution}px · ${sc.pass_limit} passes` : "scene settings") +
        ` · ${sc.format}${sc.version ? " · " + sc.version : ""}`;
      const sample = (sc.sample || []).map((r) => r.join(" | ")).join("\n");
      return `<tr title="${esc("Headers: " + sc.headers.join(" | ") + (sample ? "\nFirst rows:\n" + sample : ""))}">` +
        `<td><div class="scene-key">${esc(sc.key)}</div>${sc.label !== sc.key ? `<div class="scene-sub">${esc(sc.label)}</div>` : ""}</td>` +
        `<td class="file${missing ? " missing" : ""}" title="${esc(sc.path)}">${missing ? "⚠ " : ""}${esc(baseName(sc.path))}</td>` +
        `<td class="num">${sc.rows}</td><td class="num">${sc.jobs}</td>` +
        `<td class="ranges">${split}</td><td class="ranges">${esc(render)}</td></tr>`;
    }).join("") +
      `<tr class="totals"><td><b>Total</b></td><td></td><td class="num"><b>${t.rows}</b></td><td class="num"><b>${t.jobs}</b></td><td></td><td></td></tr>`;
  }
  const log = p.log || [];
  $("preview-log").hidden = !log.length;
  $("preview-log-text").textContent = log.join("\n");
  submit.disabled = !(p.ok && t.jobs > 0);
  submit.textContent = p.ok && t.jobs ? `Submit ${t.jobs} job(s)` : "Submit";
}

// ── Saving the working state ─────────────────────────────────────────────────

function onStateChanged(preview = true) {
  updateRowCount();
  scheduleSave();
  if (preview) schedulePreview();
}

function stateBody() {
  return {
    state: {
      rows: S.rows, options: S.options, settings: S.settings,
      source_name: S.sourceName, saved_at: new Date().toISOString(),
    },
  };
}

function scheduleSave() {
  if (!S.id || !S.meta) return;
  if (saveTimer) clearTimeout(saveTimer);
  $("pill-saved").textContent = "Unsaved changes";
  saveTimer = setTimeout(() => saveStateNow(), 900);
}

async function saveStateNow(keepalive) {
  if (saveTimer) { clearTimeout(saveTimer); saveTimer = null; }
  if (!S.id || !S.meta) return;
  const id = S.id;
  try {
    await api("POST", `/recipes/${encodeURIComponent(id)}/state`, stateBody(), { keepalive });
    if (id === S.id) {
      $("pill-saved").textContent = "Saved " + fmtWhen(new Date().toISOString());
      $("pill-saved").classList.remove("error");
    }
  } catch (e) {
    $("pill-saved").textContent = "Not saved: " + e.message;
  }
}

async function flushSave() {
  if (saveTimer) await saveStateNow();
}

// ── Grid actions ─────────────────────────────────────────────────────────────

function newRow() {
  const row = { _on: true };
  for (const c of S.meta.columns) row[c.key] = c.default || "";
  return row;
}

function onGridInput(ev) {
  const tr = ev.target.closest("tr[data-i]");
  if (!tr) return;
  const row = S.rows[Number(tr.dataset.i)];
  if (!row) return;
  if (ev.target.classList.contains("row-tick")) {
    row._on = ev.target.checked;
    refreshRowCells(tr);
  } else if (ev.target.dataset.k) {
    row[ev.target.dataset.k] = ev.target.value;
    if (ev.type === "change" || ev.target.tagName === "SELECT") refreshRowCells(tr);
    else {
      const col = S.meta.columns.find((c) => c.key === ev.target.dataset.k);
      const v = ev.target.value;
      ev.target.classList.toggle("cell-empty-req", row._on !== false && col.required && !v.trim());
    }
  }
  onStateChanged();
}

function onGridClick(ev) {
  const del = ev.target.closest(".row-del");
  if (!del) return;
  const tr = del.closest("tr[data-i]");
  S.rows.splice(Number(tr.dataset.i), 1);
  renderGrid();
  onStateChanged();
}

function addRow() {
  S.rows.push(newRow());
  renderGrid();
  onStateChanged();
  const last = $("grid-body").querySelector("tr:last-child .cell-input, tr:last-child .cell-select");
  if (last) last.focus();
  $("grid-wrap").scrollTop = $("grid-wrap").scrollHeight;
}

function tickAll(on) {
  S.rows.forEach((r) => { r._on = on; });
  renderGrid();
  onStateChanged();
}

function deleteTicked() {
  const n = S.rows.filter((r) => r._on !== false).length;
  if (!n) { toast("No ticked rows."); return; }
  if (!confirm(`Delete ${n} ticked row(s) from the grid?`)) return;
  S.rows = S.rows.filter((r) => r._on === false);
  renderGrid();
  onStateChanged();
}

async function loadCsvFile(file) {
  if (!file) return;
  if (S.rows.length && !confirm(`Replace the ${S.rows.length} row(s) in the grid with ${file.name}?`)) return;
  try {
    const buf = await file.arrayBuffer();
    const res = await api("POST", `/recipes/${encodeURIComponent(S.id)}/load_csv`,
      { filename: file.name, data_b64: arrayBufferToBase64(buf) });
    S.rows = res.rows || [];
    S.sourceName = file.name;
    S.inputWarnings = res.warnings || [];
    renderAll();
    onStateChanged();
    toast(`Loaded ${S.rows.length} row(s) from ${file.name}.`);
  } catch (e) {
    S.inputWarnings = [];
    banner($("input-warnings"), [e.message]);
    toast("Could not load the file.", true);
  }
}

async function scanFolder() {
  try {
    const res = await api("POST", `/recipes/${encodeURIComponent(S.id)}/scan`, { options: S.options, rows: S.rows });
    S.rows = res.rows || [];
    const scan = S.meta.folder_scan;
    S.sourceName = "Folder scan of " + (S.options[scan.option] || "");
    S.inputWarnings = res.warnings || [];
    renderAll();
    onStateChanged();
  } catch (e) {
    banner($("input-warnings"), [e.message]);
  }
}

// ── Bulk edit ────────────────────────────────────────────────────────────────

function bulkColumns() { return S.meta.columns.filter((c) => !c.readonly); }

function openBulk() {
  const ticked = S.rows.filter((r) => r._on !== false).length;
  if (!ticked) { toast("Tick the rows to edit first."); return; }
  const cols = bulkColumns();
  if (!cols.length) { toast("This recipe has no editable columns."); return; }
  $("bulk-column").innerHTML = cols.map((c) => `<option value="${esc(c.key)}">${esc(c.name)}</option>`).join("");
  syncBulk();
  $("bulk-overlay").hidden = false;
  $("bulk-column").focus();
}

function syncBulk() {
  const col = S.meta.columns.find((c) => c.key === $("bulk-column").value);
  const act = $("bulk-action");
  act.querySelector('option[value="random"]').disabled = !col.choices;
  if (!col.choices && act.value === "random") act.value = "set";
  const random = act.value === "random";
  $("bulk-value-row").hidden = random;
  $("bulk-value-text").hidden = !!col.choices;
  $("bulk-value-select").hidden = !col.choices;
  if (col.choices) {
    $("bulk-value-select").innerHTML = (col.required ? "" : `<option value="">—</option>`) +
      col.choices.map((c) => `<option value="${esc(c)}">${esc(c)}</option>`).join("");
  }
  const n = S.rows.filter((r) => r._on !== false).length;
  $("bulk-hint").textContent = random
    ? `Each of the ${n} ticked row(s) gets a random ${col.name} from its ${col.choices.length} choices. This replaces their current values.`
    : `Applies to the ${n} ticked row(s).`;
}

function applyBulk() {
  const col = S.meta.columns.find((c) => c.key === $("bulk-column").value);
  const random = $("bulk-action").value === "random";
  const value = col.choices ? $("bulk-value-select").value : $("bulk-value-text").value.trim();
  let n = 0;
  for (const r of S.rows) {
    if (r._on === false) continue;
    r[col.key] = random ? col.choices[Math.floor(Math.random() * col.choices.length)] : value;
    n++;
  }
  $("bulk-overlay").hidden = true;
  renderGrid();
  onStateChanged();
  toast(`${random ? "Randomized" : "Set"} ${col.name} on ${n} row(s).`);
}

// ── Submit / download ────────────────────────────────────────────────────────

async function submit() {
  const p = S.preview;
  if (!p || !p.ok) return;
  const t = p.totals;
  const folder = S.settings.output.folder;
  if (!confirm(`Queue ${t.jobs} job(s) (${t.rows} variation rows in ${t.scenes} scene(s)) as one submission?\n\nOutput: ${folder}`)) return;
  const btn = $("btn-submit");
  btn.disabled = true;
  await flushSave();
  try {
    const res = await api("POST", `/recipes/${encodeURIComponent(S.id)}/submit`,
      { ...requestBody(), source_name: S.sourceName });
    const el = $("submit-result");
    el.hidden = false;
    el.innerHTML = `Queued ${res.count} job(s) as one submission (request ${esc(res.request_id.slice(0, 8))}). ` +
      `<a href="/">Open the queue</a>` +
      (res.archive ? `<br>Inputs and payloads archived as ${esc(res.archive)}.` : "") +
      (res.archive_error ? `<br>Archive failed: ${esc(res.archive_error)}` : "");
    toast(`Submitted ${res.count} job(s).`);
    loadHistory();
  } catch (e) {
    if (e.data && e.data.result) { S.preview = e.data.result; renderPreview(); }
    toast("Submit failed: " + e.message, true);
  } finally {
    renderPreview();
  }
}

async function downloadPayloads() {
  try {
    const res = await api("POST", `/recipes/${encodeURIComponent(S.id)}/preview`, { ...requestBody(), include_payloads: true });
    if (!res.ok) { toast("Fix the preview problems first.", true); return; }
    const blob = new Blob([JSON.stringify(res.payloads, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${S.id}_payloads.json`;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
  } catch (e) {
    toast("Download failed: " + e.message, true);
  }
}

// ── History ──────────────────────────────────────────────────────────────────

async function loadHistory() {
  const box = $("history");
  if (!S.id) { box.innerHTML = `<div class="history-empty">None yet.</div>`; return; }
  try {
    const res = await api("GET", `/recipes/${encodeURIComponent(S.id)}/history`);
    const items = res.history || [];
    box.innerHTML = items.length ? items.map((h) =>
      `<div class="history-item"><div class="history-main">` +
      `<span class="history-when">${esc(fmtWhen(h.submitted_at))} · ${h.jobs} job(s)</span>` +
      `<span class="history-meta" title="${esc(h.file)}">${h.rows} rows${h.source_name ? " · " + esc(h.source_name) : ""}</span></div>` +
      `<button class="btn" data-restore="${esc(h.file)}" title="Load this submission's rows, options and settings into the page">Restore</button></div>`
    ).join("") : `<div class="history-empty">None yet.</div>`;
  } catch (e) {
    box.innerHTML = `<div class="history-empty">${esc(e.message)}</div>`;
  }
}

async function restoreSubmission(file) {
  if (!confirm("Replace the grid, options and settings with this submission's inputs?")) return;
  try {
    const rec = await api("GET", `/submissions/${encodeURIComponent(file)}`);
    S.rows = rec.rows || [];
    S.options = { ...optionDefaults(S.meta), ...(rec.options || {}) };
    S.settings = mergeSettings(S.meta.settings, rec.settings);
    S.sourceName = (rec.source_name || "") + ` (restored from ${fmtWhen(rec.submitted_at)})`;
    S.inputWarnings = [];
    renderAll();
    onStateChanged();
  } catch (e) {
    toast("Restore failed: " + e.message, true);
  }
}

// ── Recipe editor ────────────────────────────────────────────────────────────

async function openEditor() {
  if (!S.id) return;
  try {
    const d = await api("GET", `/recipes/${encodeURIComponent(S.id)}`);
    editor = { id: S.id, mtime: d.mtime, loaded: d.source };
    $("editor-text").value = d.source;
    $("editor-title").textContent = `Edit recipe · ${S.id}.py`;
    $("editor-path").textContent = S.folder;
    banner($("editor-error"), d.load_error ? [d.load_error] : []);
    $("editor-overlay").hidden = false;
    $("editor-text").focus();
  } catch (e) {
    toast("Could not open the recipe: " + e.message, true);
  }
}

function editorDirty() { return $("editor-text").value !== editor.loaded; }

function closeEditor(force) {
  if (!force && editorDirty() && !confirm("Discard unsaved changes to the recipe?")) return;
  $("editor-overlay").hidden = true;
}

async function saveEditor(force) {
  const source = $("editor-text").value;
  const btn = $("editor-save");
  btn.disabled = true;
  try {
    const res = await api("POST", `/recipes/${encodeURIComponent(editor.id)}/source`,
      { source, base_mtime: editor.mtime, force: !!force });
    editor.mtime = res.mtime;
    editor.loaded = source;
    banner($("editor-error"), res.load_error ? ["Saved, but the recipe fails to load:\n\n" + res.load_error] : []);
    toast(res.load_error ? "Saved with errors." : "Recipe saved.", !!res.load_error);
    await loadRecipeList(S.id);
    await refreshRecipeMeta();
  } catch (e) {
    if (e.status === 409 && e.data && e.data.error === "changed_on_disk") {
      if (confirm("The recipe file changed on disk since you opened it (edited elsewhere?).\n\nOverwrite it with your version?")) {
        btn.disabled = false;
        return saveEditor(true);
      }
    } else {
      toast("Save failed: " + e.message, true);
    }
  } finally {
    btn.disabled = false;
  }
}

async function reloadEditor() {
  if (editorDirty() && !confirm("Discard your edits and reload the file from disk?")) return;
  await openEditor();
}

function onEditorKeydown(ev) {
  const ta = ev.target;
  if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "s") {
    ev.preventDefault();
    saveEditor();
    return;
  }
  if (ev.key !== "Tab") return;
  ev.preventDefault();
  const { selectionStart: a, selectionEnd: b, value } = ta;
  const lineStart = value.lastIndexOf("\n", a - 1) + 1;
  if (a === b && !ev.shiftKey) {
    ta.setRangeText("    ", a, b, "end");
    return;
  }
  // Indent / dedent every line touched by the selection.
  const block = value.slice(lineStart, b);
  const lines = block.split("\n");
  const changed = ev.shiftKey
    ? lines.map((l) => l.replace(/^ {1,4}/, ""))
    : lines.map((l) => "    " + l);
  const text = changed.join("\n");
  ta.setRangeText(text, lineStart, b, "select");
  if (a === b) ta.setSelectionRange(Math.max(lineStart, a - (block.length - text.length)), Math.max(lineStart, a - (block.length - text.length)));
}

async function newRecipe() {
  const id = (prompt("File name for the new recipe (letters, digits, _ and -), e.g. client_project:", "") || "").trim();
  if (!id) return;
  if (!RECIPE_ID_RE.test(id)) { toast("Use letters, digits, _ and - only.", true); return; }
  try {
    await api("POST", `/recipes/${encodeURIComponent(id)}/source`, { create: true });
    await loadRecipeList(id);
    await selectRecipe(id);
    await openEditor();
  } catch (e) {
    toast("Could not create the recipe: " + e.message, true);
  }
}

// ── Wiring ───────────────────────────────────────────────────────────────────

function onOptionChange(ev) {
  const key = ev.target.dataset.opt;
  if (!key) return;
  const o = S.meta.options.find((x) => x.key === key);
  let v;
  if (o.kind === "toggle") v = ev.target.checked;
  else if (o.kind === "number") v = ev.target.value === "" ? o.default : Number(ev.target.value);
  else if (o.kind === "folder") {
    v = cleanPathText(ev.target.value);
    if (ev.type === "change" && v !== ev.target.value) ev.target.value = v;
  } else v = ev.target.value;
  S.options[key] = v;
  onStateChanged();
}

function onSettingsChange(ev) {
  if (!S.settings) return;
  if (ev.target.id === "s-format") syncFormatDependents();
  if (ev.target.id === "s-folder" && ev.type === "change") {
    const c = cleanPathText(ev.target.value);
    if (c !== ev.target.value) ev.target.value = c;
  }
  readSettings();
  onStateChanged();
}

function resetSettings() {
  if (!S.meta) return;
  if (!confirm("Reset output & render settings to this recipe's defaults?")) return;
  S.settings = mergeSettings(S.meta.settings, null);
  renderSettings();
  onStateChanged();
}

function onKeydown(ev) {
  if (ev.key !== "Escape") return;
  if (!$("bulk-overlay").hidden) $("bulk-overlay").hidden = true;
  else if (!$("editor-overlay").hidden) closeEditor();
}

function wire() {
  $("recipe-select").addEventListener("change", (ev) => selectRecipe(ev.target.value));
  $("btn-edit-recipe").addEventListener("click", openEditor);
  $("btn-new-recipe").addEventListener("click", newRecipe);

  $("btn-load-csv").addEventListener("click", () => { $("csv-file").value = ""; $("csv-file").click(); });
  $("csv-file").addEventListener("change", (ev) => loadCsvFile(ev.target.files[0]));
  $("btn-scan").addEventListener("click", scanFolder);
  $("btn-add-row").addEventListener("click", addRow);
  $("btn-tick-all").addEventListener("click", () => tickAll(true));
  $("btn-tick-none").addEventListener("click", () => tickAll(false));
  $("btn-delete-ticked").addEventListener("click", deleteTicked);
  $("btn-bulk").addEventListener("click", openBulk);
  $("grid-body").addEventListener("input", onGridInput);
  $("grid-body").addEventListener("change", onGridInput);
  $("grid-body").addEventListener("click", onGridClick);

  $("options-form").addEventListener("input", onOptionChange);
  $("options-form").addEventListener("change", onOptionChange);
  $("options-form").addEventListener("click", (ev) => {
    const b = ev.target.closest("[data-browse]");
    if (b) browseFolderInto($(b.dataset.browse));
  });

  const settings = document.querySelector(".settings-form");
  settings.addEventListener("input", onSettingsChange);
  settings.addEventListener("change", onSettingsChange);
  $("s-folder-browse").addEventListener("click", () => browseFolderInto($("s-folder")));
  $("btn-reset-settings").addEventListener("click", resetSettings);

  $("btn-submit").addEventListener("click", submit);
  $("btn-download").addEventListener("click", downloadPayloads);
  $("history").addEventListener("click", (ev) => {
    const b = ev.target.closest("[data-restore]");
    if (b) restoreSubmission(b.dataset.restore);
  });

  $("bulk-column").addEventListener("change", syncBulk);
  $("bulk-action").addEventListener("change", syncBulk);
  $("bulk-apply").addEventListener("click", applyBulk);
  $("bulk-cancel").addEventListener("click", () => { $("bulk-overlay").hidden = true; });
  $("bulk-close").addEventListener("click", () => { $("bulk-overlay").hidden = true; });

  $("editor-text").addEventListener("keydown", onEditorKeydown);
  $("editor-save").addEventListener("click", () => saveEditor());
  $("editor-reload").addEventListener("click", reloadEditor);
  $("editor-cancel").addEventListener("click", () => closeEditor());
  $("editor-close").addEventListener("click", () => closeEditor());

  document.addEventListener("keydown", onKeydown);
  window.addEventListener("pywebviewready", revealNativePickers);
  // Don't lose the last edits when leaving the page (e.g. back to the queue).
  window.addEventListener("pagehide", () => { if (saveTimer) saveStateNow(true); });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden" && saveTimer) saveStateNow(true);
  });
  revealNativePickers();
}

async function init() {
  wire();
  try {
    const id = await loadRecipeList();
    await selectRecipe(id);
  } catch (e) {
    S.loadError = "Could not load recipes: " + e.message;
    renderAll();
  }
}

init();

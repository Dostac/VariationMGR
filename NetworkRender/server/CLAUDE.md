# NetworkRender Server Context

This folder contains the network job server and the web dashboard it serves.
There is a single UI — the browser dashboard. `--ui` simply wraps that same
dashboard in a native window (pywebview); there is no separate desktop UI codebase.

## Core Service (`server.py`)

`server.py` hosts a threaded HTTP API (`ThreadingHTTPServer`) backed by `JobServerState`.
State is protected by a re-entrant lock and persisted as JSON with atomic file replacement.

### CLI

`python server.py [--host HOST] [--port PORT] [--state-file PATH] [--allow-non-local] [--no-discovery] [--ui]`

Without `--ui` the server runs headless (just the HTTP API + web dashboard). With
`--ui` it additionally opens the web dashboard in a native window via pywebview
(Edge WebView2 on Windows). If pywebview is not installed, `--ui` falls back to
headless. `pip install pywebview` is required for the windowed mode.

### In-Memory State Shape

- `jobs`: job records keyed by `job_id`.
- `queue`: ordered queued `job_id` deque.
- `requests`: submission groups keyed by `request_id` with linked job ids.
- `workers`: ephemeral worker registry keyed by `worker_id`.
- `queue_paused`: flag that blocks new claims while leaving existing jobs intact.

### Job Lifecycle

Jobs move through: `queued -> claimed/running -> done/failed` (or back to `queued` for retries/requeue).

A queued job may also carry a `frozen: true` flag (orthogonal to status). `claim_job`
scans the queue for the first non-frozen queued job, leaving frozen jobs in place;
it prunes genuinely-stale ids as it goes. Frozen is *not* a status, so it doesn't
touch the state machine — it just gates claiming. An explicit requeue clears it.

State repair logic removes dangling references, de-duplicates queue entries, requeues orphaned claims, and prunes empty requests.

### HTTP API Surface

- `GET /`: read-only HTML dashboard for browser-based status/health monitoring.
- `GET /static/server_dashboard.css`: stylesheet for the internal dashboard.
- `GET /health`: health, schema version, aggregate stats.
- `GET /jobs` and `GET /jobs/{job_id}`: list or inspect jobs.
- `GET /workers`: current worker snapshot list.
- `POST /submit`: normalize request and enqueue one job per scene file.
- `POST /workers/register`: register/refresh worker identity (accepts an optional `color` hex).
- Worker heartbeats may also carry `color`; the server sanitizes it to `#rrggbb` (or `""`) and the dashboard prefers it over the auto-assigned hue.
- `POST /workers/{id}/heartbeat`: update worker status and activity.
- `POST /workers/{id}/claim`: claim next queued job.
- `POST /workers/{id}/job/{job_id}/status`: worker status update for a claimed job.
- `POST /workers/{id}/unregister`: remove worker and optionally requeue its claimed work.
- `POST /admin/queue/pause`, `/admin/auto_requeue`: queue/auto-requeue toggles.
- `POST /admin/queue/reorder`: rewrite the pending queue order from a `job_ids` list (claim order). Ignores ids no longer queued; appends still-queued jobs missing from the request.
- `POST /admin/jobs/freeze`: set/clear the `frozen` flag on queued jobs (`{job_ids, frozen}`). Frozen jobs stay queued at their position but are skipped by `claim_job` until unfrozen.
- `POST /admin/jobs/update`: edit already-submitted jobs' render/output settings. Accepts either `{job_id, render?, output?}` (single) or `{job_ids:[...], render?, output?}` (multi). Only the `render` and `output` sub-dicts are editable, and they are applied **sparsely** — only the keys present are written, so a multi-select edit that omits a field preserves each job's own value for it. Each affected job's merged `scene_job` is re-run through `schema.normalize_job_request` so every value stays valid (e.g. a bad format falls back to `jpg`). Scene file, variation/csv overrides, render range, status, and queue position are left untouched — editing a non-queued job does not change an already-finished render unless it is requeued. Response: `{ok, updated:[ids], count}` (single also echoes `job`).
- `POST /admin/jobs/requeue`, `/admin/jobs/remove`, `/admin/jobs/clear_queue`, `/admin/jobs/remove_by_status`, `/admin/jobs/clear_all`: job/queue management.

### Network/Access Model

- Local-network filtering is active by default (`private`, `loopback`, `link-local`).
- `--allow-non-local` disables that filter.
- UDP discovery responder listens on `port + 1` for `VB_BATCH_DISCOVER_V1` and returns HTTP host/port.

### Runtime Wrapper

`ServerRuntime` coordinates:
- HTTP server lifecycle.
- Optional UDP discovery thread.
- Graceful stop/shutdown and state flush.

## Web Dashboard (`server_dashboard.*`)

The dashboard is plain HTML/CSS/JS served by the HTTP API and rendered by
`server_dashboard.py` (`render_dashboard`, `read_stylesheet`, `read_js`). It polls
`/dashboard_data` and drives every control through the `/admin/*` endpoints:
worker table, job table (with a per-row copy-output-path button), progress, and
performance charts.

On the **Queued** tab, rows are shown in true queue order (`queue_position` from
the payload) and can be dragged to reorder; the drop commits via
`/admin/queue/reorder`. Polling is suspended mid-drag so a refresh can't rebuild
the table under the dragged row.

Selected jobs can be frozen/unfrozen (from the right-click menu below), which
posts to `/admin/jobs/freeze`. Frozen rows show a ❄ badge and a tint; the
payload's `frozen_count` is shown in the stats line and excluded from the ETA
estimate.

**Per-selection actions live in a right-click context menu on job rows**, not on
the action bar — the bar would otherwise sprout too many buttons and hurt the
overview. Right-click is smart about selection: right-clicking a row already in
the selection acts on the whole selection; right-clicking an unselected row
selects just it first. The menu offers Edit / Requeue / Freeze / Unfreeze / Copy
output path / Remove …, all worded with a constant "item(s)" (no plural-switching
logic). Items that don't apply to the selection are greyed, not hidden (e.g.
Freeze when nothing freezable, Copy when multiple rows are selected), so the
menu shape stays stable. Each item just calls the existing `act*` selection
functions — no new endpoints. The native WebView2/browser menu is suppressed via
`preventDefault()`; the menu dismisses on click-away, scroll, resize, or Escape.
Only **queue-wide** actions that have no per-row home stay as bar buttons:
Clear Queue, Remove Done, Remove Failed, Clear All, plus the green **+ New Job**
button docked to the right edge of that bar (see "New Job" below).

Each job row has a pencil button that opens a modal overlay to edit that job's
render/output settings. The modal's layout deliberately mirrors the 3ds Max
Batch Renderer UI (`batchrenderer_UI.py`): grouped sections in the same order —
Output & Naming, Render Settings, VariationMGR Integration, Format Configuration
— with the same labels ("Longest Side", "Pass Limit", "Noise Limit", "Fallback
Camera Mode", "Use VariationMGR scene data", etc.). It reproduces the renderer's
behaviours: the resolution/pass/noise block is collapsed unless "Override scene
render settings" is on, and the Bit Depth options are format-dependent (jpg =
8-bit fixed + alpha hidden; png/tif = 8/16-bit; exr = 16/32-bit), with
`output.depth_index` stored as the index into the current format's list.

The same modal also does **multi-edit**: select rows (click / Ctrl+click /
Shift+click) and choose "Edit selected item(s)" from the right-click menu (or
the pencil on any selected row) to edit the whole selection at once. Fields where every selected job already
agrees are shown with that shared value; fields that differ show a **mixed**
affordance — a dashed input with a "— mixed —" placeholder, a "— mixed —"
`<select>` option, or an **indeterminate (dashed) checkbox**. A mixed field left
untouched is omitted from the save so each job keeps its own value; touching it
(typing, picking an option, clicking the checkbox) commits one value to all.
This is tracked client-side by `editTouched` plus per-control `dataset.mixed`,
and assembled into a sparse body by `computeSave()`; the server applies it via
`update_jobs_fields`.

Save posts to `/admin/jobs/update`. The form prefills from `render`/`output`
included on each job row in `/dashboard_data`, so no extra round-trip is needed.
Polling is suspended while the modal is open (via the `editingJobIds` guard in
`loadData`) so a refresh can't overwrite the fields mid-edit. For non-queued
jobs the modal shows an orange warning that the change only takes effect on
requeue (with a count when multiple are selected); it never blocks the edit.

Not editable in the modal (candidates if needed later): the row range
(`render_range_expr` is settable at submit time, see below, but not via
`/admin/jobs/update`), OCIO color-management overrides (`ocio.*`), and the
per-scene `variation_override` / `csv_override` payloads, all of which the
batch renderer offers.

**New Job** (`openNewJobModal` in `server_dashboard.js`) reuses the very same
modal in a second mode (`modalMode = "new"`) so the two forms can't drift.
`setModalMode()` swaps the title, reveals the submit-only controls (a Scene
Files textarea, one `.max` path per line, which `parseScenePaths()` trims,
de-dupes, unquotes via `cleanPathText()` and flips `\` to `/`; and a Row Range
input under VariationMGR Integration) and relabels the footer button "Submit"
in green. Explorer's "Copy as path" wraps paths in double quotes (PowerShell
in single quotes): `cleanPathText()` strips one matching pair wherever a path
enters the form, the scene list and the folder field normalise pasted text in
place (`onScenePaste` / `onFolderPaste`, via `setRangeText`), the folder field
also tidies typed quotes on blur, and `computeSave()` cleans the folder again
as a safety net, so this applies to edits too.
`fillJobForm()` prefills render/output from `NEW_JOB_DEFAULTS` (the schema
defaults) overlaid with the last submission remembered in `localStorage`
(`vb_new_job_form`; the scene list and row range are never remembered).
Submit validates client-side: at least one scene, output folder set,
`isValidRowRangeExpr()` (a mirror of `variation_core.is_valid_row_range_expr`),
and a camera name when the fallback mode is `by_name`. Lines not ending in
`.max` are flagged in the hint and confirmed, not blocked. It then POSTs the
full request `{max_files, load_scene: true, render, output, render_range_expr}`
to the existing `/submit` (no new endpoint); the server mints the request id
and fans out one queued job per scene. On failure the modal stays open with
the error in the banner. Polling keeps running in new mode: only
`editingJobIds` suspends it.

Inside the `--ui` window the Scene Files block and the Folder field each get a
**Browse…** button that opens a native Explorer dialog through pywebview's
`js_api` (`_DashboardNativeApi` in `server.py`: `pick_scene_files` is a
multi-select `.max` picker, `pick_output_folder` a folder picker). Returned
paths are native Windows form with mapped drive letters resolved to UNC via
`WNetGetConnectionW`, so workers can reach them. The page reveals the buttons on
pywebview's `pywebviewready` event (`revealNativePickers`) and keeps them
hidden in a plain browser, where a file input cannot expose full paths. The
folder button also works in edit mode and marks the field touched, so a
multi-select edit writes it.

`--ui` opens this same page in a pywebview window (`run_server_window` in
`server.py`) — the server runs headless in-process and the window just points at
`http://127.0.0.1:<port>/`. Closing the window stops the server. The window is
created with `js_api=_DashboardNativeApi()` (native pickers, above) and started
with `private_mode=False` and a `storage_path` under the state file's folder
(`.../webview`), so the page's localStorage survives restarts.

Note: a browser/WebView cannot open Explorer on the host, so the old native
"open output folder" action is replaced by a copy-path button (copies the
Windows-native `\\…` path to the clipboard, ready to paste into Explorer).

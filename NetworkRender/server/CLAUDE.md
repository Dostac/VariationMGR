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

Selected jobs can be frozen/unfrozen ("Freeze/Unfreeze Selected"), which posts to
`/admin/jobs/freeze`. Frozen rows show a ❄ badge and a tint; the payload's
`frozen_count` is shown in the stats line and excluded from the ETA estimate.

`--ui` opens this same page in a pywebview window (`run_server_window` in
`server.py`) — the server runs headless in-process and the window just points at
`http://127.0.0.1:<port>/`. Closing the window stops the server.

Note: a browser/WebView cannot open Explorer on the host, so the old native
"open output folder" action is replaced by a copy-path button (copies the
Windows-native `\\…` path to the clipboard, ready to paste into Explorer).

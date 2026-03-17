# NetworkRender Server Context

This folder contains the network job server and its desktop monitoring UI.

## Core Service (`server.py`)

`server.py` hosts a threaded HTTP API (`ThreadingHTTPServer`) backed by `JobServerState`.
State is protected by a re-entrant lock and persisted as JSON with atomic file replacement.

### CLI

`python server.py [--host HOST] [--port PORT] [--state-file PATH] [--allow-non-local] [--no-discovery] [--ui]`

The `--ui` flag launches the PySide6 desktop dashboard (`server_ui.py`) instead of headless mode.

### In-Memory State Shape

- `jobs`: job records keyed by `job_id`.
- `queue`: ordered queued `job_id` deque.
- `requests`: submission groups keyed by `request_id` with linked job ids.
- `workers`: ephemeral worker registry keyed by `worker_id`.
- `queue_paused`: flag that blocks new claims while leaving existing jobs intact.

### Job Lifecycle

Jobs move through: `queued -> claimed/running -> done/failed` (or back to `queued` for retries/requeue).

State repair logic removes dangling references, de-duplicates queue entries, requeues orphaned claims, and prunes empty requests.

### HTTP API Surface

- `GET /`: read-only HTML dashboard for browser-based status/health monitoring.
- `GET /static/server_dashboard.css`: stylesheet for the internal dashboard.
- `GET /health`: health, schema version, aggregate stats.
- `GET /jobs` and `GET /jobs/{job_id}`: list or inspect jobs.
- `GET /workers`: current worker snapshot list.
- `POST /submit`: normalize request and enqueue one job per scene file.
- `POST /workers/register`: register/refresh worker identity.
- `POST /workers/{id}/heartbeat`: update worker status and activity.
- `POST /workers/{id}/claim`: claim next queued job.
- `POST /workers/{id}/job/{job_id}/status`: worker status update for a claimed job.
- `POST /workers/{id}/unregister`: remove worker and optionally requeue its claimed work.
- `POST /admin/requeue_stale`: requeue stale claimed/running jobs by age threshold.

### Network/Access Model

- Local-network filtering is active by default (`private`, `loopback`, `link-local`).
- `--allow-non-local` disables that filter.
- UDP discovery responder listens on `port + 1` for `VB_BATCH_DISCOVER_V1` and returns HTTP host/port.

### Runtime Wrapper

`ServerRuntime` coordinates:
- HTTP server lifecycle.
- Optional UDP discovery thread.
- Graceful stop/shutdown and state flush.

## Desktop Dashboard (`server_ui.py`)

`server_ui.py` provides a PySide6 control panel over the in-process `ServerRuntime`.

The UI polls server state every second and visualizes:
- Worker table (identity, host, status, current job, last seen).
- Job table (scene/output, status chip, worker ownership, attempts, errors).
- Progress from done/total jobs.

UI actions map directly to state operations:
- Pause/resume queue assignment.
- Requeue stale claims.
- Repair persisted state links.
- Remove one job or bulk-remove by status.
- Clear queued jobs or clear all jobs.
- Open a selected job output folder in Explorer.

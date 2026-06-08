# NetworkRender Worker Context

This folder contains the worker runtime, the single-job batch script invoked by 3ds Max, and the optional worker desktop UI.

## Worker Runtime (`worker.py`)

`WorkerRuntime` is a long-running state machine that connects to the server, claims jobs, executes them, and reports status.

### CLI

`python worker.py [--server-url URL] [--worker-id ID] [--worker-name NAME] [--host HOST] [--color #rrggbb] [--mock] [--ui] ...`

The `--ui` flag launches the PySide6 dashboard (`worker_ui.py`) instead of headless mode.

### Configuration Model

`WorkerConfig` includes:
- Server location (`server_url`) and UDP discovery port.
- Worker identity/display fields.
- Poll and heartbeat timing.
- Execution mode (`mock_mode` vs real execution).
- Real execution settings (`executor_cmd`, `max_batch_exe`, `networkrender_script`, timeout).

### Identity and Discovery

- Worker id is persisted per machine key in `worker_identity.json` under `%LOCALAPPDATA%\VirtualBuilders\VariationMGR` (with home/temp fallbacks).
- An optional per-machine dashboard color (`#rrggbb`) is persisted in the same file under `worker_colors` and sent in both register and heartbeat payloads. Empty = the dashboard auto-assigns a hue. Set it with `--color` or the UI color picker (`set_color`/`get_color` on the runtime).
- If no `server_url` is provided, worker uses UDP broadcast discovery through `NetworkRender.shared.server_client.discover_server`.

### Main Loop Behavior

Loop sequence:
1. Ensure a server URL exists (configured or discovered).
2. Check `/health`.
3. Register when entering `starting`.
4. Send periodic heartbeat.
5. When idle, claim a job.
6. Execute and report `running` then `done` or `failed`.
7. Repeat until stop is requested.

If heartbeat/claim returns `worker_not_found`, runtime attempts automatic re-registration and continues.

### Job Execution Paths

- Mock mode: sleep for configured duration and return success payload.
- Custom executor mode: run `executor_cmd` template with `{job_json}` and `{result_json}` placeholders.
- Native batch mode: launch `3dsmaxbatch.exe` with `networkrender.py`, passing paths through `VB_JOB_JSON_PATH` and `VB_RESULT_JSON_PATH`.

Temporary job/result JSON files are created per execution and cleaned up afterward.

Status reporting uses:
- `POST /workers/{id}/job/{job_id}/status` for `running`, `done`, `failed`.
- Error detail is propagated into server-side `last_error`.

## Single-Job Batch Script (`networkrender.py`)

`networkrender.py` is designed for execution inside 3ds Max Python runtime.

Responsibilities:
- Load a single job payload from CLI args or env vars.
- Normalize/coerce payload to exactly one scene job via shared schema.
- Invoke `batchrenderer_core.BatchRendererCore.render_scene_job`.
- Write optional result JSON.
- Return process code `0` for success/skipped and `1` for failure.

## Worker UI (`worker_ui.py`)

`worker_ui.py` wraps `WorkerRuntime` in a PySide6 dashboard.

The UI shows:
- Worker identity, server URL, status, current job.
- Counters for claimed/done/failed work.
- Recent runtime event log.

Available actions:
- Start/stop runtime thread.
- Trigger discovery manually.
- Pick a dashboard color (swatch + color dialog) or reset to Auto.
- Auto-detect duplicate worker entries on the same host and unregister stale entries via server API.

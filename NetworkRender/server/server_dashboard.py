import html
import os
import time
from pathlib import Path

_CSS_PATH = Path(__file__).with_name("server_dashboard.css")

def read_stylesheet():
    return _CSS_PATH.read_text(encoding="utf-8")

def _fmt_ts(ts):
    if not ts:
        return "-"
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(ts)))
    except Exception:
        return "-"


def _short_id(value, length=8):
    text = str(value or "")
    if len(text) <= length:
        return text
    return text[:length]

def render_dashboard(state, server_address):
    stats = state.stats()
    workers = state.list_workers()
    jobs = state.list_jobs()
    jobs_sorted = sorted(jobs, key=lambda item: item.get("updated_at", 0), reverse=True)
    recent_jobs = jobs_sorted[:25]

    total_jobs = max(int(stats.get("jobs_total", 0)), 0)
    done_jobs = int(stats.get("by_status", {}).get("done", 0))
    progress_pct = int((done_jobs / total_jobs) * 100) if total_jobs else 0
    queue_paused = bool(stats.get("queue_paused"))

    def esc(value):
        return html.escape(str(value or ""))

    def status_chip(status):
        # Maps internal status to MD3 semantic chip classes
        css = {
            "queued": "queued",
            "claimed": "running",
            "running": "running",
            "done": "done",
            "success": "done",
            "failed": "failed",
            "idle": "idle",
        }.get(str(status or "").strip().lower(), "idle")
        return f'<span class="chip {css}">{esc(status or "-")}</span>'

    # Determine Queue Indicator Class
    queue_status_text = "Paused" if queue_paused else "Active"
    queue_class = "paused" if queue_paused else "processing"

    worker_rows = []
    for worker in workers:
        worker_rows.append(
            "<tr>"
            f"<td>{esc(worker.get('worker_name') or worker.get('worker_id'))}</td>"
            f"<td>{esc(worker.get('host'))}</td>"
            f"<td>{status_chip(worker.get('status'))}</td>"
            f"<td>{esc(worker.get('current_job_id')) or '-'}</td>"
            f"<td>{esc(_fmt_ts(worker.get('last_seen')))}</td>"
            "</tr>"
        )
    if not worker_rows:
        worker_rows.append('<tr><td colspan="5" class="empty">No workers connected.</td></tr>')

    job_rows = []
    for job in recent_jobs:
        scene_job = job.get("scene_job") or {}
        job_rows.append(
            "<tr>"
            f"<td title=\"{esc(job.get('job_id'))}\">{esc(_short_id(job.get('job_id')))}</td>"
            f"<td title=\"{esc(scene_job.get('scene_file'))}\">{esc(os.path.basename(scene_job.get('scene_file') or '')) or '-'}</td>"
            f"<td title=\"{esc(scene_job.get('output_file'))}\">{esc(os.path.basename(scene_job.get('output_file') or '')) or '-'}</td>"
            f"<td>{status_chip(job.get('status'))}</td>"
            f"<td>{esc(job.get('claimed_by')) or '-'}</td>"
            f"<td>{esc(job.get('attempts', 0))}</td>"
            f"<td>{esc(_fmt_ts(job.get('updated_at')))}</td>"
            f"<td title=\"{esc(job.get('last_error'))}\">{esc(job.get('last_error')) or '-'}</td>"
            "</tr>"
        )
    if not job_rows:
        job_rows.append('<tr><td colspan="8" class="empty">No jobs in the server state.</td></tr>')

    stat_cards = []
    summary_order = (
        ("Total Jobs", total_jobs),
        ("Queued", stats.get("by_status", {}).get("queued", 0)),
        ("Running", stats.get("by_status", {}).get("running", 0) + stats.get("by_status", {}).get("claimed", 0)),
        ("Done", done_jobs),
        ("Failed", stats.get("by_status", {}).get("failed", 0)),
    )
    for label, value in summary_order:
        stat_cards.append(
            "<div class=\"card\">"
            f"<div class=\"label\">{esc(label)}</div>"
            f"<div class=\"value\">{esc(value)}</div>"
            "</div>"
        )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="5">
  <title>VB Batch Server</title>
  <link rel="stylesheet" href="/static/server_dashboard.css">
</head>
<body>
  <div class="wrap">
    <header class="hero">
      <h1>VB Batch Server</h1>
      <div class="sub">Read-only internal dashboard for queue status, worker health, and recent job activity.</div>
      
      <div class="statusline">
        <div class="pill">HTTP: {esc(f"http://{server_address[0]}:{server_address[1]}")}</div>
        <div class="pill">
            Queue: <span class="status-indicator {queue_class}">{esc(queue_status_text)}</span>
        </div>
        <div class="pill">Workers: {esc(stats.get("workers_total", 0))}</div>
        <div class="pill">Auto refresh: 5s</div>
        <div class="pill">Updated: {esc(_fmt_ts(time.time()))}</div>
      </div>
    </header>

    <div class="grid">
      {''.join(stat_cards)}
    </div>

    <section class="panel">
      <div class="label">Total Progress</div>
      <div class="progress-summary">{esc(done_jobs)} of {esc(total_jobs)} jobs complete</div>
      <div class="progress"><div class="bar" style="width: {progress_pct}%"></div></div>
    </section>

    <section class="panel">
      <h2>Workers</h2>
      <table>
        <thead>
          <tr><th>Name</th><th>Host</th><th>Status</th><th>Current Job</th><th>Last Seen</th></tr>
        </thead>
        <tbody>
          {''.join(worker_rows)}
        </tbody>
      </table>
    </section>

    <section class="panel">
      <h2>Recent Jobs</h2>
      <table>
        <thead>
          <tr><th>Job ID</th><th>Scene</th><th>Output</th><th>Status</th><th>Worker</th><th>Attempts</th><th>Updated</th><th>Last Error</th></tr>
        </thead>
        <tbody>
          {''.join(job_rows)}
        </tbody>
      </table>
      <div class="foot">Showing the 25 most recently updated jobs. JSON endpoints remain available at /health, /jobs, and /workers.</div>
    </section>
  </div>
</body>
</html>"""

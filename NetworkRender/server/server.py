import argparse
import copy
import ipaddress
import json
import os
import socket
import sys
import tempfile
import threading
import time
import uuid
from collections import deque
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

if __package__ is None or __package__ == "":
    # Allow direct execution: python NetworkRender/server/server.py
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

from NetworkRender.shared import job_schema as schema
from NetworkRender.server.server_dashboard import read_stylesheet, render_dashboard


DISCOVERY_MAGIC = "VB_BATCH_DISCOVER_V1"
MAX_REQUEST_BODY_BYTES = 10 * 1024 * 1024
DEFAULT_STALE_REQUEUE_SECONDS = 900

# Required on every mutating /admin/* request. Browsers cannot send custom
# headers cross-origin without a CORS preflight, and we never send the
# matching Access-Control-Allow-Headers, so this blocks drive-by POSTs from
# any non-dashboard origin. The dashboard JS adds this header explicitly.
CSRF_HEADER = "X-VB-Request"
CSRF_HEADER_EXPECTED = "1"

AUTO_REQUEUE_TICK_SECONDS = 5
AUTO_REQUEUE_MAX_ATTEMPTS = 2


def _default_server_state_path():
    local_appdata = os.environ.get("LOCALAPPDATA", "").strip()
    if local_appdata:
        try:
            base = Path(local_appdata) / "VirtualBuilders" / "VariationMGR"
            base.mkdir(parents=True, exist_ok=True)
            return str(base / "server_state.json")
        except Exception:
            pass
    return str(Path(__file__).resolve().with_name("server_state.json"))


DEFAULT_STATE_FILE = _default_server_state_path()


def unix_now():
    return time.time()


def utc_now():
    return unix_now()


def _safe_json_load(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _atomic_json_save(path, payload):
    path = os.fspath(path)
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = None
    # NOTE: this is atomic replacement, but intentionally does not provide
    # inter-process file locking. Do not run multiple server instances against
    # the same state file.
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=parent or None,
            prefix=f"{os.path.basename(path)}.",
            suffix=".tmp",
            delete=False,
        ) as f:
            json.dump(payload, f, indent=2)
            tmp = f.name
        os.replace(tmp, path)
    finally:
        if tmp and os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception:
                pass


def _is_local_network_ip(ip_text):
    try:
        ip = ipaddress.ip_address(ip_text)
    except ValueError:
        return False
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
    )


class JobServerState:
    def __init__(self, state_file):
        self.state_file = state_file
        self.lock = threading.RLock()
        self.jobs = {}
        self.queue = deque()
        self.requests = {}
        self.workers = {}
        self.queue_paused = False
        self.auto_requeue_failed = False
        self.load()

    def load(self):
        payload = _safe_json_load(
            self.state_file,
            {"jobs": {}, "queue": [], "requests": {}, "queue_paused": False},
        )
        with self.lock:
            self.jobs = payload.get("jobs", {})
            self.queue = deque(payload.get("queue", []))
            self.requests = payload.get("requests", {})
            self.workers = {}  # workers are ephemeral; never restored from disk
            self.queue_paused = bool(payload.get("queue_paused", False))
            self.auto_requeue_failed = bool(payload.get("auto_requeue_failed", False))
            self.repair_state(save=False)

    def save(self):
        with self.lock:
            payload = {
                "jobs": self.jobs,
                "queue": list(self.queue),
                "requests": self.requests,
                "queue_paused": self.queue_paused,
                "auto_requeue_failed": self.auto_requeue_failed,
            }
            _atomic_json_save(self.state_file, payload)

    def repair_state(self, save=True):
        """
        Repair stale/mismatched links between jobs, queue, requests, and workers.
        This keeps persisted state resilient if the process was killed mid-write
        or older schemas left dangling references.
        """
        with self.lock:
            changed = False

            # Keep queue only to real queued jobs, de-duplicated.
            seen = set()
            fixed_queue = deque()
            for job_id in self.queue:
                if job_id in seen:
                    changed = True
                    continue
                seen.add(job_id)
                job = self.jobs.get(job_id)
                if not job or job.get("status") != "queued":
                    changed = True
                    continue
                fixed_queue.append(job_id)
            if fixed_queue != self.queue:
                self.queue = fixed_queue
                changed = True

            # Reset claimed/running jobs whose worker is no longer registered.
            in_queue = set(self.queue)
            for job_id, job in self.jobs.items():
                if job.get("status") not in ("claimed", "running"):
                    continue
                claimed_by = job.get("claimed_by")
                if claimed_by and claimed_by in self.workers:
                    continue
                job["status"] = "queued"
                job["claimed_by"] = None
                job["updated_at"] = utc_now()
                job["started_at"] = 0
                job["finished_at"] = 0
                if job_id not in in_queue:
                    self.queue.append(job_id)
                    in_queue.add(job_id)
                changed = True

            # Requests: remove missing job links and drop empty requests.
            to_remove_requests = []
            for req_id, req in list(self.requests.items()):
                old = list(req.get("job_ids", []))
                new = [jid for jid in old if jid in self.jobs]
                if new != old:
                    req["job_ids"] = new
                    req["updated_at"] = utc_now()
                    changed = True
                if not req.get("job_ids"):
                    to_remove_requests.append(req_id)
            for req_id in to_remove_requests:
                self.requests.pop(req_id, None)
                changed = True

            # Workers: clear current_job_id if it no longer exists.
            for worker in self.workers.values():
                cur = worker.get("current_job_id")
                if cur and cur not in self.jobs:
                    worker["current_job_id"] = None
                    if worker.get("status") in ("claimed", "running"):
                        worker["status"] = "idle"
                    changed = True

            if changed and save:
                self.save()
            return changed

    def stats(self):
        with self.lock:
            status_counts = {}
            for job in self.jobs.values():
                s = job.get("status", "unknown")
                status_counts[s] = status_counts.get(s, 0) + 1
            return {
                "jobs_total": len(self.jobs),
                "queue_depth": len(self.queue),
                "workers_total": len(self.workers),
                "queue_paused": self.queue_paused,
                "by_status": status_counts,
            }

    def is_queue_paused(self):
        with self.lock:
            return bool(self.queue_paused)

    def set_queue_paused(self, paused):
        with self.lock:
            self.queue_paused = bool(paused)
            self.save()
            return self.queue_paused

    def is_auto_requeue_failed(self):
        with self.lock:
            return bool(self.auto_requeue_failed)

    def set_auto_requeue_failed(self, enabled):
        with self.lock:
            self.auto_requeue_failed = bool(enabled)
            self.save()
            return self.auto_requeue_failed

    def submit_request(self, raw_request):
        normalized = schema.normalize_job_request(raw_request)
        scene_jobs = schema.build_scene_jobs(normalized, already_normalized=True)
        if not scene_jobs:
            raise ValueError("Request contains no scene jobs (scene_file/max_files missing).")

        request_id = normalized.get("request_id", "").strip() or str(uuid.uuid4())
        now = utc_now()
        created = []

        with self.lock:
            req = self.requests.get(request_id)
            if not req:
                req = {
                    "request_id": request_id,
                    "schema_version": normalized.get("schema_version", schema.JOB_SCHEMA_VERSION),
                    "created_at": now,
                    "updated_at": now,
                    "job_ids": [],
                }
                self.requests[request_id] = req

            for scene_job in scene_jobs:
                job_id = str(uuid.uuid4())
                job = {
                    "job_id": job_id,
                    "request_id": request_id,
                    "schema_version": scene_job.get("schema_version", schema.JOB_SCHEMA_VERSION),
                    "status": "queued",
                    "scene_job": scene_job,
                    "created_at": now,
                    "updated_at": now,
                    "started_at": 0,
                    "finished_at": 0,
                    "claimed_by": None,
                    "attempts": 0,
                    "last_error": "",
                    "result": {},
                }
                self.jobs[job_id] = job
                self.queue.append(job_id)
                req["job_ids"].append(job_id)
                created.append(job)

            req["updated_at"] = now
            self.save()
        return request_id, created

    def register_worker(self, worker_info):
        now = utc_now()
        worker_id = worker_info.get("worker_id", "").strip() or str(uuid.uuid4())
        worker_name = worker_info.get("worker_name", "").strip() or worker_id
        with self.lock:
            self.workers[worker_id] = {
                "worker_id": worker_id,
                "worker_name": worker_name,
                "host": worker_info.get("host", ""),
                "capabilities": worker_info.get("capabilities", {}),
                "status": worker_info.get("status", "idle"),
                "last_seen": now,
                "current_job_id": None,
            }
            self.save()
            return copy.deepcopy(self.workers[worker_id])

    def unregister_worker(self, worker_id, requeue_claimed=True):
        now = utc_now()
        with self.lock:
            worker = self.workers.get(worker_id)
            if not worker:
                return None

            if requeue_claimed:
                in_queue = set(self.queue)
                for job_id, job in self.jobs.items():
                    if job.get("claimed_by") != worker_id:
                        continue
                    if job.get("status") in ("claimed", "running"):
                        job["status"] = "queued"
                        job["claimed_by"] = None
                        job["updated_at"] = now
                        if job_id not in in_queue:
                            self.queue.append(job_id)
                            in_queue.add(job_id)

            out = dict(worker)
            del self.workers[worker_id]
            self.save()
            return out

    def worker_heartbeat(self, worker_id, status_payload):
        now = utc_now()
        with self.lock:
            worker = self.workers.get(worker_id)
            if not worker:
                return None
            if "status" in status_payload:
                worker["status"] = status_payload["status"]
            worker["last_seen"] = now
            if "current_job_id" in status_payload:
                cur_job_id = status_payload["current_job_id"]
                if cur_job_id and cur_job_id in self.jobs:
                    worker["current_job_id"] = cur_job_id
                else:
                    worker["current_job_id"] = None
                    if worker.get("status") in ("claimed", "running"):
                        worker["status"] = "idle"
            self.save()
            return copy.deepcopy(worker)

    def claim_job(self, worker_id):
        now = utc_now()
        with self.lock:
            worker = self.workers.get(worker_id)
            if not worker:
                return None, "unknown_worker"

            if self.queue_paused:
                worker["status"] = "idle"
                worker["current_job_id"] = None
                worker["last_seen"] = now
                self.save()
                return None, None

            while self.queue:
                job_id = self.queue.popleft()
                job = self.jobs.get(job_id)
                if not job:
                    continue
                if job.get("status") != "queued":
                    continue
                job["status"] = "claimed"
                job["claimed_by"] = worker_id
                job["claimed_by_host"] = worker.get("host", "")
                job["updated_at"] = now
                job["attempts"] = int(job.get("attempts", 0)) + 1
                worker["status"] = "claimed"
                worker["current_job_id"] = job_id
                worker["last_seen"] = now
                self.save()
                return job, None

            worker["status"] = "idle"
            worker["current_job_id"] = None
            worker["last_seen"] = now
            self.save()
            return None, None

    def update_job_status(self, worker_id, job_id, status_payload):
        now = utc_now()
        with self.lock:
            worker = self.workers.get(worker_id)
            job = self.jobs.get(job_id)
            if not worker:
                return None, "unknown_worker"
            if not job:
                return None, "unknown_job"

            new_status = status_payload.get("status", "").strip().lower()
            if new_status not in ("running", "done", "failed", "queued", "claimed"):
                return None, "invalid_status"

            detail = status_payload.get("detail", "")
            result = status_payload.get("result", {})

            job["status"] = new_status
            job["updated_at"] = now
            if detail:
                job["last_error"] = str(detail)
            if isinstance(result, dict):
                job["result"] = result

            # Stamp duration milestones. started_at is set on the first
            # running report and never overwritten; finished_at is rewritten
            # on each terminal report (failure followed by retry will reset).
            if new_status == "running":
                if not job.get("started_at"):
                    job["started_at"] = now
            elif new_status in ("done", "failed"):
                if not job.get("started_at"):
                    job["started_at"] = now
                job["finished_at"] = now
            elif new_status == "queued":
                job["started_at"] = 0
                job["finished_at"] = 0

            if new_status == "queued":
                # Requeue explicitly requested retries.
                if job_id not in self.queue:
                    self.queue.append(job_id)
                job["claimed_by"] = None
                worker["current_job_id"] = None
                worker["status"] = "idle"
            elif new_status in ("done", "failed"):
                worker["current_job_id"] = None
                worker["status"] = "idle"
            else:
                worker["status"] = new_status
                worker["current_job_id"] = job_id

            worker["last_seen"] = now
            self.save()
            return copy.deepcopy(job), None

    def get_job(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            return copy.deepcopy(job) if job else None

    def list_jobs(self, status=None):
        with self.lock:
            out = []
            for job in self.jobs.values():
                if status and job.get("status") != status:
                    continue
                out.append(copy.deepcopy(job))
            out.sort(key=lambda x: x.get("created_at", 0))
            return out

    def list_workers(self):
        with self.lock:
            out = [copy.deepcopy(worker) for worker in self.workers.values()]
            out.sort(key=lambda x: (x.get("worker_name", ""), x.get("worker_id", "")))
            return out

    def requeue_stale_claims(self, stale_seconds):
        now = utc_now()
        requeued = []
        with self.lock:
            in_queue = set(self.queue)
            for job_id, job in self.jobs.items():
                if job.get("status") not in ("claimed", "running"):
                    continue
                last = job.get("updated_at", 0)
                if (now - last) < stale_seconds:
                    continue
                job["status"] = "queued"
                job["claimed_by"] = None
                job["updated_at"] = now
                job["started_at"] = 0
                job["finished_at"] = 0
                if job_id not in in_queue:
                    self.queue.append(job_id)
                    in_queue.add(job_id)
                requeued.append(job_id)
            if requeued:
                self.save()
        return requeued

    def requeue_failed_jobs(self, max_attempts=2):
        """Requeue failed jobs that have been attempted fewer than max_attempts times."""
        now = utc_now()
        requeued = []
        with self.lock:
            in_queue = set(self.queue)
            for job_id, job in self.jobs.items():
                if job.get("status") != "failed":
                    continue
                if job.get("attempts", 0) >= max_attempts:
                    continue
                job["status"] = "queued"
                job["claimed_by"] = None
                job["updated_at"] = now
                job["started_at"] = 0
                job["finished_at"] = 0
                if job_id not in in_queue:
                    self.queue.append(job_id)
                    in_queue.add(job_id)
                requeued.append(job_id)
            if requeued:
                self.save()
        return requeued

    def requeue_jobs(self, job_ids):
        """Force-requeue any jobs regardless of current status.

        Resets each job back to 'queued', clears claim metadata and last error,
        and appends it to the queue if not already present. Returns the list
        of job ids that were actually requeued.
        """
        now = utc_now()
        requeued = []
        with self.lock:
            in_queue = set(self.queue)
            for job_id in job_ids:
                job = self.jobs.get(job_id)
                if not job:
                    continue
                claimed_by = job.get("claimed_by")
                if claimed_by:
                    worker = self.workers.get(claimed_by)
                    if worker and worker.get("current_job_id") == job_id:
                        worker["current_job_id"] = None
                        if worker.get("status") in ("claimed", "running"):
                            worker["status"] = "idle"
                        worker["last_seen"] = now
                job["status"] = "queued"
                job["claimed_by"] = None
                job["last_error"] = ""
                job["updated_at"] = now
                job["started_at"] = 0
                job["finished_at"] = 0
                if job_id not in in_queue:
                    self.queue.append(job_id)
                    in_queue.add(job_id)
                requeued.append(job_id)
            if requeued:
                self.save()
        return requeued

    def remove_jobs(self, job_ids):
        with self.lock:
            existing = [jid for jid in job_ids if jid in self.jobs]
            if not existing:
                return 0
            return self._remove_jobs_locked(existing)

    def remove_job(self, job_id):
        with self.lock:
            job = self.jobs.pop(job_id, None)
            if not job:
                return False

            self.queue = deque(qid for qid in self.queue if qid != job_id)

            req_id = job.get("request_id")
            if req_id and req_id in self.requests:
                req = self.requests[req_id]
                req["job_ids"] = [jid for jid in req.get("job_ids", []) if jid != job_id]
                req["updated_at"] = utc_now()
                if not req["job_ids"]:
                    del self.requests[req_id]

            self.save()
            return True

    def clear_queue(self):
        with self.lock:
            queued_ids = list(self.queue)
            if not queued_ids:
                return 0
            for job_id in queued_ids:
                self.jobs.pop(job_id, None)
            self.queue.clear()

            live_job_ids = set(self.jobs.keys())
            empty_requests = []
            for req_id, req in self.requests.items():
                req["job_ids"] = [jid for jid in req.get("job_ids", []) if jid in live_job_ids]
                req["updated_at"] = utc_now()
                if not req["job_ids"]:
                    empty_requests.append(req_id)
            for req_id in empty_requests:
                self.requests.pop(req_id, None)

            self.save()
            return len(queued_ids)

    def remove_jobs_by_status(self, statuses):
        with self.lock:
            statuses = {str(s).strip().lower() for s in (statuses or []) if str(s).strip()}
            if not statuses:
                return 0

            remove_ids = [
                job_id
                for job_id, job in self.jobs.items()
                if str(job.get("status", "")).strip().lower() in statuses
            ]
            if not remove_ids:
                return 0

            return self._remove_jobs_locked(remove_ids)

    def clear_all_jobs(self):
        with self.lock:
            if not self.jobs:
                return 0
            return self._remove_jobs_locked(list(self.jobs.keys()))

    def _remove_jobs_locked(self, remove_ids):
        remove_set = set(remove_ids)
        if not remove_set:
            return 0

        for job_id in remove_set:
            self.jobs.pop(job_id, None)

        self.queue = deque(qid for qid in self.queue if qid not in remove_set)

        now = utc_now()
        empty_requests = []
        for req_id, req in self.requests.items():
            req["job_ids"] = [jid for jid in req.get("job_ids", []) if jid not in remove_set]
            req["updated_at"] = now
            if not req["job_ids"]:
                empty_requests.append(req_id)
        for req_id in empty_requests:
            self.requests.pop(req_id, None)

        # Clear worker references to removed jobs.
        for worker in self.workers.values():
            cur = worker.get("current_job_id")
            if cur and cur in remove_set:
                worker["current_job_id"] = None
                if worker.get("status") in ("claimed", "running"):
                    worker["status"] = "idle"
                worker["last_seen"] = now

        self.save()
        return len(remove_set)


class DiscoveryResponder(threading.Thread):
    def __init__(self, host, port, announce_host=None, stop_event=None):
        super().__init__(daemon=True)
        self.host = host
        self.port = port
        self.announce_host = announce_host or host
        self.stop_event = stop_event or threading.Event()

    def run(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("0.0.0.0", self.port + 1))
            sock.settimeout(0.5)
            while not self.stop_event.is_set():
                try:
                    data, addr = sock.recvfrom(4096)
                except socket.timeout:
                    continue
                except Exception:
                    continue

                if not _is_local_network_ip(addr[0]):
                    continue
                if data.decode("utf-8", errors="ignore").strip() != DISCOVERY_MAGIC:
                    continue

                response = {
                    "magic": DISCOVERY_MAGIC,
                    "http_host": self.announce_host,
                    "http_port": self.port,
                }
                try:
                    sock.sendto(json.dumps(response).encode("utf-8"), addr)
                except Exception:
                    pass
        finally:
            sock.close()


class JobServerHTTP(ThreadingHTTPServer):
    def __init__(self, server_address, handler_cls, state, local_only):
        super().__init__(server_address, handler_cls)
        self.state = state
        self.local_only = local_only


def build_dashboard_payload(server):
    """Pre-resolved snapshot used by the web dashboard JS poller.

    Resolves worker/job names so the browser never has to know about
    worker_ids or job UUIDs. Strips internal-only fields.
    """
    state = server.state
    stats = state.stats()
    workers = state.list_workers()
    jobs = state.list_jobs()

    workers_by_id = {str(w.get("worker_id", "")): w for w in workers}
    jobs_by_id = {str(j.get("job_id", "")): j for j in jobs}

    # We display the worker's hostname everywhere on the dashboard. The
    # internal worker_name carries an id suffix (for log disambiguation) that
    # we deliberately keep out of the UI. For jobs claimed by a worker that
    # has since disconnected, fall back to claimed_by_host stored on the job
    # at claim time so the row keeps showing who did the work.
    worker_rows = []
    for w in workers:
        cur_id = str(w.get("current_job_id") or "")
        cur_scene = ""
        if cur_id:
            cur_job = jobs_by_id.get(cur_id)
            if cur_job:
                scene_path = str((cur_job.get("scene_job", {}) or {}).get("scene_file", "") or "")
                if scene_path:
                    cur_scene = os.path.basename(scene_path) or scene_path
        worker_rows.append({
            "name": w.get("host") or w.get("worker_name") or "",
            "status": w.get("status", ""),
            "current_scene": cur_scene,
            "last_seen_ts": w.get("last_seen") or 0,
        })

    now_ts = time.time()
    # Collected (finished_at, duration) tuples for the rolling average below.
    done_pairs = []

    job_rows = []
    for j in jobs:
        scene_job = j.get("scene_job", {}) or {}
        scene_path = str(scene_job.get("scene_file", "") or "")
        output_folder = str((scene_job.get("output", {}) or {}).get("folder", "") or "")
        claimed_by = str(j.get("claimed_by") or "")
        worker_label = ""
        if claimed_by:
            worker_label = workers_by_id.get(claimed_by, {}).get("host", "") or ""
        if not worker_label:
            worker_label = j.get("claimed_by_host", "") or ""

        started_ts = float(j.get("started_at") or 0)
        finished_ts = float(j.get("finished_at") or 0)
        status_norm = str(j.get("status", "") or "").lower()
        duration = 0.0
        if finished_ts and started_ts and finished_ts >= started_ts:
            duration = finished_ts - started_ts
            if status_norm == "done":
                done_pairs.append((finished_ts, duration))
        elif started_ts and status_norm in ("running", "claimed"):
            duration = max(0.0, now_ts - started_ts)

        job_rows.append({
            "job_id": j.get("job_id", ""),
            "scene_name": os.path.basename(scene_path) if scene_path else "",
            "scene_path": scene_path,
            "output_folder": output_folder,
            "status": j.get("status", ""),
            "worker_name": worker_label,
            "attempts": int(j.get("attempts", 0)),
            "started_at_ts": started_ts,
            "finished_at_ts": finished_ts,
            "duration_seconds": duration,
            "updated_at_ts": j.get("updated_at") or 0,
            "last_error": j.get("last_error", "") or "",
        })

    # Rolling average over the most recent N completed jobs. Using the most
    # recent ones (by finished_at) keeps the average tracking the current
    # scene mix instead of ancient outliers.
    avg_duration = 0.0
    if done_pairs:
        done_pairs.sort(reverse=True)
        recent = done_pairs[:20]
        avg_duration = sum(d for _, d in recent) / len(recent)

    queued_count = stats.get("by_status", {}).get("queued", 0)
    running_count = (
        stats.get("by_status", {}).get("running", 0)
        + stats.get("by_status", {}).get("claimed", 0)
    )
    active_worker_count = len(workers)
    eta_seconds = 0.0
    if avg_duration > 0 and active_worker_count > 0 and not state.is_queue_paused():
        # Running jobs count as one full average each (we don't know their
        # remaining time). Conservative; gets better as more jobs finish.
        eta_seconds = ((queued_count + running_count) * avg_duration) / active_worker_count

    host, port = server.server_address[0], server.server_address[1]
    return {
        "now_ts": now_ts,
        "server": {
            "host": host,
            "port": port,
            "local_only": bool(server.local_only),
        },
        "stats": stats,
        "queue_paused": state.is_queue_paused(),
        "auto_requeue_failed": state.is_auto_requeue_failed(),
        "avg_duration_seconds": avg_duration,
        "eta_seconds": eta_seconds,
        "workers": worker_rows,
        "jobs": job_rows,
    }


class RequestHandler(BaseHTTPRequestHandler):
    # Intentionally no auth layer: this server is designed for trusted LAN use.
    # Enforce local-only mode unless --allow-non-local is explicitly enabled.
    server_version = "VBBatchServer/1.0"

    def log_message(self, fmt, *args):
        print(f"[{self.log_date_time_string()}] {self.client_address[0]} - {fmt % args}")

    def _json(self, code, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, code, body_text):
        body = body_text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _css(self, code, body_text):
        body = body_text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/css; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _deny_if_not_local(self):
        if not self.server.local_only:
            return False
        ip = self.client_address[0]
        if _is_local_network_ip(ip):
            return False
        self._json(HTTPStatus.FORBIDDEN, {"error": "local_network_only"})
        return True

    def _deny_if_missing_csrf(self):
        """Reject mutating /admin/* requests that don't carry the CSRF header.

        Browsers can't send custom headers cross-origin without a CORS
        preflight that we never grant, so any request reaching this point
        with the header set originates from our own dashboard JS (or a
        deliberate same-origin client).
        """
        got = (self.headers.get(CSRF_HEADER) or "").strip()
        if got == CSRF_HEADER_EXPECTED:
            return False
        self._json(HTTPStatus.FORBIDDEN, {"error": "csrf_header_required"})
        return True

    def _parse_json_body(self):
        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
        except Exception:
            raise ValueError("Invalid Content-Length header")
        if length > MAX_REQUEST_BODY_BYTES:
            raise ValueError(f"Request body too large (max {MAX_REQUEST_BODY_BYTES} bytes)")
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            raise ValueError("Invalid JSON body")

    def do_GET(self):
        if self._deny_if_not_local():
            return
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if path in ("", "/"):
            self._html(HTTPStatus.OK, render_dashboard(self.server.state, self.server.server_address))
            return

        if path == "/static/server_dashboard.css":
            self._css(HTTPStatus.OK, read_stylesheet())
            return

        if path == "/health":
            self._json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "schema_version": schema.JOB_SCHEMA_VERSION,
                    "stats": self.server.state.stats(),
                },
            )
            return

        if path == "/dashboard_data":
            self._json(HTTPStatus.OK, build_dashboard_payload(self.server))
            return

        if path == "/jobs":
            status = (qs.get("status", [""])[0] or "").strip()
            jobs = self.server.state.list_jobs(status=status or None)
            self._json(
                HTTPStatus.OK,
                {"jobs": jobs, "count": len(jobs)},
            )
            return

        if path == "/workers":
            workers = self.server.state.list_workers()
            self._json(
                HTTPStatus.OK,
                {"workers": workers, "count": len(workers)},
            )
            return

        if path.startswith("/jobs/"):
            job_id = path.split("/", 2)[2]
            job = self.server.state.get_job(job_id)
            if not job:
                self._json(HTTPStatus.NOT_FOUND, {"error": "job_not_found"})
                return
            self._json(HTTPStatus.OK, job)
            return

        self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_POST(self):
        if self._deny_if_not_local():
            return

        parsed = urlparse(self.path)
        path = parsed.path

        try:
            payload = self._parse_json_body()
        except ValueError as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return

        if path == "/submit":
            try:
                request_id, jobs = self.server.state.submit_request(payload)
            except Exception as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            self._json(
                HTTPStatus.OK,
                {
                    "request_id": request_id,
                    "job_ids": [j["job_id"] for j in jobs],
                    "count": len(jobs),
                },
            )
            return

        if path == "/workers/register":
            worker = self.server.state.register_worker(payload if isinstance(payload, dict) else {})
            self._json(HTTPStatus.OK, worker)
            return

        if path.startswith("/workers/") and path.endswith("/heartbeat"):
            parts = path.strip("/").split("/")
            if len(parts) != 3:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                return
            worker_id = parts[1]
            worker = self.server.state.worker_heartbeat(
                worker_id,
                payload if isinstance(payload, dict) else {},
            )
            if not worker:
                self._json(HTTPStatus.NOT_FOUND, {"error": "worker_not_found"})
                return
            self._json(HTTPStatus.OK, worker)
            return

        if path.startswith("/workers/") and path.endswith("/unregister"):
            parts = path.strip("/").split("/")
            if len(parts) != 3:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                return
            worker_id = parts[1]
            worker = self.server.state.unregister_worker(worker_id, requeue_claimed=True)
            if not worker:
                self._json(HTTPStatus.NOT_FOUND, {"error": "worker_not_found"})
                return
            self._json(HTTPStatus.OK, {"ok": True, "worker_id": worker_id})
            return

        if path.startswith("/workers/") and path.endswith("/claim"):
            parts = path.strip("/").split("/")
            if len(parts) != 3:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                return
            worker_id = parts[1]
            job, err = self.server.state.claim_job(worker_id)
            if err == "unknown_worker":
                self._json(HTTPStatus.NOT_FOUND, {"error": "worker_not_found"})
                return
            if not job:
                self._json(HTTPStatus.OK, {"job": None})
                return
            self._json(HTTPStatus.OK, job)
            return

        if path.startswith("/workers/") and "/job/" in path and path.endswith("/status"):
            parts = path.strip("/").split("/")
            # workers/{worker_id}/job/{job_id}/status
            if len(parts) != 5 or parts[0] != "workers" or parts[2] != "job" or parts[4] != "status":
                self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                return
            worker_id = parts[1]
            job_id = parts[3]
            job, err = self.server.state.update_job_status(
                worker_id,
                job_id,
                payload if isinstance(payload, dict) else {},
            )
            if err == "unknown_worker":
                self._json(HTTPStatus.NOT_FOUND, {"error": "worker_not_found"})
                return
            if err == "unknown_job":
                self._json(HTTPStatus.NOT_FOUND, {"error": "job_not_found"})
                return
            if err == "invalid_status":
                self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid_status"})
                return
            self._json(HTTPStatus.OK, job)
            return

        if path.startswith("/admin/"):
            if self._deny_if_missing_csrf():
                return
            payload_dict = payload if isinstance(payload, dict) else {}

            if path == "/admin/requeue_stale":
                stale_seconds = int(payload_dict.get("stale_seconds", DEFAULT_STALE_REQUEUE_SECONDS))
                requeued = self.server.state.requeue_stale_claims(stale_seconds)
                self._json(HTTPStatus.OK, {"requeued": requeued, "count": len(requeued)})
                return

            if path == "/admin/queue/pause":
                paused = bool(payload_dict.get("paused", False))
                self.server.state.set_queue_paused(paused)
                self._json(HTTPStatus.OK, {"queue_paused": paused})
                return

            if path == "/admin/auto_requeue":
                enabled = bool(payload_dict.get("enabled", False))
                self.server.state.set_auto_requeue_failed(enabled)
                self._json(HTTPStatus.OK, {"auto_requeue_failed": enabled})
                return

            if path == "/admin/jobs/requeue":
                job_ids = payload_dict.get("job_ids") or []
                if not isinstance(job_ids, list):
                    self._json(HTTPStatus.BAD_REQUEST, {"error": "job_ids must be a list"})
                    return
                requeued = self.server.state.requeue_jobs([str(j) for j in job_ids])
                self._json(HTTPStatus.OK, {"requeued": requeued, "count": len(requeued)})
                return

            if path == "/admin/jobs/remove":
                job_ids = payload_dict.get("job_ids") or []
                if not isinstance(job_ids, list):
                    self._json(HTTPStatus.BAD_REQUEST, {"error": "job_ids must be a list"})
                    return
                removed = self.server.state.remove_jobs([str(j) for j in job_ids])
                self._json(HTTPStatus.OK, {"removed": removed})
                return

            if path == "/admin/jobs/clear_queue":
                removed = self.server.state.clear_queue()
                self._json(HTTPStatus.OK, {"removed": removed})
                return

            if path == "/admin/jobs/remove_by_status":
                statuses = payload_dict.get("statuses") or []
                if not isinstance(statuses, list):
                    self._json(HTTPStatus.BAD_REQUEST, {"error": "statuses must be a list"})
                    return
                removed = self.server.state.remove_jobs_by_status(statuses)
                self._json(HTTPStatus.OK, {"removed": removed})
                return

            if path == "/admin/jobs/clear_all":
                removed = self.server.state.clear_all_jobs()
                self._json(HTTPStatus.OK, {"removed": removed})
                return

            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return

        self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})


class ServerRuntime:
    def __init__(self, host, port, state_file, local_only=True, enable_discovery=True):
        self.host = host
        self.port = port
        self.state_file = state_file
        self.local_only = local_only
        self.enable_discovery = enable_discovery

        self.state = JobServerState(state_file=state_file)
        self.httpd = JobServerHTTP((host, port), RequestHandler, state=self.state, local_only=local_only)
        self.stop_event = threading.Event()
        self.discovery = None
        self._thread = None
        self._auto_requeue_thread = None
        self._started = False

    def _auto_requeue_loop(self):
        while not self.stop_event.is_set():
            try:
                if self.state.is_auto_requeue_failed():
                    self.state.requeue_failed_jobs(max_attempts=AUTO_REQUEUE_MAX_ATTEMPTS)
            except Exception:
                pass
            self.stop_event.wait(AUTO_REQUEUE_TICK_SECONDS)

    def start(self):
        if self._started:
            return

        if self.enable_discovery:
            announce_host = self.host
            if announce_host in ("0.0.0.0", "::"):
                try:
                    announce_host = socket.gethostbyname(socket.gethostname())
                except Exception:
                    announce_host = "127.0.0.1"
            self.discovery = DiscoveryResponder(
                host=self.host,
                port=self.port,
                announce_host=announce_host,
                stop_event=self.stop_event,
            )
            self.discovery.start()

        self._thread = threading.Thread(
            target=self.httpd.serve_forever,
            kwargs={"poll_interval": 0.5},
            daemon=True,
        )
        self._thread.start()

        self._auto_requeue_thread = threading.Thread(
            target=self._auto_requeue_loop,
            daemon=True,
            name="auto-requeue",
        )
        self._auto_requeue_thread.start()

        self._started = True

    def stop(self):
        if not self._started:
            return
        self.stop_event.set()
        try:
            self.httpd.shutdown()
        except Exception:
            pass
        try:
            self.httpd.server_close()
        except Exception:
            pass
        self.state.save()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        if self._auto_requeue_thread is not None:
            self._auto_requeue_thread.join(timeout=2.0)
        self._started = False

    def wait_forever(self):
        try:
            while True:
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()


def run_server(host, port, state_file, local_only=True, enable_discovery=True):
    runtime = ServerRuntime(
        host=host,
        port=port,
        state_file=state_file,
        local_only=local_only,
        enable_discovery=enable_discovery,
    )
    runtime.start()
    print(f"VB Batch Server listening on http://{host}:{port}")
    print(f"Local network only: {local_only}")
    print(f"State file: {os.path.abspath(state_file)}")
    if enable_discovery:
        print(f"Discovery UDP port: {port + 1}")
    runtime.wait_forever()
    print("Server stopped.")


def parse_args():
    parser = argparse.ArgumentParser(description="VirtualBuilders Batch Render Server")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8765, help="Bind port (default: 8765)")
    parser.add_argument(
        "--state-file",
        default=DEFAULT_STATE_FILE,
        help=f"State JSON path (default: {DEFAULT_STATE_FILE})",
    )
    parser.add_argument(
        "--allow-non-local",
        action="store_true",
        help="Allow requests from non-local IPs (disabled by default).",
    )
    parser.add_argument(
        "--no-discovery",
        action="store_true",
        help="Disable UDP discovery responder.",
    )
    parser.add_argument(
        "--ui",
        action="store_true",
        help="Launch server with desktop UI dashboard.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    if args.ui:
        from NetworkRender.server import server_ui

        server_ui.run_server_ui(
            host=args.host,
            port=args.port,
            state_file=args.state_file,
            local_only=(not args.allow_non_local),
            enable_discovery=(not args.no_discovery),
        )
        return

    run_server(
        host=args.host,
        port=args.port,
        state_file=args.state_file,
        local_only=(not args.allow_non_local),
        enable_discovery=(not args.no_discovery),
    )


if __name__ == "__main__":
    main()

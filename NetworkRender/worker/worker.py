import argparse
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

if __package__ is None or __package__ == "":
    # Allow direct execution: python NetworkRender/worker/worker.py
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

from NetworkRender.shared import job_schema as schema
from NetworkRender.shared import server_client


DEFAULT_DISCOVERY_PORT = 8766
STOP_JOIN_TIMEOUT_SEC = 10.0


def _now():
    return time.time()


def _hostname():
    try:
        return socket.gethostname()
    except Exception:
        return "worker"


def _decode_proc_text(data):
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    if not isinstance(data, (bytes, bytearray)):
        return str(data)
    raw = bytes(data)
    for enc in ("utf-16-le", "utf-16", "utf-8", "cp1252"):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode("utf-8", errors="replace")


def _default_worker_id_path():
    candidates = []

    local_appdata = os.environ.get("LOCALAPPDATA", "").strip()
    if local_appdata:
        candidates.append(Path(local_appdata))

    # Fallback for environments where LOCALAPPDATA isn't exposed.
    try:
        candidates.append(Path.home() / "AppData" / "Local")
    except Exception:
        pass

    for root in candidates:
        try:
            base = root / "VirtualBuilders" / "VariationMGR"
            base.mkdir(parents=True, exist_ok=True)
            return str(base / "worker_identity.json")
        except Exception:
            continue

    # Last resort: temp dir stays machine-local and avoids shared NAS identity files.
    base = Path(tempfile.gettempdir()) / "VirtualBuilders" / "VariationMGR"
    try:
        base.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return str(base / "worker_identity.json")


def _load_or_create_worker_id(path, machine_key=""):
    key = (machine_key or _hostname() or "worker").strip().lower()

    payload = {}
    try:
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            if isinstance(payload, dict):
                worker_ids = payload.get("worker_ids", {})
                if isinstance(worker_ids, dict):
                    wid = str(worker_ids.get(key, "")).strip()
                    if wid:
                        return wid

                # Legacy format migration: single worker_id value.
                legacy = str(payload.get("worker_id", "")).strip()
                legacy_key = str(payload.get("host_key", "")).strip().lower()
                if legacy and (not legacy_key or legacy_key == key):
                    worker_ids = dict(worker_ids) if isinstance(worker_ids, dict) else {}
                    worker_ids[key] = legacy
                    payload["worker_ids"] = worker_ids
                    payload["host_key"] = key
                    try:
                        with open(path, "w", encoding="utf-8") as wf:
                            json.dump(payload, wf, indent=2)
                    except Exception:
                        pass
                    return legacy
    except Exception:
        pass

    wid = str(uuid.uuid4())
    try:
        worker_ids = {}
        if isinstance(payload, dict):
            prev = payload.get("worker_ids", {})
            if isinstance(prev, dict):
                worker_ids.update(prev)
        worker_ids[key] = wid
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "worker_id": wid,  # backward-compat convenience
                    "host_key": key,
                    "worker_ids": worker_ids,
                },
                f,
                indent=2,
            )
    except Exception:
        pass
    return wid


_HEX_COLOR_RE = re.compile(r"^#?([0-9a-fA-F]{6})$")


def _normalize_hex_color(value):
    """Return '#rrggbb' (lowercase) for a valid 6-digit hex, else '' (auto color)."""
    m = _HEX_COLOR_RE.match(str(value or "").strip())
    return "#" + m.group(1).lower() if m else ""


def _load_worker_color(path, machine_key=""):
    """Read this machine's saved worker color from the identity file ('' if none)."""
    key = (machine_key or _hostname() or "worker").strip().lower()
    try:
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            if isinstance(payload, dict):
                colors = payload.get("worker_colors", {})
                if isinstance(colors, dict):
                    return _normalize_hex_color(colors.get(key, ""))
    except Exception:
        pass
    return ""


def _save_worker_color(path, machine_key, color):
    """Persist (or clear, if color is '') this machine's worker color."""
    key = (machine_key or _hostname() or "worker").strip().lower()
    color = _normalize_hex_color(color)
    payload = {}
    try:
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                payload = loaded
    except Exception:
        payload = {}
    colors = payload.get("worker_colors", {})
    if not isinstance(colors, dict):
        colors = {}
    if color:
        colors[key] = color
    else:
        colors.pop(key, None)
    payload["worker_colors"] = colors
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
    except Exception:
        pass


def _find_3dsmaxbatch():
    env_val = os.environ.get("VB_MAX_BATCH_EXE", "").strip()
    if env_val and os.path.isfile(env_val):
        return env_val

    # Try PATH lookup first.
    try:
        probe = subprocess.run(
            ["where", "3dsmaxbatch.exe"],
            capture_output=True,
            text=True,
            timeout=2.0,
        )
        if probe.returncode == 0:
            for line in (probe.stdout or "").splitlines():
                cand = line.strip().strip('"')
                if cand and os.path.isfile(cand):
                    return cand
    except Exception:
        pass

    # Fall back to common Autodesk install roots.
    roots = [
        os.path.join(os.environ.get("ProgramW6432", r"C:\Program Files"), "Autodesk"),
        os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Autodesk"),
    ]
    found = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        try:
            for name in os.listdir(root):
                low = name.lower()
                if not low.startswith("3ds max"):
                    continue
                exe = os.path.join(root, name, "3dsmaxbatch.exe")
                if os.path.isfile(exe):
                    found.append(exe)
        except Exception:
            pass
    if not found:
        return ""
    found.sort(reverse=True)
    return found[0]


@dataclass(frozen=True)
class WorkerConfig:
    server_url: str = ""
    worker_id: str = ""
    worker_name: str = ""
    host: str = ""
    poll_interval: float = 2.0
    heartbeat_interval: float = 5.0
    mock_mode: bool = True
    mock_render_seconds: float = 2.0
    executor_cmd: str = ""
    max_batch_exe: str = ""
    networkrender_script: str = ""
    job_timeout_sec: int = 0
    discovery_port: int = DEFAULT_DISCOVERY_PORT
    color: str = ""

    @classmethod
    def from_args(cls, args):
        return cls(
            server_url=args.server_url,
            worker_id=args.worker_id,
            worker_name=args.worker_name,
            host=args.host,
            poll_interval=args.poll_interval,
            heartbeat_interval=args.heartbeat_interval,
            mock_mode=bool(args.mock),
            mock_render_seconds=args.mock_seconds,
            executor_cmd=args.executor_cmd,
            max_batch_exe=args.max_batch_exe,
            networkrender_script=args.networkrender_script,
            job_timeout_sec=args.job_timeout_sec,
            discovery_port=args.discovery_port,
            color=getattr(args, "color", ""),
        )


class WorkerRuntime:
    def __init__(self, config, log_cb=None):
        if not isinstance(config, WorkerConfig):
            raise TypeError("config must be a WorkerConfig instance")

        resolved_host = config.host.strip() or _hostname()
        default_networkrender = str(Path(__file__).resolve().with_name("networkrender.py"))

        self._config = config
        self.server_url = server_client.normalize_server_url(config.server_url)
        self._identity_path = _default_worker_id_path()
        self._color_key = resolved_host
        self.worker_id = config.worker_id.strip() or _load_or_create_worker_id(
            self._identity_path,
            machine_key=resolved_host,
        )
        self.worker_name = config.worker_name.strip() or f"{_hostname()}-{self.worker_id[:8]}"
        self.host = resolved_host
        # Optional worker-chosen dashboard color: CLI flag wins, else the saved
        # per-machine value. Empty means the dashboard auto-assigns a hue.
        self.worker_color = _normalize_hex_color(config.color) or _load_worker_color(
            self._identity_path, resolved_host
        )
        self.poll_interval = float(config.poll_interval)
        self.heartbeat_interval = float(config.heartbeat_interval)
        self.mock_mode = bool(config.mock_mode)
        self.mock_render_seconds = float(config.mock_render_seconds)
        self.executor_cmd = config.executor_cmd.strip()
        self.max_batch_exe = config.max_batch_exe.strip() or _find_3dsmaxbatch()
        self.networkrender_script = config.networkrender_script.strip() or os.environ.get(
            "VB_NETWORKRENDER_SCRIPT",
            default_networkrender,
        )
        self.job_timeout_sec = int(config.job_timeout_sec) if int(config.job_timeout_sec) > 0 else 0
        self.discovery_port = int(config.discovery_port)
        self.log_cb = log_cb

        self.stop_event = threading.Event()
        self._thread = None
        self._lock = threading.RLock()
        self._is_registered = False

        self.current_status = "starting"
        self.current_job_id = None
        self.last_error = ""
        self.last_seen_server = 0.0
        self.jobs_done = 0
        self.jobs_failed = 0
        self.jobs_claimed = 0
        self.recent_events = []

    def log(self, msg):
        ts = time.strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        if callable(self.log_cb):
            self.log_cb(line)
        else:
            print(line)
        with self._lock:
            self.recent_events.append(line)
            if len(self.recent_events) > 300:
                self.recent_events = self.recent_events[-300:]

    def snapshot(self):
        with self._lock:
            return {
                "server_url": self.server_url,
                "worker_id": self.worker_id,
                "worker_name": self.worker_name,
                "host": self.host,
                "status": self.current_status,
                "current_job_id": self.current_job_id,
                "last_error": self.last_error,
                "last_seen_server": self.last_seen_server,
                "jobs_done": self.jobs_done,
                "jobs_failed": self.jobs_failed,
                "jobs_claimed": self.jobs_claimed,
                "mock_mode": self.mock_mode,
                "max_batch_exe": self.max_batch_exe,
                "networkrender_script": self.networkrender_script,
                "job_timeout_sec": self.job_timeout_sec,
                "worker_color": self.worker_color,
                "recent_events": list(self.recent_events),
            }

    def _set_state(self, **kwargs):
        with self._lock:
            for key, value in kwargs.items():
                setattr(self, key, value)

    def _bump_counter(self, counter_name, delta=1):
        with self._lock:
            setattr(self, counter_name, int(getattr(self, counter_name, 0)) + int(delta))

    def _get_server_url(self):
        with self._lock:
            return self.server_url

    def _set_server_url(self, server_url):
        normalized = server_client.normalize_server_url(server_url)
        with self._lock:
            self.server_url = normalized
            return self.server_url

    def _get_worker_identity(self):
        with self._lock:
            return self.worker_id, self.worker_name

    def _get_current_status(self):
        with self._lock:
            return self.current_status

    def _heartbeat_payload(self):
        with self._lock:
            return {
                "status": self.current_status,
                "current_job_id": self.current_job_id,
                "color": self.worker_color,
            }

    def get_color(self):
        with self._lock:
            return self.worker_color

    def set_color(self, color):
        """Set this worker's dashboard color (''=auto), persist it, and let the
        next heartbeat propagate it to the server. Returns the normalized value."""
        normalized = _normalize_hex_color(color)
        with self._lock:
            self.worker_color = normalized
        _save_worker_color(self._identity_path, self._color_key, normalized)
        self.log(f"Worker color set to {normalized or '(auto)'}")
        return normalized

    def _api_request(self, method, path, payload=None, timeout=10):
        base = self._get_server_url()
        if not base:
            raise RuntimeError("server_url is not set")
        return server_client.request_json(
            method=method,
            url=f"{base}{path}",
            payload=payload,
            timeout=timeout,
        )

    def _api_post(self, path, payload, timeout=10):
        return self._api_request("POST", path, payload=payload, timeout=timeout)

    def _api_get(self, path, timeout=10):
        return self._api_request("GET", path, payload=None, timeout=timeout)

    @staticmethod
    def _is_worker_not_found_error(exc):
        return "worker_not_found" in str(exc)

    def discover_server(self, timeout_sec=2.0):
        found = server_client.discover_server(
            discovery_port=self.discovery_port,
            timeout=timeout_sec,
        )
        if found:
            discovered = self._set_server_url(found)
            self.log(f"Discovered server: {discovered}")
            return discovered
        return ""

    def register(self):
        worker_id, worker_name = self._get_worker_identity()
        payload = {
            "worker_id": worker_id,
            "worker_name": worker_name,
            "host": self.host,
            "status": "idle",
            "capabilities": {"mock_mode": self.mock_mode},
            "color": self.worker_color,
        }
        out = self._api_post("/workers/register", payload)
        with self._lock:
            self.worker_id = out.get("worker_id", self.worker_id)
            self.worker_name = out.get("worker_name", self.worker_name)
            self.current_status = "idle"
            self.last_seen_server = _now()
            self._is_registered = True
        self.log(f"Registered worker: {self.worker_name} ({self.worker_id})")

    def heartbeat(self):
        worker_id, _ = self._get_worker_identity()
        payload = self._heartbeat_payload()
        out = self._api_post(f"/workers/{worker_id}/heartbeat", payload)
        with self._lock:
            self.current_status = out.get("status", self.current_status)
            self.last_seen_server = _now()

    def claim_job(self):
        worker_id, _ = self._get_worker_identity()
        out = self._api_post(f"/workers/{worker_id}/claim", {})
        job = out.get("job")
        if isinstance(job, dict):
            return job
        if "job_id" in out:
            return out
        return None

    def list_workers(self):
        out = self._api_get("/workers")
        workers = out.get("workers", [])
        if isinstance(workers, list):
            return workers
        return []

    def find_duplicate_workers(self):
        """
        Find likely stale workers on this same machine.
        Criteria:
        - same host label
        - different worker_id
        """
        out = []
        try:
            workers = self.list_workers()
        except Exception:
            return out

        with self._lock:
            my_worker_id = self.worker_id
            my_host = self.host

        for worker in workers:
            wid = str(worker.get("worker_id", "")).strip()
            if not wid or wid == my_worker_id:
                continue
            host = str(worker.get("host", "")).strip()
            if host and host == my_host:
                out.append(worker)
        return out

    def update_job_status(self, job_id, status, detail="", result=None):
        worker_id, _ = self._get_worker_identity()
        payload = {
            "status": status,
            "detail": detail or "",
            "result": result or {},
        }
        self._api_post(f"/workers/{worker_id}/job/{job_id}/status", payload)
        self._set_state(last_seen_server=_now())

    def unregister(self):
        if not self._get_server_url():
            return
        with self._lock:
            if not self._is_registered:
                return
            worker_id = self.worker_id
        try:
            self._api_post(f"/workers/{worker_id}/unregister", {})
            self.log(f"Unregistered worker: {worker_id}")
        except Exception as exc:
            self.log(f"Unregister failed: {exc}")
        finally:
            with self._lock:
                self._is_registered = False

    def unregister_worker_by_id(self, worker_id):
        if not self._get_server_url():
            return False
        try:
            self._api_post(f"/workers/{worker_id}/unregister", {})
            self.log(f"Unregistered stale worker: {worker_id}")
            return True
        except Exception as exc:
            self.log(f"Failed to unregister stale worker {worker_id}: {exc}")
            return False

    def _execute_job(self, scene_job, job_id=""):
        if self.mock_mode:
            time.sleep(max(0.0, self.mock_render_seconds))
            return {"status": "success", "mock": True}

        normalized = schema.normalize_job_request(scene_job)
        # Carry the worker's job id into the core so its progress log is named
        # <output_folder>/<job_id>.log -- the file becomes the channel the
        # worker (and colleagues) tail for live progress.
        if job_id:
            normalized["job_id"] = job_id
        fd, job_path = tempfile.mkstemp(prefix="vb_job_", suffix=".json")
        os.close(fd)
        result_path = os.path.join(
            tempfile.gettempdir(),
            f"vb_job_result_{uuid.uuid4().hex}.json",
        )
        try:
            with open(job_path, "w", encoding="utf-8") as f:
                json.dump(normalized, f, indent=2)

            if self.executor_cmd:
                cmd = self.executor_cmd.replace("{job_json}", job_path).replace(
                    "{result_json}", result_path
                )
                proc = subprocess.run(cmd, shell=True, capture_output=True)
                if proc.returncode != 0:
                    stderr = _decode_proc_text(proc.stderr).strip()
                    stdout = _decode_proc_text(proc.stdout).strip()
                    msg = stderr if stderr else stdout
                    raise RuntimeError(f"Executor failed rc={proc.returncode}: {msg}")
                if os.path.isfile(result_path) and os.path.getsize(result_path) > 0:
                    with open(result_path, "r", encoding="utf-8") as f:
                        payload = json.load(f)
                    if str(payload.get("status", "")).lower() in ("failed", "error"):
                        raise RuntimeError(payload.get("error", str(payload)))
                    return payload
                raise RuntimeError("Executor completed but produced no result JSON.")

            if not self.max_batch_exe or not os.path.isfile(self.max_batch_exe):
                raise RuntimeError(
                    "3dsmaxbatch.exe not found. Set --max-batch-exe or VB_MAX_BATCH_EXE."
                )
            if not self.networkrender_script or not os.path.isfile(self.networkrender_script):
                raise RuntimeError(
                    "networkrender.py not found. Set --networkrender-script or VB_NETWORKRENDER_SCRIPT."
                )

            env = os.environ.copy()
            env["VB_JOB_JSON_PATH"] = job_path
            env["VB_RESULT_JSON_PATH"] = result_path

            # 3dsmaxbatch expects script_file as positional arg (not -pythonScript).
            cmd = [self.max_batch_exe, self.networkrender_script]
            proc = subprocess.run(
                cmd,
                shell=False,
                capture_output=True,
                env=env,
                timeout=(self.job_timeout_sec if self.job_timeout_sec > 0 else None),
            )
            if os.path.isfile(result_path) and os.path.getsize(result_path) > 0:
                with open(result_path, "r", encoding="utf-8") as f:
                    payload = json.load(f)
                if proc.returncode != 0:
                    err = payload.get("error", "")
                    if err:
                        raise RuntimeError(
                            f"3dsmaxbatch failed rc={proc.returncode}: {err}"
                        )
                if str(payload.get("status", "")).lower() in ("failed", "error"):
                    raise RuntimeError(payload.get("error", str(payload)))
                return payload

            if proc.returncode != 0:
                stderr = _decode_proc_text(proc.stderr).strip()
                stdout = _decode_proc_text(proc.stdout).strip()
                msg = stderr if stderr else stdout
                raise RuntimeError(f"3dsmaxbatch failed rc={proc.returncode}: {msg}")

            stderr = _decode_proc_text(proc.stderr).strip()
            stdout = _decode_proc_text(proc.stdout).strip()
            msg = stderr if stderr else stdout
            if msg:
                self.log(f"3dsmaxbatch warning: {msg}")
            raise RuntimeError("3dsmaxbatch completed but produced no result JSON.")
        finally:
            try:
                os.remove(job_path)
            except Exception:
                pass
            try:
                os.remove(result_path)
            except Exception:
                pass

    def process_job(self, job):
        job_id = job.get("job_id", "")
        scene_job = job.get("scene_job", {})
        scene_path = (scene_job.get("scene_file", "") if isinstance(scene_job, dict) else "")
        self._set_state(current_status="running", current_job_id=job_id)
        self.update_job_status(job_id, "running")
        self.log(f"Running job {job_id} :: {scene_path}")

        try:
            result = self._execute_job(scene_job, job_id=job_id)
            status = str((result or {}).get("status", "")).lower()
            if status not in ("success", "skipped", "done", "ok"):
                raise RuntimeError(f"Job returned non-success status: {status or 'unknown'}")
            self.update_job_status(job_id, "done", result=result)
            self._bump_counter("jobs_done", 1)
            self.log(f"Completed job {job_id}")
        except Exception as exc:
            msg = str(exc)
            self.update_job_status(job_id, "failed", detail=msg, result={"status": "failed"})
            self._bump_counter("jobs_failed", 1)
            self._set_state(last_error=msg)
            self.log(f"Failed job {job_id}: {msg}")
        finally:
            self._set_state(current_status="idle", current_job_id=None)

    def _try_reregister(self, context, exc):
        if self.stop_event.is_set() or (not self._is_worker_not_found_error(exc)):
            return False, False
        self.log(f"Worker not found during {context}; re-registering.")
        self._set_state(current_status="starting", current_job_id=None)
        try:
            self.register()
            return True, True
        except Exception as reg_exc:
            self._set_state(last_error=str(reg_exc))
            self.log(f"Re-register failed: {reg_exc}")
            time.sleep(1.0)
            return True, False

    def _loop(self):
        self.log("Worker loop started.")
        last_heartbeat = 0.0

        if not self._get_server_url():
            self.discover_server(timeout_sec=2.0)
        if not self._get_server_url():
            self.log("No server URL configured/discovered. Waiting for --server-url or discovery.")

        while not self.stop_event.is_set():
            if not self._get_server_url():
                self.discover_server(timeout_sec=1.0)
                time.sleep(1.0)
                continue

            try:
                self._api_get("/health")
                if self._get_current_status() == "starting":
                    self.register()
            except Exception as exc:
                self._set_state(last_error=str(exc))
                self.log(f"Server unavailable: {exc}")
                time.sleep(2.0)
                continue

            now = _now()
            if (now - last_heartbeat) >= self.heartbeat_interval:
                try:
                    self.heartbeat()
                    last_heartbeat = now
                except Exception as exc:
                    handled, registered = self._try_reregister("heartbeat", exc)
                    if handled:
                        if registered:
                            last_heartbeat = _now()
                        continue
                    self._set_state(last_error=str(exc))
                    self.log(f"Heartbeat failed: {exc}")
                    time.sleep(1.0)
                    continue

            if self._get_current_status() == "idle":
                try:
                    job = self.claim_job()
                except Exception as exc:
                    handled, _registered = self._try_reregister("claim", exc)
                    if handled:
                        continue
                    self._set_state(last_error=str(exc))
                    self.log(f"Claim failed: {exc}")
                    time.sleep(self.poll_interval)
                    continue

                if not job:
                    time.sleep(self.poll_interval)
                    continue

                self._bump_counter("jobs_claimed", 1)
                self.process_job(job)
            else:
                time.sleep(0.2)

        self.log("Worker loop stopped.")
        self.unregister()

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._set_state(current_status="starting", current_job_id=None, last_error="")
        self.stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self.stop_event.set()
        if self._thread:
            self._thread.join(timeout=STOP_JOIN_TIMEOUT_SEC)
            if self._thread.is_alive():
                self.log("Stop requested; waiting for current job to finish before unregister.")

    def wait_forever(self):
        try:
            while True:
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()


def run_worker(config=None, **kwargs):
    if config is None:
        config = WorkerConfig(**kwargs)
    runtime = WorkerRuntime(config)
    runtime.start()
    runtime.wait_forever()


def parse_args():
    parser = argparse.ArgumentParser(description="VirtualBuilders Batch Worker")
    parser.add_argument("--server-url", default="", help="Server URL, e.g. http://10.0.0.10:8765")
    parser.add_argument("--worker-id", default="", help="Stable worker id (optional)")
    parser.add_argument("--worker-name", default="", help="Display worker name (optional)")
    parser.add_argument("--host", default="", help="Worker host label (optional)")
    parser.add_argument("--color", default="", help="Dashboard color as #rrggbb hex (optional; blank = auto)")
    parser.add_argument("--poll-interval", type=float, default=2.0, help="Job polling interval seconds")
    parser.add_argument("--heartbeat-interval", type=float, default=5.0, help="Heartbeat interval seconds")
    parser.add_argument("--discovery-port", type=int, default=DEFAULT_DISCOVERY_PORT, help="UDP discovery port")
    parser.add_argument("--mock", action="store_true", help="Use mock execution mode")
    parser.add_argument("--mock-seconds", type=float, default=2.0, help="Mock execution duration seconds")
    parser.add_argument(
        "--executor-cmd",
        default="",
        help="Custom command template for real execution; supports {job_json} and {result_json}.",
    )
    parser.add_argument(
        "--max-batch-exe",
        default="",
        help="Path to 3dsmaxbatch.exe (auto-detected if omitted).",
    )
    parser.add_argument(
        "--networkrender-script",
        default="",
        help="Path to networkrender.py executed by 3dsmaxbatch.",
    )
    parser.add_argument(
        "--job-timeout-sec",
        type=int,
        default=0,
        help="Per-job timeout in seconds (0 = no timeout).",
    )
    parser.add_argument("--ui", action="store_true", help="Launch worker UI dashboard")
    return parser.parse_args()


def main():
    args = parse_args()
    config = WorkerConfig.from_args(args)
    if args.ui:
        from NetworkRender.worker import worker_ui

        worker_ui.run_worker_ui(config=config)
        return

    run_worker(config=config)


if __name__ == "__main__":
    main()

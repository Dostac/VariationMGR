"""Spawn ``3dsmaxbatch.exe`` to render scene jobs headlessly.

Mirrors the execution pattern in
``NetworkRender/worker/worker.py  WorkerRuntime._execute_job()``.
"""

import json
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

from PySide6 import QtCore

from standalone_batchrenderer import max_discovery

# Locate networkrender.py relative to the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_NETWORKRENDER = str(
    _REPO_ROOT / "NetworkRender" / "worker" / "networkrender.py"
)


def _decode_proc_text(data):
    if isinstance(data, bytes):
        for enc in ("utf-8", "cp1252", "latin-1"):
            try:
                return data.decode(enc)
            except Exception:
                pass
        return data.decode("utf-8", errors="replace")
    return str(data or "")


# -------------------------------------------------------------------------
# QThread-based batch runner (non-blocking for the UI)
# -------------------------------------------------------------------------

class HeadlessRunner(QtCore.QObject):
    """Runs scene jobs via ``3dsmaxbatch.exe`` in a background thread."""

    # Signals emitted on the main thread via Qt's event loop.
    log_message = QtCore.Signal(str)
    progress = QtCore.Signal(int, int)       # (current_index, total)
    finished = QtCore.Signal(dict)           # aggregated result dict

    def __init__(self, max_batch_exe="", parent=None):
        super().__init__(parent)
        self.max_batch_exe = max_batch_exe or max_discovery.find_3dsmaxbatch_exe()
        self.networkrender_script = (
            os.environ.get("VB_NETWORKRENDER_SCRIPT", "").strip()
            or _DEFAULT_NETWORKRENDER
        )
        self._cancel = False
        self._thread = None

    # -- public API -------------------------------------------------------

    def set_max_batch_exe(self, path):
        self.max_batch_exe = path

    def cancel(self):
        self._cancel = True

    def run_batch(self, scene_jobs):
        """Start rendering *scene_jobs* in a background thread."""
        self._cancel = False
        self._thread = _WorkerThread(self, scene_jobs)
        self._thread.start()

    # -- internal ---------------------------------------------------------

    def _log(self, msg):
        self.log_message.emit(msg)

    def _run_scene_job(self, scene_job):
        """Execute one scene job via 3dsmaxbatch.exe.  Returns result dict."""
        if not self.max_batch_exe or not os.path.isfile(self.max_batch_exe):
            return {
                "status": "failed",
                "error": "3dsmaxbatch.exe not found. Configure the path in settings.",
            }
        if not self.networkrender_script or not os.path.isfile(
            self.networkrender_script
        ):
            return {
                "status": "failed",
                "error": f"networkrender.py not found: {self.networkrender_script}",
            }

        fd, job_path = tempfile.mkstemp(prefix="vb_job_", suffix=".json")
        os.close(fd)
        result_path = os.path.join(
            tempfile.gettempdir(),
            f"vb_job_result_{uuid.uuid4().hex}.json",
        )
        try:
            with open(job_path, "w", encoding="utf-8") as f:
                json.dump(scene_job, f, indent=2)

            env = os.environ.copy()
            env["VB_JOB_JSON_PATH"] = job_path
            env["VB_RESULT_JSON_PATH"] = result_path

            cmd = [self.max_batch_exe, self.networkrender_script]
            self._log(f"  Launching: {os.path.basename(self.max_batch_exe)}")

            proc = subprocess.run(
                cmd,
                shell=False,
                capture_output=True,
                env=env,
            )

            if os.path.isfile(result_path) and os.path.getsize(result_path) > 0:
                with open(result_path, "r", encoding="utf-8") as f:
                    payload = json.load(f)
                if proc.returncode != 0:
                    err = payload.get("error", "")
                    if err:
                        return {"status": "failed", "error": err}
                if str(payload.get("status", "")).lower() in ("failed", "error"):
                    return {
                        "status": "failed",
                        "error": payload.get("error", str(payload)),
                    }
                return payload

            if proc.returncode != 0:
                stderr = _decode_proc_text(proc.stderr).strip()
                stdout = _decode_proc_text(proc.stdout).strip()
                msg = stderr if stderr else stdout
                return {
                    "status": "failed",
                    "error": f"3dsmaxbatch failed rc={proc.returncode}: {msg}",
                }

            return {
                "status": "failed",
                "error": "3dsmaxbatch completed but produced no result JSON.",
            }
        except Exception as exc:
            return {"status": "failed", "error": str(exc)}
        finally:
            for p in (job_path, result_path):
                try:
                    os.remove(p)
                except Exception:
                    pass


class _WorkerThread(QtCore.QThread):
    """Thin thread wrapper that iterates scene jobs."""

    def __init__(self, runner, scene_jobs):
        super().__init__()
        self._runner = runner
        self._scene_jobs = scene_jobs

    def run(self):
        runner = self._runner
        total = len(self._scene_jobs)
        results = []
        completed = 0

        for idx, scene_job in enumerate(self._scene_jobs):
            if runner._cancel:
                runner._log("Aborted.")
                break

            scene_file = scene_job.get("scene_file", "")
            label = os.path.basename(scene_file) if scene_file else f"Job {idx + 1}"
            runner._log(f"[{idx + 1}/{total}] {label}")
            runner.progress.emit(idx, total)

            result = runner._run_scene_job(scene_job)
            results.append(result)

            status = result.get("status", "failed")
            if status in ("success", "done", "ok", "skipped"):
                runner._log(f"  Result: {status}")
                completed += 1
            else:
                runner._log(f"  Failed: {result.get('error', 'unknown error')}")

        runner.progress.emit(total, total)
        runner.finished.emit({
            "status": "complete" if not runner._cancel else "aborted",
            "total_scenes": total,
            "completed_scenes": completed,
            "results": results,
        })

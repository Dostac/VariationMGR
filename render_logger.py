"""Headless render-progress logging.

One render job -> one log file in that job's output folder, plus an optional
live "mirror" callback that forwards every line to whoever is watching (a
3ds Max UI panel, the worker's stdout, an event buffer, ...).

This layer owns the log *file* so the render core can stay focused on
rendering, and so the same log is produced whether the core runs interactively
inside 3ds Max or headless under the network worker. Nothing here imports Qt or
any UI: it is safe to use in 3dsmaxbatch.

The file is the channel. Every viewer is just a reader of it -- the worker and
colleagues tail "<output_folder>/<job_id>.log"; nobody has to push progress
across a process boundary.
"""

import datetime
import os
import re


_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize_job_id(job_id):
    """Make a job id safe to use as a filename stem."""
    cleaned = _UNSAFE.sub("_", str(job_id).strip())
    return cleaned.strip("._") or "render"


def make_job_id(scene_name, when=None):
    """Mint a job id for renders that weren't handed one.

    Server jobs arrive with a job_id from the worker; local / interactive
    renders call this so every render still gets a unique, readable id and
    its own log file. Same code path either way.
    """
    when = when or datetime.datetime.now()
    stem = sanitize_job_id(scene_name) if scene_name else "render"
    return f"{stem}_{when:%d%m%y_%H%M%S}"


class RenderLog:
    """A single render's progress log: a file + an optional live mirror.

    Use as a context manager so the file is always flushed and closed, even
    if the render raises:

        mirror = ui_panel.append            # or print, or None
        with RenderLog(out_dir, job_id, mirror=mirror) as rlog:
            rlog.write("Opening scene ...")

    The file lines are timestamped; the mirror receives the raw message so the
    live viewer can format it however it likes (the UI already timestamps for
    display). Logging never raises into the render: if the file can't be
    opened or written, it degrades to mirror-only.
    """

    FILENAME_TEMPLATE = "{job_id}.log"

    def __init__(self, out_dir, job_id, mirror=None):
        self.out_dir = out_dir
        self.job_id = job_id
        self.mirror = mirror if callable(mirror) else None
        self.path = ""
        self._fh = None
        if out_dir:
            self.path = os.path.join(
                out_dir,
                self.FILENAME_TEMPLATE.format(job_id=sanitize_job_id(job_id)),
            )

    def open(self):
        if self.path:
            try:
                os.makedirs(self.out_dir, exist_ok=True)
                # Append so a retried job keeps its history in one file.
                self._fh = open(self.path, "a", encoding="utf-8")
            except Exception:
                self._fh = None  # mirror-only; never break the render
        return self

    def write(self, msg):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        if self._fh is not None:
            try:
                self._fh.write(f"[{ts}] {msg}\n")
                self._fh.flush()  # flush per line so tailing readers see it live
            except Exception:
                pass
        if self.mirror is not None:
            try:
                self.mirror(msg)
            except Exception:
                pass

    def close(self):
        if self._fh is not None:
            try:
                self._fh.close()
            except Exception:
                pass
            self._fh = None

    def __enter__(self):
        return self.open()

    def __exit__(self, exc_type, exc, tb):
        if exc is not None:
            self.write(f"Aborted: {exc}")
        self.close()
        return False  # don't swallow the exception

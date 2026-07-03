"""Headless render-progress logging.

One output folder -> one shared log file ("batchrender.log"), plus an optional
live "mirror" callback that forwards every line to whoever is watching (a
3ds Max UI panel, the worker's stdout, an event buffer, ...).

Every line is tagged with the job id that produced it, so jobs that were split
across multiple workers but render into the same folder interleave into a
single readable history instead of scattering one file per job id.

This layer owns the log *file* so the render core can stay focused on
rendering, and so the same log is produced whether the core runs interactively
inside 3ds Max or headless under the network worker. Nothing here imports Qt or
any UI: it is safe to use in 3dsmaxbatch.

Concurrency: writers append whole, individually-flushed lines. Concurrent jobs
may interleave *lines* (disambiguated by the job tag), but not partial lines.
"""

import datetime
import os
import re


_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize_job_id(job_id):
    """Make a job id safe to use as a log tag / filename stem."""
    cleaned = _UNSAFE.sub("_", str(job_id).strip())
    return cleaned.strip("._") or "render"


def make_job_id(scene_name, when=None):
    """Mint a job id for renders that weren't handed one.

    Server jobs arrive with a job_id from the worker; local / interactive
    renders call this so every render still gets a unique, readable id that
    tags its lines in the shared log. Same code path either way.
    """
    when = when or datetime.datetime.now()
    stem = sanitize_job_id(scene_name) if scene_name else "render"
    return f"{stem}_{when:%d%m%y_%H%M%S}"


class RenderLog:
    """One render job's view onto the shared folder log + an optional mirror.

    All jobs rendering into the same output folder append to the same file;
    each instance stamps its own job id onto every line it writes.

    Use as a context manager so the file is always flushed and closed, even
    if the render raises:

        mirror = ui_panel.append            # or print, or None
        with RenderLog(out_dir, job_id, mirror=mirror) as rlog:
            rlog.write("Opening scene ...")

    The file lines carry a date+time stamp (the file lives across days) and
    the job tag; the mirror receives the raw message so the live viewer can
    format it however it likes (the UI already timestamps for display).
    Logging never raises into the render: if the file can't be opened or
    written, it degrades to mirror-only.
    """

    FILENAME = "batchrender.log"

    def __init__(self, out_dir, job_id, mirror=None):
        self.out_dir = out_dir
        self.job_id = sanitize_job_id(job_id)
        self.mirror = mirror if callable(mirror) else None
        self.path = ""
        self._fh = None
        if out_dir:
            self.path = os.path.join(out_dir, self.FILENAME)

    def open(self):
        if self.path:
            try:
                os.makedirs(self.out_dir, exist_ok=True)
                # Append: the file is shared by every job that renders into
                # this folder, and a retried job keeps its history here too.
                self._fh = open(self.path, "a", encoding="utf-8")
            except Exception:
                self._fh = None  # mirror-only; never break the render
        return self

    def write(self, msg):
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if self._fh is not None:
            try:
                self._fh.write(f"[{ts}] [{self.job_id}] {msg}\n")
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

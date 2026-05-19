import datetime
import os
import subprocess
import sys
import time
from pathlib import Path

from PySide6 import QtCore, QtWidgets
from PySide6.QtGui import QColor, QPainter


class StatusChipDelegate(QtWidgets.QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)

    def _palette_for(self, status):
        s = str(status).strip().lower()
        if s == "queued":
            # Brighter blue for queued.
            return {"chip_bg": QColor(90, 170, 255, 170), "chip_fg": None, "text_fg": None}
        if s == "failed":
            # Brighter red.
            return {"chip_bg": QColor(255, 110, 110, 170), "chip_fg": None, "text_fg": None}
        if s in ("running", "claimed"):
            # Brighter amber.
            return {"chip_bg": QColor(255, 200, 95, 170), "chip_fg": None, "text_fg": None}
        if s in ("done", "success"):
            # Brighter green.
            return {"chip_bg": QColor(120, 230, 120, 170), "chip_fg": None, "text_fg": None}
        return {"chip_bg": None, "chip_fg": None, "text_fg": None}

    def paint(self, painter, option, index):
        text = str(index.data(QtCore.Qt.ItemDataRole.DisplayRole) or "")
        colors = self._palette_for(text)

        # Draw base item (selection/alternating rows/etc.) without default text.
        opt = QtWidgets.QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        style = opt.widget.style() if opt.widget else QtWidgets.QApplication.style()
        style.drawControl(QtWidgets.QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        chip_bg = colors["chip_bg"]
        chip_fg = colors["chip_fg"]
        text_fg = colors["text_fg"]

        if chip_bg is not None:
            chip_rect = option.rect.adjusted(8, 5, -8, -5)
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(chip_bg)
            radius = max(5.0, min(chip_rect.height() / 2.0, 10.0))
            painter.drawRoundedRect(chip_rect, radius, radius)
            painter.setPen(option.palette.text().color())
            painter.drawText(chip_rect, QtCore.Qt.AlignmentFlag.AlignCenter, text)
        else:
            if text_fg is not None:
                painter.setPen(text_fg)
            else:
                painter.setPen(option.palette.text().color())
            text_rect = option.rect.adjusted(8, 0, -8, 0)
            painter.drawText(
                text_rect,
                QtCore.Qt.AlignmentFlag.AlignCenter | QtCore.Qt.AlignmentFlag.AlignVCenter,
                text,
            )

        painter.restore()

if __package__ is None or __package__ == "":
    # Allow direct execution: python NetworkRender/server/server_ui.py
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

from NetworkRender.server.server import (
    DEFAULT_STALE_REQUEUE_SECONDS,
    ServerRuntime,
    parse_args as parse_server_args,
)


def _fmt_ts(ts):
    if not ts:
        return "-"
    try:
        return datetime.datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return "-"


def _short_id(value, length=8):
    text = str(value or "")
    if len(text) <= length:
        return text
    return text[:length]


def _fmt_duration(secs):
    if not secs or secs <= 0:
        return "-"
    secs = int(secs)
    if secs < 60:
        return f"{secs}s"
    m, s = divmod(secs, 60)
    if m < 60:
        return f"{m}m {s}s" if s else f"{m}m"
    h, mm = divmod(m, 60)
    return f"{h}h {mm}m" if mm else f"{h}h"


def _short_path_tail(path_value, parts=3):
    path_text = str(path_value or "").strip()
    if not path_text:
        return ""
    normalized = os.path.normpath(path_text).replace("\\", "/")
    chunks = [c for c in normalized.split("/") if c]
    if len(chunks) <= parts:
        return normalized
    return ".../" + "/".join(chunks[-parts:])


class ServerWindow(QtWidgets.QMainWindow):
    def __init__(self, runtime):
        super().__init__()
        self.runtime = runtime
        self.setWindowTitle("VB Batch Server")
        self.resize(1200, 820)
        self._updating_jobs = False

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        
        # MD3 Root Layout
        root = QtWidgets.QVBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(0)

        # 1. Server Overview Card
        top_group = QtWidgets.QGroupBox("1. Server Overview")
        top_layout = QtWidgets.QVBoxLayout(top_group)
        top_layout.setContentsMargins(16, 12, 16, 12)
        top_layout.setSpacing(8)

        # Info and Actions inline (action density rule)
        info_row = QtWidgets.QHBoxLayout()
        info_row.setSpacing(8)
        
        self.lbl_info = QtWidgets.QLabel("")
        info_row.addWidget(self.lbl_info, stretch=1)

        self.btn_refresh = QtWidgets.QPushButton("Refresh")

        self.btn_pause_resume = QtWidgets.QPushButton("")
        self.btn_pause_resume.setFixedWidth(28)  # MD3 icon-action button fixed width
        self.btn_pause_resume.setToolTip("Pause/resume assigning queued jobs to workers.")

        info_row.addWidget(self.btn_refresh)
        info_row.addWidget(self.btn_pause_resume)
        
        top_layout.addLayout(info_row)

        self.lbl_stats = QtWidgets.QLabel("")
        top_layout.addWidget(self.lbl_stats)

        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setToolTip("Done jobs / total jobs")
        top_layout.addWidget(self.progress)

        root.addWidget(top_group)
        root.addSpacing(8)  # MD3 standard inter-card gap

        # Splitter to hold main tables
        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)

        # 2. Workers Card
        workers_panel = QtWidgets.QGroupBox("2. Workers")
        workers_layout = QtWidgets.QVBoxLayout(workers_panel)
        workers_layout.setContentsMargins(16, 12, 16, 12)
        workers_layout.setSpacing(8)
        
        self.tbl_workers = QtWidgets.QTableWidget(0, 4)
        self.tbl_workers.setHorizontalHeaderLabels([
            "Host",
            "Status",
            "Running",
            "Last Seen",
        ])
        self.tbl_workers.horizontalHeader().setStretchLastSection(False)
        self.tbl_workers.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeMode.Interactive
        )
        self.tbl_workers.verticalHeader().setVisible(False)
        self.tbl_workers.setAlternatingRowColors(True)
        self.tbl_workers.setShowGrid(False)
        self.tbl_workers.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl_workers.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl_workers.setItemDelegateForColumn(2, StatusChipDelegate(self.tbl_workers))
        self.tbl_workers.setColumnWidth(0, 200)
        self.tbl_workers.setColumnWidth(1, 120)
        self.tbl_workers.setColumnWidth(2, 320)
        self.tbl_workers.setColumnWidth(3, 170)
        workers_layout.addWidget(self.tbl_workers)
        
        splitter.addWidget(workers_panel)

        # 3. Jobs Card
        jobs_panel = QtWidgets.QGroupBox("3. Jobs Queue")
        jobs_layout = QtWidgets.QVBoxLayout(jobs_panel)
        jobs_layout.setContentsMargins(16, 12, 16, 12)
        jobs_layout.setSpacing(8)
        
        # Job Actions Row - Grouped logically with the relevant context, no loose bottom row
        jobs_act_row = QtWidgets.QHBoxLayout()
        jobs_act_row.setSpacing(8)
        
        self.chk_auto_requeue = QtWidgets.QCheckBox("Auto-requeue failed (max 2 attempts)")
        self.chk_auto_requeue.setToolTip(
            "When checked, failed jobs with fewer than 2 attempts are automatically\n"
            "requeued on every refresh cycle."
        )
        self.chk_auto_requeue.setChecked(self.runtime.state.is_auto_requeue_failed())
        self.chk_auto_requeue.toggled.connect(self.runtime.state.set_auto_requeue_failed)
        self.btn_requeue = QtWidgets.QPushButton("Requeue Stale")
        self.btn_requeue.setToolTip("Requeue claimed/running jobs stale for 15+ min")
        
        self.btn_clear_queue = QtWidgets.QPushButton("Clear Queue")
        self.btn_clear_queue.setToolTip("Remove queued jobs from server")
        
        self.btn_remove_done = QtWidgets.QPushButton("Remove Done")
        self.btn_remove_done.setToolTip("Remove all jobs with status 'done'.")
        
        self.btn_remove_failed = QtWidgets.QPushButton("Remove Failed")
        self.btn_remove_failed.setToolTip("Remove all jobs with status 'failed'.")
        
        self.btn_clear_all = QtWidgets.QPushButton("Clear All")
        self.btn_clear_all.setToolTip("Remove all jobs from server.")

        jobs_act_row.addWidget(self.chk_auto_requeue)
        jobs_act_row.addStretch()
        jobs_act_row.addWidget(self.btn_requeue)
        jobs_act_row.addWidget(self.btn_remove_done)
        jobs_act_row.addWidget(self.btn_remove_failed)
        jobs_act_row.addWidget(self.btn_clear_queue)
        jobs_act_row.addWidget(self.btn_clear_all)
        
        jobs_layout.addLayout(jobs_act_row)

        self.tbl_jobs = QtWidgets.QTableWidget(0, 9)
        self.tbl_jobs.setHorizontalHeaderLabels([
            "Job ID",
            "Scene",
            "Output",
            "Status",
            "Host",
            "Duration",
            "Attempts",
            "Updated",
            "Last Error",
        ])
        self.tbl_jobs.horizontalHeader().setStretchLastSection(False)
        self.tbl_jobs.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeMode.Interactive
        )
        self.tbl_jobs.verticalHeader().setVisible(False)
        self.tbl_jobs.setAlternatingRowColors(True)
        self.tbl_jobs.setShowGrid(False)
        self.tbl_jobs.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl_jobs.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tbl_jobs.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl_jobs.setItemDelegateForColumn(3, StatusChipDelegate(self.tbl_jobs))
        self.tbl_jobs.setColumnWidth(0, 100)
        self.tbl_jobs.setColumnWidth(1, 260)
        self.tbl_jobs.setColumnWidth(2, 260)
        self.tbl_jobs.setColumnWidth(3, 110)
        self.tbl_jobs.setColumnWidth(4, 160)
        self.tbl_jobs.setColumnWidth(5, 90)
        self.tbl_jobs.setColumnWidth(6, 70)
        self.tbl_jobs.setColumnWidth(7, 155)
        self.tbl_jobs.setColumnWidth(8, 240)
        self.tbl_jobs.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.tbl_jobs.customContextMenuRequested.connect(self.show_jobs_menu)
        self.tbl_jobs.cellDoubleClicked.connect(self._on_job_cell_double_clicked)
        jobs_layout.addWidget(self.tbl_jobs)

        splitter.addWidget(jobs_panel)
        splitter.setSizes([250, 520])

        root.addWidget(splitter, stretch=1)

        # Logic Connections
        self.btn_refresh.clicked.connect(self.refresh)
        self.btn_requeue.clicked.connect(self.requeue_stale)
        self.btn_remove_done.clicked.connect(self.remove_done_jobs)
        self.btn_remove_failed.clicked.connect(self.remove_failed_jobs)
        self.btn_clear_queue.clicked.connect(self.clear_queue)
        self.btn_clear_all.clicked.connect(self.clear_all_jobs)
        self.btn_pause_resume.clicked.connect(self.toggle_queue_pause)

        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()

        self.refresh()

    def closeEvent(self, event):
        self.timer.stop()
        self.runtime.stop()
        event.accept()

    def _set_item(self, table, row, col, value, tooltip=None, user_data=None):
        item = QtWidgets.QTableWidgetItem(str(value))
        if tooltip:
            item.setToolTip(str(tooltip))
        if user_data is not None:
            item.setData(QtCore.Qt.ItemDataRole.UserRole, user_data)
        table.setItem(row, col, item)

    def refresh(self):
        # Auto-requeue runs in a background thread inside ServerRuntime now,
        # gated on state.is_auto_requeue_failed(). No need to drive it from
        # the UI refresh tick.
        stats = self.runtime.state.stats()
        workers = self.runtime.state.list_workers()
        jobs = self.runtime.state.list_jobs()
        jobs_by_id = {str(j.get("job_id", "")): j for j in jobs}
        workers_by_id = {str(w.get("worker_id", "")): w for w in workers}

        done = stats.get("by_status", {}).get("done", 0)
        total = stats.get("jobs_total", 0)
        pct = int((done * 100 / total)) if total else 0
        self.progress.setValue(pct)
        paused = bool(stats.get("queue_paused", False))

        self.lbl_info.setText(
            f"Server: http://{self.runtime.host}:{self.runtime.port} | "
            f"Local only: {self.runtime.local_only} | Queue paused: {paused}"
        )
        self.lbl_stats.setText(
            f"Jobs={stats.get('jobs_total', 0)} | "
            f"Queued={stats.get('queue_depth', 0)} | "
            f"Workers={stats.get('workers_total', 0)} | "
            f"Done={done} ({pct}%)"
        )

        # Use unicode glyphs as button text so the color follows the palette,
        # rather than the OS-styled (black) standard media icons.
        self.btn_pause_resume.setText("▶" if paused else "⏸")

        self.tbl_workers.setRowCount(len(workers))
        for row, w in enumerate(workers):
            wid = w.get("worker_id", "")
            self._set_item(
                self.tbl_workers,
                row,
                0,
                w.get("host", ""),
                tooltip=f"Worker ID: {wid}" if wid else "",
                user_data=wid,
            )
            self._set_item(self.tbl_workers, row, 1, w.get("status", ""))
            cur_job = w.get("current_job_id", "")
            running_text = "-"
            running_tooltip = ""
            if cur_job:
                running_job = jobs_by_id.get(str(cur_job), {})
                scene_path = str((running_job.get("scene_job", {}) or {}).get("scene_file", "") or "")
                if scene_path:
                    running_text = os.path.basename(scene_path) or scene_path
                    running_tooltip = f"{scene_path}\nJob ID: {cur_job}"
                else:
                    running_text = _short_id(cur_job)
                    running_tooltip = f"Job ID: {cur_job}"
            self._set_item(
                self.tbl_workers,
                row,
                2,
                running_text,
                tooltip=running_tooltip,
                user_data=cur_job or "",
            )
            self._set_item(self.tbl_workers, row, 3, _fmt_ts(w.get("last_seen")))
        self._updating_jobs = True
        try:
            now = time.time()
            self.tbl_jobs.setRowCount(len(jobs))
            for row, j in enumerate(jobs):
                scene_job = j.get("scene_job", {}) or {}
                scene = scene_job.get("scene_file", "")
                output_folder = (scene_job.get("output", {}) or {}).get("folder", "")
                job_id = j.get("job_id", "")
                req_id = j.get("request_id", "")
                claimed_by = str(j.get("claimed_by", "") or "")
                host = workers_by_id.get(claimed_by, {}).get("host", "") if claimed_by else ""
                if not host:
                    host = j.get("claimed_by_host", "")
                scene_name = os.path.basename(scene) if scene else ""
                id_tooltip = f"Job ID: {job_id}\nRequest ID: {req_id}"

                started_ts = float(j.get("started_at") or 0)
                finished_ts = float(j.get("finished_at") or 0)
                status_lower = (j.get("status", "") or "").lower()
                if finished_ts and started_ts and finished_ts >= started_ts:
                    duration = finished_ts - started_ts
                elif started_ts and status_lower in ("running", "claimed"):
                    duration = max(0.0, now - started_ts)
                else:
                    duration = 0.0
                duration_text = _fmt_duration(duration)
                duration_tooltip = ""
                if started_ts:
                    duration_tooltip = f"Started: {_fmt_ts(started_ts)}"
                    if finished_ts:
                        duration_tooltip += f"\nFinished: {_fmt_ts(finished_ts)}"

                self._set_item(self.tbl_jobs, row, 0, _short_id(job_id), tooltip=id_tooltip, user_data=job_id)
                self._set_item(self.tbl_jobs, row, 1, scene_name, tooltip=scene, user_data=scene)
                self._set_item(
                    self.tbl_jobs,
                    row,
                    2,
                    _short_path_tail(output_folder, parts=3),
                    tooltip=output_folder,
                    user_data=output_folder,
                )
                self._set_item(self.tbl_jobs, row, 3, j.get("status", ""))
                self._set_item(self.tbl_jobs, row, 4, host, tooltip=claimed_by, user_data=claimed_by)
                self._set_item(self.tbl_jobs, row, 5, duration_text, tooltip=duration_tooltip)
                self._set_item(self.tbl_jobs, row, 6, j.get("attempts", 0))
                self._set_item(self.tbl_jobs, row, 7, _fmt_ts(j.get("updated_at")))
                self._set_item(self.tbl_jobs, row, 8, j.get("last_error", ""))
        finally:
            self._updating_jobs = False

    def requeue_stale(self):
        requeued = self.runtime.state.requeue_stale_claims(DEFAULT_STALE_REQUEUE_SECONDS)
        QtWidgets.QMessageBox.information(
            self,
            "Requeue Complete",
            f"Requeued {len(requeued)} stale job(s).",
        )
        self.refresh()

    def clear_queue(self):
        queued_count = self.runtime.state.stats().get("queue_depth", 0)
        if queued_count <= 0:
            QtWidgets.QMessageBox.information(self, "Clear Queue", "Queue is already empty.")
            return

        answer = QtWidgets.QMessageBox.question(
            self,
            "Clear Queue",
            f"Remove all queued jobs ({queued_count})?\n\nRunning/claimed/done jobs are not removed.",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No,
        )
        if answer != QtWidgets.QMessageBox.StandardButton.Yes:
            return

        removed = self.runtime.state.clear_queue()
        QtWidgets.QMessageBox.information(self, "Clear Queue", f"Removed {removed} queued job(s).")
        self.refresh()

    def remove_done_jobs(self):
        count = len(self.runtime.state.list_jobs(status="done"))
        if count <= 0:
            QtWidgets.QMessageBox.information(self, "Remove Done", "No done jobs found.")
            return

        answer = QtWidgets.QMessageBox.question(
            self,
            "Remove Done Jobs",
            f"Remove all done jobs ({count})?",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No,
        )
        if answer != QtWidgets.QMessageBox.StandardButton.Yes:
            return

        removed = self.runtime.state.remove_jobs_by_status({"done", "success"})
        QtWidgets.QMessageBox.information(self, "Remove Done", f"Removed {removed} done job(s).")
        self.refresh()

    def remove_failed_jobs(self):
        count = len(self.runtime.state.list_jobs(status="failed"))
        if count <= 0:
            QtWidgets.QMessageBox.information(self, "Remove Failed", "No failed jobs found.")
            return

        answer = QtWidgets.QMessageBox.question(
            self,
            "Remove Failed Jobs",
            f"Remove all failed jobs ({count})?",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No,
        )
        if answer != QtWidgets.QMessageBox.StandardButton.Yes:
            return

        removed = self.runtime.state.remove_jobs_by_status({"failed"})
        QtWidgets.QMessageBox.information(self, "Remove Failed", f"Removed {removed} failed job(s).")
        self.refresh()

    def clear_all_jobs(self):
        total = self.runtime.state.stats().get("jobs_total", 0)
        if total <= 0:
            QtWidgets.QMessageBox.information(self, "Clear All", "There are no jobs to remove.")
            return

        answer = QtWidgets.QMessageBox.question(
            self,
            "Clear All Jobs",
            f"Remove all jobs ({total})?\n\nThis includes queued, claimed, running, done and failed jobs.",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No,
        )
        if answer != QtWidgets.QMessageBox.StandardButton.Yes:
            return

        removed = self.runtime.state.clear_all_jobs()
        QtWidgets.QMessageBox.information(self, "Clear All", f"Removed {removed} job(s).")
        self.refresh()

    def toggle_queue_pause(self):
        paused_now = self.runtime.state.is_queue_paused()
        paused_next = self.runtime.state.set_queue_paused(not paused_now)
        QtWidgets.QMessageBox.information(
            self,
            "Queue State",
            "Queue paused. Queued jobs will not be assigned to workers."
            if paused_next
            else "Queue resumed. Queued jobs can be assigned to workers again.",
        )
        self.refresh()

    @staticmethod
    def _to_native_path(path_str):
        """Convert forward-slash paths to Windows backslash form."""
        return str(path_str or "").replace("/", "\\")

    def _open_folder(self, folder_path):
        native = self._to_native_path(folder_path)
        try:
            if hasattr(os, "startfile"):
                os.startfile(native)
            else:
                subprocess.Popen(["explorer", native])
        except Exception as exc:
            QtWidgets.QMessageBox.warning(
                self,
                "Open Folder",
                f"Could not open folder:\n{native}\n\n{exc}",
            )

    def _open_file_selected(self, file_path):
        """Open Explorer with the file pre-selected."""
        native = self._to_native_path(file_path)
        try:
            subprocess.Popen(["explorer", f"/select,{native}"])
        except Exception as exc:
            QtWidgets.QMessageBox.warning(
                self,
                "Open Folder",
                f"Could not open folder for:\n{native}\n\n{exc}",
            )

    def _job_id_at_row(self, row):
        item = self.tbl_jobs.item(row, 0)
        if item is None:
            return ""
        job_id = str(item.data(QtCore.Qt.ItemDataRole.UserRole) or "").strip()
        if not job_id:
            job_id = (item.text() or "").strip()
        return job_id

    def _user_data_at(self, row, col):
        item = self.tbl_jobs.item(row, col)
        if item is None:
            return ""
        return str(item.data(QtCore.Qt.ItemDataRole.UserRole) or "").strip()

    def show_jobs_menu(self, pos):
        if self._updating_jobs:
            return

        rows = sorted({idx.row() for idx in self.tbl_jobs.selectionModel().selectedRows()})
        if not rows:
            item = self.tbl_jobs.itemAt(pos)
            if item is None:
                return
            rows = [item.row()]

        job_ids = [jid for jid in (self._job_id_at_row(r) for r in rows) if jid]
        if not job_ids:
            return

        multi = len(job_ids) > 1
        menu = QtWidgets.QMenu(self.tbl_jobs)
        act_open_scene = None
        act_open_output = None

        if not multi:
            scene_path = self._user_data_at(rows[0], 1)
            output_folder = self._user_data_at(rows[0], 2)
            if scene_path:
                act_open_scene = menu.addAction("Open Scene Folder")
            if output_folder:
                act_open_output = menu.addAction("Show Output in Explorer")
            if scene_path or output_folder:
                menu.addSeparator()

        act_requeue = menu.addAction(f"Requeue {len(job_ids)} Jobs" if multi else "Requeue Job")
        act_remove = menu.addAction(f"Remove {len(job_ids)} Jobs" if multi else "Remove Job")

        action = menu.exec(self.tbl_jobs.viewport().mapToGlobal(pos))
        if action is None:
            return
        if action == act_open_scene:
            self._open_file_selected(self._user_data_at(rows[0], 1))
            return
        if action == act_open_output:
            self._open_folder(self._user_data_at(rows[0], 2))
            return
        if action == act_requeue:
            self._requeue_jobs(job_ids)
            return
        if action == act_remove:
            self._remove_selected_jobs(job_ids)
            return

    def _requeue_jobs(self, job_ids):
        n = len(job_ids)
        if n > 1:
            answer = QtWidgets.QMessageBox.question(
                self,
                "Requeue Jobs",
                f"Requeue {n} job(s)?\n\nThey will go back into the queue regardless of current status.",
                QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
                QtWidgets.QMessageBox.StandardButton.Yes,
            )
            if answer != QtWidgets.QMessageBox.StandardButton.Yes:
                return
        requeued = self.runtime.state.requeue_jobs(job_ids)
        if not requeued:
            QtWidgets.QMessageBox.warning(self, "Requeue Jobs", "No matching jobs to requeue.")
        self.refresh()

    def _remove_selected_jobs(self, job_ids):
        n = len(job_ids)
        prompt = f"Remove {n} jobs?" if n > 1 else f"Remove job {job_ids[0]}?"
        answer = QtWidgets.QMessageBox.question(
            self,
            "Remove Jobs",
            prompt,
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No,
        )
        if answer != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        removed = self.runtime.state.remove_jobs(job_ids)
        if not removed:
            QtWidgets.QMessageBox.warning(self, "Remove Jobs", "No matching jobs to remove.")
        self.refresh()

    def _on_job_cell_double_clicked(self, row, col):
        if col == 1:
            path = self._user_data_at(row, 1)
            if path:
                self._open_file_selected(path)
        elif col == 2:
            folder = self._user_data_at(row, 2)
            if folder:
                self._open_folder(folder)


def run_server_ui(host, port, state_file, local_only=True, enable_discovery=True):
    app = QtWidgets.QApplication.instance()
    owns_app = False
    if app is None:
        app = QtWidgets.QApplication(sys.argv)
        owns_app = True

    runtime = ServerRuntime(
        host=host,
        port=port,
        state_file=state_file,
        local_only=local_only,
        enable_discovery=enable_discovery,
    )
    win = None
    try:
        runtime.start()
        win = ServerWindow(runtime)
        win.show()

        if owns_app:
            app.exec()
    finally:
        # ServerWindow.closeEvent stops runtime when the UI closes.
        # This additional stop is a safety net for startup/runtime failures
        # and for owned app-loop shutdown paths.
        if win is None or owns_app:
            runtime.stop()


def parse_args():
    return parse_server_args()


def main():
    args = parse_args()
    run_server_ui(
        host=args.host,
        port=args.port,
        state_file=args.state_file,
        local_only=(not args.allow_non_local),
        enable_discovery=(not args.no_discovery),
    )


if __name__ == "__main__":
    main()
import datetime
import sys
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

if __package__ is None or __package__ == "":
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

from NetworkRender.worker.worker import WorkerConfig, WorkerRuntime


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


class WorkerWindow(QtWidgets.QMainWindow):
    def __init__(self, runtime):
        super().__init__()
        self.runtime = runtime
        self.setWindowTitle("VB Batch Worker")
        self.resize(980, 720)
        self._last_log_text = ""

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        root = QtWidgets.QVBoxLayout(central)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        overview_group = QtWidgets.QGroupBox("Worker Overview")
        overview_layout = QtWidgets.QVBoxLayout(overview_group)
        overview_layout.setContentsMargins(12, 12, 12, 12)
        overview_layout.setSpacing(8)

        self.lbl_info = QtWidgets.QLabel("")
        self.lbl_state = QtWidgets.QLabel("")
        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)

        overview_layout.addWidget(self.lbl_info)
        overview_layout.addWidget(self.lbl_state)
        overview_layout.addWidget(self.progress)
        root.addWidget(overview_group)

        log_group = QtWidgets.QGroupBox("Worker Log")
        log_layout = QtWidgets.QVBoxLayout(log_group)
        log_layout.setContentsMargins(12, 12, 12, 12)
        log_layout.setSpacing(8)

        self.txt_log = QtWidgets.QPlainTextEdit()
        self.txt_log.setReadOnly(True)
        log_layout.addWidget(self.txt_log, stretch=1)
        root.addWidget(log_group, stretch=1)

        buttons = QtWidgets.QHBoxLayout()
        self.lbl_color = QtWidgets.QLabel("Dashboard color:")
        self.color_swatch = QtWidgets.QFrame()
        self.color_swatch.setFixedSize(18, 18)
        self.color_swatch.setFrameShape(QtWidgets.QFrame.Shape.Box)
        self.btn_color = QtWidgets.QPushButton("Pick…")
        self.btn_color.setToolTip("Choose the color this worker shows as in the server dashboard.")
        self.btn_color_auto = QtWidgets.QPushButton("Auto")
        self.btn_color_auto.setToolTip("Clear the custom color and let the dashboard auto-assign one.")
        self.btn_refresh = QtWidgets.QPushButton("Refresh")
        self.btn_discover = QtWidgets.QPushButton("Discover Server")
        self.btn_stop = QtWidgets.QPushButton("Stop Worker")
        self.btn_start = QtWidgets.QPushButton("Start Worker")
        self.chk_autoscroll = QtWidgets.QCheckBox("Auto-scroll log")
        self.chk_autoscroll.setChecked(True)
        buttons.addWidget(self.lbl_color)
        buttons.addWidget(self.color_swatch)
        buttons.addWidget(self.btn_color)
        buttons.addWidget(self.btn_color_auto)
        buttons.addStretch()
        buttons.addWidget(self.chk_autoscroll)
        buttons.addWidget(self.btn_refresh)
        buttons.addWidget(self.btn_discover)
        buttons.addWidget(self.btn_stop)
        buttons.addWidget(self.btn_start)
        root.addLayout(buttons)

        self.btn_color.clicked.connect(self.pick_color)
        self.btn_color_auto.clicked.connect(self.clear_color)
        self.btn_refresh.clicked.connect(self.refresh)
        self.btn_discover.clicked.connect(self.discover_server)
        self.btn_stop.clicked.connect(self.stop_worker)
        self.btn_start.clicked.connect(self.start_worker)

        self._last_swatch = object()  # force first swatch paint
        self._update_color_swatch(self.runtime.get_color())

        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.refresh()
        QtCore.QTimer.singleShot(1200, self.prompt_cleanup_duplicates)

    def closeEvent(self, event):
        self.timer.stop()
        self.runtime.stop()
        event.accept()

    def start_worker(self):
        self.runtime.start()
        self.refresh()

    def stop_worker(self):
        self.runtime.stop()
        self.refresh()

    def pick_color(self):
        current = self.runtime.get_color()
        initial = QtGui.QColor(current) if current else QtGui.QColor("#79c0ff")
        chosen = QtWidgets.QColorDialog.getColor(initial, self, "Choose Worker Color")
        if not chosen.isValid():
            return
        self._update_color_swatch(self.runtime.set_color(chosen.name()))

    def clear_color(self):
        self._update_color_swatch(self.runtime.set_color(""))

    def _update_color_swatch(self, color):
        color = color or ""
        if color == self._last_swatch:
            return
        self._last_swatch = color
        if color:
            self.color_swatch.setStyleSheet(f"background-color: {color}; border: 1px solid #555;")
            self.color_swatch.setToolTip(f"Worker color: {color}")
        else:
            self.color_swatch.setStyleSheet("background-color: transparent; border: 1px dashed #888;")
            self.color_swatch.setToolTip("Worker color: auto (assigned by the dashboard)")

    def discover_server(self):
        found = self.runtime.discover_server(timeout_sec=2.0)
        if found:
            QtWidgets.QMessageBox.information(self, "Discovery", f"Found server:\n{found}")
        else:
            QtWidgets.QMessageBox.warning(self, "Discovery", "No server discovered.")
        self.refresh()

    def refresh(self):
        s = self.runtime.snapshot()
        self._update_color_swatch(s.get("worker_color", ""))
        done = int(s.get("jobs_done", 0))
        failed = int(s.get("jobs_failed", 0))
        claimed = int(s.get("jobs_claimed", 0))
        total = claimed if claimed > 0 else 1
        pct = int((done * 100.0) / total)
        if pct < 0:
            pct = 0
        if pct > 100:
            pct = 100
        self.progress.setValue(pct)

        self.lbl_info.setText(
            f"Worker: {s.get('worker_name')} ({_short_id(s.get('worker_id'))}) | "
            f"Host: {s.get('host')} | Server: {s.get('server_url') or '(none)'}"
        )
        self.lbl_info.setToolTip(f"Worker ID: {s.get('worker_id')}")
        self.lbl_state.setText(
            f"Status: {s.get('status')} | Current Job: "
            f"{_short_id(s.get('current_job_id')) if s.get('current_job_id') else '-'} | "
            f"Claimed: {claimed} | Done: {done} | Failed: {failed} | "
            f"Last Server Contact: {_fmt_ts(s.get('last_seen_server'))}"
        )
        cur_job = s.get("current_job_id") or ""
        self.lbl_state.setToolTip(
            f"Current Job ID: {cur_job}" if cur_job else "Current Job ID: (none)"
        )
        mode = "MOCK" if s.get("mock_mode") else "REAL"
        self.setWindowTitle(
            f"VB Batch Worker [{mode}] - {s.get('worker_name')} ({_short_id(s.get('worker_id'))})"
        )
        events = s.get("recent_events", [])
        new_text = "\n".join(events[-400:])
        cursor = self.txt_log.textCursor()
        has_selection = cursor.hasSelection()
        if has_selection and self.txt_log.hasFocus():
            # Don't replace text while user is selecting/copying.
            return
        if new_text != self._last_log_text:
            self.txt_log.setPlainText(new_text)
            self._last_log_text = new_text
            if self.chk_autoscroll.isChecked():
                sb = self.txt_log.verticalScrollBar()
                sb.setValue(sb.maximum())

    def prompt_cleanup_duplicates(self):
        # Best effort check - only when connected to a server.
        if not self.runtime.snapshot().get("server_url"):
            return
        try:
            dups = self.runtime.find_duplicate_workers()
        except Exception:
            return
        if not dups:
            return

        lines = []
        for worker in dups:
            lines.append(
                f"- {worker.get('worker_name', worker.get('worker_id', ''))} "
                f"[{worker.get('worker_id', '')}] status={worker.get('status', '')}"
            )

        msg = (
            "Existing worker entries were found for this machine.\n\n"
            "Do you want to unregister them automatically?\n\n"
            + "\n".join(lines[:12])
        )
        if len(lines) > 12:
            msg += f"\n...and {len(lines) - 12} more"

        answer = QtWidgets.QMessageBox.question(
            self,
            "Cleanup Existing Workers",
            msg,
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.Yes,
        )
        if answer != QtWidgets.QMessageBox.StandardButton.Yes:
            return

        removed = 0
        for worker in dups:
            wid = str(worker.get("worker_id", "")).strip()
            if not wid:
                continue
            if self.runtime.unregister_worker_by_id(wid):
                removed += 1

        QtWidgets.QMessageBox.information(
            self,
            "Cleanup Complete",
            f"Unregistered {removed} worker entr{'y' if removed == 1 else 'ies'}.",
        )
        self.refresh()


def run_worker_ui(
    config=None,
    **kwargs,
):
    if config is None:
        config = WorkerConfig(**kwargs)
    runtime = WorkerRuntime(config)

    app = QtWidgets.QApplication.instance()
    owns_app = False
    if app is None:
        app = QtWidgets.QApplication(sys.argv)
        owns_app = True

    win = None
    try:
        runtime.start()
        win = WorkerWindow(runtime)
        win.show()

        if owns_app:
            app.exec()
    finally:
        # WorkerWindow.closeEvent stops runtime on normal close.
        # Keep explicit cleanup for startup/loop exceptions.
        if win is None or owns_app:
            runtime.stop()


def main():
    from NetworkRender.worker.worker import parse_args

    args = parse_args()
    run_worker_ui(config=WorkerConfig.from_args(args))


if __name__ == "__main__":
    main()

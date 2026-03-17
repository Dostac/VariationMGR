"""Application bootstrap for the standalone VB Batch Renderer."""

import argparse
import sys
from pathlib import Path

from PySide6 import QtWidgets

# Ensure repo root is on sys.path for shared module imports.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from standalone_batchrenderer.batch_panel import BatchPanel
from standalone_batchrenderer import tools_registry


class StandaloneMainWindow(QtWidgets.QMainWindow):
    """Top-level window with a tab widget for the batch panel and future tools."""

    def __init__(self, max_exe=""):
        super().__init__()
        self.setWindowTitle("VB Batch Renderer (Standalone)")
        self.resize(780, 1100)

        self.tabs = QtWidgets.QTabWidget()
        self.setCentralWidget(self.tabs)

        self.batch_panel = BatchPanel()
        self.tabs.addTab(self.batch_panel, "Batch Renderer")

        if max_exe:
            self.batch_panel.set_max_batch_exe(max_exe)

        # Register any future tool tabs.
        for name, widget_cls in tools_registry.iter_tools():
            self.tabs.addTab(widget_cls(), name)

    def closeEvent(self, event):
        self.batch_panel.save_ini()
        event.accept()


def _parse_args():
    parser = argparse.ArgumentParser(
        description="VB Batch Renderer — standalone edition"
    )
    parser.add_argument(
        "--max-exe",
        default="",
        help="Path to 3dsmaxbatch.exe (auto-detected if omitted)",
    )
    return parser.parse_args()


def main():
    args = _parse_args()

    app = QtWidgets.QApplication.instance()
    owns_app = app is None
    if owns_app:
        app = QtWidgets.QApplication(sys.argv)

    win = StandaloneMainWindow(max_exe=args.max_exe)
    win.show()

    if owns_app:
        sys.exit(app.exec())


if __name__ == "__main__":
    main()

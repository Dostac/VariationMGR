"""Batch Renderer panel — standalone edition (no pymxs / qtmax).

Adapted from ``batchrenderer_UI.py`` with all 3ds Max dependencies replaced
by standalone equivalents.  Layout follows the MD3 guide in
``.claude/commands/redesign-ui.md``.
"""

import datetime
import json
import os
import subprocess
import sys
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

# Ensure the repo root is importable for shared modules.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from NetworkRender.shared import job_schema as schema
from NetworkRender.shared import server_client

from standalone_batchrenderer import ini_persistence, max_discovery
from standalone_batchrenderer.headless_runner import HeadlessRunner
from standalone_batchrenderer.ocio_config import OcioConfig


class BatchPanel(QtWidgets.QWidget):
    """Main batch-renderer panel, embeddable as a tab."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_initializing = True

        # Each entry: {"path": str, "var_json": str}
        self.file_entries = []
        self.format_prefs = {
            "jpg": [0, False],
            "png": [0, True],
            "tif": [1, True],
            "exr": [0, True],
        }
        self.ocio = OcioConfig()
        self.runner = HeadlessRunner()

        self._build_ui()
        self._connect_signals()

        # Startup sequence.
        self.log("Initializing...")
        self._init_ocio()
        self.toggle_ocio_ui()
        self.load_ini()
        self.on_format_changed()
        self._setup_autosave()
        self.log(f"Config: {ini_persistence.get_ini_path()}")
        if self.ocio.loaded_from_file:
            self.log(f"OCIO : {self.ocio.config_path}")
        else:
            self.log("OCIO : using built-in defaults")
        self.log("Ready.")
        self._is_initializing = False

    # =================================================================
    # UI CONSTRUCTION  (MD3 layout — no setStyleSheet except status)
    # =================================================================

    def _build_ui(self):
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        outer.addWidget(scroll)

        container = QtWidgets.QWidget()
        scroll.setWidget(container)

        root = QtWidgets.QVBoxLayout(container)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(0)

        # -- 1. Batch Queue -----------------------------------------------
        gb_files = QtWidgets.QGroupBox("1. Batch Queue")
        fl = QtWidgets.QVBoxLayout(gb_files)
        fl.setContentsMargins(16, 12, 16, 12)
        fl.setSpacing(8)

        self.tree_widget = QtWidgets.QTreeWidget()
        self.tree_widget.setColumnCount(2)
        self.tree_widget.setHeaderLabels(["Scene File", "Variation Data"])
        hdr = self.tree_widget.header()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.tree_widget.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.tree_widget.setMinimumHeight(120)
        self.tree_widget.setContextMenuPolicy(
            QtCore.Qt.ContextMenuPolicy.CustomContextMenu
        )

        file_bar = QtWidgets.QHBoxLayout()
        file_bar.setSpacing(8)
        self.btn_add         = QtWidgets.QPushButton("Add Files")
        self.btn_assign_json = QtWidgets.QPushButton("Assign JSON")
        self.btn_remove      = QtWidgets.QPushButton("Remove")
        self.btn_clear       = QtWidgets.QPushButton("Clear")
        file_bar.addWidget(self.btn_add)
        file_bar.addWidget(self.btn_assign_json)
        file_bar.addWidget(self.btn_remove)
        file_bar.addStretch()
        file_bar.addWidget(self.btn_clear)

        fl.addWidget(self.tree_widget)
        fl.addLayout(file_bar)
        root.addWidget(gb_files)

        root.addSpacing(8)

        # -- 2. Output & Naming -------------------------------------------
        gb_out = QtWidgets.QGroupBox("2. Output & Naming")
        out_lay = QtWidgets.QVBoxLayout(gb_out)
        out_lay.setContentsMargins(16, 12, 16, 12)
        out_lay.setSpacing(8)

        out_lay.addWidget(QtWidgets.QLabel("Folder:"))
        path_row = QtWidgets.QHBoxLayout()
        self.le_path = QtWidgets.QLineEdit()
        self.btn_browse = QtWidgets.QPushButton("...")
        self.btn_browse.setFixedWidth(28)
        path_row.addWidget(self.le_path, stretch=1)
        path_row.addWidget(self.btn_browse)
        out_lay.addLayout(path_row)

        out_lay.addWidget(QtWidgets.QLabel("Version:"))
        self.cmb_version = QtWidgets.QComboBox()
        self.cmb_version.addItem("None")
        self.cmb_version.addItems([f"V{i}" for i in range(1, 11)])
        out_lay.addWidget(self.cmb_version)

        root.addWidget(gb_out)

        root.addSpacing(8)

        # -- 3. Render Settings -------------------------------------------
        gb_rend = QtWidgets.QGroupBox("3. Render Settings")
        rend_lay = QtWidgets.QVBoxLayout(gb_rend)
        rend_lay.setContentsMargins(16, 12, 16, 12)
        rend_lay.setSpacing(8)

        self.chk_override_settings = QtWidgets.QCheckBox(
            "Override scene render settings"
        )
        rend_lay.addWidget(self.chk_override_settings)

        self.widget_settings = QtWidgets.QWidget()
        settings_form = QtWidgets.QFormLayout(self.widget_settings)
        settings_form.setContentsMargins(16, 4, 0, 0)
        settings_form.setHorizontalSpacing(8)
        settings_form.setVerticalSpacing(8)

        self.spn_res = QtWidgets.QSpinBox()
        self.spn_res.setRange(100, 30000)
        self.spn_res.setValue(4000)
        self.spn_res.setSuffix(" px")

        self.spn_passes = QtWidgets.QSpinBox()
        self.spn_passes.setRange(0, 10000)
        self.spn_passes.setValue(75)

        self.spn_noise = QtWidgets.QDoubleSpinBox()
        self.spn_noise.setRange(0.0, 100.0)
        self.spn_noise.setValue(6.0)
        self.spn_noise.setSingleStep(0.5)
        self.spn_noise.setSuffix("%")

        settings_form.addRow("Longest Side:", self.spn_res)
        settings_form.addRow("Pass Limit:", self.spn_passes)
        settings_form.addRow("Noise Limit:", self.spn_noise)
        rend_lay.addWidget(self.widget_settings)
        self.widget_settings.setVisible(False)

        rend_lay.addWidget(QtWidgets.QLabel("Fallback Camera Mode:"))
        self.cmb_mode = QtWidgets.QComboBox()
        self.cmb_mode.addItems([
            "Render All Cameras",
            "Render Active View Only",
            "Render Camera By Name",
        ])
        rend_lay.addWidget(self.cmb_mode)

        self.le_fallback_cam = QtWidgets.QLineEdit()
        self.le_fallback_cam.setPlaceholderText("e.g. Detail")
        self.le_fallback_cam.setToolTip(
            "Loosely matched per scene: 'Detail' finds 'Detailbeeld' or 'Detail'.")
        rend_lay.addWidget(self.le_fallback_cam)
        self.le_fallback_cam.setVisible(False)

        root.addWidget(gb_rend)

        root.addSpacing(8)

        # -- 4. VariationMGR Integration ----------------------------------
        gb_var = QtWidgets.QGroupBox("4. VariationMGR Integration")
        var_lay = QtWidgets.QVBoxLayout(gb_var)
        var_lay.setContentsMargins(16, 12, 16, 12)
        var_lay.setSpacing(8)

        self.chk_use_variations = QtWidgets.QCheckBox(
            "Use VariationMGR scene data"
        )
        var_lay.addWidget(self.chk_use_variations)

        lbl_hint = QtWidgets.QLabel(
            "When enabled, camera mode and output naming are driven by the "
            "VariationManagerData embedded in each scene file.\n"
            "If no data is found the Fallback Camera Mode above is used.\n"
            "Use 'Assign JSON' in the queue to override per-scene variation data."
        )
        lbl_hint.setWordWrap(True)
        var_lay.addWidget(lbl_hint)

        root.addWidget(gb_var)

        root.addSpacing(8)

        # -- 5. Format Configuration --------------------------------------
        gb_fmt = QtWidgets.QGroupBox("5. Format Configuration")
        fmt_lay = QtWidgets.QVBoxLayout(gb_fmt)
        fmt_lay.setContentsMargins(16, 12, 16, 12)
        fmt_lay.setSpacing(8)

        fmt_lay.addWidget(QtWidgets.QLabel("Format:"))
        self.cmb_ext = QtWidgets.QComboBox()
        self.cmb_ext.addItems(["jpg", "png", "tif", "exr"])
        fmt_lay.addWidget(self.cmb_ext)

        fmt_lay.addWidget(QtWidgets.QLabel("Bit Depth:"))
        self.cmb_depth = QtWidgets.QComboBox()
        fmt_lay.addWidget(self.cmb_depth)

        self.chk_alpha = QtWidgets.QCheckBox("Save Alpha Channel")
        self.chk_re = QtWidgets.QCheckBox("Save Render Elements")
        fmt_lay.addWidget(self.chk_alpha)
        fmt_lay.addWidget(self.chk_re)

        root.addWidget(gb_fmt)

        root.addSpacing(8)

        # -- 6. Color Management ------------------------------------------
        gb_ocio = QtWidgets.QGroupBox("6. Color Management (Output Only)")
        ocio_lay = QtWidgets.QVBoxLayout(gb_ocio)
        ocio_lay.setContentsMargins(16, 12, 16, 12)
        ocio_lay.setSpacing(8)

        # OCIO config path row.
        ocio_lay.addWidget(QtWidgets.QLabel("OCIO Config:"))
        ocio_path_row = QtWidgets.QHBoxLayout()
        self.le_ocio_config = QtWidgets.QLineEdit()
        self.le_ocio_config.setPlaceholderText("Auto-detected from 3ds Max install")
        self.le_ocio_config.setReadOnly(True)
        self.btn_ocio_browse = QtWidgets.QPushButton("...")
        self.btn_ocio_browse.setFixedWidth(28)
        self.btn_ocio_reset = QtWidgets.QPushButton("Auto")
        self.btn_ocio_reset.setFixedWidth(40)
        ocio_path_row.addWidget(self.le_ocio_config, stretch=1)
        ocio_path_row.addWidget(self.btn_ocio_browse)
        ocio_path_row.addWidget(self.btn_ocio_reset)
        ocio_lay.addLayout(ocio_path_row)

        sep = QtWidgets.QFrame()
        sep.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        ocio_lay.addWidget(sep)
        ocio_lay.addSpacing(4)

        self.chk_ocio_override = QtWidgets.QCheckBox("Override Output Transform")
        ocio_lay.addWidget(self.chk_ocio_override)

        ocio_lay.addWidget(QtWidgets.QLabel("Output Mode:"))
        self.cmb_ocio_mode = QtWidgets.QComboBox()
        self.cmb_ocio_mode.addItems([
            "Display / View Transform",
            "Color Space Conversion",
        ])
        ocio_lay.addWidget(self.cmb_ocio_mode)

        self.lbl_display = QtWidgets.QLabel("Display:")
        ocio_lay.addWidget(self.lbl_display)
        self.cmb_ocio_display = QtWidgets.QComboBox()
        self.cmb_ocio_display.setSizeAdjustPolicy(
            QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToContents
        )
        ocio_lay.addWidget(self.cmb_ocio_display)

        self.lbl_view = QtWidgets.QLabel("View Transform:")
        ocio_lay.addWidget(self.lbl_view)
        self.cmb_ocio_view = QtWidgets.QComboBox()
        self.cmb_ocio_view.setSizeAdjustPolicy(
            QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToContents
        )
        ocio_lay.addWidget(self.cmb_ocio_view)

        self.lbl_target = QtWidgets.QLabel("Target Space:")
        ocio_lay.addWidget(self.lbl_target)
        self.cmb_ocio_target_space = QtWidgets.QComboBox()
        self.cmb_ocio_target_space.setSizeAdjustPolicy(
            QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToContents
        )
        ocio_lay.addWidget(self.cmb_ocio_target_space)

        root.addWidget(gb_ocio)

        root.addSpacing(8)

        # -- 7. Process Log -----------------------------------------------
        gb_log = QtWidgets.QGroupBox("7. Process Log")
        log_lay = QtWidgets.QVBoxLayout(gb_log)
        log_lay.setContentsMargins(16, 12, 16, 12)
        log_lay.setSpacing(8)

        self.txt_log = QtWidgets.QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setMinimumHeight(160)
        log_lay.addWidget(self.txt_log)

        root.addWidget(gb_log)

        root.addSpacing(8)

        # -- Render Buttons -----------------------------------------------
        render_bar = QtWidgets.QHBoxLayout()
        render_bar.setSpacing(8)
        self.btn_submit_server = QtWidgets.QPushButton("SUBMIT TO SERVER")
        self.btn_run_headless = QtWidgets.QPushButton("RUN HEADLESS")
        render_bar.addWidget(self.btn_submit_server, stretch=2)
        render_bar.addWidget(self.btn_run_headless, stretch=1)
        root.addLayout(render_bar)

        root.addSpacing(8)

        # -- Network Server -----------------------------------------------
        gb_net = QtWidgets.QGroupBox("8. Network Server")
        net_lay = QtWidgets.QVBoxLayout(gb_net)
        net_lay.setContentsMargins(16, 12, 16, 12)
        net_lay.setSpacing(8)

        net_lay.addWidget(QtWidgets.QLabel("Server URL:"))
        server_row = QtWidgets.QHBoxLayout()
        self.le_server_url = QtWidgets.QLineEdit()
        self.le_server_url.setPlaceholderText(
            "e.g. http://192.168.1.10:8765  or  http://85.123.45.67:8765"
        )
        self.btn_discover_server = QtWidgets.QPushButton("Discover")
        server_row.addWidget(self.le_server_url, stretch=1)
        server_row.addWidget(self.btn_discover_server)
        net_lay.addLayout(server_row)

        root.addWidget(gb_net)

        root.addSpacing(8)

        # -- 3dsmaxbatch.exe path -----------------------------------------
        gb_exe = QtWidgets.QGroupBox("9. 3dsmaxbatch.exe")
        exe_lay = QtWidgets.QVBoxLayout(gb_exe)
        exe_lay.setContentsMargins(16, 12, 16, 12)
        exe_lay.setSpacing(8)

        exe_row = QtWidgets.QHBoxLayout()
        self.le_max_exe = QtWidgets.QLineEdit()
        self.le_max_exe.setPlaceholderText("Auto-detected")
        self.btn_max_exe_browse = QtWidgets.QPushButton("...")
        self.btn_max_exe_browse.setFixedWidth(28)
        self.btn_max_exe_detect = QtWidgets.QPushButton("Auto")
        self.btn_max_exe_detect.setFixedWidth(40)
        exe_row.addWidget(self.le_max_exe, stretch=1)
        exe_row.addWidget(self.btn_max_exe_browse)
        exe_row.addWidget(self.btn_max_exe_detect)
        exe_lay.addLayout(exe_row)

        root.addWidget(gb_exe)

        root.addStretch()

    # =================================================================
    # SIGNAL CONNECTIONS
    # =================================================================

    def _connect_signals(self):
        self.btn_add.clicked.connect(self.add_files)
        self.btn_assign_json.clicked.connect(self._assign_var_json)
        self.btn_remove.clicked.connect(self.remove_files)
        self.btn_clear.clicked.connect(self.clear_files)
        self.btn_browse.clicked.connect(self.browse_path)
        self.tree_widget.customContextMenuRequested.connect(self.show_queue_menu)

        self.btn_submit_server.clicked.connect(self.submit_to_server)
        self.btn_run_headless.clicked.connect(self.run_headless)
        self.btn_discover_server.clicked.connect(self.discover_server)

        self.btn_max_exe_browse.clicked.connect(self._browse_max_exe)
        self.btn_max_exe_detect.clicked.connect(self._auto_detect_max_exe)

        self.btn_ocio_browse.clicked.connect(self._browse_ocio_config)
        self.btn_ocio_reset.clicked.connect(self._reset_ocio_config)

        self.chk_override_settings.toggled.connect(
            lambda v: self.widget_settings.setVisible(v)
        )
        self.cmb_mode.currentIndexChanged.connect(
            lambda i: self.le_fallback_cam.setVisible(i == 2)
        )
        self.chk_ocio_override.stateChanged.connect(self.toggle_ocio_ui)
        self.cmb_ocio_mode.currentIndexChanged.connect(self.update_ocio_visibility)
        self.cmb_ocio_display.currentIndexChanged.connect(self.update_ocio_views)

        self.cmb_ext.currentIndexChanged.connect(self.on_format_changed)
        self.cmb_depth.currentIndexChanged.connect(self.save_current_format_state)
        self.chk_alpha.stateChanged.connect(self.save_current_format_state)

        # Headless runner signals.
        self.runner.log_message.connect(self.log)
        self.runner.finished.connect(self._on_headless_finished)

    # =================================================================
    # LOGGING
    # =================================================================

    def log(self, msg):
        # Screen-only: the file record is the render core's job (it writes the
        # shared batchrender.log in the output folder); writing UI chatter to a
        # second file just duplicated the same lines with different timestamps.
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        self.txt_log.append(line)
        self.txt_log.moveCursor(QtGui.QTextCursor.MoveOperation.End)
        QtCore.QCoreApplication.processEvents()

    # =================================================================
    # FORMAT
    # =================================================================

    def on_format_changed(self):
        self.cmb_depth.blockSignals(True)
        self.chk_alpha.blockSignals(True)
        fmt = self.cmb_ext.currentText()
        self.cmb_depth.clear()
        if fmt == "jpg":
            self.cmb_depth.addItem("8-bit (Fixed)")
            self.cmb_depth.setEnabled(False)
            self.chk_alpha.setVisible(False)
        elif fmt in ("png", "tif"):
            self.cmb_depth.addItems(["8-bit", "16-bit"])
            self.cmb_depth.setEnabled(True)
            self.chk_alpha.setVisible(True)
        elif fmt == "exr":
            self.cmb_depth.addItems(
                ["16-bit (Half)", "32-bit (Float)", "32-bit (Integer)"]
            )
            self.cmb_depth.setEnabled(True)
            self.chk_alpha.setVisible(True)
        prefs = self.format_prefs.get(fmt, [0, True])
        self.cmb_depth.setCurrentIndex(
            min(prefs[0], self.cmb_depth.count() - 1)
        )
        self.chk_alpha.setChecked(prefs[1])
        self.cmb_depth.blockSignals(False)
        self.chk_alpha.blockSignals(False)

        # Max's pngio writes render-element PNGs with an invalid IHDR ("PNG
        # Library Internal Error" per element, 0-byte files) regardless of bit
        # depth. The beauty pass is unaffected. Disable render elements for PNG
        # so the option can't be armed for a format that can't honour it.
        re_ok = fmt != "png"
        self.chk_re.setEnabled(re_ok)
        if re_ok:
            self.chk_re.setToolTip("")
        else:
            self.chk_re.setChecked(False)
            self.chk_re.setToolTip(
                "Render elements aren't supported for PNG output.\n"
                "Use EXR or TIFF to save passes.")

        self.save_ini()

    def save_current_format_state(self):
        fmt = self.cmb_ext.currentText()
        self.format_prefs[fmt] = [
            self.cmb_depth.currentIndex(),
            self.chk_alpha.isChecked(),
        ]
        self.save_ini()

    # =================================================================
    # OCIO
    # =================================================================

    def _init_ocio(self):
        displays = self.ocio.get_displays()
        self.cmb_ocio_display.addItems(displays)
        if "sRGB" in displays:
            self.cmb_ocio_display.setCurrentText("sRGB")
        self.update_ocio_views()
        self.cmb_ocio_target_space.addItems(self.ocio.get_colorspaces())
        self.le_ocio_config.setText(self.ocio.config_path or "(built-in defaults)")

    def update_ocio_views(self):
        self.cmb_ocio_view.clear()
        display = self.cmb_ocio_display.currentText()
        views = self.ocio.get_views(display)
        self.cmb_ocio_view.addItems(views)
        if "ACES 1.0 SDR-video" in views:
            self.cmb_ocio_view.setCurrentText("ACES 1.0 SDR-video")

    def toggle_ocio_ui(self):
        is_ovr = self.chk_ocio_override.isChecked()
        self.cmb_ocio_mode.setEnabled(is_ovr)
        self.update_ocio_visibility()

    def update_ocio_visibility(self):
        is_ovr = self.chk_ocio_override.isChecked()
        is_display = self.cmb_ocio_mode.currentIndex() == 0
        self.lbl_display.setVisible(is_display)
        self.cmb_ocio_display.setVisible(is_display)
        self.lbl_view.setVisible(is_display)
        self.cmb_ocio_view.setVisible(is_display)
        self.cmb_ocio_display.setEnabled(is_ovr and is_display)
        self.cmb_ocio_view.setEnabled(is_ovr and is_display)
        self.lbl_target.setVisible(not is_display)
        self.cmb_ocio_target_space.setVisible(not is_display)
        self.cmb_ocio_target_space.setEnabled(is_ovr and not is_display)

    def _browse_ocio_config(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Select OCIO Config", "", "OCIO Configs (*.ocio);;All Files (*)"
        )
        if path:
            self.ocio.reload(path)
            self._refresh_ocio_combos()
            self.save_ini()

    def _reset_ocio_config(self):
        self.ocio.reload("")
        self._refresh_ocio_combos()
        self.save_ini()

    def _refresh_ocio_combos(self):
        self.le_ocio_config.setText(
            self.ocio.config_path or "(built-in defaults)"
        )
        prev_display = self.cmb_ocio_display.currentText()
        prev_view = self.cmb_ocio_view.currentText()
        prev_space = self.cmb_ocio_target_space.currentText()

        self.cmb_ocio_display.clear()
        self.cmb_ocio_display.addItems(self.ocio.get_displays())
        if prev_display:
            idx = self.cmb_ocio_display.findText(prev_display)
            if idx >= 0:
                self.cmb_ocio_display.setCurrentIndex(idx)
        self.update_ocio_views()
        if prev_view:
            idx = self.cmb_ocio_view.findText(prev_view)
            if idx >= 0:
                self.cmb_ocio_view.setCurrentIndex(idx)

        self.cmb_ocio_target_space.clear()
        self.cmb_ocio_target_space.addItems(self.ocio.get_colorspaces())
        if prev_space:
            idx = self.cmb_ocio_target_space.findText(prev_space)
            if idx >= 0:
                self.cmb_ocio_target_space.setCurrentIndex(idx)

    # =================================================================
    # FILE QUEUE
    # =================================================================

    def _make_tree_item(self, path, var_json=""):
        """Create a QTreeWidgetItem for one file entry."""
        item = QtWidgets.QTreeWidgetItem()
        item.setText(0, os.path.basename(path))
        item.setToolTip(0, path)
        self._refresh_tree_item(item, var_json)
        return item

    def _refresh_tree_item(self, item, var_json):
        """Update the Variation Data column of a tree item."""
        if var_json:
            item.setText(1, os.path.basename(var_json))
            item.setToolTip(1, var_json)
        else:
            item.setText(1, "(scene data)")
            item.setToolTip(1, "Uses VariationManagerData embedded in the .max file")

    def add_files(self):
        files, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "Select .max Files", "", "Max Files (*.max)"
        )
        existing_paths = {e["path"] for e in self.file_entries}
        added = False
        for f in files:
            f = f.replace("\\", "/")
            if f not in existing_paths:
                entry = {"path": f, "var_json": ""}
                self.file_entries.append(entry)
                self.tree_widget.addTopLevelItem(self._make_tree_item(f))
                existing_paths.add(f)
                added = True
        if added:
            self.save_ini()

    def remove_files(self):
        selected_ids = {id(item) for item in self.tree_widget.selectedItems()}
        if not selected_ids:
            return
        to_remove = [
            i for i in range(self.tree_widget.topLevelItemCount())
            if id(self.tree_widget.topLevelItem(i)) in selected_ids
        ]
        for i in reversed(to_remove):
            self.tree_widget.takeTopLevelItem(i)
            self.file_entries.pop(i)
        self.save_ini()

    def clear_files(self):
        self.file_entries = []
        self.tree_widget.clear()
        self.save_ini()

    def _assign_var_json(self):
        """Open a JSON file dialog and assign it to all selected queue entries."""
        selected_rows = self._selected_row_indices()
        if not selected_rows:
            self.log("Select one or more scenes in the queue first.")
            return
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Select Variation Data JSON", "", "JSON Files (*.json)"
        )
        if not path:
            return
        path = path.replace("\\", "/")
        for i in selected_rows:
            self.file_entries[i]["var_json"] = path
            self._refresh_tree_item(self.tree_widget.topLevelItem(i), path)
        self.save_ini()

    def _clear_var_json(self):
        """Clear the variation JSON assignment for all selected queue entries."""
        selected_rows = self._selected_row_indices()
        if not selected_rows:
            return
        for i in selected_rows:
            self.file_entries[i]["var_json"] = ""
            self._refresh_tree_item(self.tree_widget.topLevelItem(i), "")
        self.save_ini()

    def _selected_row_indices(self):
        """Return the top-level indices of currently selected tree items, in order."""
        selected_ids = {id(item) for item in self.tree_widget.selectedItems()}
        return [
            i for i in range(self.tree_widget.topLevelItemCount())
            if id(self.tree_widget.topLevelItem(i)) in selected_ids
        ]

    def browse_path(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Output Folder")
        if d:
            self.le_path.setText(d.replace("\\", "/"))
            self.save_ini()

    def show_queue_menu(self, pos):
        item = self.tree_widget.itemAt(pos)
        if not item:
            return
        menu = QtWidgets.QMenu()
        act_show        = menu.addAction("Show in Explorer")
        menu.addSeparator()
        act_assign_json = menu.addAction("Assign Variation JSON...")
        act_clear_json  = menu.addAction("Clear Variation JSON")
        menu.addSeparator()
        act_remove      = menu.addAction("Remove from Queue")
        action = menu.exec(QtGui.QCursor.pos())

        if action == act_show:
            path = item.toolTip(0).replace("/", "\\")
            if os.path.exists(path):
                subprocess.Popen(["explorer", "/select,", path])
            else:
                self.log(f"File not found: {path}")
        elif action == act_assign_json:
            if not item.isSelected():
                self.tree_widget.clearSelection()
                item.setSelected(True)
            self._assign_var_json()
        elif action == act_clear_json:
            if not item.isSelected():
                self.tree_widget.clearSelection()
                item.setSelected(True)
            self._clear_var_json()
        elif action == act_remove:
            if not item.isSelected():
                self.tree_widget.clearSelection()
                item.setSelected(True)
            self.remove_files()

    # =================================================================
    # 3dsmaxbatch.exe
    # =================================================================

    def set_max_batch_exe(self, path):
        self.le_max_exe.setText(path)
        self.runner.set_max_batch_exe(path)

    def _browse_max_exe(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select 3dsmaxbatch.exe",
            "",
            "Executables (*.exe);;All Files (*)",
        )
        if path:
            self.set_max_batch_exe(path)
            self.save_ini()

    def _auto_detect_max_exe(self):
        exe = max_discovery.find_3dsmaxbatch_exe()
        if exe:
            self.set_max_batch_exe(exe)
            self.log(f"Found: {exe}")
            self.save_ini()
        else:
            self.log("3dsmaxbatch.exe not found on this machine.")

    # =================================================================
    # INI PERSISTENCE
    # =================================================================

    def _setup_autosave(self):
        for sig in [
            self.le_path.editingFinished,
            self.cmb_version.currentIndexChanged,
            self.cmb_mode.currentIndexChanged,
            self.le_fallback_cam.editingFinished,
            self.chk_override_settings.stateChanged,
            self.spn_res.valueChanged,
            self.spn_passes.valueChanged,
            self.spn_noise.valueChanged,
            self.chk_use_variations.stateChanged,
            self.chk_re.stateChanged,
            self.chk_ocio_override.stateChanged,
            self.cmb_ocio_mode.currentIndexChanged,
            self.cmb_ocio_display.currentIndexChanged,
            self.cmb_ocio_view.currentIndexChanged,
            self.cmb_ocio_target_space.currentIndexChanged,
            self.le_server_url.editingFinished,
            self.le_max_exe.editingFinished,
        ]:
            sig.connect(self.save_ini)

    def save_ini(self):
        if getattr(self, "_is_initializing", False):
            return
        ini = ini_persistence.get_ini_path()
        settings = {
            "Settings": {
                "OutputPath": self.le_path.text(),
                "LastFormat": self.cmb_ext.currentText(),
                "LastVersion": self.cmb_version.currentText(),
                "RenderMode": str(self.cmb_mode.currentIndex()),
                "FallbackCameraName": self.le_fallback_cam.text().strip(),
                "OverrideSettings": str(self.chk_override_settings.isChecked()),
                "Resolution": str(self.spn_res.value()),
                "PassLimit": str(self.spn_passes.value()),
                "NoiseLimit": str(self.spn_noise.value()),
                "UseVariations": str(self.chk_use_variations.isChecked()),
                "SaveRE": str(self.chk_re.isChecked()),
            },
            "OCIO": {
                "Override": str(self.chk_ocio_override.isChecked()),
                "Mode": str(self.cmb_ocio_mode.currentIndex()),
                "Display": self.cmb_ocio_display.currentText(),
                "View": self.cmb_ocio_view.currentText(),
                "TargetSpace": self.cmb_ocio_target_space.currentText(),
                "ConfigPath": self.ocio.config_path or "",
            },
            "Network": {
                "ServerUrl": self.le_server_url.text().strip(),
            },
            "Headless": {
                "MaxBatchExe": self.le_max_exe.text().strip(),
            },
        }
        ini_persistence.save_settings(ini, settings)
        ini_persistence.save_file_entries(ini, self.file_entries)
        ini_persistence.save_format_prefs(ini, self.format_prefs)

    def load_ini(self):
        self.file_entries = []
        self.tree_widget.clear()
        ini = ini_persistence.get_ini_path()
        cfg = ini_persistence.load_settings(ini)

        def _get(section, key, fallback=""):
            return cfg.get(section, key, fallback=fallback)

        def _int(section, key, default):
            try:
                return int(_get(section, key, str(default)))
            except ValueError:
                return default

        def _float(section, key, default):
            try:
                return float(_get(section, key, str(default)))
            except ValueError:
                return default

        def _bool(section, key):
            return _get(section, key, "False") == "True"

        self.le_path.setText(_get("Settings", "OutputPath"))
        self.spn_res.setValue(_int("Settings", "Resolution", 4000))
        self.spn_passes.setValue(_int("Settings", "PassLimit", 75))
        self.spn_noise.setValue(_float("Settings", "NoiseLimit", 6.0))
        self.cmb_mode.setCurrentIndex(_int("Settings", "RenderMode", 0))
        self.le_fallback_cam.setText(_get("Settings", "FallbackCameraName"))
        self.le_fallback_cam.setVisible(self.cmb_mode.currentIndex() == 2)
        self.chk_override_settings.setChecked(_bool("Settings", "OverrideSettings"))
        self.chk_use_variations.setChecked(_bool("Settings", "UseVariations"))
        self.chk_re.setChecked(_bool("Settings", "SaveRE"))
        self.chk_ocio_override.setChecked(_bool("OCIO", "Override"))
        self.cmb_ocio_mode.setCurrentIndex(_int("OCIO", "Mode", 0))

        if _bool("OCIO", "Override"):
            d = _get("OCIO", "Display")
            if d:
                self.cmb_ocio_display.setCurrentText(d)
            self.update_ocio_views()
            v = _get("OCIO", "View")
            if v:
                self.cmb_ocio_view.setCurrentText(v)
            t = _get("OCIO", "TargetSpace")
            if t:
                self.cmb_ocio_target_space.setCurrentText(t)

        # Reload OCIO config from INI-stored custom path.
        ocio_path = _get("OCIO", "ConfigPath")
        if ocio_path and ocio_path != self.ocio.config_path:
            self.ocio.reload(ocio_path)
            self._refresh_ocio_combos()

        last_fmt = _get("Settings", "LastFormat")
        if last_fmt:
            idx = self.cmb_ext.findText(last_fmt)
            if idx >= 0:
                self.cmb_ext.setCurrentIndex(idx)

        last_ver = _get("Settings", "LastVersion")
        if last_ver:
            idx = self.cmb_version.findText(last_ver)
            if idx >= 0:
                self.cmb_version.setCurrentIndex(idx)

        self.format_prefs = ini_persistence.load_format_prefs(
            ini, self.format_prefs
        )

        self.file_entries = ini_persistence.load_file_entries(ini)
        for entry in self.file_entries:
            self.tree_widget.addTopLevelItem(
                self._make_tree_item(entry["path"], entry.get("var_json", ""))
            )

        server_url = _get("Network", "ServerUrl")
        if server_url:
            self.le_server_url.setText(server_url.strip())

        max_exe = _get("Headless", "MaxBatchExe")
        if max_exe:
            self.le_max_exe.setText(max_exe.strip())
            self.runner.set_max_batch_exe(max_exe.strip())

        if self.file_entries:
            self.log(f"Loaded {len(self.file_entries)} file(s) from config.")

    # =================================================================
    # JOB REQUEST BUILDING
    # =================================================================

    def build_job_request(self, file_list=None):
        files = [
            (path or "").replace("\\", "/")
            for path in (file_list or [])
            if str(path).strip()
        ]
        request = {
            "schema_version": schema.JOB_SCHEMA_VERSION,
            "request_id": datetime.datetime.now().strftime("%Y%m%d%H%M%S"),
            "scene_file": "",
            "max_files": files,
            "load_scene": True,
            "output": {
                "folder": self.le_path.text(),
                "version": self.cmb_version.currentText(),
                "format": self.cmb_ext.currentText(),
                "depth_index": self.cmb_depth.currentIndex(),
                "save_alpha": self.chk_alpha.isChecked(),
                "save_render_elements": self.chk_re.isChecked(),
            },
            "render": {
                "override_settings": self.chk_override_settings.isChecked(),
                "resolution": self.spn_res.value(),
                "pass_limit": self.spn_passes.value(),
                "noise_limit": self.spn_noise.value(),
                "use_variations": self.chk_use_variations.isChecked(),
                "fallback_camera_mode": (
                    ("all", "active", "by_name")[self.cmb_mode.currentIndex()]
                ),
                "fallback_camera_name": self.le_fallback_cam.text().strip(),
            },
            "ocio": {
                "override": self.chk_ocio_override.isChecked(),
                "mode": (
                    "display_view"
                    if self.cmb_ocio_mode.currentIndex() == 0
                    else "color_space"
                ),
                "display": self.cmb_ocio_display.currentText(),
                "view": self.cmb_ocio_view.currentText(),
                "target_space": self.cmb_ocio_target_space.currentText(),
            },
        }
        return schema.normalize_job_request(request)

    def _load_variation_override(self, var_json_path, scene_label=""):
        """Read and parse a variation JSON file. Returns the dict or None on error."""
        if not var_json_path:
            return None
        if not os.path.isfile(var_json_path):
            self.log(f"  Warning: Variation JSON not found for {scene_label or var_json_path}")
            return None
        try:
            with open(var_json_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            self.log(f"  Warning: Could not parse variation JSON for {scene_label or var_json_path}: {e}")
            return None

    def _collect_scene_jobs(self, entries):
        """Build a flat list of scene_jobs with per-entry variation overrides applied."""
        all_jobs = []
        for entry in entries:
            path     = entry["path"]
            var_json = entry.get("var_json", "")
            request  = self.build_job_request([path])
            if var_json:
                override = self._load_variation_override(var_json, os.path.basename(path))
                if override is not None:
                    request["variation_override"] = override
            all_jobs.extend(schema.build_scene_jobs(request))
        return all_jobs

    # =================================================================
    # SUBMIT TO SERVER
    # =================================================================

    def discover_server(self):
        self.log("Discovering server on local network...")
        found = server_client.discover_server()
        if found:
            self.le_server_url.setText(found)
            self.save_ini()
            self.log(f"Discovered server: {found}")
            return
        self.log("No server response found via broadcast discovery.")

    def submit_to_server(self):
        if not self.file_entries:
            self.log("Error: No files in the batch queue.")
            return

        server_url = self.le_server_url.text().strip()
        if not server_url:
            self.log(
                "Error: Server URL is empty. Enter a URL or click Discover."
            )
            return

        try:
            health = server_client.check_health(server_url)
            self.log(f"Server online: {health.get('status', 'ok')}")
        except Exception as e:
            self.log(f"Server unreachable: {e}")
            return

        total_jobs = 0
        for entry in self.file_entries:
            request = self.build_job_request([entry["path"]])
            request["request_id"] = ""
            var_json = entry.get("var_json", "")
            if var_json:
                override = self._load_variation_override(
                    var_json, os.path.basename(entry["path"])
                )
                if override is not None:
                    request["variation_override"] = override
            try:
                response  = server_client.submit_job(server_url, request)
                job_ids   = response.get("job_ids", []) or []
                total_jobs += len(job_ids)
                json_tag  = " [+JSON]" if var_json else ""
                self.log(
                    f"  {os.path.basename(entry['path'])}{json_tag}: "
                    f"{len(job_ids)} job(s) queued"
                )
            except Exception as e:
                self.log(f"  {os.path.basename(entry['path'])}: Submit failed: {e}")

        self.log(f"Submitted {total_jobs} total job(s) to server.")

    # =================================================================
    # HEADLESS RENDER
    # =================================================================

    def run_headless(self):
        if not self.file_entries:
            self.log("Error: No files in the batch queue.")
            return

        max_exe = self.le_max_exe.text().strip()
        if max_exe:
            self.runner.set_max_batch_exe(max_exe)

        if not self.runner.max_batch_exe or not os.path.isfile(
            self.runner.max_batch_exe
        ):
            self.log(
                "Error: 3dsmaxbatch.exe not found. "
                "Set the path in section 9 or click Auto."
            )
            return

        scene_jobs = self._collect_scene_jobs(self.file_entries)
        if not scene_jobs:
            self.log("No render jobs resolved from request.")
            return

        self.log(f"=== Headless Batch: {len(scene_jobs)} scene(s) ===")
        self.btn_run_headless.setEnabled(False)
        self.btn_submit_server.setEnabled(False)
        self.runner.run_batch(scene_jobs)

    def _on_headless_finished(self, result):
        self.btn_run_headless.setEnabled(True)
        self.btn_submit_server.setEnabled(True)
        status = result.get("status", "")
        completed = result.get("completed_scenes", 0)
        total = result.get("total_scenes", 0)
        self.log(f"=== {status.title()}: {completed}/{total} scene(s) ===")

    # =================================================================
    # COMPATIBILITY
    # =================================================================

    @property
    def file_list(self):
        """Plain list of paths — for any external callers that expect the old shape."""
        return [e["path"] for e in self.file_entries]

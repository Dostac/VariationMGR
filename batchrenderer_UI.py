import os
import json
import datetime
from PySide6 import QtWidgets, QtCore, QtGui
import pymxs
import qtmax
import batchrenderer_core as brcore
import job_schema as schema
from NetworkRender.shared import server_client


rt = pymxs.runtime

# Core rendering execution lives in batchrenderer_core.
# Shared job contract lives in job_schema.


# =============================================================================
# MAIN DIALOG
# =============================================================================
class BatchRenderDialog(QtWidgets.QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_initializing = True

        self.setWindowTitle("VB Batch Renderer")
        self.resize(720, 1300)
        self.setWindowFlags(QtCore.Qt.WindowType.Tool)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
        qtmax.DisableMaxAcceleratorsOnFocus(self, True)

        # Each entry: {"path": str, "var_json": str}
        self.file_entries = []
        self.format_prefs = {
            "jpg": [0, False],
            "png": [0, True],
            "tif": [1, True],
            "exr": [0, True],
        }

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        outer.addWidget(scroll)

        _container = QtWidgets.QWidget()
        scroll.setWidget(_container)

        main_layout = QtWidgets.QVBoxLayout(_container)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(16)

        def _ctrl(w, min_h=40):
            w.setMinimumHeight(min_h)
            return w

        def _group_vbox(group):
            lay = QtWidgets.QVBoxLayout(group)
            lay.setContentsMargins(16, 16, 16, 16)
            lay.setSpacing(8)
            return lay

        def _group_form(group):
            lay = QtWidgets.QFormLayout(group)
            lay.setContentsMargins(16, 16, 16, 16)
            lay.setHorizontalSpacing(10)
            lay.setVerticalSpacing(8)
            lay.setLabelAlignment(
                QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter)
            return lay

        # ------------------------------------------------------------------
        # 1. BATCH QUEUE
        # ------------------------------------------------------------------
        gb_files = QtWidgets.QGroupBox("Batch Queue")
        fl = _group_vbox(gb_files)

        self.tree_widget = QtWidgets.QTreeWidget()
        self.tree_widget.setColumnCount(2)
        self.tree_widget.setHeaderLabels(["Scene File", "Variation Data"])
        hdr = self.tree_widget.header()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.tree_widget.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree_widget.setMinimumHeight(120)
        self.tree_widget.setContextMenuPolicy(
            QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree_widget.customContextMenuRequested.connect(self.show_queue_menu)

        file_bar = QtWidgets.QHBoxLayout()
        file_bar.setSpacing(8)
        self.btn_add        = _ctrl(QtWidgets.QPushButton("＋ Add Files"))
        self.btn_assign_json = _ctrl(QtWidgets.QPushButton("📄 Assign JSON"))
        self.btn_remove     = _ctrl(QtWidgets.QPushButton("− Remove"))
        self.btn_clear      = _ctrl(QtWidgets.QPushButton("✕ Clear"))
        file_bar.addWidget(self.btn_add)
        file_bar.addWidget(self.btn_assign_json)
        file_bar.addWidget(self.btn_remove)
        file_bar.addStretch()
        file_bar.addWidget(self.btn_clear)

        fl.addWidget(self.tree_widget)
        fl.addLayout(file_bar)
        main_layout.addWidget(gb_files)

        # ------------------------------------------------------------------
        # 2. OUTPUT & NAMING
        # ------------------------------------------------------------------
        gb_out   = QtWidgets.QGroupBox("Output & Naming")
        out_form = _group_form(gb_out)

        path_row = QtWidgets.QWidget()
        path_box = QtWidgets.QHBoxLayout(path_row)
        path_box.setContentsMargins(0, 0, 0, 0)
        path_box.setSpacing(6)
        self.le_path    = _ctrl(QtWidgets.QLineEdit())
        self.btn_browse = _ctrl(QtWidgets.QPushButton("📂 Browse..."))
        path_box.addWidget(self.le_path)
        path_box.addWidget(self.btn_browse)

        self.cmb_version = _ctrl(QtWidgets.QComboBox())
        self.cmb_version.addItem("None")
        self.cmb_version.addItems([f"V{i}" for i in range(1, 11)])

        out_form.addRow("Folder:",  path_row)
        out_form.addRow("Version:", self.cmb_version)
        main_layout.addWidget(gb_out)

        # ------------------------------------------------------------------
        # 3. RENDER SETTINGS
        # ------------------------------------------------------------------
        gb_rend   = QtWidgets.QGroupBox("Render Settings")
        rend_vbox = _group_vbox(gb_rend)

        self.chk_override_settings = QtWidgets.QCheckBox(
            "Override scene render settings")
        rend_vbox.addWidget(self.chk_override_settings)

        # Collapsible block - visible only when override is on
        self.widget_settings = QtWidgets.QWidget()
        settings_form = QtWidgets.QFormLayout(self.widget_settings)
        settings_form.setContentsMargins(16, 4, 0, 0)
        settings_form.setHorizontalSpacing(10)
        settings_form.setVerticalSpacing(8)

        self.spn_res    = _ctrl(QtWidgets.QSpinBox())
        self.spn_res.setRange(100, 30000)
        self.spn_res.setValue(4000)
        self.spn_res.setSuffix(" px")

        self.spn_passes = _ctrl(QtWidgets.QSpinBox())
        self.spn_passes.setRange(0, 10000)
        self.spn_passes.setValue(75)

        self.spn_noise  = _ctrl(QtWidgets.QDoubleSpinBox())
        self.spn_noise.setRange(0.0, 100.0)
        self.spn_noise.setValue(6.0)
        self.spn_noise.setSingleStep(0.5)
        self.spn_noise.setSuffix("%")

        settings_form.addRow("Longest Side:", self.spn_res)
        settings_form.addRow("Pass Limit:",   self.spn_passes)
        settings_form.addRow("Noise Limit:",  self.spn_noise)
        rend_vbox.addWidget(self.widget_settings)
        self.widget_settings.setVisible(False)

        rend_vbox.addWidget(QtWidgets.QLabel("Fallback Camera Mode:"))
        self.cmb_mode = _ctrl(QtWidgets.QComboBox())
        self.cmb_mode.addItems(["Render All Cameras", "Render Active View Only"])
        rend_vbox.addWidget(self.cmb_mode)

        main_layout.addWidget(gb_rend)

        # ------------------------------------------------------------------
        # 4. VARIATIONMGR INTEGRATION
        # ------------------------------------------------------------------
        gb_var   = QtWidgets.QGroupBox("VariationMGR Integration")
        var_vbox = _group_vbox(gb_var)

        self.chk_use_variations = QtWidgets.QCheckBox(
            "Use VariationMGR scene data")
        var_vbox.addWidget(self.chk_use_variations)

        lbl_var_hint = QtWidgets.QLabel(
            "When enabled, camera mode and output naming are driven by the\n"
            "VariationManagerData embedded in each scene file.\n"
            "If no data is found the Fallback Camera Mode above is used.\n"
            "Use '📄 Assign JSON' in the queue to override per-scene variation data.")
        lbl_var_hint.setStyleSheet("color: #888; font-style: italic;")
        lbl_var_hint.setWordWrap(True)
        var_vbox.addWidget(lbl_var_hint)

        main_layout.addWidget(gb_var)

        # ------------------------------------------------------------------
        # 5. FORMAT
        # ------------------------------------------------------------------
        gb_fmt   = QtWidgets.QGroupBox("Format Configuration")
        fmt_form = _group_form(gb_fmt)

        self.cmb_ext   = _ctrl(QtWidgets.QComboBox())
        self.cmb_ext.addItems(["jpg", "png", "tif", "exr"])

        self.cmb_depth = _ctrl(QtWidgets.QComboBox())

        self.chk_alpha = QtWidgets.QCheckBox("Save Alpha Channel")
        self.chk_re    = QtWidgets.QCheckBox("Save Render Elements")

        fmt_form.addRow("Format:",    self.cmb_ext)
        fmt_form.addRow("Bit Depth:", self.cmb_depth)
        fmt_form.addRow("",           self.chk_alpha)
        fmt_form.addRow("",           self.chk_re)
        main_layout.addWidget(gb_fmt)

        # ------------------------------------------------------------------
        # 6. COLOR MANAGEMENT
        # ------------------------------------------------------------------
        gb_ocio   = QtWidgets.QGroupBox("Color Management (Output Only)")
        ocio_vbox = _group_vbox(gb_ocio)

        self.chk_ocio_override = QtWidgets.QCheckBox("Override Output Transform")
        self.form_ocio = QtWidgets.QFormLayout()
        self.form_ocio.setHorizontalSpacing(10)
        self.form_ocio.setVerticalSpacing(8)
        self.form_ocio.setLabelAlignment(
            QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter)

        self.cmb_ocio_mode = _ctrl(QtWidgets.QComboBox())
        self.cmb_ocio_mode.addItems(["Display / View Transform",
                                     "Color Space Conversion"])

        self.cmb_ocio_display      = self._wide_combo()
        self.cmb_ocio_view         = self._wide_combo()
        self.cmb_ocio_target_space = self._wide_combo()

        self.lbl_display = QtWidgets.QLabel("Display:")
        self.lbl_view    = QtWidgets.QLabel("View Transform:")
        self.lbl_target  = QtWidgets.QLabel("Target Space:")

        self.form_ocio.addRow("Output Mode:",   self.cmb_ocio_mode)
        self.form_ocio.addRow(self.lbl_display, self.cmb_ocio_display)
        self.form_ocio.addRow(self.lbl_view,    self.cmb_ocio_view)
        self.form_ocio.addRow(self.lbl_target,  self.cmb_ocio_target_space)

        ocio_vbox.addWidget(self.chk_ocio_override)
        ocio_vbox.addLayout(self.form_ocio)
        main_layout.addWidget(gb_ocio)

        # ------------------------------------------------------------------
        # 7. LOG
        # ------------------------------------------------------------------
        gb_log   = QtWidgets.QGroupBox("Process Log")
        log_vbox = _group_vbox(gb_log)
        self.txt_log = QtWidgets.QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setStyleSheet(
            "background-color: #222; color: #DDD; "
            "font-family: Consolas, monospace; font-size: 11px;")
        self.txt_log.setMinimumHeight(160)
        log_vbox.addWidget(self.txt_log)
        main_layout.addWidget(gb_log)

        # ------------------------------------------------------------------
        # RENDER BUTTONS
        # ------------------------------------------------------------------
        render_bar = QtWidgets.QHBoxLayout()
        render_bar.setSpacing(8)
        self.btn_render_current = QtWidgets.QPushButton("RENDER CURRENT SCENE")
        self.btn_render_current.setMinimumHeight(48)
        self.btn_render = QtWidgets.QPushButton("▶  START BATCH RENDER")
        self.btn_render.setMinimumHeight(48)
        self.btn_submit_server = QtWidgets.QPushButton("⇪  SUBMIT TO SERVER")
        self.btn_submit_server.setMinimumHeight(48)
        render_bar.addWidget(self.btn_render_current)
        render_bar.addWidget(self.btn_render)
        render_bar.addWidget(self.btn_submit_server)
        main_layout.addLayout(render_bar)

        network_row = QtWidgets.QHBoxLayout()
        network_row.setSpacing(8)
        self.le_server_url = _ctrl(QtWidgets.QLineEdit(), min_h=34)
        self.le_server_url.setPlaceholderText("Server URL (e.g. http://192.168.1.10:8765)")
        self.btn_discover_server = _ctrl(QtWidgets.QPushButton("Discover Server"), min_h=34)
        network_row.addWidget(QtWidgets.QLabel("Network Server:"))
        network_row.addWidget(self.le_server_url, 1)
        network_row.addWidget(self.btn_discover_server)
        main_layout.addLayout(network_row)

        # ------------------------------------------------------------------
        # CONNECTIONS
        # ------------------------------------------------------------------
        self.btn_add.clicked.connect(self.add_files)
        self.btn_assign_json.clicked.connect(self._assign_var_json)
        self.btn_remove.clicked.connect(self.remove_files)
        self.btn_clear.clicked.connect(self.clear_files)
        self.btn_browse.clicked.connect(self.browse_path)
        self.btn_render.clicked.connect(self.run_batch)
        self.btn_render_current.clicked.connect(self.render_current_scene)
        self.btn_submit_server.clicked.connect(self.submit_to_server)
        self.btn_discover_server.clicked.connect(self.discover_server)

        self.chk_override_settings.toggled.connect(
            lambda v: self.widget_settings.setVisible(v))

        self.chk_ocio_override.stateChanged.connect(self.toggle_ocio_ui)
        self.cmb_ocio_mode.currentIndexChanged.connect(self.update_ocio_visibility)
        self.cmb_ocio_display.currentIndexChanged.connect(self.update_ocio_views)

        self.cmb_ext.currentIndexChanged.connect(self.on_format_changed)
        self.cmb_depth.currentIndexChanged.connect(self.save_current_format_state)
        self.chk_alpha.stateChanged.connect(self.save_current_format_state)

        self.renderer = brcore.BatchRendererCore(log_cb=self.log)
        self.last_job_json = ""

        # ------------------------------------------------------------------
        # STARTUP
        # ------------------------------------------------------------------
        self.log("Initializing...")
        self._init_ocio()
        self._sync_ocio_with_scene()
        self.toggle_ocio_ui()
        self.load_ini()
        self.on_format_changed()
        self._setup_autosave()
        self.log(f"Config: {self.get_ini_path()}")
        self.log("Ready.")
        self._is_initializing = False

    # -----------------------------------------------------------------------
    # SMALL HELPERS
    # -----------------------------------------------------------------------

    def _wide_combo(self):
        c = QtWidgets.QComboBox()
        c.setSizeAdjustPolicy(
            QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToContents)
        c.view().setMinimumWidth(300)
        return c

    def closeEvent(self, event):
        self.save_ini()
        event.accept()

    def _setup_autosave(self):
        for sig in [
            self.le_path.editingFinished,
            self.cmb_version.currentIndexChanged,
            self.cmb_mode.currentIndexChanged,
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
        ]:
            sig.connect(self.save_ini)

    # -----------------------------------------------------------------------
    # LOGGING
    # -----------------------------------------------------------------------

    def log(self, msg):
        ts   = datetime.datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        self.txt_log.append(line)
        self.txt_log.moveCursor(QtGui.QTextCursor.MoveOperation.End)
        QtCore.QCoreApplication.processEvents()
        out_dir = self.le_path.text()
        if out_dir and os.path.exists(out_dir):
            try:
                with open(os.path.join(out_dir, "batch_render_log.txt"), "a") as f:
                    f.write(line + "\n")
            except Exception:
                pass

    # -----------------------------------------------------------------------
    # FORMAT
    # -----------------------------------------------------------------------

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
                ["16-bit (Half)", "32-bit (Float)", "32-bit (Integer)"])
            self.cmb_depth.setEnabled(True)
            self.chk_alpha.setVisible(True)
        prefs = self.format_prefs.get(fmt, [0, True])
        self.cmb_depth.setCurrentIndex(
            min(prefs[0], self.cmb_depth.count() - 1))
        self.chk_alpha.setChecked(prefs[1])
        self.cmb_depth.blockSignals(False)
        self.chk_alpha.blockSignals(False)
        self.save_ini()

    def save_current_format_state(self):
        fmt = self.cmb_ext.currentText()
        self.format_prefs[fmt] = [
            self.cmb_depth.currentIndex(), self.chk_alpha.isChecked()]
        self.save_ini()

    # -----------------------------------------------------------------------
    # OCIO
    # -----------------------------------------------------------------------

    def _init_ocio(self):
        try:
            cpm = rt.ColorPipelineMgr
            if not cpm:
                return
            displays = list(cpm.GetDisplayList())
            self.cmb_ocio_display.addItems(displays)
            if "sRGB" in displays:
                self.cmb_ocio_display.setCurrentText("sRGB")
            self.update_ocio_views()
            io_spaces = list(cpm.GetFileIOColorSpaceList())
            self.cmb_ocio_target_space.addItems(io_spaces)
        except Exception:
            self.chk_ocio_override.setEnabled(False)

    def update_ocio_views(self):
        self.cmb_ocio_view.clear()
        cpm = rt.ColorPipelineMgr
        curr_disp = self.cmb_ocio_display.currentText()
        if not cpm or not curr_disp:
            return

        views = list(cpm.GetViewList(curr_disp))

        # Some OCIO configs expose ACES views under a different display; include them as fallback.
        if "ACES 1.0 SDR-video" not in views:
            try:
                for disp in list(cpm.GetDisplayList()):
                    for view in list(cpm.GetViewList(disp)):
                        if view not in views:
                            views.append(view)
            except Exception:
                pass

        self.cmb_ocio_view.addItems(views)
        if "ACES 1.0 SDR-video" in views:
            self.cmb_ocio_view.setCurrentText("ACES 1.0 SDR-video")

    def _sync_ocio_with_scene(self):
        try:
            data = list(rt.getSceneOcioSettings())
            mode_str = data[0]
            if mode_str == "#DisplayViewtransform":
                self.cmb_ocio_mode.setCurrentIndex(0)
                self.cmb_ocio_display.setCurrentText(data[2])
                self.update_ocio_views()
                self.cmb_ocio_view.setCurrentText(data[3])
            elif mode_str == "#ColorSpaceConversion":
                self.cmb_ocio_mode.setCurrentIndex(1)
                self.cmb_ocio_target_space.setCurrentText(data[1])
        except Exception as e:
            self.log(f"OCIO Sync Error: {e}")

    def toggle_ocio_ui(self):
        is_ovr = self.chk_ocio_override.isChecked()
        if not is_ovr:
            self._sync_ocio_with_scene()
        self.cmb_ocio_mode.setEnabled(is_ovr)
        self.update_ocio_visibility()

    def update_ocio_visibility(self):
        is_ovr     = self.chk_ocio_override.isChecked()
        is_display = (self.cmb_ocio_mode.currentIndex() == 0)
        self.lbl_display.setVisible(is_display)
        self.cmb_ocio_display.setVisible(is_display)
        self.lbl_view.setVisible(is_display)
        self.cmb_ocio_view.setVisible(is_display)
        self.cmb_ocio_display.setEnabled(is_ovr and is_display)
        self.cmb_ocio_view.setEnabled(is_ovr and is_display)
        self.lbl_target.setVisible(not is_display)
        self.cmb_ocio_target_space.setVisible(not is_display)
        self.cmb_ocio_target_space.setEnabled(is_ovr and not is_display)

    # -----------------------------------------------------------------------
    # FILES / QUEUE
    # -----------------------------------------------------------------------

    def _make_tree_item(self, path, var_json=""):
        """Create a QTreeWidgetItem for one file entry."""
        item = QtWidgets.QTreeWidgetItem()
        item.setText(0, os.path.basename(path))
        item.setToolTip(0, path)
        self._refresh_tree_item(item, var_json)
        return item

    def _refresh_tree_item(self, item, var_json):
        """Update the Variation Data column of a tree item from var_json path."""
        if var_json:
            item.setText(1, os.path.basename(var_json))
            item.setToolTip(1, var_json)
        else:
            item.setText(1, "(scene data)")
            item.setToolTip(1, "Uses VariationManagerData embedded in the .max file")

    def add_files(self):
        files, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "Select .max Files", "", "Max Files (*.max)")
        added = False
        existing_paths = {e["path"] for e in self.file_entries}
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
        selected = self.tree_widget.selectedItems()
        if not selected:
            return
        selected_set = set(id(item) for item in selected)
        # Remove entries and tree items in reverse index order.
        to_remove = []
        for i in range(self.tree_widget.topLevelItemCount()):
            item = self.tree_widget.topLevelItem(i)
            if id(item) in selected_set:
                to_remove.append(i)
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
        selected = self.tree_widget.selectedItems()
        if not selected:
            self.log("Select one or more scenes in the queue first.")
            return
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Select Variation Data JSON", "", "JSON Files (*.json)")
        if not path:
            return
        path = path.replace("\\", "/")
        selected_rows = self._selected_row_indices()
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

    # -----------------------------------------------------------------------
    # INI
    # -----------------------------------------------------------------------

    def get_ini_path(self):
        return os.path.join(
            rt.getDir(rt.Name("userScripts")), "vb_batch_renderer.ini")

    def save_ini(self):
        if getattr(self, "_is_initializing", False):
            return
        ini = self.get_ini_path()
        S = "Settings"
        rt.setINISetting(ini, S, "OutputPath",      self.le_path.text())
        rt.setINISetting(ini, S, "LastFormat",       self.cmb_ext.currentText())
        rt.setINISetting(ini, S, "LastVersion",      self.cmb_version.currentText())
        rt.setINISetting(ini, S, "RenderMode",       str(self.cmb_mode.currentIndex()))
        rt.setINISetting(ini, S, "OverrideSettings", str(self.chk_override_settings.isChecked()))
        rt.setINISetting(ini, S, "Resolution",       str(self.spn_res.value()))
        rt.setINISetting(ini, S, "PassLimit",        str(self.spn_passes.value()))
        rt.setINISetting(ini, S, "NoiseLimit",       str(self.spn_noise.value()))
        rt.setINISetting(ini, S, "UseVariations",    str(self.chk_use_variations.isChecked()))
        rt.setINISetting(ini, S, "SaveRE",           str(self.chk_re.isChecked()))
        O = "OCIO"
        rt.setINISetting(ini, O, "Override",    str(self.chk_ocio_override.isChecked()))
        rt.setINISetting(ini, O, "Mode",        str(self.cmb_ocio_mode.currentIndex()))
        rt.setINISetting(ini, O, "Display",     self.cmb_ocio_display.currentText())
        rt.setINISetting(ini, O, "View",        self.cmb_ocio_view.currentText())
        rt.setINISetting(ini, O, "TargetSpace", self.cmb_ocio_target_space.currentText())
        rt.setINISetting(ini, "Network", "ServerUrl", self.le_server_url.text().strip())
        for fmt, prefs in self.format_prefs.items():
            rt.setINISetting(ini, "FormatPrefs", fmt,
                             f"{prefs[0]},{1 if prefs[1] else 0}")
        rt.setINISetting(ini, "Meta", "Count", str(len(self.file_entries)))
        for i, entry in enumerate(self.file_entries):
            rt.setINISetting(ini, "MaxFiles", f"File{i+1}", entry["path"])
            rt.setINISetting(ini, "VarJson",  f"File{i+1}", entry.get("var_json", ""))

    def load_ini(self):
        self.file_entries = []
        self.tree_widget.clear()
        ini = self.get_ini_path()

        def _int(s, k, default):
            v = rt.getINISetting(ini, s, k)
            try:    return int(v) if v else default
            except: return default

        def _float(s, k, default):
            v = rt.getINISetting(ini, s, k)
            try:    return float(v) if v else default
            except: return default

        def _bool(s, k):
            return rt.getINISetting(ini, s, k) == "True"

        path = rt.getINISetting(ini, "Settings", "OutputPath")
        self.le_path.setText(
            path if path else
            rt.getDir(rt.Name("renderoutput")).replace("\\", "/"))

        for fmt in ("jpg", "png", "tif", "exr"):
            val = rt.getINISetting(ini, "FormatPrefs", fmt)
            if val:
                parts = val.split(",")
                if len(parts) == 2:
                    self.format_prefs[fmt] = [int(parts[0]), parts[1] == "1"]

        self.spn_res.setValue(    _int("Settings",   "Resolution",  4000))
        self.spn_passes.setValue( _int("Settings",   "PassLimit",   75))
        self.spn_noise.setValue( _float("Settings",  "NoiseLimit",  6.0))
        self.cmb_mode.setCurrentIndex(_int("Settings", "RenderMode", 0))
        self.chk_override_settings.setChecked(_bool("Settings", "OverrideSettings"))
        self.chk_use_variations.setChecked(   _bool("Settings", "UseVariations"))
        self.chk_re.setChecked(               _bool("Settings", "SaveRE"))
        self.chk_ocio_override.setChecked(    _bool("OCIO",     "Override"))
        self.cmb_ocio_mode.setCurrentIndex(   _int("OCIO",      "Mode", 0))

        if _bool("OCIO", "Override"):
            d = rt.getINISetting(ini, "OCIO", "Display")
            if d: self.cmb_ocio_display.setCurrentText(d)
            self.update_ocio_views()
            v = rt.getINISetting(ini, "OCIO", "View")
            if v: self.cmb_ocio_view.setCurrentText(v)
            t = rt.getINISetting(ini, "OCIO", "TargetSpace")
            if t: self.cmb_ocio_target_space.setCurrentText(t)

        last_fmt = rt.getINISetting(ini, "Settings", "LastFormat")
        if last_fmt:
            idx = self.cmb_ext.findText(last_fmt)
            if idx >= 0: self.cmb_ext.setCurrentIndex(idx)

        last_ver = rt.getINISetting(ini, "Settings", "LastVersion")
        if last_ver:
            idx = self.cmb_version.findText(last_ver)
            if idx >= 0: self.cmb_version.setCurrentIndex(idx)

        cnt = _int("Meta", "Count", 0)
        for i in range(1, cnt + 1):
            f = rt.getINISetting(ini, "MaxFiles", f"File{i}")
            if f:
                var_json = rt.getINISetting(ini, "VarJson", f"File{i}") or ""
                entry = {"path": f, "var_json": var_json}
                self.file_entries.append(entry)
                self.tree_widget.addTopLevelItem(self._make_tree_item(f, var_json))

        server_url = rt.getINISetting(ini, "Network", "ServerUrl")
        if server_url:
            self.le_server_url.setText(server_url.strip())
        if cnt:
            self.log(f"Loaded {len(self.file_entries)} file(s) from config.")

    # -----------------------------------------------------------------------
    # QUEUE CONTEXT MENU
    # -----------------------------------------------------------------------

    def show_queue_menu(self, pos):
        item = self.tree_widget.itemAt(pos)
        if not item:
            return
        menu = QtWidgets.QMenu()
        act_open        = menu.addAction("Open Scene")
        menu.addSeparator()
        act_assign_json = menu.addAction("Assign Variation JSON...")
        act_clear_json  = menu.addAction("Clear Variation JSON")
        menu.addSeparator()
        act_remove      = menu.addAction("Remove from Queue")
        action = menu.exec(QtGui.QCursor.pos())

        if action == act_open:
            path = item.toolTip(0)
            if os.path.exists(path):
                self.log(f"Opening: {os.path.basename(path)}")
                try:
                    rt.loadMaxFile(path, useFileUnits=True, quiet=True)
                    self.log("  Scene loaded.")
                except Exception as e:
                    self.log(f"  Error opening scene: {e}")
            else:
                self.log(f"File not found: {path}")
        elif action == act_assign_json:
            self._assign_var_json()
        elif action == act_clear_json:
            self._clear_var_json()
        elif action == act_remove:
            # Ensure the right-clicked item is in the selection, then remove all selected.
            if not item.isSelected():
                self.tree_widget.clearSelection()
                item.setSelected(True)
            self.remove_files()

    # -----------------------------------------------------------------------
    # JOB BUILDING
    # -----------------------------------------------------------------------

    def build_job_request(self, file_list=None, load_scene=True):
        files = [
            (path or "").replace("\\", "/")
            for path in (file_list or [])
            if str(path).strip()
        ]

        request = {
            "schema_version": schema.JOB_SCHEMA_VERSION,
            "request_id": datetime.datetime.now().strftime("%Y%m%d%H%M%S"),
            "scene_file": files[0] if (files and not load_scene) else "",
            "max_files": files if load_scene else [],
            "load_scene": bool(load_scene),
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
                    "all" if self.cmb_mode.currentIndex() == 0 else "active"
                ),
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

    def build_job_request_json(self, file_list=None, load_scene=True, pretty=False):
        request = self.build_job_request(file_list=file_list, load_scene=load_scene)
        self.last_job_json = schema.job_request_to_json(request, pretty=pretty)
        return self.last_job_json

    def _load_variation_override(self, var_json_path, scene_label=""):
        """Read and parse a variation JSON file. Returns the dict or None on error."""
        if not var_json_path:
            return None
        if not os.path.isfile(var_json_path):
            label = scene_label or var_json_path
            self.log(f"  Warning: Variation JSON not found for {label}: {var_json_path}")
            return None
        try:
            with open(var_json_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            label = scene_label or var_json_path
            self.log(f"  Warning: Could not parse variation JSON for {label}: {e}")
            return None

    def _collect_scene_jobs(self, entries, load_scene=True):
        """Build a flat list of scene_jobs from file entries with per-entry variation overrides."""
        all_jobs = []
        for entry in entries:
            path     = entry["path"]
            var_json = entry.get("var_json", "")
            request  = self.build_job_request([path], load_scene=load_scene)
            if var_json:
                override = self._load_variation_override(var_json, os.path.basename(path))
                if override is not None:
                    request["variation_override"] = override
            all_jobs.extend(schema.build_scene_jobs(request))
        return all_jobs

    # -----------------------------------------------------------------------
    # LOCAL RENDERING
    # -----------------------------------------------------------------------

    def _run_job_request(self, request):
        """Run a pre-built (already normalized) job request locally. Used for single-scene renders."""
        out_dir = request["output"]["folder"]
        if not out_dir:
            self.log("Error: No output folder set.")
            return
        if not os.path.exists(out_dir):
            os.makedirs(out_dir, exist_ok=True)
        scene_jobs = schema.build_scene_jobs(request)
        self._run_scene_jobs(scene_jobs)

    def _run_scene_jobs(self, scene_jobs):
        """Execute a pre-built list of scene_jobs locally with a progress dialog."""
        if not scene_jobs:
            self.log("No render jobs resolved from request.")
            return

        out_dir = self.le_path.text()
        if not out_dir:
            self.log("Error: No output folder set.")
            return
        if not os.path.exists(out_dir):
            os.makedirs(out_dir, exist_ok=True)

        prog = QtWidgets.QProgressDialog(
            "Rendering...", "Abort", 0, len(scene_jobs), self)
        prog.setWindowModality(QtCore.Qt.WindowModality.WindowModal)
        prog.show()

        aborted = False
        for file_idx, scene_job in enumerate(scene_jobs):
            if prog.wasCanceled():
                aborted = True
                self.log("Aborted.")
                break

            scene_file = scene_job.get("scene_file", "")
            label = os.path.basename(scene_file) if scene_file else "Current scene"
            prog.setLabelText(label)
            prog.setValue(file_idx)
            self.renderer.render_scene_job(scene_job)

        prog.setValue(len(scene_jobs))
        if not aborted:
            self.log("=== Complete ===")

    def render_current_scene(self):
        if not rt.maxFileName:
            self.log("Error: Current scene is unsaved. Save the .max file first.")
            return
        scene_path = (rt.maxFilePath + rt.maxFileName).replace("\\", "/")
        if not scene_path.strip("/") or not os.path.isfile(scene_path):
            self.log("Error: No scene is currently open.")
            return
        self.log("=== Render Current Scene ===")
        request = self.build_job_request([scene_path], load_scene=False)
        self.last_job_json = schema.job_request_to_json(request)
        self._run_job_request(request)

    # -----------------------------------------------------------------------
    # BATCH RENDER
    # -----------------------------------------------------------------------

    def run_batch(self):
        if not self.file_entries:
            self.log("No files queued.")
            return
        self.log(f"=== Batch Start: {len(self.file_entries)} file(s) ===")
        self.save_ini()
        scene_jobs = self._collect_scene_jobs(self.file_entries, load_scene=True)
        if scene_jobs:
            self.last_job_json = schema.job_request_to_json(
                self.build_job_request([e["path"] for e in self.file_entries]))
        self._run_scene_jobs(scene_jobs)

    def _get_submit_entries(self):
        """Return entries for network submission: queued entries, or current scene as fallback."""
        if self.file_entries:
            return list(self.file_entries)
        if not rt.maxFileName:
            return []
        scene_path = (rt.maxFilePath + rt.maxFileName).replace("\\", "/")
        if not scene_path.strip("/") or not os.path.isfile(scene_path):
            return []
        return [{"path": scene_path, "var_json": ""}]

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
        entries = self._get_submit_entries()
        if not entries:
            self.log("Error: No queued files and no saved current scene to submit.")
            return

        server_url = self.le_server_url.text().strip()
        if not server_url:
            self.log("Error: Server URL is empty. Enter URL or click Discover Server.")
            return

        try:
            health = server_client.check_health(server_url)
            self.log(f"Server online: {health.get('status', 'ok')}")
        except Exception as e:
            self.log(f"Server unreachable: {e}")
            return

        total_jobs = 0
        for entry in entries:
            request = self.build_job_request([entry["path"]], load_scene=True)
            request["request_id"] = ""
            var_json = entry.get("var_json", "")
            if var_json:
                override = self._load_variation_override(var_json, os.path.basename(entry["path"]))
                if override is not None:
                    request["variation_override"] = override
            self.last_job_json = schema.job_request_to_json(request)
            try:
                response  = server_client.submit_job(server_url, request)
                job_ids   = response.get("job_ids", []) or []
                total_jobs += len(job_ids)
                json_tag  = f" [+JSON]" if var_json else ""
                self.log(
                    f"  {os.path.basename(entry['path'])}{json_tag}: "
                    f"{len(job_ids)} job(s) queued"
                )
            except Exception as e:
                self.log(f"  {os.path.basename(entry['path'])}: Submit failed: {e}")

        self.log(f"Submitted {total_jobs} total job(s) to server.")

    # Compatibility: keeps old internal call sites functional.
    def _render_files(self, file_list, load_files=True):
        entries = [{"path": p, "var_json": ""} for p in file_list]
        scene_jobs = self._collect_scene_jobs(entries, load_scene=load_files)
        self._run_scene_jobs(scene_jobs)

    # Compatibility: expose file_list as a plain list of paths for any external callers.
    @property
    def file_list(self):
        return [e["path"] for e in self.file_entries]


# =============================================================================
# ENTRY POINT
# =============================================================================
def main():
    max_win = qtmax.GetQMaxMainWindow()
    app = QtWidgets.QApplication.instance()
    prev = getattr(app, '_vb_batch_renderer', None)
    if prev is not None:
        try:
            prev.close()
            prev.deleteLater()
        except Exception:
            pass
    win = BatchRenderDialog(parent=max_win)
    app._vb_batch_renderer = win
    win.show()


if __name__ == "__main__":
    main()

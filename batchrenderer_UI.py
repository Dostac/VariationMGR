import os
import json
import datetime
from PySide6 import QtWidgets, QtCore, QtGui
import pymxs
import qtmax
import batchrenderer_core as brcore
import job_schema as schema
import variation_core as vcore
from NetworkRender.shared import server_client


rt = pymxs.runtime

# Core rendering execution lives in batchrenderer_core.
# Shared job contract lives in job_schema.


class _NoWheelFilter(QtCore.QObject):
    """Swallows wheel events so a widget doesn't scrub its value when the user
    is trying to scroll the surrounding panel. Installed on combo and spin boxes."""
    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.Type.Wheel:
            event.ignore()
            return True
        return False


# =============================================================================
# MAIN DIALOG
# =============================================================================
class BatchRenderDialog(QtWidgets.QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_initializing = True

        self.setWindowTitle("VB Batch Renderer")
        self.setMinimumWidth(1000)
        self.resize(1000, 1300)
        self.setWindowFlags(QtCore.Qt.WindowType.Tool)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
        qtmax.DisableMaxAcceleratorsOnFocus(self, True)

        self._no_wheel_filter = _NoWheelFilter(self)

        # Each entry: {"path": str, "var_json": str, "csv_file": str, "split_size": int,
        #              "row_range_expr": str,
        #              # Legacy mirror for one release; written alongside row_range_expr.
        #              "row_start": int, "row_end": int}
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
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
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
        self.tree_widget.setColumnCount(3)
        self.tree_widget.setHeaderLabels(["Scene File", "Variation Data", "CSV Override"])
        hdr = self.tree_widget.header()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.tree_widget.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree_widget.setMinimumHeight(120)
        self.tree_widget.setContextMenuPolicy(
            QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree_widget.customContextMenuRequested.connect(self.show_queue_menu)

        file_bar = QtWidgets.QHBoxLayout()
        file_bar.setSpacing(8)
        self.btn_add         = _ctrl(QtWidgets.QPushButton("＋ Add Files"))
        self.btn_add_current = _ctrl(QtWidgets.QPushButton("＋ Add Current"))
        self.btn_add_current.setToolTip(
            "Add the currently open scene file to the queue.")
        self.btn_assign_csv  = _ctrl(QtWidgets.QPushButton("📊 Assign CSV"))
        self.btn_split_jobs  = _ctrl(QtWidgets.QPushButton("✂ Split for Server"))
        self.btn_split_jobs.setToolTip(
            "Split variation rows into multiple server jobs.\n"
            "Requires a Variation JSON or CSV override to be assigned first.")
        self.btn_split_jobs.setEnabled(False)
        self.btn_remove     = _ctrl(QtWidgets.QPushButton("− Remove"))
        self.btn_clear      = _ctrl(QtWidgets.QPushButton("✕ Clear"))
        file_bar.addWidget(self.btn_add)
        file_bar.addWidget(self.btn_add_current)
        file_bar.addWidget(self.btn_assign_csv)
        file_bar.addWidget(self.btn_split_jobs)
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
            "Use '📄 Assign JSON' or '📊 Assign CSV' in the queue to override data.")
        lbl_var_hint.setStyleSheet("color: #888; font-style: italic;")
        lbl_var_hint.setWordWrap(True)
        var_vbox.addWidget(lbl_var_hint)

        sep_var = QtWidgets.QFrame()
        sep_var.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        var_vbox.addWidget(sep_var)
        var_vbox.addSpacing(4)

        br_range_btn_row = QtWidgets.QHBoxLayout()
        br_range_btn_row.setSpacing(8)
        br_range_btn_row.addWidget(QtWidgets.QLabel("Row Range (per file):"))
        self.btn_set_range = _ctrl(QtWidgets.QPushButton("📐 Set Range..."))
        self.btn_clear_range = _ctrl(QtWidgets.QPushButton("Clear Range"))
        br_range_btn_row.addWidget(self.btn_set_range)
        br_range_btn_row.addWidget(self.btn_clear_range)
        br_range_btn_row.addStretch()
        var_vbox.addLayout(br_range_btn_row)

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
        self.btn_submit_server.setToolTip(
            "Submit queued files to the network render server.\n"
            "Right-click to preview the JSON / PowerShell payload."
        )
        self.btn_submit_server.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.btn_submit_server.customContextMenuRequested.connect(
            lambda _pos: self._show_submit_payload_preview()
        )
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
        self.btn_add_current.clicked.connect(self.add_current_scene)
        self.btn_assign_csv.clicked.connect(self._assign_csv_override)
        self.btn_split_jobs.clicked.connect(self._split_for_server)
        self.btn_set_range.clicked.connect(self._set_row_range)
        self.btn_clear_range.clicked.connect(self._clear_row_range)
        self.tree_widget.itemSelectionChanged.connect(self._update_queue_button_states)
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
        self._disable_combo_wheel(self)
        self._update_queue_button_states()
        self._is_initializing = False

    # -----------------------------------------------------------------------
    # SMALL HELPERS
    # -----------------------------------------------------------------------

    def _disable_combo_wheel(self, root):
        """Install the no-wheel filter on every QComboBox and spin box under
        `root` so scrolling the panel doesn't scrub their values. A spin box
        wraps an internal QLineEdit that receives the wheel event when the
        cursor is over the number field, so the filter is installed on that
        child too — otherwise scrolling the text area still scrubs the value.
        Idempotent: each widget is marked so re-running on freshly-added
        widgets is safe."""
        if root is None:
            return
        marker = "_br_no_wheel_installed"
        widgets = (root.findChildren(QtWidgets.QComboBox)
                   + root.findChildren(QtWidgets.QAbstractSpinBox))
        for spin in root.findChildren(QtWidgets.QAbstractSpinBox):
            line_edit = spin.lineEdit()
            if line_edit is not None:
                widgets.append(line_edit)
        for widget in widgets:
            if widget.property(marker):
                continue
            widget.installEventFilter(self._no_wheel_filter)
            widget.setProperty(marker, True)

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

    def _make_tree_item(self, path, entry=None):
        """Create a QTreeWidgetItem for one file entry."""
        item = QtWidgets.QTreeWidgetItem()
        item.setText(0, os.path.basename(path))
        item.setToolTip(0, path)
        self._refresh_tree_item(item, entry or {})
        return item

    def _refresh_tree_item(self, item, entry):
        """Update Variation Data and CSV Override columns from an entry dict."""
        var_json   = entry.get("var_json", "")
        csv_file   = entry.get("csv_file", "")
        split_size = entry.get("split_size", 0)
        row_expr   = self._entry_row_expr(entry)

        # Column 1: Variation Data + range/split indicators
        if var_json:
            label = os.path.basename(var_json)
            item.setToolTip(1, var_json)
        else:
            label = "(scene data)"
            item.setToolTip(1, "Uses VariationManagerData embedded in the .max file")
        if row_expr:
            label += f" [{row_expr}]"
        if split_size > 0:
            label += f" [\u2702 {split_size}/job]"
        item.setText(1, label)

        # Column 2: CSV Override
        if csv_file:
            item.setText(2, os.path.basename(csv_file))
            item.setToolTip(2, csv_file)
        else:
            item.setText(2, "")
            item.setToolTip(2, "")

    def add_files(self):
        files, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "Select .max Files", "", "Max Files (*.max)")
        added = False
        existing_paths = {e["path"] for e in self.file_entries}
        for f in files:
            f = f.replace("\\", "/")
            if f not in existing_paths:
                entry = {"path": f, "var_json": "", "csv_file": "", "split_size": 0,
                         "row_range_expr": "", "row_start": 0, "row_end": 0}
                self.file_entries.append(entry)
                self.tree_widget.addTopLevelItem(self._make_tree_item(f, entry))
                existing_paths.add(f)
                added = True
        if added:
            self.save_ini()

    def add_current_scene(self):
        """Add the currently open .max scene to the queue, deduping against
        entries already present. The on-disk file is what renders, so this
        requires the scene to have been saved at least once."""
        if not rt.maxFileName:
            self.log("Current scene is unsaved. Save the .max file first.")
            return
        scene_path = (rt.maxFilePath + rt.maxFileName).replace("\\", "/")
        if not scene_path.strip("/") or not os.path.isfile(scene_path):
            self.log("No scene is currently open.")
            return
        if scene_path in {e["path"] for e in self.file_entries}:
            self.log(f"Already in queue: {os.path.basename(scene_path)}")
            return
        entry = {"path": scene_path, "var_json": "", "csv_file": "", "split_size": 0,
                 "row_range_expr": "", "row_start": 0, "row_end": 0}
        self.file_entries.append(entry)
        self.tree_widget.addTopLevelItem(self._make_tree_item(scene_path, entry))
        self.log(f"Added current scene: {os.path.basename(scene_path)}")
        if rt.getSaveRequired():
            self.log("  Note: scene has unsaved changes — the file on disk will be "
                     "rendered, not the current viewport state.")
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
        selected_rows = self._selected_row_indices()
        default_dir = (os.path.dirname(self.file_entries[selected_rows[0]]["path"])
                       if selected_rows else "")
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Select Variation Data JSON", default_dir, "JSON Files (*.json)")
        if not path:
            return
        path = path.replace("\\", "/")
        selected_rows = self._selected_row_indices()
        for i in selected_rows:
            self.file_entries[i]["var_json"] = path
            self._refresh_tree_item(self.tree_widget.topLevelItem(i), self.file_entries[i])
        self._update_split_button_state()
        self.save_ini()

    def _clear_var_json(self):
        """Clear the variation JSON assignment for all selected queue entries."""
        selected_rows = self._selected_row_indices()
        if not selected_rows:
            return
        for i in selected_rows:
            entry = self.file_entries[i]
            entry["var_json"] = ""
            if not entry.get("csv_file"):
                entry["split_size"] = 0
            self._refresh_tree_item(self.tree_widget.topLevelItem(i), entry)
        self._update_split_button_state()
        self.save_ini()

    def _assign_csv_override(self):
        """Open a CSV file dialog and assign it to all selected queue entries."""
        selected = self.tree_widget.selectedItems()
        if not selected:
            self.log("Select one or more scenes in the queue first.")
            return
        selected_rows = self._selected_row_indices()
        default_dir = (os.path.dirname(self.file_entries[selected_rows[0]]["path"])
                       if selected_rows else "")
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Select CSV Override", default_dir, "CSV Files (*.csv)")
        if not path:
            return
        path = path.replace("\\", "/")
        selected_rows = self._selected_row_indices()
        for i in selected_rows:
            self.file_entries[i]["csv_file"] = path
            self._refresh_tree_item(self.tree_widget.topLevelItem(i), self.file_entries[i])
        self._update_split_button_state()
        self.save_ini()

    def _clear_csv_override(self):
        """Clear the CSV override for all selected queue entries."""
        selected_rows = self._selected_row_indices()
        if not selected_rows:
            return
        for i in selected_rows:
            entry = self.file_entries[i]
            entry["csv_file"] = ""
            if not entry.get("var_json"):
                entry["split_size"] = 0
            self._refresh_tree_item(self.tree_widget.topLevelItem(i), entry)
        self._update_split_button_state()
        self.save_ini()

    def _load_csv_override(self, csv_path, scene_label=""):
        """Read a CSV file and return {"headers": [...], "rows": [[...], ...]} or None."""
        if not csv_path:
            return None
        if not os.path.isfile(csv_path):
            self.log(f"  Warning: CSV override not found for {scene_label}: {csv_path}")
            return None
        try:
            import csv
            with open(csv_path, newline="", encoding="utf-8") as f:
                reader = list(csv.reader(f))
            if not reader:
                return None
            return {"headers": reader[0], "rows": reader[1:]}
        except Exception as e:
            self.log(f"  Warning: Could not parse CSV for {scene_label}: {e}")
            return None

    def _get_override_row_count(self, entry):
        """Return total data-row count from the entry's CSV or JSON override. 0 if unknown."""
        csv_file = entry.get("csv_file", "")
        if csv_file and os.path.isfile(csv_file):
            try:
                import csv
                with open(csv_file, newline="", encoding="utf-8") as f:
                    return max(0, sum(1 for _ in f) - 1)
            except Exception:
                return 0
        var_json = entry.get("var_json", "")
        if var_json and os.path.isfile(var_json):
            try:
                with open(var_json, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return len(data.get("rows", []))
            except Exception:
                return 0
        return 0

    def _split_for_server(self):
        """Configure row-based job splitting for selected queue entries."""
        selected_rows = self._selected_row_indices()
        if not selected_rows:
            self.log("Select one or more scenes in the queue first.")
            return
        # Validate that at least one entry has override data
        valid = [i for i in selected_rows
                 if self.file_entries[i].get("var_json") or self.file_entries[i].get("csv_file")]
        if not valid:
            self.log("Split requires a Variation JSON or CSV override to be assigned first.")
            return
        # Get row count from first valid entry to show context
        first_entry = self.file_entries[valid[0]]
        total_rows = self._get_override_row_count(first_entry)
        prompt = f"Rows per job (total rows: {total_rows}):" if total_rows else "Rows per job:"
        split_size, ok = QtWidgets.QInputDialog.getInt(
            self, "Split Variations for Server", prompt, 10, 1, 99999)
        if not ok:
            return
        for i in valid:
            self.file_entries[i]["split_size"] = split_size
            self._refresh_tree_item(self.tree_widget.topLevelItem(i), self.file_entries[i])
        if total_rows:
            import math
            num_jobs = math.ceil(total_rows / split_size)
            self.log(f"Split configured: {total_rows} rows / {split_size} = {num_jobs} job(s)")
        else:
            self.log(f"Split configured: {split_size} rows per job (row count resolved at submit)")
        self.save_ini()

    def _clear_split(self):
        """Clear job splitting for selected queue entries."""
        selected_rows = self._selected_row_indices()
        if not selected_rows:
            return
        for i in selected_rows:
            self.file_entries[i]["split_size"] = 0
            self._refresh_tree_item(self.tree_widget.topLevelItem(i), self.file_entries[i])
        self.save_ini()

    def _apply_row_range(self, request, expr):
        """Write a row-range expression into a job request, mirroring a legacy
        start/end dict alongside it so older renderer builds still understand
        simple ranges. Pass empty `expr` to leave the request untouched."""
        if not expr:
            return
        request["render_range_expr"] = expr
        legacy_s, legacy_e = self._expr_to_legacy_start_end(expr)
        if legacy_s > 0 or legacy_e > 0:
            request["render_range"] = {"start": legacy_s, "end": legacy_e}

    def _entry_row_expr(self, entry):
        """Resolve the row-range expression for a queue entry, preferring the
        new row_range_expr field and falling back to legacy row_start/end."""
        expr = entry.get("row_range_expr", "")
        if isinstance(expr, str) and expr.strip():
            return expr.strip()
        return vcore.format_row_range_expr(
            entry.get("row_start", 0), entry.get("row_end", 0))

    def _set_row_range(self):
        """Prompt for a row-range expression and assign it to selected entries."""
        selected_rows = self._selected_row_indices()
        if not selected_rows:
            self.log("Select one or more scenes in the queue first.")
            return
        cur_expr = self._entry_row_expr(self.file_entries[selected_rows[0]])
        while True:
            expr, ok = QtWidgets.QInputDialog.getText(
                self, "Row Range",
                "Rows to render (e.g. 2,4-7,10).\n"
                "Header is row 1; data starts at row 2.  Empty = render all rows.",
                QtWidgets.QLineEdit.Normal, cur_expr)
            if not ok:
                return
            expr = expr.strip()
            if not vcore.is_valid_row_range_expr(expr):
                QtWidgets.QMessageBox.warning(
                    self, "Row Range",
                    "Invalid expression. Use comma-separated row numbers or "
                    "ranges, e.g. 2,4-7,10. Row 1 is the header.")
                cur_expr = expr
                continue
            break
        # Mirror to legacy fields for backwards-compat with older renderer builds.
        legacy_start, legacy_end = self._expr_to_legacy_start_end(expr)
        for i in selected_rows:
            self.file_entries[i]["row_range_expr"] = expr
            self.file_entries[i]["row_start"]      = legacy_start
            self.file_entries[i]["row_end"]        = legacy_end
            self._refresh_tree_item(self.tree_widget.topLevelItem(i), self.file_entries[i])
        self.log(
            f"Row range set: '{expr or 'all'}' on {len(selected_rows)} entry(ies).")
        self.save_ini()

    def _expr_to_legacy_start_end(self, expr):
        """Derive (start, end) ints from an expression for legacy mirroring.
        Only meaningful for simple shapes; complex expressions emit (0, 0)."""
        if not expr:
            return 0, 0
        if "," in expr:
            return 0, 0
        if "-" in expr:
            a, _, b = expr.partition("-")
            try:
                s = int(a.strip()) if a.strip() else 0
                e = int(b.strip()) if b.strip() else 0
            except ValueError:
                return 0, 0
            return s, e
        try:
            n = int(expr)
        except ValueError:
            return 0, 0
        return n, n

    def _clear_row_range(self):
        """Clear the row range for selected queue entries."""
        selected_rows = self._selected_row_indices()
        if not selected_rows:
            return
        for i in selected_rows:
            self.file_entries[i]["row_range_expr"] = ""
            self.file_entries[i]["row_start"]      = 0
            self.file_entries[i]["row_end"]        = 0
            self._refresh_tree_item(self.tree_widget.topLevelItem(i), self.file_entries[i])
        self.save_ini()

    def _update_queue_button_states(self):
        """Drive the enabled state of queue action buttons from the current
        selection. Buttons that operate on selected entries are dimmed when
        nothing is selected, since they would otherwise just no-op with a log
        message. The split button has the stricter requirement of selected
        override data, handled by _update_split_button_state."""
        has_selection = bool(self.tree_widget.selectedItems())
        for btn in (self.btn_assign_csv, self.btn_remove,
                    self.btn_set_range, self.btn_clear_range):
            btn.setEnabled(has_selection)
        self._update_split_button_state()

    def _update_split_button_state(self):
        """Enable the split button only if a selected entry has var_json or csv_file."""
        for i in self._selected_row_indices():
            entry = self.file_entries[i]
            if entry.get("var_json") or entry.get("csv_file"):
                self.btn_split_jobs.setEnabled(True)
                return
        self.btn_split_jobs.setEnabled(False)

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
            rt.setINISetting(ini, "MaxFiles",  f"File{i+1}", entry["path"])
            rt.setINISetting(ini, "VarJson",   f"File{i+1}", entry.get("var_json", ""))
            rt.setINISetting(ini, "CsvFile",   f"File{i+1}", entry.get("csv_file", ""))
            rt.setINISetting(ini, "SplitSize", f"File{i+1}", str(entry.get("split_size", 0)))
            rt.setINISetting(ini, "RowRangeExpr", f"File{i+1}", entry.get("row_range_expr", ""))
            # Legacy mirror kept for one release; remove once all clients understand RowRangeExpr.
            rt.setINISetting(ini, "RowStart",     f"File{i+1}", str(entry.get("row_start", 0)))
            rt.setINISetting(ini, "RowEnd",       f"File{i+1}", str(entry.get("row_end",   0)))

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
                var_json   = rt.getINISetting(ini, "VarJson",   f"File{i}") or ""
                csv_file   = rt.getINISetting(ini, "CsvFile",   f"File{i}") or ""
                split_size = _int("SplitSize", f"File{i}", 0)
                row_expr   = rt.getINISetting(ini, "RowRangeExpr", f"File{i}") or ""
                row_start  = _int("RowStart",  f"File{i}", 0)
                row_end    = _int("RowEnd",    f"File{i}", 0)
                # Migrate forward: if the INI predates RowRangeExpr, synthesise one
                # from the legacy ints.
                if not row_expr and (row_start > 0 or row_end > 0):
                    row_expr = vcore.format_row_range_expr(row_start, row_end)
                entry = {"path": f, "var_json": var_json, "csv_file": csv_file,
                         "split_size": split_size, "row_range_expr": row_expr,
                         "row_start": row_start, "row_end": row_end}
                self.file_entries.append(entry)
                self.tree_widget.addTopLevelItem(self._make_tree_item(f, entry))

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
        act_assign_csv  = menu.addAction("Assign CSV Override...")
        act_clear_csv   = menu.addAction("Clear CSV Override")
        menu.addSeparator()
        act_set_range   = menu.addAction("Set Row Range...")
        act_clear_range = menu.addAction("Clear Row Range")
        menu.addSeparator()
        act_split       = menu.addAction("Split Variations for Server...")
        act_clear_split = menu.addAction("Clear Split")
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
        elif action == act_assign_csv:
            self._assign_csv_override()
        elif action == act_clear_csv:
            self._clear_csv_override()
        elif action == act_set_range:
            self._set_row_range()
        elif action == act_clear_range:
            self._clear_row_range()
        elif action == act_split:
            self._split_for_server()
        elif action == act_clear_split:
            self._clear_split()
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
        """Build a flat list of scene_jobs from file entries with per-entry overrides."""
        all_jobs = []
        for entry in entries:
            path      = entry["path"]
            var_json  = entry.get("var_json", "")
            csv_file  = entry.get("csv_file", "")
            row_expr  = self._entry_row_expr(entry)
            request   = self.build_job_request([path], load_scene=load_scene)
            if var_json:
                override = self._load_variation_override(var_json, os.path.basename(path))
                if override is not None:
                    request["variation_override"] = override
            if csv_file:
                csv_data = self._load_csv_override(csv_file, os.path.basename(path))
                if csv_data is not None:
                    request["csv_override"] = csv_data
            self._apply_row_range(request, row_expr)
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

    def _confirm_render(self, action_label, file_count):
        """Show a compact confirmation dialog before starting a render. Returns True if confirmed."""
        fmt        = self.cmb_ext.currentText()
        depth      = self.cmb_depth.currentText()
        alpha      = "ENABLED" if self.chk_alpha.isChecked() else "DISABLED"
        resolution = self.spn_res.value()
        variation  = "Enabled" if self.chk_use_variations.isChecked() else "Disabled"
        folder     = self.le_path.text().strip() or "(not set)"

        if action_label == "current":
            header = "This will render the current scene file."
        elif action_label == "submit":
            header = f"This will submit {file_count} job(s) to the server."
        else:
            header = f"This will render {file_count} file(s) in batch mode."

        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("Confirm Render")
        dlg.setMinimumWidth(420)
        layout = QtWidgets.QVBoxLayout(dlg)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 16, 20, 16)

        layout.addWidget(QtWidgets.QLabel(header))

        sep = QtWidgets.QFrame()
        sep.setFrameShape(QtWidgets.QFrame.HLine)
        layout.addWidget(sep)

        form = QtWidgets.QFormLayout()
        form.setSpacing(6)
        form.addRow("Variation:",  QtWidgets.QLabel(variation))
        form.addRow("Resolution:", QtWidgets.QLabel(f"{resolution} px"))
        form.addRow("Format:",     QtWidgets.QLabel(f"{fmt}  ({depth}, alpha {alpha})"))
        layout.addLayout(form)

        sep2 = QtWidgets.QFrame()
        sep2.setFrameShape(QtWidgets.QFrame.HLine)
        layout.addWidget(sep2)

        lbl_folder_title = QtWidgets.QLabel("OUTPUT FOLDER:")
        font = lbl_folder_title.font()
        font.setPointSize(font.pointSize() + 3)
        font.setBold(True)
        lbl_folder_title.setFont(font)
        layout.addWidget(lbl_folder_title)

        lbl_folder = QtWidgets.QLabel(folder)
        lbl_folder.setWordWrap(True)
        font2 = lbl_folder.font()
        font2.setPointSize(font2.pointSize() + 2)
        lbl_folder.setFont(font2)
        layout.addWidget(lbl_folder)

        btns = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        layout.addWidget(btns)

        return dlg.exec() == QtWidgets.QDialog.Accepted

    def render_current_scene(self):
        if not rt.maxFileName:
            self.log("Error: Current scene is unsaved. Save the .max file first.")
            return
        scene_path = (rt.maxFilePath + rt.maxFileName).replace("\\", "/")
        if not scene_path.strip("/") or not os.path.isfile(scene_path):
            self.log("Error: No scene is currently open.")
            return
        if not self._confirm_render("current", 1):
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
        if not self._confirm_render("batch", len(self.file_entries)):
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
        return [{"path": scene_path, "var_json": "", "csv_file": "", "split_size": 0,
                 "row_range_expr": "", "row_start": 0, "row_end": 0}]

    def discover_server(self):
        self.log("Discovering server on local network...")
        found = server_client.discover_server()
        if found:
            self.le_server_url.setText(found)
            self.save_ini()
            self.log(f"Discovered server: {found}")
            return
        self.log("No server response found via broadcast discovery.")

    def _build_submit_requests(self):
        """Return [(label, request_dict), ...] that submit_to_server would POST.
        Mirrors submit_to_server's request construction without contacting the server."""
        import math, copy
        out = []
        for entry in self._get_submit_entries():
            basename = os.path.basename(entry["path"])
            request = self.build_job_request([entry["path"]], load_scene=True)
            request["request_id"] = ""

            var_json = entry.get("var_json", "")
            if var_json:
                override = self._load_variation_override(var_json, basename)
                if override is not None:
                    request["variation_override"] = override

            csv_file = entry.get("csv_file", "")
            if csv_file:
                csv_data = self._load_csv_override(csv_file, basename)
                if csv_data is not None:
                    request["csv_override"] = csv_data

            row_expr = self._entry_row_expr(entry)
            self._apply_row_range(request, row_expr)

            split_size = entry.get("split_size", 0)
            if split_size > 0:
                row_count = self._get_override_row_count(entry)
                if row_count > 0:
                    num_chunks = math.ceil(row_count / split_size)
                    for chunk_idx in range(num_chunks):
                        # Chunk boundaries are simple table-row ranges; emit as expr
                        # and as the legacy dict so older renderers still slice.
                        chunk_start = chunk_idx * split_size + 2
                        chunk_end   = min((chunk_idx + 1) * split_size + 1, row_count + 1)
                        chunk_req   = copy.deepcopy(request)
                        chunk_req["render_range_expr"] = f"{chunk_start}-{chunk_end}"
                        chunk_req["render_range"]      = {"start": chunk_start, "end": chunk_end}
                        chunk_req["request_id"]        = ""
                        out.append((f"{basename}  (chunk {chunk_idx+1}/{num_chunks})", chunk_req))
                    continue

            out.append((basename, request))
        return out

    def _show_submit_payload_preview(self):
        """Open a read-only dialog showing the JSON / PowerShell payload that would
        be POSTed to the server's /submit endpoint. Triggered by right-click on
        the SUBMIT TO SERVER button."""
        requests = self._build_submit_requests()
        if not requests:
            QtWidgets.QMessageBox.information(
                self, "Submit Payload Preview",
                "No queued files and no saved current scene to preview."
            )
            return

        raw_url    = self.le_server_url.text().strip()
        server_url = server_client.normalize_server_url(raw_url) if raw_url else "http://SERVER:PORT"
        submit_url = f"{server_url}/submit"

        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("Submit Payload Preview")
        dlg.resize(820, 620)

        root = QtWidgets.QVBoxLayout(dlg)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        hdr = QtWidgets.QHBoxLayout()
        hdr.addWidget(QtWidgets.QLabel("Entry:"))
        cmb_entry = QtWidgets.QComboBox()
        for label, _req in requests:
            cmb_entry.addItem(label)
        hdr.addWidget(cmb_entry, stretch=1)
        hdr.addWidget(QtWidgets.QLabel("Format:"))
        cmb_fmt = QtWidgets.QComboBox()
        cmb_fmt.addItems(["JSON", "PowerShell"])
        hdr.addWidget(cmb_fmt)
        root.addLayout(hdr)
        self._disable_combo_wheel(dlg)

        lbl_url = QtWidgets.QLabel(f"POST  {submit_url}")
        lbl_url.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        root.addWidget(lbl_url)

        txt = QtWidgets.QPlainTextEdit()
        txt.setReadOnly(True)
        txt.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        mono = QtGui.QFont("Consolas")
        mono.setStyleHint(QtGui.QFont.Monospace)
        txt.setFont(mono)
        root.addWidget(txt, stretch=1)

        btn_row = QtWidgets.QHBoxLayout()
        btn_copy  = QtWidgets.QPushButton("Copy to Clipboard")
        btn_close = QtWidgets.QPushButton("Close")
        btn_row.addWidget(btn_copy)
        btn_row.addStretch()
        btn_row.addWidget(btn_close)
        root.addLayout(btn_row)

        def render_payload():
            idx = cmb_entry.currentIndex()
            if idx < 0:
                return
            _label, req = requests[idx]
            json_text = schema.job_request_to_json(req, pretty=True)
            if cmb_fmt.currentText() == "JSON":
                txt.setPlainText(json_text)
            else:
                ps = (
                    f"$server  = '{server_url}'\n"
                    f"$payload = @'\n"
                    f"{json_text}\n"
                    f"'@\n"
                    f"Invoke-RestMethod -Uri \"$server/submit\" -Method POST "
                    f"-Body $payload -ContentType 'application/json'\n"
                )
                txt.setPlainText(ps)

        cmb_entry.currentIndexChanged.connect(render_payload)
        cmb_fmt.currentIndexChanged.connect(render_payload)
        btn_copy.clicked.connect(
            lambda: QtWidgets.QApplication.clipboard().setText(txt.toPlainText())
        )
        btn_close.clicked.connect(dlg.accept)
        render_payload()
        dlg.exec()

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

        if not self._confirm_render("submit", len(entries)):
            return

        total_jobs = 0
        for entry in entries:
            basename  = os.path.basename(entry["path"])
            request   = self.build_job_request([entry["path"]], load_scene=True)
            request["request_id"] = ""

            var_json = entry.get("var_json", "")
            if var_json:
                override = self._load_variation_override(var_json, basename)
                if override is not None:
                    request["variation_override"] = override

            csv_file = entry.get("csv_file", "")
            if csv_file:
                csv_data = self._load_csv_override(csv_file, basename)
                if csv_data is not None:
                    request["csv_override"] = csv_data

            row_expr = self._entry_row_expr(entry)
            self._apply_row_range(request, row_expr)

            split_size = entry.get("split_size", 0)
            if split_size > 0:
                row_count = self._get_override_row_count(entry)
                if row_count > 0:
                    import math, copy
                    num_chunks = math.ceil(row_count / split_size)
                    for chunk_idx in range(num_chunks):
                        # Convention: header = row 1, data starts at row 2.
                        chunk_start = chunk_idx * split_size + 2
                        chunk_end = min((chunk_idx + 1) * split_size + 1, row_count + 1)
                        chunk_req = copy.deepcopy(request)
                        chunk_req["render_range_expr"] = f"{chunk_start}-{chunk_end}"
                        chunk_req["render_range"]      = {"start": chunk_start, "end": chunk_end}
                        chunk_req["request_id"] = ""
                        try:
                            response = server_client.submit_job(server_url, chunk_req)
                            job_ids = response.get("job_ids", []) or []
                            total_jobs += len(job_ids)
                        except Exception as e:
                            self.log(f"  {basename} chunk {chunk_idx+1}: Submit failed: {e}")
                    self.log(f"  {basename}: Split into {num_chunks} jobs ({split_size} rows each)")
                    continue
                else:
                    self.log(f"  {basename}: Could not determine row count for split, submitting as single job.")

            self.last_job_json = schema.job_request_to_json(request)
            try:
                response  = server_client.submit_job(server_url, request)
                job_ids   = response.get("job_ids", []) or []
                total_jobs += len(job_ids)
                tags = []
                if var_json: tags.append("+JSON")
                if csv_file: tags.append("+CSV")
                tag_str = f" [{', '.join(tags)}]" if tags else ""
                self.log(
                    f"  {basename}{tag_str}: "
                    f"{len(job_ids)} job(s) queued"
                )
            except Exception as e:
                self.log(f"  {basename}: Submit failed: {e}")

        self.log(f"Submitted {total_jobs} total job(s) to server.")

    # Compatibility: keeps old internal call sites functional.
    def _render_files(self, file_list, load_files=True):
        entries = [{"path": p, "var_json": "", "csv_file": "", "split_size": 0,
                    "row_range_expr": "", "row_start": 0, "row_end": 0} for p in file_list]
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

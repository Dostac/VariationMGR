import os
import sys
import csv
import json
import uuid
import datetime
import tempfile
from PySide6 import QtWidgets, QtCore, QtGui
from PySide6.QtWidgets import (QWidget, QLabel, QLineEdit, QPushButton,
                               QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
                               QHeaderView, QMenu, QTabWidget, QGroupBox,
                               QComboBox, QSplitter, QToolButton, QMessageBox)
import qtmax
from pymxs import runtime as rt

_script_dir = os.path.dirname(os.path.realpath(__file__))
if _script_dir not in sys.path:
    sys.path.insert(0, _script_dir)

import variation_core as vcore

class VariationManager(QtWidgets.QDialog):
    columns_changed = QtCore.Signal(list)

    def __init__(self, parent=None):
        max_hwnd = rt.windows.getMAXHWND()
        super(VariationManager, self).__init__(QWidget.find(max_hwnd))
        
        self.setWindowTitle("Variation Manager")
        self.resize(1100, 1300)
        self.setWindowFlags(QtCore.Qt.Window | QtCore.Qt.WindowMinMaxButtonsHint | QtCore.Qt.WindowCloseButtonHint)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        
        qtmax.DisableMaxAcceleratorsOnFocus(self, True)
        
        self.custom_properties = []
        self.available_ops_classes = {}
        self.active_ops_instances = []
        self.render_camera_mode = "active"   # "active" | "column"
        self.render_camera_column = ""
        self.render_range_start = 0   # 0 = from beginning
        self.render_range_end = 0     # 0 = to end
        self._csv_watcher = None
        self._csv_temp_path = None
        
        # --- PREFERENCE SETUP VIA CORE ---
        # INI lives in userScripts so each team member has their own local settings.
        script_dir = os.path.dirname(os.path.realpath(__file__))
        self.ini_path = os.path.join(str(rt.getDir(rt.Name("userScripts"))), "VariationManager.ini")
        default_folder = os.path.normpath(os.path.join(script_dir, "Operators"))

        if not os.path.exists(default_folder):
            try: os.makedirs(default_folder)
            except: pass

        self.init_ui()

        self._csv_debounce = QtCore.QTimer(self)
        self._csv_debounce.setSingleShot(True)
        self._csv_debounce.setInterval(300)
        self._csv_debounce.timeout.connect(self._on_csv_file_settled)

        # 1. Load Global Settings via Core
        self.ops_folder = vcore.load_preferences(self.ini_path, default_folder)

        # 2. Scan Operators via Core
        self.scan_operators()

        # 3. Load Scene Data (Table & Tab Instances)
        self.load_from_max_file()

    def init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(16)

        def _mat_button(btn, min_w=100):
            btn.setMinimumHeight(40)
            btn.setMinimumWidth(min_w)
            btn.setDefault(False)
            btn.setAutoDefault(False)
            return btn

        fixed_v_policy = QtWidgets.QSizePolicy(
            QtWidgets.QSizePolicy.Preferred,
            QtWidgets.QSizePolicy.Fixed,
        )

        # --- TOP SECTION: SETTINGS ---
        top_layout = QHBoxLayout()
        top_layout.setSpacing(16)

        # A. Naming
        naming_group = QGroupBox("Output Naming Scheme")
        naming_group.setSizePolicy(fixed_v_policy)
        naming_vbox = QVBoxLayout(naming_group)
        naming_vbox.setContentsMargins(16, 16, 16, 16)
        naming_vbox.setSpacing(8)

        naming_input = QHBoxLayout()
        naming_input.setSpacing(8)

        self.edt_pattern = QLineEdit("{Scene}_{Row}_{Camera}")
        self.edt_pattern.setMinimumHeight(40)
        self.edt_pattern.setFocusPolicy(QtCore.Qt.ClickFocus)

        self.cb_prop_tokens = QComboBox()
        self.cb_prop_tokens.setMinimumHeight(40)

        self.btn_insert_prop = QPushButton("Insert Property")
        self.btn_insert_prop.setMinimumHeight(40)
        self.btn_insert_prop.setDefault(False)
        self.btn_insert_prop.setAutoDefault(False)
        self.btn_insert_prop.setFocusPolicy(QtCore.Qt.NoFocus)
        self.btn_insert_prop.clicked.connect(self.insert_prop_token)

        naming_input.addWidget(self.edt_pattern, stretch=1)
        naming_input.addWidget(self.cb_prop_tokens)
        naming_input.addWidget(self.btn_insert_prop)

        token_row = QHBoxLayout()
        token_row.setSpacing(4)
        for label, token in [("Scene", "{Scene}"), ("Row", "{Row}"), ("Camera", "{Camera}"), ("Date", "{Date}")]:
            btn = QToolButton()
            btn.setText(label)
            btn.setAutoRaise(True)
            btn.clicked.connect(lambda _=False, t=token: self.edt_pattern.insert(t))
            token_row.addWidget(btn)
        token_row.addStretch()

        self.lbl_preview = QLabel("Preview: ...")
        preview_font = self.lbl_preview.font()
        preview_font.setItalic(True)
        self.lbl_preview.setFont(preview_font)

        naming_vbox.addLayout(naming_input)
        naming_vbox.addLayout(token_row)
        naming_vbox.addWidget(self.lbl_preview)

        # B. Render Settings
        cam_group = QGroupBox("Render Settings")
        cam_group.setSizePolicy(fixed_v_policy)
        cam_vbox = QVBoxLayout(cam_group)
        cam_vbox.setContentsMargins(16, 16, 16, 16)
        cam_vbox.setSpacing(8)

        self.radio_cam_active = QtWidgets.QRadioButton("Active Camera")
        self.radio_cam_active.setChecked(True)
        self.radio_cam_all = QtWidgets.QRadioButton("All Cameras")
        self.radio_cam_column = QtWidgets.QRadioButton("From Column:")

        self.combo_cam_column = QComboBox()
        self.combo_cam_column.setEnabled(False)
        self.combo_cam_column.setMinimumHeight(32)
        self.combo_cam_column.setMinimumWidth(150)

        col_row = QHBoxLayout()
        col_row.setSpacing(8)
        col_row.addWidget(self.radio_cam_column)
        col_row.addWidget(self.combo_cam_column)
        col_row.addStretch()

        cam_vbox.addWidget(self.radio_cam_active)
        cam_vbox.addWidget(self.radio_cam_all)
        cam_vbox.addLayout(col_row)

        sep_render = QtWidgets.QFrame()
        sep_render.setFrameShape(QtWidgets.QFrame.HLine)
        cam_vbox.addWidget(sep_render)
        cam_vbox.addSpacing(4)

        cam_vbox.addWidget(QLabel("Row Range (0 = all, header = row 1, data starts at row 2):"))
        range_row = QHBoxLayout()
        range_row.setSpacing(8)
        range_row.addWidget(QLabel("From:"))
        self.spn_range_start = QtWidgets.QSpinBox()
        self.spn_range_start.setRange(0, 99999)
        self.spn_range_start.setSpecialValueText("all")
        self.spn_range_start.setValue(0)
        self.spn_range_start.setMinimumHeight(32)
        self.spn_range_start.setFixedWidth(80)
        range_row.addWidget(self.spn_range_start)
        range_row.addWidget(QLabel("To:"))
        self.spn_range_end = QtWidgets.QSpinBox()
        self.spn_range_end.setRange(0, 99999)
        self.spn_range_end.setSpecialValueText("all")
        self.spn_range_end.setValue(0)
        self.spn_range_end.setMinimumHeight(32)
        self.spn_range_end.setFixedWidth(80)
        range_row.addWidget(self.spn_range_end)
        range_row.addStretch()
        cam_vbox.addLayout(range_row)

        top_layout.addWidget(naming_group, stretch=2)
        top_layout.addWidget(cam_group, stretch=1)

        # --- MIDDLE SECTION: SPLITTER ---
        self.splitter = QSplitter(QtCore.Qt.Vertical)
        self.splitter.setHandleWidth(8)

        # A. Data + actions
        data_widget = QWidget()
        data_layout = QVBoxLayout(data_widget)
        data_layout.setContentsMargins(0, 0, 0, 0)
        data_layout.setSpacing(8)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        self.btn_add_row = QPushButton("＋ Row")
        self.btn_add_col = QPushButton("＋ Column")
        self.btn_edit_csv = QToolButton()
        self.btn_edit_csv.setText("✎ Edit CSV")
        self.btn_edit_csv.setMinimumHeight(40)
        self.btn_edit_csv.setMinimumWidth(120)
        csv_menu = QMenu(self)
        csv_menu.addAction("Import CSV", self.import_csv)
        csv_menu.addAction("Export CSV", self.export_csv)
        self.btn_edit_csv.setMenu(csv_menu)
        self.btn_edit_csv.setPopupMode(QToolButton.DelayedPopup)
        self.btn_folder = QPushButton("📂 Ops Folder")
        self.btn_reset = QPushButton("🗑 Reset")
        self.btn_save_max = QToolButton()
        self.btn_save_max.setText("💾 Save to Scene")
        self.btn_save_max.setMinimumHeight(40)
        self.btn_save_max.setMinimumWidth(140)
        scene_menu = QMenu(self)
        scene_menu.addAction("Import Variation Config...", self.import_json_config)
        scene_menu.addAction("Export Variation Config...", self.export_json_config)
        self.btn_save_max.setMenu(scene_menu)
        self.btn_save_max.setPopupMode(QToolButton.DelayedPopup)

        _mat_button(self.btn_add_row, 90)
        _mat_button(self.btn_add_col, 100)
        _mat_button(self.btn_folder, 120)
        _mat_button(self.btn_reset, 100)

        toolbar.addWidget(self.btn_add_row)
        toolbar.addWidget(self.btn_add_col)
        toolbar.addStretch()
        toolbar.addWidget(self.btn_edit_csv)
        toolbar.addWidget(self.create_separator())
        toolbar.addWidget(self.btn_folder)
        toolbar.addWidget(self.btn_reset)
        toolbar.addWidget(self.btn_save_max)

        self.table = QTableWidget(0, 0)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionsMovable(True)
        self.table.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.table.horizontalHeader().setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.table.verticalHeader().setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(lambda pos: None)
        self.table.horizontalHeader().customContextMenuRequested.connect(self.show_column_menu)
        self.table.verticalHeader().customContextMenuRequested.connect(self.show_row_menu)
        # Keep row numbers in sync with the header=row1 / data=row2 convention.
        self.table.model().rowsInserted.connect(self._update_row_headers)
        self.table.model().rowsRemoved.connect(self._update_row_headers)

        data_layout.addLayout(toolbar)
        data_layout.addWidget(self.table)

        # B. Operators
        op_container = QWidget()
        op_layout = QVBoxLayout(op_container)
        op_layout.setContentsMargins(0, 16, 0, 0)
        op_layout.setSpacing(8)

        op_bar = QHBoxLayout()
        op_bar.setSpacing(8)
        self.lbl_op_status = QLabel("Operators: 0 loaded")
        op_bar.addWidget(self.lbl_op_status)
        op_bar.addStretch()

        self.btn_add_tab = QPushButton("＋ Add Operator")
        self.btn_add_tab.setToolTip("Add Operator from loaded folder")
        self.btn_add_tab.clicked.connect(self.show_add_op_menu)
        _mat_button(self.btn_add_tab, 140)
        op_bar.addWidget(self.btn_add_tab)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.tabCloseRequested.connect(self.remove_operator_tab)
        self.tabs.tabBar().tabMoved.connect(self._on_tab_moved)

        op_layout.addLayout(op_bar)
        op_layout.addWidget(self.tabs)

        self.splitter.addWidget(data_widget)
        self.splitter.addWidget(op_container)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)

        # --- BOTTOM BAR ---
        bottom_bar = QHBoxLayout()
        self.btn_run_row = QPushButton("▶ Run Selected Row")
        _mat_button(self.btn_run_row, 180)
        self.btn_batch_render = QPushButton("▶  Open Batch Renderer")
        _mat_button(self.btn_batch_render, 180)
        bottom_bar.addStretch()
        bottom_bar.addWidget(self.btn_run_row)
        bottom_bar.addWidget(self.btn_batch_render)

        root.addLayout(top_layout)
        root.addWidget(self.splitter)
        root.addLayout(bottom_bar)

        # --- CONNECTIONS ---
        self.btn_add_row.clicked.connect(self.add_row)
        self.btn_add_col.clicked.connect(self.add_column)
        self.btn_edit_csv.clicked.connect(self.edit_csv)
        self.btn_save_max.clicked.connect(self.save_to_max_file)
        self.btn_reset.clicked.connect(self.reset_data)
        self.btn_folder.clicked.connect(self.change_op_folder)
        self.btn_run_row.clicked.connect(self.execute_selected_row)
        self.btn_batch_render.clicked.connect(self.open_batch_renderer)

        self.edt_pattern.textChanged.connect(self._sanitize_pattern)
        self.table.itemChanged.connect(self._on_cell_changed)
        self.radio_cam_active.toggled.connect(lambda c: self._on_cam_mode_toggled("active", c))
        self.radio_cam_column.toggled.connect(lambda c: self._on_cam_mode_toggled("column", c))
        self.radio_cam_all.toggled.connect(lambda c: self._on_cam_mode_toggled("all", c))
        self.combo_cam_column.currentTextChanged.connect(lambda t: setattr(self, 'render_camera_column', t))
        self.spn_range_start.valueChanged.connect(lambda v: setattr(self, 'render_range_start', v))
        self.spn_range_end.valueChanged.connect(lambda v: setattr(self, 'render_range_end', v))
        self.spn_range_start.editingFinished.connect(self._clamp_range_start)
        self.spn_range_end.editingFinished.connect(self._clamp_range_end)
        self.columns_changed.connect(self._on_cam_columns_changed)

    def create_separator(self):
        line = QtWidgets.QFrame()
        line.setFrameShape(QtWidgets.QFrame.VLine)
        line.setFrameShadow(QtWidgets.QFrame.Sunken)
        line.setContentsMargins(8, 0, 8, 0)
        return line
    # --- OPERATOR LOGIC ---

    def change_op_folder(self):
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, "Select Operator Folder", self.ops_folder)
        if folder:
            self.ops_folder = os.path.normpath(folder)
            vcore.save_preferences(self.ini_path, self.ops_folder)
            self.scan_operators()
            QMessageBox.information(self, "Folder Updated", f"Path saved to INI.\nFound {len(self.available_ops_classes)} valid operators.")

    def scan_operators(self):
        self.available_ops_classes = vcore.scan_operators(self.ops_folder, id(self))

        count = len(self.available_ops_classes)
        if count == 0:
            self.lbl_op_status.setText("Status: No valid operators found")
        else:
            self.lbl_op_status.setText(f"Operators: {count} loaded")

    def show_add_op_menu(self):
        menu = QMenu(self)
        if not self.available_ops_classes:
            menu.addAction("No Operators Found (Check Folder)").setEnabled(False)
            menu.addSeparator()
            menu.addAction(f"Current: {self.ops_folder}").setEnabled(False)
        else:
            for name in sorted(self.available_ops_classes.keys()):
                menu.addAction(name).triggered.connect(lambda chk=False, n=name: self.add_operator_tab(n))
        menu.exec(self.btn_add_tab.mapToGlobal(QtCore.QPoint(0, self.btn_add_tab.height())))

    def add_operator_tab(self, op_class_name, settings=None, instance_id=None):
        if op_class_name not in self.available_ops_classes:
            print(f"VM Error: Class {op_class_name} not found.")
            return

        if not instance_id:
            instance_id = uuid.uuid4().hex[:8]

        context = {"rt": rt, "instance_id": instance_id}
        try:
            op_instance = self.available_ops_classes[op_class_name](context)
        except Exception as e:
            print(f"Error instantiating {op_class_name}: {e}")
            return

        if settings and hasattr(op_instance, 'deserialize'):
            try:
                op_instance.deserialize(settings)
            except Exception as e:
                print(f"Error restoring {op_class_name}: {e}")

        self.columns_changed.connect(op_instance.on_columns_changed)
        widget = op_instance.get_ui()

        self.active_ops_instances.append({
            "name": op_class_name,
            "instance": op_instance,
            "widget": widget,
            "instance_id": instance_id,
        })
        
        self.tabs.addTab(widget, op_class_name)

        if hasattr(op_instance, 'status_changed'):
            op_instance.status_changed.connect(
                lambda msg, err, w=widget: self._on_operator_status(w, msg, err)
            )

        if hasattr(op_instance, 'on_columns_changed'):
            op_instance.on_columns_changed(self.custom_properties)
            
        self.tabs.setCurrentIndex(self.tabs.count() - 1)

    def _on_operator_status(self, widget, msg, is_error):
        idx = self.tabs.indexOf(widget)
        if idx == -1:
            return
        base_name = ""
        for op in self.active_ops_instances:
            if op["widget"] is widget:
                base_name = op["name"]
                break
        if not base_name:
            return
        if is_error and msg:
            self.tabs.setTabText(idx, f"\u26a0 {base_name}")
        else:
            self.tabs.setTabText(idx, base_name)

    def remove_operator_tab(self, index):
        widget = self.tabs.widget(index)
        self.active_ops_instances = [op for op in self.active_ops_instances if op["widget"] != widget]
        self.tabs.removeTab(index)

    def _on_tab_moved(self, from_idx, to_idx):
        """Resync active_ops_instances to match the dragged tab order."""
        new_order = []
        for i in range(self.tabs.count()):
            widget = self.tabs.widget(i)
            for op in self.active_ops_instances:
                if op["widget"] is widget:
                    new_order.append(op)
                    break
        self.active_ops_instances = new_order

    def execute_selected_row(self):
        row = self.table.currentRow()
        if row == -1: return

        row_data = {}
        for c in range(self.table.columnCount()):
            header = self.table.horizontalHeaderItem(c).text()
            item = self.table.item(row, c)
            val = item.text() if item else ""
            row_data[header] = val

        for op in self.active_ops_instances:
            try:
                op["instance"].execute(row_data)
            except Exception as e:
                print(f"Error in {op['name']}: {e}")
        rt.redrawViews()

    # --- RENDER CAMERA ---

    def _on_cam_mode_toggled(self, mode, checked):
        if not checked:
            return
        self.render_camera_mode = mode
        self.combo_cam_column.setEnabled(mode == "column")

    def _on_cam_columns_changed(self, columns):
        saved = self.render_camera_column
        self.combo_cam_column.blockSignals(True)
        self.combo_cam_column.clear()
        self.combo_cam_column.addItem("-- Select Column --")
        self.combo_cam_column.addItems(columns)
        idx = self.combo_cam_column.findText(saved)
        self.combo_cam_column.setCurrentIndex(idx if idx != -1 else 0)
        self.combo_cam_column.blockSignals(False)
        self.render_camera_column = self.combo_cam_column.currentText()

    # --- SAVE / LOAD SYSTEM (SCENE ONLY) ---

    def _scene_dir(self):
        """Return the directory of the currently open .max file, or '' if unsaved."""
        try:
            d = str(rt.maxFilePath).strip()
            return d if d else ""
        except Exception:
            return ""

    def _scene_default_save_path(self, ext):
        """Return '<scene_dir>\\<scene_name_without_ext><ext>', or '' if unsaved."""
        try:
            d = str(rt.maxFilePath).strip()
            n = str(rt.maxFileName).strip()
            if not d or not n:
                return ""
            base = os.path.splitext(n)[0]
            return os.path.normpath(os.path.join(d, base + ext))
        except Exception:
            return ""

    def _build_current_data(self):
        hdr = self.table.horizontalHeader()
        headers = [self.table.horizontalHeaderItem(hdr.logicalIndex(v)).text()
                   for v in range(self.table.columnCount())]
        rows = []
        for r in range(self.table.rowCount()):
            row_vals = []
            for v in range(self.table.columnCount()):
                item = self.table.item(r, hdr.logicalIndex(v))
                row_vals.append(item.text() if item else "")
            rows.append(row_vals)

        saved_ops = []
        for op in self.active_ops_instances:
            inst = op["instance"]
            settings = inst.serialize() if hasattr(inst, 'serialize') else {}
            saved_ops.append({
                "class_name": op["name"],
                "instance_id": op["instance_id"],
                "settings": settings,
                # Persisted for deterministic loading in BatchRenderer.
                "ops_folder": self.ops_folder,
            })

        return {
            "scheme": self.edt_pattern.text(),
            "render_camera_mode": self.render_camera_mode,
            "render_camera_column": self.render_camera_column,
            "render_range_start": self.render_range_start,
            "render_range_end": self.render_range_end,
            "ops_folder": self.ops_folder,
            "headers": headers,
            "rows": rows,
            "operators": saved_ops,
        }

    def _read_saved_data(self):
        prop_count = rt.fileProperties.getNumProperties(rt.name('custom'))
        for i in range(1, prop_count + 1):
            if rt.fileProperties.getPropertyName(rt.name('custom'), i) == "VariationManagerData":
                try:
                    return json.loads(rt.fileProperties.getPropertyValue(rt.name('custom'), i))
                except Exception:
                    return None
        return None

    def save_to_max_file(self):
        data = self._build_current_data()
        rt.fileProperties.addProperty(rt.name('custom'), "VariationManagerData", json.dumps(data))
        QMessageBox.information(self, "Variation Manager", "Data saved successfully.")

    def load_from_max_file(self):
        self.table.setRowCount(0)
        self.table.setColumnCount(0)
        self.custom_properties = []
        while self.tabs.count() > 0:
            self.remove_operator_tab(0)

        prop_count = rt.fileProperties.getNumProperties(rt.name('custom'))
        loaded_data = False
        
        for i in range(1, prop_count + 1):
            if rt.fileProperties.getPropertyName(rt.name('custom'), i) == "VariationManagerData":
                val = rt.fileProperties.getPropertyValue(rt.name('custom'), i)
                try:
                    data = json.loads(val)
                    loaded_data = True
                    
                    self.edt_pattern.setText(data.get("scheme", ""))

                    cam_mode = data.get("render_camera_mode", "active")
                    self.render_camera_mode = cam_mode
                    self.render_camera_column = data.get("render_camera_column", "")
                    if cam_mode == "column":
                        self.radio_cam_column.setChecked(True)
                    elif cam_mode == "all":
                        self.radio_cam_all.setChecked(True)
                    else:
                        self.radio_cam_active.setChecked(True)

                    self.render_range_start = data.get("render_range_start", 0)
                    self.render_range_end = data.get("render_range_end", 0)
                    self.spn_range_start.setValue(self.render_range_start)
                    self.spn_range_end.setValue(self.render_range_end)

                    headers = data.get("headers", [])
                    self.table.setColumnCount(len(headers))
                    self.table.setHorizontalHeaderLabels(headers)
                    self.custom_properties = headers

                    scene_ops_folder = data.get("ops_folder", "")
                    if scene_ops_folder and os.path.isdir(scene_ops_folder):
                        scene_ops_folder = os.path.normpath(scene_ops_folder)
                        if scene_ops_folder != self.ops_folder:
                            self.ops_folder = scene_ops_folder
                            vcore.save_preferences(self.ini_path, self.ops_folder)
                            self.scan_operators()
                    
                    for row in data.get("rows", []):
                        r = self.table.rowCount()
                        self.table.insertRow(r)
                        for c, txt in enumerate(row):
                            self.table.setItem(r, c, QTableWidgetItem(txt))
                    
                    for op_entry in data.get("operators", []):
                        class_name = op_entry.get("class_name", "")
                        if not class_name:
                            continue
                        instance_id = op_entry.get("instance_id", None)
                        if hasattr(vcore, "get_operator_state"):
                            op_state = vcore.get_operator_state(op_entry)
                        else:
                            # Fallback for stale/cached variation_core modules.
                            op_state = op_entry.get("settings", op_entry.get("state", {}))
                        self.add_operator_tab(
                            class_name,
                            op_state,
                            instance_id=instance_id)
                        
                except Exception as e:
                    print(f"VM: Error loading JSON data: {e}")
                break
        
        self.update_prop_dropdown()
        self.columns_changed.emit(self.custom_properties)
        self.update_naming_preview()
        return loaded_data

    def closeEvent(self, event):
        saved = self._read_saved_data()
        current = self._build_current_data()

        saved_str   = json.dumps(saved,   sort_keys=True) if saved is not None else None
        current_str = json.dumps(current, sort_keys=True)

        if saved_str != current_str:
            reply = QMessageBox.question(
                self,
                "Unsaved Changes",
                "You have unsaved variation data.\nSave to scene before closing?",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
                QMessageBox.Yes,
            )
            if reply == QMessageBox.Yes:
                rt.fileProperties.addProperty(
                    rt.name('custom'), "VariationManagerData", json.dumps(current)
                )
            elif reply == QMessageBox.Cancel:
                event.ignore()
                return

        self._cleanup_csv_watcher()
        super().closeEvent(event)

    def reset_data(self):
        reply = QMessageBox.question(
            self,
            "Reset Data",
            "This will delete all variation data from the scene.\nThis cannot be undone. Continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        self._cleanup_csv_watcher()
        rt.fileProperties.deleteProperty(rt.name('custom'), "VariationManagerData")
        self.table.setRowCount(0)
        self.table.setColumnCount(0)
        self.custom_properties = []
        while self.tabs.count() > 0:
            self.remove_operator_tab(0)
        self.update_prop_dropdown()
        self.columns_changed.emit(self.custom_properties)
        print("VM: Scene data cleared.")

    # --- HELPERS ---

    def _update_row_headers(self, *_):
        """Set vertical header labels so header=row 1, first data row=row 2."""
        for i in range(self.table.rowCount()):
            self.table.setVerticalHeaderItem(i, QTableWidgetItem(str(i + 2)))

    def _clamp_range_start(self):
        if self.spn_range_start.value() == 1:
            self.spn_range_start.setValue(2)

    def _clamp_range_end(self):
        if self.spn_range_end.value() == 1:
            self.spn_range_end.setValue(2)

    def add_row(self):
        self.table.insertRow(self.table.rowCount())

    def add_column(self):
        name, ok = QtWidgets.QInputDialog.getText(self, "New Column", "Name:")
        if ok and name:
            idx = self.table.columnCount()
            self.table.insertColumn(idx)
            self.table.setHorizontalHeaderItem(idx, QTableWidgetItem(name))
            self.custom_properties.append(name)
            self.update_prop_dropdown()
            self.columns_changed.emit(self.custom_properties)

    def insert_prop_token(self):
        t = self.cb_prop_tokens.currentText()
        if t and t != "-- No Properties --":
            self.edt_pattern.insert(f"[{t}]")

    def update_prop_dropdown(self):
        self.cb_prop_tokens.clear()
        if self.custom_properties:
            self.cb_prop_tokens.addItems(self.custom_properties)
        else:
            self.cb_prop_tokens.addItem("-- No Properties --")

    def _on_cell_changed(self, item):
        """Sanitize cell text on edit, then refresh the naming preview."""
        if item is None:
            return
        raw = item.text()
        clean = "".join(c for c in raw if ord(c) >= 32 and c not in "\r\n\t")
        if clean != raw:
            self.table.blockSignals(True)
            item.setText(clean)
            self.table.blockSignals(False)
        self.update_naming_preview()

    def _sanitize_pattern(self, text):
        """Strip control characters and Windows-illegal filename chars from the naming scheme."""
        clean = "".join(
            c for c in text
            if ord(c) >= 32 and c not in r'\/:*?"<>|'
        )
        if clean != text:
            self.edt_pattern.blockSignals(True)
            cursor = self.edt_pattern.cursorPosition() - (len(text) - len(clean))
            self.edt_pattern.setText(clean)
            self.edt_pattern.setCursorPosition(max(0, cursor))
            self.edt_pattern.blockSignals(False)
        self.update_naming_preview()

    def update_naming_preview(self):
        row_data = {}
        if self.table.rowCount() > 0:
            for c in range(self.table.columnCount()):
                h = self.table.horizontalHeaderItem(c).text()
                val = self.table.item(0, c).text() if self.table.item(0, c) else ""
                row_data[h] = val

        scene_name = "Scene"
        try:
            current_name = str(rt.maxFileName) if rt.maxFileName else ""
            if current_name:
                scene_name = os.path.splitext(current_name)[0]
        except Exception:
            pass

        date_str = datetime.date.today().strftime("%Y%m%d")
        # Keep camera unresolved in preview; final camera name is resolved at render time.
        cam_placeholder = "{Camera}"

        res = vcore.resolve_output_name(
            self.edt_pattern.text(),
            row_data,
            scene_name=scene_name,
            camera_name=cam_placeholder,
            date_str=date_str,
            row_index=0,
        )
        self.lbl_preview.setText(f"Preview: {res}")

    def show_row_menu(self, pos):
        r = self.table.verticalHeader().logicalIndexAt(pos)
        if r < 0:
            return
        selected = sorted(set(i.row() for i in self.table.selectionModel().selectedRows()))
        if not selected:
            selected = [r]
        menu = QMenu()
        act_duplicate = menu.addAction("Duplicate Selected Row(s)")
        menu.addSeparator()
        act_delete = menu.addAction("Delete Selected Row(s)")
        action = menu.exec(QtGui.QCursor.pos())
        n = len(selected)
        row_word = f"{n} row{'s' if n > 1 else ''}"
        if action == act_duplicate:
            reply = QtWidgets.QMessageBox.question(
                self, "Duplicate Rows",
                f"Duplicate {row_word}?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            )
            if reply == QtWidgets.QMessageBox.Yes:
                self.duplicate_rows(selected)
        elif action == act_delete:
            reply = QtWidgets.QMessageBox.question(
                self, "Delete Rows",
                f"Delete {row_word}?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            )
            if reply == QtWidgets.QMessageBox.Yes:
                for row in sorted(selected, reverse=True):
                    self.table.removeRow(row)

    def duplicate_rows(self, rows):
        """Duplicate the given source rows directly below each source row."""
        if not rows:
            return
        rows = sorted(set(rows))
        col_count = self.table.columnCount()
        inserted = []
        offset = 0
        for src in rows:
            src_idx = src + offset
            dst_idx = src_idx + 1
            self.table.insertRow(dst_idx)
            for c in range(col_count):
                item = self.table.item(src_idx, c)
                txt = item.text() if item else ""
                self.table.setItem(dst_idx, c, QTableWidgetItem(txt))
            inserted.append(dst_idx)
            offset += 1

        self.table.clearSelection()
        for row in inserted:
            self.table.selectRow(row)

    def show_column_menu(self, pos):
        c = self.table.horizontalHeader().logicalIndexAt(pos)
        if c < 0:
            return
        menu = QMenu()
        act_rename = menu.addAction("Rename Column")
        act_delete = menu.addAction("Delete Column")
        action = menu.exec(QtGui.QCursor.pos())
        if action == act_rename:
            old_name = self.table.horizontalHeaderItem(c).text()
            new_name, ok = QtWidgets.QInputDialog.getText(self, "Rename Column", "New name:", text=old_name)
            if ok and new_name and new_name != old_name:
                self.table.setHorizontalHeaderItem(c, QTableWidgetItem(new_name))
                self.custom_properties[c] = new_name
                self.update_prop_dropdown()
                self.columns_changed.emit(self.custom_properties)
        elif action == act_delete:
            self.table.removeColumn(c)
            self.custom_properties.pop(c)
            self.update_prop_dropdown()
            self.columns_changed.emit(self.custom_properties)
    
    def import_csv(self):
        self._cleanup_csv_watcher()
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Open CSV", self._scene_default_save_path(".csv"), "CSV Files (*.csv)")
        if not path: return
        with open(path, newline='') as f:
            reader = list(csv.reader(f))
        if not reader: return
        self.table.setRowCount(0)
        self.table.setColumnCount(len(reader[0]))
        self.table.setHorizontalHeaderLabels(reader[0])
        self.custom_properties = reader[0]
        for r_idx, row in enumerate(reader[1:]):
            self.table.insertRow(r_idx)
            for c_idx, val in enumerate(row):
                self.table.setItem(r_idx, c_idx, QTableWidgetItem(val))
        self.update_prop_dropdown()
        self.columns_changed.emit(self.custom_properties)
        self.update_naming_preview()

    def _write_table_to_csv(self, path):
        """Write current table contents to a CSV file at *path*."""
        hdr = self.table.horizontalHeader()
        headers = [self.table.horizontalHeaderItem(hdr.logicalIndex(v)).text()
                   for v in range(self.table.columnCount())]
        with open(path, "w", newline='', encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            for r in range(self.table.rowCount()):
                row_vals = []
                for v in range(self.table.columnCount()):
                    item = self.table.item(r, hdr.logicalIndex(v))
                    row_vals.append(item.text() if item else "")
                writer.writerow(row_vals)

    def export_csv(self):
        if self.table.columnCount() == 0:
            QMessageBox.warning(self, "Export CSV", "Nothing to export — the table is empty.")
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save CSV", self._scene_default_save_path(".csv"), "CSV Files (*.csv)")
        if not path:
            return
        if not path.lower().endswith(".csv"):
            path += ".csv"
        self._write_table_to_csv(path)
        print(f"VM: Exported {self.table.rowCount()} rows to {path}")
        QMessageBox.information(self, "Export CSV", f"Exported successfully:\n{path}")

    # --- EXTERNAL CSV EDITING ---

    def edit_csv(self):
        if self.table.columnCount() == 0:
            QMessageBox.warning(self, "Edit CSV",
                                "Nothing to edit — add columns first.")
            return

        # If already editing, re-open the same file
        if self._csv_temp_path and os.path.isfile(self._csv_temp_path):
            os.startfile(self._csv_temp_path)
            return

        fd, tmp_path = tempfile.mkstemp(prefix="vb_variation_", suffix=".csv")
        os.close(fd)
        self._write_table_to_csv(tmp_path)
        self._csv_temp_path = tmp_path

        self._csv_watcher = QtCore.QFileSystemWatcher([tmp_path], parent=self)
        self._csv_watcher.fileChanged.connect(self._on_csv_file_changed)

        os.startfile(tmp_path)

    def _on_csv_file_changed(self, path):
        # Re-add the path if the editor used delete+recreate save
        if self._csv_watcher and path not in self._csv_watcher.files():
            QtCore.QTimer.singleShot(200, lambda: self._re_add_watched_path(path))
        self._csv_debounce.start()

    def _re_add_watched_path(self, path):
        if self._csv_watcher and os.path.isfile(path):
            self._csv_watcher.addPath(path)

    def _on_csv_file_settled(self):
        """Reload table from the externally-edited temp CSV."""
        path = self._csv_temp_path
        if not path or not os.path.isfile(path):
            return

        try:
            with open(path, newline='', encoding="utf-8") as f:
                reader = list(csv.reader(f))
        except Exception as e:
            print(f"VM: Error re-reading CSV: {e}")
            return
        if not reader:
            return

        self.table.blockSignals(True)
        self.table.setRowCount(0)
        self.table.setColumnCount(len(reader[0]))
        self.table.setHorizontalHeaderLabels(reader[0])
        self.custom_properties = list(reader[0])
        for r_idx, row in enumerate(reader[1:]):
            self.table.insertRow(r_idx)
            for c_idx, val in enumerate(row):
                self.table.setItem(r_idx, c_idx, QTableWidgetItem(val))
        self.table.blockSignals(False)

        self.update_prop_dropdown()
        self.columns_changed.emit(self.custom_properties)
        self.update_naming_preview()

    def _cleanup_csv_watcher(self):
        """Stop watching and delete the temp CSV file."""
        if self._csv_watcher:
            try:
                self._csv_watcher.fileChanged.disconnect(self._on_csv_file_changed)
            except RuntimeError:
                pass
            self._csv_watcher.deleteLater()
            self._csv_watcher = None
        if self._csv_debounce.isActive():
            self._csv_debounce.stop()
        if self._csv_temp_path and os.path.isfile(self._csv_temp_path):
            try:
                os.remove(self._csv_temp_path)
            except OSError:
                pass
        self._csv_temp_path = None

    def export_json_config(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export Variation Config", self._scene_default_save_path(".json"), "JSON Files (*.json)")
        if not path:
            return
        if not path.lower().endswith(".json"):
            path += ".json"
        data = self._build_current_data()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        QMessageBox.information(self, "Export Config", f"Config exported:\n{path}")

    def import_json_config(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Import Variation Config", self._scene_default_save_path(".json"), "JSON Files (*.json)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            QMessageBox.critical(self, "Import Config", f"Failed to read JSON:\n{e}")
            return

        self._cleanup_csv_watcher()
        self.table.setRowCount(0)
        self.table.setColumnCount(0)
        self.custom_properties = []
        while self.tabs.count() > 0:
            self.remove_operator_tab(0)

        self.edt_pattern.setText(data.get("scheme", ""))

        cam_mode = data.get("render_camera_mode", "active")
        self.render_camera_mode = cam_mode
        self.render_camera_column = data.get("render_camera_column", "")
        if cam_mode == "column":
            self.radio_cam_column.setChecked(True)
        elif cam_mode == "all":
            self.radio_cam_all.setChecked(True)
        else:
            self.radio_cam_active.setChecked(True)

        self.render_range_start = data.get("render_range_start", 0)
        self.render_range_end = data.get("render_range_end", 0)
        self.spn_range_start.setValue(self.render_range_start)
        self.spn_range_end.setValue(self.render_range_end)

        headers = data.get("headers", [])
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.custom_properties = headers

        scene_ops_folder = data.get("ops_folder", "")
        if scene_ops_folder and os.path.isdir(scene_ops_folder):
            scene_ops_folder = os.path.normpath(scene_ops_folder)
            if scene_ops_folder != self.ops_folder:
                self.ops_folder = scene_ops_folder
                vcore.save_preferences(self.ini_path, self.ops_folder)
                self.scan_operators()

        for row in data.get("rows", []):
            r = self.table.rowCount()
            self.table.insertRow(r)
            for c, txt in enumerate(row):
                self.table.setItem(r, c, QTableWidgetItem(txt))

        for op_entry in data.get("operators", []):
            class_name = op_entry.get("class_name", "")
            if not class_name:
                continue
            instance_id = op_entry.get("instance_id", None)
            op_state = vcore.get_operator_state(op_entry) if hasattr(vcore, "get_operator_state") \
                else op_entry.get("settings", op_entry.get("state", {}))
            self.add_operator_tab(class_name, op_state, instance_id=instance_id)

        self.update_prop_dropdown()
        self.columns_changed.emit(self.custom_properties)
        self.update_naming_preview()

    def open_batch_renderer(self):
        import importlib
        if "batchrenderer" in sys.modules:
            br = importlib.reload(sys.modules["batchrenderer"])
        else:
            br = importlib.import_module("batchrenderer")
        br.main()


def main():
    app = QtWidgets.QApplication.instance()
    prev = getattr(app, '_vb_variation_manager', None)
    if prev is not None:
        try:
            prev.close()
            prev.deleteLater()
        except Exception:
            pass
    win = VariationManager()
    app._vb_variation_manager = win
    win.show()

if __name__ == "__main__":
    main()

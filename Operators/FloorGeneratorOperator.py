from PySide6 import QtWidgets, QtCore
import os

class CollapsibleSection(QtWidgets.QWidget):
    def __init__(self, title, parent=None, expanded=True):
        super().__init__(parent)

        self.toggle_button = QtWidgets.QToolButton()
        self.toggle_button.setText(title)
        self.toggle_button.setCheckable(True)
        self.toggle_button.setChecked(expanded)
        self.toggle_button.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self.toggle_button.setArrowType(
            QtCore.Qt.ArrowType.DownArrow if expanded else QtCore.Qt.ArrowType.RightArrow
        )
        self.toggle_button.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )

        self.content = QtWidgets.QWidget()
        self.content.setVisible(expanded)
        self.content_layout = QtWidgets.QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(16, 12, 16, 12)
        self.content_layout.setSpacing(8)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.toggle_button)
        layout.addWidget(self.content)

        self.toggle_button.toggled.connect(self._on_toggled)

    def _on_toggled(self, checked):
        self.toggle_button.setArrowType(
            QtCore.Qt.ArrowType.DownArrow if checked else QtCore.Qt.ArrowType.RightArrow
        )
        self.content.setVisible(checked)

class FloorGeneratorOperator(QtCore.QObject):
    """
    Static Fields: Texture Library, Recursive Checkbox, Floor Object, Rotate 90 Checkbox.
    Properties (Driven): Plank Name, Length, Width, Laying Pattern.
    """
    status_changed = QtCore.Signal(str, bool)

    def __init__(self, context=None):
        super().__init__()
        self.rt = context.get("rt") if context else None

        # --- Persistent State (Static Fields) ---
        self.tex_path = ""
        self.recursive_search = True
        self.max_textures = 8
        self.rotate_90 = True
        self.target_node_name = ""
        self.target_node_handle = None

        # --- Properties (Driven by Parent/CSV) ---
        self.col_plank = ""
        self.col_length = ""
        self.col_width = ""
        self.col_pattern = ""
        self.combined_size = False  # if True, parse "WxL" from a single column
        self.col_size = ""

        # --- Row Offset Override (Optional) ---
        self.override_row_offset = False
        self.row_offset_lock = False
        self.col_row_offset_min = ""
        self.col_row_offset_max = ""

        self.main_widget = QtWidgets.QWidget()
        self._setup_ui()

    def _setup_ui(self):
        root = QtWidgets.QVBoxLayout(self.main_widget)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        root.addWidget(scroll)

        container = QtWidgets.QWidget()
        scroll.setWidget(container)

        content_root = QtWidgets.QVBoxLayout(container)
        content_root.setContentsMargins(12, 12, 12, 12)
        content_root.setSpacing(0)

        self.lbl_status = QtWidgets.QLabel("")
        self.lbl_status.setWordWrap(True)
        content_root.addWidget(self.lbl_status)
        content_root.addSpacing(4)

        # --- Card 1: Texture Library ---
        grp1 = CollapsibleSection("1. Texture Library")
        lay1 = grp1.content_layout

        lay1.addWidget(QtWidgets.QLabel("Root Folder:"))
        path_row = QtWidgets.QHBoxLayout()
        self.edit_path = QtWidgets.QLineEdit()
        btn_browse = QtWidgets.QPushButton("...")
        btn_browse.setFixedWidth(28)
        path_row.addWidget(self.edit_path, stretch=1)
        path_row.addWidget(btn_browse)
        lay1.addLayout(path_row)

        self.chk_recursive = QtWidgets.QCheckBox("Recursive Search")
        self.chk_recursive.setChecked(True)
        lay1.addWidget(self.chk_recursive)

        max_tex_row = QtWidgets.QHBoxLayout()
        max_tex_row.addWidget(QtWidgets.QLabel("Max Textures:"))
        self.spin_max_textures = QtWidgets.QSpinBox()
        self.spin_max_textures.setRange(1, 999)
        self.spin_max_textures.setValue(8)
        self.spin_max_textures.setFixedWidth(60)
        max_tex_row.addWidget(self.spin_max_textures)
        max_tex_row.addStretch()
        lay1.addLayout(max_tex_row)

        content_root.addWidget(grp1)
        content_root.addSpacing(8)

        # --- Card 2: Target Floor Object ---
        grp2 = CollapsibleSection("2. Target Floor Object")
        lay2 = grp2.content_layout

        lay2.addWidget(QtWidgets.QLabel("Must have FloorGenerator modifier and CoronaMultiMap."))

        pick_row = QtWidgets.QHBoxLayout()
        self.btn_select_floor = QtWidgets.QPushButton("Pick Selected Object from Scene")
        self.lbl_floor_info = QtWidgets.QLabel("Target: (None)")
        pick_row.addWidget(self.btn_select_floor)
        pick_row.addWidget(self.lbl_floor_info, stretch=1)
        lay2.addLayout(pick_row)

        self.chk_rotate90 = QtWidgets.QCheckBox("Force +90° Extra Rotation")
        self.chk_rotate90.setChecked(True)
        lay2.addWidget(self.chk_rotate90)

        content_root.addWidget(grp2)
        content_root.addSpacing(8)

        # --- Card 3: CSV Column Mappings ---
        grp3 = CollapsibleSection("3. Drive Properties with Columns")
        lay3 = grp3.content_layout

        lay3.addWidget(QtWidgets.QLabel("Plank Name:"))
        self.combo_plank = QtWidgets.QComboBox()
        lay3.addWidget(self.combo_plank)

        lay3.addWidget(QtWidgets.QLabel("Laying Pattern:"))
        self.combo_pattern = QtWidgets.QComboBox()
        self.combo_pattern.setToolTip("Accepts strings containing 'rechte plank' (Straight) or 'visgraat' (Herringbone)")
        lay3.addWidget(self.combo_pattern)

        sep = QtWidgets.QFrame()
        sep.setFrameShape(QtWidgets.QFrame.HLine)
        lay3.addWidget(sep)

        self.chk_combined_size = QtWidgets.QCheckBox("Single dimension column (e.g. 22.8x121.9)")
        lay3.addWidget(self.chk_combined_size)

        # Stacked widget: page 0 = two columns, page 1 = single WxL column
        self.size_stack = QtWidgets.QStackedWidget()

        page_dual = QtWidgets.QWidget()
        form_dual = QtWidgets.QVBoxLayout(page_dual)
        form_dual.setContentsMargins(0, 0, 0, 0)
        form_dual.setSpacing(8)
        form_dual.addWidget(QtWidgets.QLabel("Length (cm):"))
        self.combo_length = QtWidgets.QComboBox()
        form_dual.addWidget(self.combo_length)
        form_dual.addWidget(QtWidgets.QLabel("Width (cm):"))
        self.combo_width = QtWidgets.QComboBox()
        form_dual.addWidget(self.combo_width)
        self.size_stack.addWidget(page_dual)

        page_single = QtWidgets.QWidget()
        form_single = QtWidgets.QVBoxLayout(page_single)
        form_single.setContentsMargins(0, 0, 0, 0)
        form_single.setSpacing(8)
        form_single.addWidget(QtWidgets.QLabel("Size (W×L cm):"))
        self.combo_size = QtWidgets.QComboBox()
        self.combo_size.setToolTip("Format: shortest x longest, e.g. 22.8x121.9")
        form_single.addWidget(self.combo_size)
        self.size_stack.addWidget(page_single)

        lay3.addWidget(self.size_stack)

        content_root.addWidget(grp3)
        content_root.addSpacing(8)

        # --- Card 4: Row Offset Override (Optional) ---
        grp4 = CollapsibleSection("4. Row Offset Override")
        lay4 = grp4.content_layout

        self.chk_override_row_offset = QtWidgets.QCheckBox("Enable Row Offset Override")
        lay4.addWidget(self.chk_override_row_offset)

        # Sub-widget that is enabled/disabled as a unit
        self.row_offset_widget = QtWidgets.QWidget()
        self.row_offset_widget.setEnabled(False)
        ro_lay = QtWidgets.QVBoxLayout(self.row_offset_widget)
        ro_lay.setContentsMargins(0, 0, 0, 0)
        ro_lay.setSpacing(8)

        ro_lay.addWidget(QtWidgets.QLabel("Min Row Offset Column:"))
        self.combo_row_offset_min = QtWidgets.QComboBox()
        ro_lay.addWidget(self.combo_row_offset_min)

        self.chk_row_offset_lock = QtWidgets.QCheckBox("Lock Min/Max (RowOffset_L) — Min controls both")
        ro_lay.addWidget(self.chk_row_offset_lock)

        self.row_offset_max_container = QtWidgets.QWidget()
        max_row_lay = QtWidgets.QVBoxLayout(self.row_offset_max_container)
        max_row_lay.setContentsMargins(0, 0, 0, 0)
        max_row_lay.setSpacing(8)
        max_row_lay.addWidget(QtWidgets.QLabel("Max Row Offset Column:"))
        self.combo_row_offset_max = QtWidgets.QComboBox()
        max_row_lay.addWidget(self.combo_row_offset_max)
        ro_lay.addWidget(self.row_offset_max_container)

        lay4.addWidget(self.row_offset_widget)

        content_root.addWidget(grp4)

        content_root.addStretch()

        # Connections
        btn_browse.clicked.connect(self._browse_lib)
        self.btn_select_floor.clicked.connect(self._pick_floor_object)

        self.edit_path.textChanged.connect(lambda t: setattr(self, 'tex_path', t))
        self.chk_recursive.toggled.connect(lambda v: setattr(self, 'recursive_search', v))
        self.spin_max_textures.valueChanged.connect(lambda v: setattr(self, 'max_textures', v))
        self.chk_rotate90.toggled.connect(lambda v: setattr(self, 'rotate_90', v))

        self.combo_plank.currentTextChanged.connect(lambda t: setattr(self, 'col_plank', t))
        self.combo_length.currentTextChanged.connect(lambda t: setattr(self, 'col_length', t))
        self.combo_width.currentTextChanged.connect(lambda t: setattr(self, 'col_width', t))
        self.combo_pattern.currentTextChanged.connect(lambda t: setattr(self, 'col_pattern', t))
        self.combo_size.currentTextChanged.connect(lambda t: setattr(self, 'col_size', t))
        self.combo_row_offset_min.currentTextChanged.connect(lambda t: setattr(self, 'col_row_offset_min', t))
        self.combo_row_offset_max.currentTextChanged.connect(lambda t: setattr(self, 'col_row_offset_max', t))
        self.chk_combined_size.toggled.connect(self._on_size_mode_toggled)

        self.chk_override_row_offset.toggled.connect(self._on_row_offset_override_toggled)
        self.chk_row_offset_lock.toggled.connect(self._on_row_offset_lock_toggled)

    # --- Manager Interface ---

    def get_ui(self):
        return self.main_widget

    def on_columns_changed(self, columns):
        """Updates all dropdowns when CSV loads."""
        combos = [
            (self.combo_plank, self.col_plank),
            (self.combo_length, self.col_length),
            (self.combo_width, self.col_width),
            (self.combo_pattern, self.col_pattern),
            (self.combo_size, self.col_size),
            (self.combo_row_offset_min, self.col_row_offset_min),
            (self.combo_row_offset_max, self.col_row_offset_max),
        ]

        for combo, target_val in combos:
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("-- Select Column --")
            combo.addItems(columns)
            idx = combo.findText(target_val)
            combo.setCurrentIndex(idx if idx != -1 else 0)
            combo.blockSignals(False)

        # Sync internal state to what the combos now show
        self.col_plank   = self.combo_plank.currentText()
        self.col_length  = self.combo_length.currentText()
        self.col_width   = self.combo_width.currentText()
        self.col_pattern = self.combo_pattern.currentText()
        self.col_size    = self.combo_size.currentText()
        self.col_row_offset_min = self.combo_row_offset_min.currentText()
        self.col_row_offset_max = self.combo_row_offset_max.currentText()

    def execute(self, row_data):
        if not self.rt or not self.target_node_name: return

        # 1. Resolve CSV Data
        plank_name  = row_data.get(self.col_plank, "").strip()
        pattern_str = row_data.get(self.col_pattern, "").strip()

        if not plank_name:
            self._set_status("Plank name missing in CSV row.", True)
            return

        # 2. Get Target Node & Validate
        # Look up by name first — handles are session-specific and become stale after a scene reload.
        target_node = None
        if self.target_node_name:
            target_node = self.rt.getNodeByName(self.target_node_name)
            if target_node:
                self.target_node_handle = self.rt.GetHandleByAnim(target_node)
        if not target_node and self.target_node_handle:
            target_node = self.rt.GetAnimByHandle(self.target_node_handle)
        if not target_node:
            self._set_status("Target floor object not found in scene.", True)
            return

        # Find FloorGenerator
        fg = None
        for mod in target_node.modifiers:
            if self.rt.classOf(mod) == self.rt.FloorGenerator:
                fg = mod
                break

        if not fg:
            self._set_status("FloorGenerator modifier missing.", True)
            return

        # Find CoronaMultiMap
        multi_map = self._recursive_map_search(target_node.material)
        if not multi_map:
            self._set_status("CoronaMultiMap not found in object's material.", True)
            return

        # 3. Apply Pattern and Dimensions
        pat_lower = pattern_str.lower()
        fp_value = None

        if "rechte plank" in pat_lower:
            fp_value = 2
        elif "visgraat" in pat_lower:
            fp_value = 4

        if fp_value is not None:
            try:
                fg.FloorPattern = fp_value
            except:
                pass

        try:
            if self.combined_size:
                # Parse "width x length" from a single column, e.g. "22.8x121.9"
                size_str = row_data.get(self.col_size, "").strip()
                parts = size_str.lower().split("x")
                if len(parts) != 2:
                    raise ValueError(size_str)
                w_val = float(parts[0].strip())
                l_val = float(parts[1].strip())
            else:
                l_val = float(row_data.get(self.col_length, "").strip())
                w_val = float(row_data.get(self.col_width, "").strip())

            # Swap dimensions for "rechte plank" as per original logic
            if fp_value == 2:
                l_val, w_val = w_val, l_val

            l_units = self.rt.units.decodeValue(f"{l_val}cm")
            w_units = self.rt.units.decodeValue(f"{w_val}cm")

            # Accommodate property variations in FloorGen versions
            if self.rt.isProperty(fg, "length"): fg.length = w_units
            elif self.rt.isProperty(fg, "boardLength"): fg.boardLength = w_units

            if self.rt.isProperty(fg, "width"): fg.width = l_units
            elif self.rt.isProperty(fg, "boardWidth"): fg.boardWidth = l_units
        except ValueError as e:
            self._set_status(f"Invalid size value: {e}", True)
            return

        # 4. Apply Row Offset Override
        if self.override_row_offset:
            try:
                min_value = self._get_float_from_row(row_data, self.col_row_offset_min, "Min Row Offset")
                max_value = min_value if self.row_offset_lock else self._get_float_from_row(
                    row_data, self.col_row_offset_max, "Max Row Offset"
                )

                if self.rt.isProperty(fg, "MinRowOffset"):
                    fg.MinRowOffset = min_value
                if self.rt.isProperty(fg, "RowOffset_L"):
                    fg.RowOffset_L = self.row_offset_lock
                if not self.row_offset_lock and self.rt.isProperty(fg, "MaxRowOffset"):
                    fg.MaxRowOffset = max_value
            except ValueError as e:
                self._set_status(str(e), True)
                return
            except:
                pass

        # 5. Find Textures and Apply to MultiMap
        files = self._find_textures(plank_name)
        if not files:
            self._set_status(f"No textures found for '{plank_name}'.", True)
            return

        if len(files) > self.max_textures: files = files[:self.max_textures]

        # Load Textures
        multi_map.items = len(files)
        for i, filepath in enumerate(files):
            bt = self.rt.bitmapTexture(filename=filepath)

            # Calculate Rotation
            rot = 0
            if fp_value == 2: rot += 90
            if self.rotate_90: rot += 90
            bt.coords.W_angle = rot

            # In pymxs, MAXScript arrays accessed via Python are 0-indexed
            multi_map.texmaps[i] = bt

        # Try to turn them all on (per-element — can't assign a list to a pymxs array)
        try:
            for i in range(len(files)):
                multi_map.texmapsOn[i] = True
        except:
            pass

        self._set_status(f"Success: Configured floor with {len(files)} textures.")

    # --- Internal Logic ---

    def _on_size_mode_toggled(self, checked):
        self.combined_size = checked
        self.size_stack.setCurrentIndex(1 if checked else 0)

    def _on_row_offset_override_toggled(self, checked):
        self.override_row_offset = checked
        self.row_offset_widget.setEnabled(checked)

    def _on_row_offset_lock_toggled(self, checked):
        self.row_offset_lock = checked
        self.row_offset_max_container.setVisible(not checked)

    def _browse_lib(self):
        folder = QtWidgets.QFileDialog.getExistingDirectory(None, "Select Texture Library")
        if folder:
            self.edit_path.setText(folder)

    def _pick_floor_object(self):
        if not self.rt: return
        selection = self.rt.selection
        if len(selection) == 0:
            self._set_status("Please select an object in 3ds Max first.", True)
            return

        target = selection[0]
        self.target_node_name = target.name
        self.target_node_handle = self.rt.GetHandleByAnim(target)
        self.lbl_floor_info.setText(f"Target: {self.target_node_name}")
        self._set_status("")

    def _find_textures(self, search_term):
        """Python equivalent of findMatchingFiles."""
        if not os.path.exists(self.tex_path): return []

        matches = []
        search_lower = search_term.lower()

        image_exts = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".exr", ".hdr", ".tga"}

        if self.recursive_search:
            for root, dirs, files in os.walk(self.tex_path):
                for file in files:
                    if os.path.splitext(file)[1].lower() in image_exts and search_lower in file.lower():
                        matches.append(os.path.join(root, file))
        else:
            for file in os.listdir(self.tex_path):
                if os.path.isfile(os.path.join(self.tex_path, file)):
                    if os.path.splitext(file)[1].lower() in image_exts and search_lower in file.lower():
                        matches.append(os.path.join(self.tex_path, file))

        return matches

    def _get_float_from_row(self, row_data, column_name, label):
        if not column_name or column_name == "-- Select Column --":
            raise ValueError(f"{label} column not selected.")

        raw_value = row_data.get(column_name, "").strip()
        if not raw_value:
            raise ValueError(f"{label} value missing in CSV row.")

        try:
            return float(raw_value)
        except ValueError:
            raise ValueError(f"Invalid {label.lower()} value: {raw_value}")

    def _recursive_map_search(self, mtl):
        """Python equivalent of _recursiveMapSearch."""
        if not mtl: return None
        if self.rt.classOf(mtl) == self.rt.CoronaMultiMap: return mtl

        try: sub_mtl_count = self.rt.getNumSubMtls(mtl)
        except: sub_mtl_count = 0

        for i in range(1, sub_mtl_count + 1):
            sub_mtl = self.rt.getSubMtl(mtl, i)
            if sub_mtl:
                found = self._recursive_map_search(sub_mtl)
                if found: return found

        try: sub_tex_count = self.rt.getNumSubTexmaps(mtl)
        except: sub_tex_count = 0

        for i in range(1, sub_tex_count + 1):
            sub_tex = self.rt.getSubTexmap(mtl, i)
            if sub_tex:
                found = self._recursive_map_search(sub_tex)
                if found: return found

        return None

    def _set_status(self, msg, error=False):
        self.lbl_status.setText(msg)
        self.lbl_status.setStyleSheet("color: #ff6666;" if error else "color: #66ff66;")
        self.status_changed.emit(msg, error)

    # --- Persistence ---
    def serialize(self):
        return {
            "tex_path": self.tex_path,
            "recursive_search": self.recursive_search,
            "max_textures": self.max_textures,
            "rotate_90": self.rotate_90,
            "target_node_name": self.target_node_name,
            "target_node_handle": self.target_node_handle,
            "col_plank": self.col_plank,
            "col_length": self.col_length,
            "col_width": self.col_width,
            "col_pattern": self.col_pattern,
            "combined_size": self.combined_size,
            "col_size": self.col_size,
            "override_row_offset": self.override_row_offset,
            "row_offset_lock": self.row_offset_lock,
            "col_row_offset_min": self.col_row_offset_min,
            "col_row_offset_max": self.col_row_offset_max,
        }

    def deserialize(self, data):
        self.tex_path = data.get("tex_path", "")
        self.recursive_search = data.get("recursive_search", True)
        self.max_textures = data.get("max_textures", 8)
        self.rotate_90 = data.get("rotate_90", True)
        self.target_node_name = data.get("target_node_name", "")
        self.target_node_handle = data.get("target_node_handle", None)

        self.col_plank = data.get("col_plank", "")
        self.col_length = data.get("col_length", "")
        self.col_width = data.get("col_width", "")
        self.col_pattern = data.get("col_pattern", "")
        self.combined_size = data.get("combined_size", False)
        self.col_size = data.get("col_size", "")

        self.override_row_offset = data.get("override_row_offset", False)
        self.row_offset_lock = data.get("row_offset_lock", False)
        self.col_row_offset_min = data.get("col_row_offset_min", "")
        self.col_row_offset_max = data.get("col_row_offset_max", "")

        self.edit_path.setText(self.tex_path)
        self.chk_recursive.setChecked(self.recursive_search)
        self.spin_max_textures.setValue(self.max_textures)
        self.chk_rotate90.setChecked(self.rotate_90)
        self.chk_combined_size.setChecked(self.combined_size)

        self.chk_override_row_offset.setChecked(self.override_row_offset)
        self.chk_row_offset_lock.setChecked(self.row_offset_lock)
        self._on_row_offset_lock_toggled(self.row_offset_lock)

        if self.target_node_name:
            self.lbl_floor_info.setText(f"Target: {self.target_node_name}")

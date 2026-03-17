from PySide6 import QtWidgets, QtCore
import os
import csv

class UnlitColorsOperator(QtCore.QObject):
    """
    Drives a CoronaColor map's HDR color slot from a colour library CSV.
    Library CSVs must have headers: Color Name, sRGB R, sRGB G, sRGB B
    Values are sRGB [0..1] floats, applied via colorHdr / colorSpace=0 / method=1.
    """
    status_changed = QtCore.Signal(str, bool)

    def __init__(self, context=None):
        super().__init__()
        self.rt = context.get("rt") if context else None

        self.target_map_name = ""
        self.target_map_handle = None

        self.lib_folder = ""
        self.static_library = ""   # library filename without extension
        self.lib_col_enabled = False
        self.lib_column = ""       # CSV column that overrides the library name
        self.color_column = ""     # CSV column that provides the color name

        self._lib_cache = {}       # {lib_name: {lower_color_name: (r, g, b)}}

        self.main_widget = QtWidgets.QWidget()
        self._setup_ui()
        self._try_default_folder()

    def _try_default_folder(self):
        """Default to <startupScripts>\\HDRcolours\\ if it exists."""
        if not self.rt:
            return
        try:
            startup = self.rt.getDir(self.rt.name('startupScripts'))
            default = os.path.join(startup, "HDRcolours")
            if os.path.isdir(default):
                self.lib_folder = os.path.normpath(default)
                self.edit_folder.setText(self.lib_folder)
                self._refresh_library_list()
        except Exception:
            pass

    def _setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self.main_widget)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)

        self.lbl_status = QtWidgets.QLabel("")
        self.lbl_status.setWordWrap(True)
        layout.addWidget(self.lbl_status)

        # --- 1. Target map ---
        layout.addWidget(QtWidgets.QLabel("1. Target CoronaColor Map:"))
        row_map = QtWidgets.QHBoxLayout()
        self.btn_pick_map = QtWidgets.QPushButton("Pick from Scene...")
        self.btn_clear_map = QtWidgets.QPushButton("X")
        self.btn_clear_map.setFixedWidth(28)
        row_map.addWidget(self.btn_pick_map)
        row_map.addWidget(self.btn_clear_map)
        layout.addLayout(row_map)
        self.lbl_map = QtWidgets.QLabel("Target: (None)")
        self.lbl_map.setStyleSheet("color: #aaa;")
        layout.addWidget(self.lbl_map)

        layout.addSpacing(4)

        # --- 2. Library folder ---
        layout.addWidget(QtWidgets.QLabel("2. HDR Colour Library Folder:"))
        row_folder = QtWidgets.QHBoxLayout()
        self.edit_folder = QtWidgets.QLineEdit()
        self.edit_folder.setPlaceholderText("Path to folder containing .csv libraries...")
        btn_browse = QtWidgets.QPushButton("...")
        btn_browse.setFixedWidth(28)
        row_folder.addWidget(self.edit_folder)
        row_folder.addWidget(btn_browse)
        layout.addLayout(row_folder)

        layout.addSpacing(4)

        # --- 3. Library selection ---
        layout.addWidget(QtWidgets.QLabel("3. Colour Library:"))

        row_lib = QtWidgets.QHBoxLayout()
        self.combo_library = QtWidgets.QComboBox()
        btn_refresh = QtWidgets.QPushButton("↻")
        btn_refresh.setFixedWidth(28)
        btn_refresh.setToolTip("Refresh library list from folder")
        self.btn_open_csv = QtWidgets.QPushButton("Open CSV")
        self.btn_open_csv.setToolTip("Open selected library CSV file")
        row_lib.addWidget(self.combo_library)
        row_lib.addWidget(btn_refresh)
        row_lib.addWidget(self.btn_open_csv)
        layout.addLayout(row_lib)

        row_lib_col = QtWidgets.QHBoxLayout()
        self.chk_lib_from_col = QtWidgets.QCheckBox("Override per-row from column:")
        self.combo_lib_col = QtWidgets.QComboBox()
        self.combo_lib_col.setEnabled(False)
        row_lib_col.addWidget(self.chk_lib_from_col)
        row_lib_col.addWidget(self.combo_lib_col)
        layout.addLayout(row_lib_col)

        layout.addSpacing(4)

        # --- 4. Color name column ---
        layout.addWidget(QtWidgets.QLabel("4. Colour Name Column:"))
        self.combo_color_col = QtWidgets.QComboBox()
        layout.addWidget(self.combo_color_col)

        layout.addStretch()

        # Connections
        self.btn_pick_map.clicked.connect(self._pick_map)
        self.btn_clear_map.clicked.connect(self._clear_map)
        btn_browse.clicked.connect(self._browse_folder)
        btn_refresh.clicked.connect(self._refresh_library_list)
        self.btn_open_csv.clicked.connect(self._open_csv)
        self.edit_folder.editingFinished.connect(self._on_folder_edited)
        self.combo_library.currentTextChanged.connect(self._on_library_changed)
        self.chk_lib_from_col.toggled.connect(self._on_lib_col_toggled)
        self.combo_lib_col.currentTextChanged.connect(lambda t: setattr(self, 'lib_column', t))
        self.combo_color_col.currentTextChanged.connect(lambda t: setattr(self, 'color_column', t))

    # --- VariationMGR interface ---

    def get_ui(self):
        return self.main_widget

    def on_columns_changed(self, columns):
        for combo, attr in [(self.combo_lib_col, 'lib_column'), (self.combo_color_col, 'color_column')]:
            saved = getattr(self, attr)
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("-- Select Column --")
            combo.addItems(columns)
            idx = combo.findText(saved)
            combo.setCurrentIndex(idx if idx != -1 else 0)
            combo.blockSignals(False)
            setattr(self, attr, combo.currentText())

    def execute(self, row_data):
        if not self.rt:
            self._set_status("3ds Max runtime not available.", error=True)
            return

        # Resolve target map — look up by name first (handles are session-specific).
        if not self.target_map_name:
            self._set_status("No CoronaColor map selected.", error=True)
            return
        target_map = None
        for m in self.rt.getClassInstances(self.rt.CoronaColor):
            if m.name == self.target_map_name:
                target_map = m
                self.target_map_handle = self.rt.GetHandleByAnim(m)
                break
        if not target_map and self.target_map_handle:
            target_map = self.rt.GetAnimByHandle(self.target_map_handle)
        if not target_map:
            self._set_status("Map node not found (deleted?).", error=True)
            return

        # Resolve library name
        if self.chk_lib_from_col.isChecked() and self.lib_column and self.lib_column != "-- Select Column --":
            if self.lib_column not in row_data:
                self._set_status(f"Column '{self.lib_column}' missing.", error=True)
                return
            lib_name = row_data.get(self.lib_column, "").strip()
        else:
            lib_name = self.static_library
        if not lib_name:
            self._set_status("No library selected.", error=True)
            return

        # Resolve color name
        if not self.color_column or self.color_column == "-- Select Column --":
            self._set_status("No colour column selected.", error=True)
            return
        if self.color_column not in row_data:
            self._set_status(f"Column '{self.color_column}' missing.", error=True)
            return
        color_name = row_data.get(self.color_column, "").strip()
        if not color_name:
            self._set_status(f"Empty colour name in column '{self.color_column}'.", error=True)
            return

        # Load library (cached)
        lib_data = self._load_library(lib_name)
        if lib_data is None:
            return  # status already set

        # Find color (case-insensitive)
        rgb = lib_data.get(color_name.lower())
        if rgb is None:
            self._set_status(f"'{color_name}' not found in '{lib_name}'.", error=True)
            return

        r, g, b = rgb

        # Apply — matches the MaxScript: colorHdr = color r g b, colorSpace=0, method=1
        try:
            target_map.colorHdr = self.rt.color(r, g, b)
            target_map.colorSpace = 0
            target_map.method = 1
            self._set_status(f"Applied '{color_name}' to {target_map.name}")
        except Exception as e:
            self._set_status(f"Apply failed: {e}", error=True)

    def serialize(self):
        return {
            "target_map_name": self.target_map_name,
            "target_map_handle": self.target_map_handle,
            "lib_folder": self.lib_folder,
            "static_library": self.static_library,
            "lib_col_enabled": self.chk_lib_from_col.isChecked(),
            "lib_column": self.lib_column,
            "color_column": self.color_column,
        }

    def deserialize(self, data):
        self.target_map_name = data.get("target_map_name", "")
        self.target_map_handle = data.get("target_map_handle", None)
        self.lib_folder = data.get("lib_folder", "")
        self.static_library = data.get("static_library", "")
        self.lib_col_enabled = data.get("lib_col_enabled", False)
        self.lib_column = data.get("lib_column", "")
        self.color_column = data.get("color_column", "")

        if self.target_map_name:
            self.lbl_map.setText(f"Target: {self.target_map_name}")
        if self.lib_folder:
            self.edit_folder.setText(self.lib_folder)
            self._refresh_library_list()
        if self.static_library:
            idx = self.combo_library.findText(self.static_library)
            if idx != -1:
                self.combo_library.setCurrentIndex(idx)
        self.chk_lib_from_col.setChecked(self.lib_col_enabled)
        # combo_lib_col / combo_color_col restored by on_columns_changed

    # --- Internal ---

    def _pick_map(self):
        if not self.rt:
            return
        maps = list(self.rt.getClassInstances(self.rt.CoronaColor))
        if not maps:
            self._set_status("No CoronaColor maps found in scene.", error=True)
            return
        map_dict = {
            f"{m.name} (ID: {self.rt.GetHandleByAnim(m)})": (m, self.rt.GetHandleByAnim(m))
            for m in maps
        }
        item, ok = QtWidgets.QInputDialog.getItem(
            self.main_widget, "Select CoronaColor Map", "Maps:",
            sorted(map_dict.keys()), 0, False
        )
        if ok and item:
            sel_map, handle = map_dict[item]
            self.target_map_name = sel_map.name
            self.target_map_handle = handle
            self.lbl_map.setText(f"Target: {self.target_map_name}")
            self._set_status("")

    def _clear_map(self):
        self.target_map_name = ""
        self.target_map_handle = None
        self.lbl_map.setText("Target: (None)")

    def _browse_folder(self):
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self.main_widget, "Select HDR Colour Library Folder", self.lib_folder
        )
        if folder:
            self.lib_folder = os.path.normpath(folder)
            self.edit_folder.setText(self.lib_folder)
            self._lib_cache.clear()
            self._refresh_library_list()

    def _open_csv(self):
        lib = self.static_library
        if not lib:
            self._set_status("No library selected.", error=True)
            return
        csv_path = os.path.join(self.lib_folder, lib + ".csv")
        if os.path.isfile(csv_path):
            os.startfile(csv_path)
        else:
            self._set_status(f"File not found: '{lib}.csv'", error=True)

    def _on_folder_edited(self):
        path = self.edit_folder.text().strip()
        if not path:
            return
        path = os.path.normpath(path)
        if path != self.lib_folder:
            self.lib_folder = path
            self._lib_cache.clear()
            self._refresh_library_list()

    def _refresh_library_list(self):
        self.combo_library.blockSignals(True)
        self.combo_library.clear()
        if os.path.isdir(self.lib_folder):
            names = sorted(
                os.path.splitext(f)[0]
                for f in os.listdir(self.lib_folder)
                if f.lower().endswith(".csv")
            )
            self.combo_library.addItems(names)
            if self.static_library:
                idx = self.combo_library.findText(self.static_library)
                if idx != -1:
                    self.combo_library.setCurrentIndex(idx)
        self.combo_library.blockSignals(False)
        self.static_library = self.combo_library.currentText()

    def _on_library_changed(self, text):
        self.static_library = text

    def _on_lib_col_toggled(self, checked):
        self.lib_col_enabled = checked
        self.combo_lib_col.setEnabled(checked)
        self.combo_library.setEnabled(not checked)

    def _load_library(self, lib_name):
        """Load and cache a library. Returns {lower_color_name: (r, g, b)} or None."""
        if lib_name in self._lib_cache:
            return self._lib_cache[lib_name]

        csv_path = os.path.join(self.lib_folder, lib_name + ".csv")
        if not os.path.isfile(csv_path):
            # Case-insensitive fallback
            try:
                for f in os.listdir(self.lib_folder):
                    if f.lower() == (lib_name + ".csv").lower():
                        csv_path = os.path.join(self.lib_folder, f)
                        break
            except Exception:
                pass
        if not os.path.isfile(csv_path):
            self._set_status(f"Library not found: '{lib_name}.csv'", error=True)
            return None

        data = {}
        try:
            with open(csv_path, newline='', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    name = row.get("Color Name", "").strip()
                    if not name:
                        continue
                    try:
                        r = float(row["sRGB R"])
                        g = float(row["sRGB G"])
                        b = float(row["sRGB B"])
                    except (KeyError, ValueError):
                        continue
                    data[name.lower()] = (r, g, b)
        except Exception as e:
            self._set_status(f"Failed to read '{lib_name}': {e}", error=True)
            return None

        self._lib_cache[lib_name] = data
        return data

    def _set_status(self, msg, error=False):
        self.lbl_status.setText(msg)
        self.lbl_status.setStyleSheet("color: #ff6666;" if error else "color: #66ff66;")
        if error and msg:
            print(f"UnlitColorsOp ERROR: {msg}")
        self.status_changed.emit(msg, error)

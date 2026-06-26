from PySide6 import QtWidgets, QtCore, QtGui
import os
import csv

class UnlitColorsOperator(QtCore.QObject):
    """
    Drives a CoronaColor map's HDR color slot from a folder of colour library CSVs.

    A colour name (taken from a CSV column of the variation row) is looked up
    across every .csv in the library folder; the first match wins. Library CSVs
    must have headers: Color Name, sRGB R, sRGB G, sRGB B. Values are sRGB [0..1]
    floats, applied via colorHdr / colorSpace=0 / method=1.
    """
    status_changed = QtCore.Signal(str, bool)

    def __init__(self, context=None):
        super().__init__()
        self.rt = context.get("rt") if context else None

        self.target_map_name = ""
        self.target_map_handle = None

        self.lib_folder = ""
        self.color_column = ""     # CSV column that provides the color name

        self._lib_cache = {}       # {lib_name: {lower_color_name: (orig_name, r, g, b)}}
        self._all_colors = []      # [(orig_name, lib_name, (r, g, b))] for the browse list

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
                self._set_folder(default)
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
        self.btn_open_folder = QtWidgets.QPushButton("Open")
        self.btn_open_folder.setToolTip("Open the library folder in Explorer")
        row_folder.addWidget(self.edit_folder)
        row_folder.addWidget(btn_browse)
        row_folder.addWidget(self.btn_open_folder)
        layout.addLayout(row_folder)
        self.lbl_libs = QtWidgets.QLabel("")
        self.lbl_libs.setStyleSheet("color: #aaa;")
        self.lbl_libs.setWordWrap(True)
        layout.addWidget(self.lbl_libs)

        layout.addSpacing(4)

        # --- 3. Color name column ---
        layout.addWidget(QtWidgets.QLabel("3. Colour Name Column:"))
        self.combo_color_col = QtWidgets.QComboBox()
        layout.addWidget(self.combo_color_col)

        layout.addSpacing(4)

        # --- 4. Browse / search colours across all libraries ---
        layout.addWidget(QtWidgets.QLabel("4. Browse Colours:"))
        row_search = QtWidgets.QHBoxLayout()
        self.edit_search = QtWidgets.QLineEdit()
        self.edit_search.setPlaceholderText("Filter colour names...")
        self.edit_search.setClearButtonEnabled(True)
        self.btn_copy_color = QtWidgets.QPushButton("Copy Name")
        self.btn_copy_color.setToolTip("Copy the selected colour name to the clipboard")
        row_search.addWidget(self.edit_search)
        row_search.addWidget(self.btn_copy_color)
        layout.addLayout(row_search)

        self.list_colors = QtWidgets.QListWidget()
        self.list_colors.setToolTip("Double-click a colour to copy its name.")
        self.list_colors.setMinimumHeight(120)
        layout.addWidget(self.list_colors)

        layout.addStretch()

        # Connections
        self.btn_pick_map.clicked.connect(self._pick_map)
        self.btn_clear_map.clicked.connect(self._clear_map)
        btn_browse.clicked.connect(self._browse_folder)
        self.btn_open_folder.clicked.connect(self._open_folder)
        self.edit_folder.editingFinished.connect(self._on_folder_edited)
        self.combo_color_col.currentTextChanged.connect(lambda t: setattr(self, 'color_column', t))
        self.edit_search.textChanged.connect(self._filter_color_list)
        self.btn_copy_color.clicked.connect(self._copy_selected_color)
        self.list_colors.itemDoubleClicked.connect(self._copy_color_item)

    # --- VariationMGR interface ---

    def get_ui(self):
        return self.main_widget

    def on_columns_changed(self, columns):
        saved = self.color_column
        combo = self.combo_color_col
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("-- Select Column --")
        combo.addItems(columns)
        idx = combo.findText(saved)
        combo.setCurrentIndex(idx if idx != -1 else 0)
        combo.blockSignals(False)
        self.color_column = combo.currentText()

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

        # Find color across all libraries (case-insensitive); first match wins.
        rgb, lib_name = self._find_color_in_all_libraries(color_name)
        if rgb is None:
            self._set_status(f"'{color_name}' not found in any library.", error=True)
            return

        r, g, b = rgb

        # Apply — matches the MaxScript: colorHdr = color r g b, colorSpace=0, method=1
        try:
            target_map.colorHdr = self.rt.color(r, g, b)
            target_map.colorSpace = 0
            target_map.method = 1
            self._set_status(f"Applied '{color_name}' (from {lib_name}) to {target_map.name}")
        except Exception as e:
            self._set_status(f"Apply failed: {e}", error=True)

    def serialize(self):
        return {
            "target_map_name": self.target_map_name,
            "target_map_handle": self.target_map_handle,
            "lib_folder": self.lib_folder,
            "color_column": self.color_column,
        }

    def deserialize(self, data):
        self.target_map_name = data.get("target_map_name", "")
        self.target_map_handle = data.get("target_map_handle", None)
        self.lib_folder = data.get("lib_folder", "")
        self.color_column = data.get("color_column", "")

        if self.target_map_name:
            self.lbl_map.setText(f"Target: {self.target_map_name}")
        if self.lib_folder:
            self._set_folder(self.lib_folder)
        # combo_color_col restored by on_columns_changed

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
            self._set_folder(folder)

    def _open_folder(self):
        if os.path.isdir(self.lib_folder):
            os.startfile(self.lib_folder)
        else:
            self._set_status("Library folder not set or missing.", error=True)

    def _on_folder_edited(self):
        path = self.edit_folder.text().strip()
        if not path:
            return
        if os.path.normpath(path) != self.lib_folder:
            self._set_folder(path)

    def _set_folder(self, folder):
        """Set the active library folder, refresh the UI, drop the cache and
        scan all CSVs for duplicate colour names."""
        self.lib_folder = os.path.normpath(folder)
        self.edit_folder.setText(self.lib_folder)
        self._lib_cache.clear()
        self._scan_libraries()

    def _scan_libraries(self):
        """Load every CSV in the folder: build the browsable colour list and warn
        if a colour name appears in more than one CSV with differing RGB values
        (first match wins at run time)."""
        self._all_colors = []  # [(orig_name, lib_name, (r, g, b))], for the browse list
        if not os.path.isdir(self.lib_folder):
            self.lbl_libs.setText("")
            self._populate_color_list()
            self._set_status(f"Library folder not found: '{self.lib_folder}'", error=True)
            return

        names = self._library_names()
        if not names:
            self.lbl_libs.setText("No .csv libraries found in folder.")
            self._populate_color_list()
            return

        # color_name (lower) -> {rounded_rgb: first_lib_name_seen}
        seen = {}
        conflicts = []  # (color_name, lib_a, lib_b)
        for lib_name in names:
            lib_data = self._load_library(lib_name)
            if not lib_data:
                continue
            for cname, (orig_name, r, g, b) in lib_data.items():
                rgb = (r, g, b)
                self._all_colors.append((orig_name, lib_name, rgb))
                rgb_key = tuple(round(c, 6) for c in rgb)
                prior = seen.get(cname)
                if prior is None:
                    seen[cname] = {rgb_key: lib_name}
                elif rgb_key not in prior:
                    # Same name, different colour in another library.
                    first_lib = next(iter(prior.values()))
                    conflicts.append((cname, first_lib, lib_name))
                    prior[rgb_key] = lib_name

        self._all_colors.sort(key=lambda c: (c[0].lower(), c[1].lower()))
        self._populate_color_list()
        self.lbl_libs.setText(f"{len(names)} libraries, {len(seen)} unique colour names.")
        if conflicts:
            preview = ", ".join(f"'{c}' ({a} vs {b})" for c, a, b in conflicts[:3])
            more = f" (+{len(conflicts) - 3} more)" if len(conflicts) > 3 else ""
            self._set_status(
                f"Warning: {len(conflicts)} colour name conflict(s) across libraries: "
                f"{preview}{more}. First match wins.",
                error=True,
            )
        else:
            self._set_status("")

    def _library_names(self):
        """Sorted list of library names (CSV filenames without extension)."""
        try:
            return sorted(
                os.path.splitext(f)[0]
                for f in os.listdir(self.lib_folder)
                if f.lower().endswith(".csv")
            )
        except Exception:
            return []

    # --- Browse / search colours ---

    def _populate_color_list(self):
        """Rebuild the browse list from self._all_colors, applying the current filter."""
        self.list_colors.clear()
        for orig_name, lib_name, rgb in self._all_colors:
            item = QtWidgets.QListWidgetItem(f"{orig_name}   —   {lib_name}")
            item.setIcon(self._swatch(rgb))
            # Store the bare colour name so copy yields exactly what execute() expects.
            item.setData(QtCore.Qt.UserRole, orig_name)
            item.setToolTip(f"{orig_name}\nLibrary: {lib_name}\nsRGB: {rgb[0]:.4f}, {rgb[1]:.4f}, {rgb[2]:.4f}")
            self.list_colors.addItem(item)
        self._filter_color_list(self.edit_search.text())

    def _filter_color_list(self, text):
        """Show only rows whose colour name contains the filter text (case-insensitive)."""
        needle = text.strip().lower()
        for i in range(self.list_colors.count()):
            item = self.list_colors.item(i)
            name = (item.data(QtCore.Qt.UserRole) or "").lower()
            item.setHidden(bool(needle) and needle not in name)

    def _swatch(self, rgb, size=14):
        """Build a small colour-swatch icon from sRGB [0..1] floats."""
        r, g, b = (max(0, min(255, int(round(c * 255)))) for c in rgb)
        pix = QtGui.QPixmap(size, size)
        pix.fill(QtGui.QColor(r, g, b))
        return QtGui.QIcon(pix)

    def _copy_selected_color(self):
        item = self.list_colors.currentItem()
        if item is None:
            self._set_status("No colour selected to copy.", error=True)
            return
        self._copy_color_item(item)

    def _copy_color_item(self, item):
        name = item.data(QtCore.Qt.UserRole) or ""
        QtWidgets.QApplication.clipboard().setText(name)
        self._set_status(f"Copied '{name}' to clipboard.")

    def _find_color_in_all_libraries(self, color_name):
        """Search every CSV in the folder for color_name (case-insensitive).
        Returns (rgb, lib_name) for the first match, or (None, None)."""
        key = color_name.lower()
        if not os.path.isdir(self.lib_folder):
            self._set_status(f"Library folder not found: '{self.lib_folder}'", error=True)
            return None, None
        for lib_name in self._library_names():
            lib_data = self._load_library(lib_name)
            if not lib_data:
                continue  # unreadable/empty CSV — skip, don't abort the whole search
            entry = lib_data.get(key)
            if entry is not None:
                _orig, r, g, b = entry
                return (r, g, b), lib_name
        return None, None

    def _load_library(self, lib_name):
        """Load and cache a library. Returns {lower_color_name: (orig_name, r, g, b)}
        or None. Keyed on the lower-cased name for case-insensitive lookup; the
        original casing is preserved for display."""
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
                    data[name.lower()] = (name, r, g, b)
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

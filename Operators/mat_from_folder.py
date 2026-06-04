from PySide6 import QtWidgets, QtCore
import os
import re
import fnmatch

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".exr", ".hdr", ".tga", ".bmp"}

_DEMO_BITMAPS = [
    "oak_diffuse_4k.jpg",
    "oak_rough_4k.jpg",
    "oak_normal_dx_4k.jpg",
    "oak_metalness_4k.jpg",
    "oak_ao_4k.jpg",
]


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _collect_bitmaps(rt, node, _seen=None):
    """Recursively walk a material/map graph, return every BitmapTexture display name."""
    if _seen is None:
        _seen = set()
    if node is None:
        return []
    try:
        handle = rt.GetHandleByAnim(node)
    except Exception:
        return []
    if handle in _seen:
        return []
    _seen.add(handle)

    if rt.classOf(node) == rt.BitmapTexture:
        try:
            name = str(node.name).strip()
            if name:
                return [name]
            return [os.path.basename(str(node.filename))]
        except Exception:
            return [""]

    results = []
    try:
        for i in range(1, rt.getNumSubMtls(node) + 1):
            results.extend(_collect_bitmaps(rt, rt.getSubMtl(node, i), _seen))
    except Exception:
        pass
    try:
        for i in range(1, rt.getNumSubTexmaps(node) + 1):
            results.extend(_collect_bitmaps(rt, rt.getSubTexmap(node, i), _seen))
    except Exception:
        pass
    return results


def _find_res_folder(path):
    """Return 8k > 4k subfolder if present, otherwise the folder itself."""
    for res in ("8k", "4k"):
        candidate = os.path.join(path, res)
        if os.path.isdir(candidate):
            return candidate
    return path


def _parse_size_to_cm(size_str, default_cm=100.0):
    """
    Convert a user-typed size string to cm.
    Accepts: '50cm', '1m', '300mm', '31.7' (assumed cm), '31,7cm' (European decimal).
    """
    s = size_str.strip().lower().replace(",", ".")
    for suffix, factor in (("mm", 0.1), ("cm", 1.0), ("m", 100.0)):
        if s.endswith(suffix):
            try:
                return float(s[:-len(suffix)].strip()) * factor
            except ValueError:
                pass
    try:
        return float(s)
    except ValueError:
        return default_cm


def _read_scale_from_metadata(folder_path):
    """
    Parse physical dimensions from METADATA.txt.
    Returns (u_cm, v_cm) or None if absent / unparseable.

    Handles European comma decimals, unit-per-value, and trailing unit:
      31,7x31,7 cm   →  (31.7, 31.7)
      38 cm x 38 cm  →  (38.0, 38.0)
      300mm x 150mm  →  (30.0, 15.0)
      1.5m x 2m      →  (150.0, 200.0)
    """
    meta = os.path.join(folder_path, "METADATA.txt")
    if not os.path.isfile(meta):
        return None
    try:
        with open(meta, "r", encoding="utf-8") as f:
            content = f.read()
        text = content.lower().replace(",", ".")
        num  = r"(\d+(?:\.\d+)?)"
        unit = r"\s*(mm|cm|m)?"
        m = re.search(rf"{num}{unit}\s*x\s*{num}{unit}", text)
        if not m:
            return None
        v1, u1, v2, u2 = m.group(1), m.group(2) or "", m.group(3), m.group(4) or ""
        # If neither number has an inline unit, look for a trailing unit after the match
        if not u1 and not u2:
            tail = text[m.end():m.end() + 4].strip()
            tm = re.match(r"(mm|cm|m)\b", tail)
            if tm:
                u1 = u2 = tm.group(1)
        elif not u1:
            u1 = u2
        elif not u2:
            u2 = u1

        def to_cm(v, u):
            v = float(v)
            if u == "mm": return v / 10.0
            if u == "m":  return v * 100.0
            return v   # cm or unknown

        return to_cm(v1, u1 or "cm"), to_cm(v2, u2 or "cm")
    except Exception:
        return None


def _swap_bitmaps(rt, node, override_map, folder, scale_mode, scale_u, scale_v, _seen=None):
    """
    Walk the node graph.  For every BitmapTexture whose display name (lower-cased)
    is a key in override_map, find a matching file in folder and update the
    node's filename + UVW coords in place.
    Returns the number of successful swaps.

    override_map : { "bitmap_display_name_lower": "pattern1|pattern2" }
    scale_mode   : "realworld"  → sets realWorldScale=True,  scale_u/v in cm
                   "tiling"     → sets realWorldScale=False, scale_u/v as tile counts
    """
    if _seen is None:
        _seen = set()
    if node is None:
        return 0
    try:
        handle = rt.GetHandleByAnim(node)
    except Exception:
        return 0
    if handle in _seen:
        return 0
    _seen.add(handle)

    if rt.classOf(node) == rt.BitmapTexture:
        try:
            node_display_name = str(node.name).strip().lower()
            if not node_display_name:
                node_display_name = os.path.basename(str(node.filename)).lower()
        except Exception:
            return 0

        pattern_str = override_map.get(node_display_name, "")
        if not pattern_str:
            return 0

        patterns = [p.strip() for p in pattern_str.split("|") if p.strip()]
        matched = None
        for pat in patterns:
            for f in os.listdir(folder):
                if fnmatch.fnmatch(f.lower(), pat.lower()) and os.path.splitext(f)[1].lower() in IMAGE_EXTS:
                    matched = f
                    break
            if matched:
                break

        if not matched:
            return 0

        try:
            node.filename = os.path.join(folder, matched)
            if scale_mode == "tiling":
                node.coords.realWorldScale = False
                node.coords.U_tile = float(scale_u)
                node.coords.V_tile = float(scale_v)
            else:  # realworld
                node.coords.realWorldScale  = True
                node.coords.realWorldWidth  = rt.units.decodeValue(f"{scale_u}cm")
                node.coords.realWorldHeight = rt.units.decodeValue(f"{scale_v}cm")
            node.reload()
            return 1
        except Exception as e:
            print(f"[MatFromFolder] Swap failed for '{node_display_name}': {e}")
            return 0

    count = 0
    try:
        for i in range(1, rt.getNumSubMtls(node) + 1):
            count += _swap_bitmaps(rt, rt.getSubMtl(node, i), override_map, folder, scale_mode, scale_u, scale_v, _seen)
    except Exception:
        pass
    try:
        for i in range(1, rt.getNumSubTexmaps(node) + 1):
            count += _swap_bitmaps(rt, rt.getSubTexmap(node, i), override_map, folder, scale_mode, scale_u, scale_v, _seen)
    except Exception:
        pass
    return count


class _ScanOnOpenCombo(QtWidgets.QComboBox):
    """QComboBox that refreshes its contents each time the dropdown is opened."""
    def __init__(self, scan_fn, parent=None):
        super().__init__(parent)
        self._scan_fn = scan_fn

    def showPopup(self):
        self._scan_fn()
        super().showPopup()


# ---------------------------------------------------------------------------
# Operator
# ---------------------------------------------------------------------------

class MatFromFolderOperator(QtCore.QObject):
    """
    Clones a captured source material, swaps its bitmap filenames by matching
    files in a texture folder against user-defined patterns, and assigns the
    result to a target slot / object.

    Folder path = root_folder / subfolder_column_value
    If no subfolder column is set the root folder is used directly.
    """
    status_changed = QtCore.Signal(str, bool)

    def __init__(self, context=None):
        super().__init__()
        self.rt = context.get("rt") if context else None

        self.source_mat_name   = ""
        self.source_mat_handle = None

        self.folder_root        = ""
        self.folder_root_mode   = "static"   # "static" | "column"
        self.folder_root_column = ""         # CSV column that provides the per-row root folder
        self.subfolder_column   = ""         # CSV column that provides the per-row subfolder

        self.scale_mode         = "realworld"   # "realworld" | "tiling"
        self.scale_default_u    = "100cm"       # fallback width for real-world mode
        self.scale_default_v    = "100cm"       # fallback height for real-world mode
        self.scale_use_metadata = True          # override with METADATA.txt when found
        self.scale_tile_u       = "1"           # tile counts for tiling mode
        self.scale_tile_v       = "1"

        self.target_mode        = "object"   # "material" | "object" | "multisub"
        self.target_mat_name    = ""
        self.target_mat_handle  = None
        self.target_node_name   = ""
        self.target_node_handle = None
        self.multisub_slot      = 1

        self.main_widget = QtWidgets.QWidget()
        self._setup_ui()

    # -----------------------------------------------------------------------
    # UI
    # -----------------------------------------------------------------------

    def _setup_ui(self):
        root = QtWidgets.QVBoxLayout(self.main_widget)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(10)

        self.lbl_status = QtWidgets.QLabel("")
        self.lbl_status.setWordWrap(True)
        root.addWidget(self.lbl_status)

        root.addWidget(self._build_source_group())
        root.addWidget(self._build_folder_group())
        root.addWidget(self._build_target_group())
        root.addWidget(self._build_overrides_group())

    # ---- Source material ---------------------------------------------------

    def _build_source_group(self):
        grp = QtWidgets.QGroupBox("1.  Source Material")
        lay = QtWidgets.QHBoxLayout(grp)
        lay.setSpacing(6)

        self.combo_source = _ScanOnOpenCombo(self._refresh_material_list)
        self.combo_source.setMinimumWidth(200)
        self.combo_source.setToolTip("All materials currently in the scene.")

        btn_refresh = QtWidgets.QPushButton("↻")
        btn_refresh.setFixedWidth(28)
        btn_refresh.setToolTip("Refresh material list from scene")

        self.btn_capture = QtWidgets.QPushButton("Capture Bitmaps")
        self.btn_capture.setToolTip(
            "Walk the selected material's node graph and list every\n"
            "BitmapTexture found as a row in the Overrides table."
        )

        self.lbl_capture_info = QtWidgets.QLabel("No bitmaps captured.")
        self.lbl_capture_info.setStyleSheet("color: #aaa;")

        lay.addWidget(self.combo_source, stretch=1)
        lay.addWidget(btn_refresh)
        lay.addWidget(self.btn_capture)
        lay.addWidget(self.lbl_capture_info)

        btn_refresh.clicked.connect(self._refresh_material_list)
        self.btn_capture.clicked.connect(self._capture_bitmaps)
        self.combo_source.currentTextChanged.connect(lambda t: setattr(self, "source_mat_name", t))

        return grp

    # ---- Texture folder ----------------------------------------------------

    def _build_folder_group(self):
        grp = QtWidgets.QGroupBox("2.  Texture Folder")
        grp.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)
        lay = QtWidgets.QVBoxLayout(grp)
        lay.setSpacing(5)
        lay.setContentsMargins(8, 8, 8, 8)

        # Root mode toggle
        row_mode = QtWidgets.QHBoxLayout()
        row_mode.addWidget(QtWidgets.QLabel("Root:"))
        self.chk_root_from_column = QtWidgets.QCheckBox("Get from CSV column")
        self.chk_root_from_column.setToolTip(
            "When enabled, the root folder is read per-row from a CSV column,\n"
            "so the same job can render textures from any folder."
        )
        row_mode.addWidget(self.chk_root_from_column)
        row_mode.addStretch()
        lay.addLayout(row_mode)

        # Stacked: page 0 = static path, page 1 = column picker
        self.root_stack = QtWidgets.QStackedWidget()

        page_static = QtWidgets.QWidget()
        static_lay = QtWidgets.QHBoxLayout(page_static)
        static_lay.setContentsMargins(0, 0, 0, 0)
        static_lay.setSpacing(6)
        self.edit_folder = QtWidgets.QLineEdit()
        self.edit_folder.setPlaceholderText("D:/Textures")
        btn_browse = QtWidgets.QPushButton("...")
        btn_browse.setFixedWidth(28)
        static_lay.addWidget(self.edit_folder, stretch=1)
        static_lay.addWidget(btn_browse)
        self.root_stack.addWidget(page_static)

        page_column = QtWidgets.QWidget()
        col_lay = QtWidgets.QHBoxLayout(page_column)
        col_lay.setContentsMargins(0, 0, 0, 0)
        col_lay.setSpacing(6)
        self.combo_root_col = QtWidgets.QComboBox()
        self.combo_root_col.setToolTip(
            "CSV column with the per-row root texture folder.\n"
            "Final path = column_value / subfolder (if set)"
        )
        col_lay.addWidget(self.combo_root_col, stretch=1)
        self.root_stack.addWidget(page_column)

        lay.addWidget(self.root_stack)

        # Subfolder column row
        row_sub = QtWidgets.QHBoxLayout()
        row_sub.addWidget(QtWidgets.QLabel("Subfolder:"))
        self.combo_subfolder_col = QtWidgets.QComboBox()
        self.combo_subfolder_col.setToolTip(
            "CSV column with the per-row material subfolder name.\n"
            "Final path = Root / column_value\n"
            "Leave at '-- none --' to use Root directly."
        )
        row_sub.addWidget(self.combo_subfolder_col, stretch=1)
        lay.addLayout(row_sub)

        # Separator
        sep = QtWidgets.QFrame()
        sep.setFrameShape(QtWidgets.QFrame.HLine)
        sep.setStyleSheet("color: #333;")
        lay.addWidget(sep)

        # Sizing mode radios
        row_mode = QtWidgets.QHBoxLayout()
        row_mode.addWidget(QtWidgets.QLabel("Sizing:"))
        self.radio_rws  = QtWidgets.QRadioButton("Real World Scale")
        self.radio_tile = QtWidgets.QRadioButton("Tiling")
        self.radio_rws.setChecked(True)
        row_mode.addWidget(self.radio_rws)
        row_mode.addWidget(self.radio_tile)
        row_mode.addStretch()
        lay.addLayout(row_mode)

        # Stacked widget — one page per sizing mode
        self.scale_stack = QtWidgets.QStackedWidget()

        # Page 0 – Real World Scale
        page_rws = QtWidgets.QWidget()
        rws_lay = QtWidgets.QHBoxLayout(page_rws)
        rws_lay.setContentsMargins(0, 0, 0, 0)
        rws_lay.setSpacing(6)
        rws_lay.addSpacing(12)
        rws_lay.addWidget(QtWidgets.QLabel("Default W:"))
        self.edit_scale_default_u = QtWidgets.QLineEdit("100cm")
        self.edit_scale_default_u.setFixedWidth(60)
        self.edit_scale_default_u.setToolTip(
            "Real-world width used when METADATA.txt is absent.\n"
            "Any unit accepted: 50cm  ·  1m  ·  300mm"
        )
        rws_lay.addWidget(self.edit_scale_default_u)
        rws_lay.addWidget(QtWidgets.QLabel("H:"))
        self.edit_scale_default_v = QtWidgets.QLineEdit("100cm")
        self.edit_scale_default_v.setFixedWidth(60)
        self.edit_scale_default_v.setToolTip(
            "Real-world height used when METADATA.txt is absent.\n"
            "Any unit accepted: 50cm  ·  1m  ·  300mm"
        )
        rws_lay.addWidget(self.edit_scale_default_v)
        self.chk_metadata = QtWidgets.QCheckBox("Override with METADATA.txt when found")
        self.chk_metadata.setChecked(True)
        rws_lay.addWidget(self.chk_metadata)
        rws_lay.addStretch()
        self.scale_stack.addWidget(page_rws)

        # Page 1 – Tiling
        page_tile = QtWidgets.QWidget()
        tile_lay = QtWidgets.QHBoxLayout(page_tile)
        tile_lay.setContentsMargins(0, 0, 0, 0)
        tile_lay.setSpacing(6)
        tile_lay.addSpacing(12)
        tile_lay.addWidget(QtWidgets.QLabel("Tiles U:"))
        self.edit_tile_u = QtWidgets.QLineEdit("1")
        self.edit_tile_u.setFixedWidth(45)
        self.edit_tile_u.setToolTip("U tile count.  1 = default,  2 = twice as dense.")
        tile_lay.addWidget(self.edit_tile_u)
        tile_lay.addWidget(QtWidgets.QLabel("V:"))
        self.edit_tile_v = QtWidgets.QLineEdit("1")
        self.edit_tile_v.setFixedWidth(45)
        tile_lay.addWidget(self.edit_tile_v)
        tile_lay.addStretch()
        self.scale_stack.addWidget(page_tile)

        lay.addWidget(self.scale_stack)

        # Connections
        btn_browse.clicked.connect(self._browse_folder)
        self.edit_folder.textChanged.connect(lambda t: setattr(self, "folder_root", t))
        self.chk_root_from_column.toggled.connect(self._on_root_mode_changed)
        self.combo_root_col.currentTextChanged.connect(self._on_root_col_changed)
        self.combo_subfolder_col.currentTextChanged.connect(self._on_subfolder_col_changed)
        self.radio_rws.toggled.connect(self._on_scale_mode_changed)
        self.edit_scale_default_u.textChanged.connect(lambda t: setattr(self, "scale_default_u", t))
        self.edit_scale_default_v.textChanged.connect(lambda t: setattr(self, "scale_default_v", t))
        self.chk_metadata.toggled.connect(lambda v: setattr(self, "scale_use_metadata", v))
        self.edit_tile_u.textChanged.connect(lambda t: setattr(self, "scale_tile_u", t))
        self.edit_tile_v.textChanged.connect(lambda t: setattr(self, "scale_tile_v", t))

        return grp

    # ---- Target assignment -------------------------------------------------

    def _build_target_group(self):
        grp = QtWidgets.QGroupBox("3.  Assign Result To")
        lay = QtWidgets.QVBoxLayout(grp)
        lay.setSpacing(4)

        # Row 1 – replace named material
        row_mat = QtWidgets.QHBoxLayout()
        self.radio_mat = QtWidgets.QRadioButton("Named Material:")
        self.combo_target_mat = _ScanOnOpenCombo(self._refresh_material_list)
        self.combo_target_mat.setMinimumWidth(160)
        self.combo_target_mat.setEnabled(False)
        self.combo_target_mat.setToolTip("Replace this material across every object that uses it.")
        row_mat.addWidget(self.radio_mat)
        row_mat.addWidget(self.combo_target_mat, stretch=1)
        row_mat.addStretch()
        lay.addLayout(row_mat)

        # Row 2 – object
        row_obj = QtWidgets.QHBoxLayout()
        self.radio_obj = QtWidgets.QRadioButton("Object:")
        self.radio_obj.setChecked(True)
        self.btn_pick_obj = QtWidgets.QPushButton("Pick from Scene")
        self.lbl_obj = QtWidgets.QLabel("(None)")
        self.lbl_obj.setStyleSheet("color: #aaa;")
        row_obj.addWidget(self.radio_obj)
        row_obj.addWidget(self.btn_pick_obj)
        row_obj.addWidget(self.lbl_obj)
        row_obj.addStretch()
        lay.addLayout(row_obj)

        # Row 3 – multi-sub slot
        row_multi = QtWidgets.QHBoxLayout()
        self.radio_multi = QtWidgets.QRadioButton("Multi-Sub Slot:")
        self.btn_pick_multi = QtWidgets.QPushButton("Pick from Scene")
        self.btn_pick_multi.setEnabled(False)
        self.lbl_multi = QtWidgets.QLabel("(None)")
        self.lbl_multi.setStyleSheet("color: #aaa;")
        self.spin_slot = QtWidgets.QSpinBox()
        self.spin_slot.setRange(1, 1000)
        self.spin_slot.setEnabled(False)
        self.spin_slot.setPrefix("Slot ")
        self.spin_slot.setFixedWidth(72)
        row_multi.addWidget(self.radio_multi)
        row_multi.addWidget(self.btn_pick_multi)
        row_multi.addWidget(self.lbl_multi)
        row_multi.addWidget(self.spin_slot)
        row_multi.addStretch()
        lay.addLayout(row_multi)

        self.radio_mat.toggled.connect(lambda c: self._on_target_mode("material", c))
        self.radio_obj.toggled.connect(lambda c: self._on_target_mode("object", c))
        self.radio_multi.toggled.connect(lambda c: self._on_target_mode("multisub", c))
        self.btn_pick_obj.clicked.connect(lambda: self._pick_node("object"))
        self.btn_pick_multi.clicked.connect(lambda: self._pick_node("multisub"))
        self.spin_slot.valueChanged.connect(lambda v: setattr(self, "multisub_slot", v))
        self.combo_target_mat.currentTextChanged.connect(lambda t: setattr(self, "target_mat_name", t))

        return grp

    # ---- Overrides ---------------------------------------------------------

    def _build_overrides_group(self):
        grp = QtWidgets.QGroupBox("4.  Bitmap Overrides")
        lay = QtWidgets.QVBoxLayout(grp)
        lay.setSpacing(4)

        hint = QtWidgets.QLabel(
            "Rows are populated by Capture Bitmaps.  "
            "Fill in a pattern to replace that bitmap node — leave blank to keep it unchanged.  "
            "Use  *  as wildcard and  |  as OR fallback  (e.g.  *rough*|*gloss*)."
        )
        hint.setStyleSheet("color: #888; font-size: 11px;")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        self.ov_table = QtWidgets.QTableWidget(0, 2)
        self.ov_table.setHorizontalHeaderLabels(["Captured Bitmap Node", "Pattern(s)"])
        hdr = self.ov_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        hdr.setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        self.ov_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.ov_table.setAlternatingRowColors(True)
        self.ov_table.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.ov_table.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.ov_table.setSizeAdjustPolicy(QtWidgets.QAbstractScrollArea.AdjustToContents)
        self.ov_table.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)
        self.ov_table.verticalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents)
        self.ov_table.model().rowsInserted.connect(lambda *_: self._fit_table_height())
        self.ov_table.model().rowsRemoved.connect(lambda *_: self._fit_table_height())
        lay.addWidget(self.ov_table)

        return grp

    # -----------------------------------------------------------------------
    # Override table helpers
    # -----------------------------------------------------------------------

    def _add_override_row(self, bitmap_name="", pattern=""):
        row = self.ov_table.rowCount()
        self.ov_table.insertRow(row)

        name_item = QtWidgets.QTableWidgetItem(bitmap_name)
        name_item.setToolTip(bitmap_name)
        name_item.setFlags(name_item.flags() & ~QtCore.Qt.ItemIsEditable)
        name_item.setForeground(
            self.ov_table.palette().color(self.ov_table.foregroundRole()).darker(130)
        )
        self.ov_table.setItem(row, 0, name_item)
        self.ov_table.setItem(row, 1, QtWidgets.QTableWidgetItem(pattern))

    def _fit_table_height(self):
        t = self.ov_table
        h = t.horizontalHeader().height() + t.frameWidth() * 2
        for r in range(t.rowCount()):
            h += t.rowHeight(r)
        t.setFixedHeight(h)

    def _read_overrides(self):
        result = []
        for row in range(self.ov_table.rowCount()):
            bmp_item = self.ov_table.item(row, 0)
            pat_item = self.ov_table.item(row, 1)
            result.append({
                "bitmap":  bmp_item.text() if bmp_item else "",
                "pattern": pat_item.text() if pat_item else "",
            })
        return result

    # -----------------------------------------------------------------------
    # Source material
    # -----------------------------------------------------------------------

    def _refresh_material_list(self):
        names = []
        if self.rt:
            try:
                for m in self.rt.sceneMaterials:
                    names.append(m.name)
            except Exception:
                pass
        else:
            names = ["[Demo] OakParquet", "[Demo] ConcreteWall", "[Demo] MetalPanel"]

        for combo in (self.combo_source, self.combo_target_mat):
            combo.blockSignals(True)
            saved = combo.currentText()
            combo.clear()
            combo.addItem("-- Select --")
            combo.addItems(names)
            idx = combo.findText(saved)
            combo.setCurrentIndex(idx if idx != -1 else 0)
            combo.blockSignals(False)

    def _capture_bitmaps(self):
        mat_name = self.combo_source.currentText()
        if mat_name in ("-- Select --", ""):
            self._set_status("Select a source material first.", True)
            return

        if self.rt:
            mat = None
            try:
                for m in self.rt.sceneMaterials:
                    if m.name == mat_name:
                        mat = m
                        self.source_mat_handle = self.rt.GetHandleByAnim(mat)
                        break
            except Exception as e:
                self._set_status(f"Error accessing scene: {e}", True)
                return
            if mat is None:
                self._set_status(f"Material '{mat_name}' not found in scene.", True)
                return
            bitmaps = _collect_bitmaps(self.rt, mat)
        else:
            bitmaps = _DEMO_BITMAPS

        self.source_mat_name = mat_name
        self.ov_table.setRowCount(0)
        for bmp in bitmaps:
            self._add_override_row(bitmap_name=bmp)

        count = len(bitmaps)
        self.lbl_capture_info.setText(f"{count} bitmap(s) found.")
        self.lbl_capture_info.setStyleSheet("color: #66ff66;" if count else "color: #ff6666;")
        if count:
            self._set_status(f"Captured {count} bitmap(s) from '{mat_name}'.")
        else:
            self._set_status(f"No BitmapTexture nodes found in '{mat_name}'.", True)

    # -----------------------------------------------------------------------
    # Target / folder handlers
    # -----------------------------------------------------------------------

    def _on_target_mode(self, mode, checked):
        if not checked:
            return
        self.target_mode = mode
        self.combo_target_mat.setEnabled(mode == "material")
        self.btn_pick_obj.setEnabled(mode == "object")
        self.btn_pick_multi.setEnabled(mode == "multisub")
        self.spin_slot.setEnabled(mode == "multisub")

    def _pick_node(self, role):
        if not self.rt:
            name = "(Demo) Wall_01" if role == "object" else "(Demo) Floor_01"
            self._set_status("[STUB] Would pick the selected object from the scene.")
            lbl = self.lbl_obj if role == "object" else self.lbl_multi
            lbl.setText(name)
            lbl.setStyleSheet("color: #66ff66;")
            return
        sel = self.rt.selection
        if not sel:
            self._set_status("Select an object in 3ds Max first.", True)
            return
        obj = sel[0]
        self.target_node_name   = obj.name
        self.target_node_handle = self.rt.GetHandleByAnim(obj)
        lbl = self.lbl_obj if role == "object" else self.lbl_multi
        lbl.setText(obj.name)
        lbl.setStyleSheet("color: #66ff66;")
        self._set_status("")

    def _on_subfolder_col_changed(self, text):
        self.subfolder_column = "" if text == "-- none --" else text

    def _on_root_mode_changed(self, checked):
        self.folder_root_mode = "column" if checked else "static"
        self.root_stack.setCurrentIndex(1 if checked else 0)

    def _on_root_col_changed(self, text):
        self.folder_root_column = "" if text == "-- Select Column --" else text

    def _on_scale_mode_changed(self):
        if self.radio_rws.isChecked():
            self.scale_mode = "realworld"
            self.scale_stack.setCurrentIndex(0)
        else:
            self.scale_mode = "tiling"
            self.scale_stack.setCurrentIndex(1)

    def _browse_folder(self):
        folder = QtWidgets.QFileDialog.getExistingDirectory(self.main_widget, "Select Root Texture Folder")
        if folder:
            self.edit_folder.setText(folder)

    # -----------------------------------------------------------------------
    # Manager interface
    # -----------------------------------------------------------------------

    def get_ui(self):
        return self.main_widget

    def on_columns_changed(self, columns):
        self.combo_subfolder_col.blockSignals(True)
        saved = self.subfolder_column
        self.combo_subfolder_col.clear()
        self.combo_subfolder_col.addItem("-- none --")
        self.combo_subfolder_col.addItems(columns)
        idx = self.combo_subfolder_col.findText(saved)
        self.combo_subfolder_col.setCurrentIndex(idx if idx != -1 else 0)
        self.combo_subfolder_col.blockSignals(False)

        self.combo_root_col.blockSignals(True)
        saved_root = self.folder_root_column
        self.combo_root_col.clear()
        self.combo_root_col.addItem("-- Select Column --")
        self.combo_root_col.addItems(columns)
        idx = self.combo_root_col.findText(saved_root)
        self.combo_root_col.setCurrentIndex(idx if idx != -1 else 0)
        self.combo_root_col.blockSignals(False)
        self.folder_root_column = "" if self.combo_root_col.currentText() == "-- Select Column --" else self.combo_root_col.currentText()

    # -----------------------------------------------------------------------
    # Execute
    # -----------------------------------------------------------------------

    def execute(self, row_data):
        if not self.rt:
            self._set_status("3ds Max runtime not available.", True)
            return
        self._execute_real(row_data)

    def _execute_real(self, row_data):
        # 1. Resolve folder
        if self.folder_root_mode == "column":
            if not self.folder_root_column:
                self._set_status("Root mode is 'CSV column' but no column is selected — check step 2.", True)
                return
            if self.folder_root_column not in row_data:
                self._set_status(f"Root column '{self.folder_root_column}' missing from row.", True)
                return
            root = row_data[self.folder_root_column].strip()
            if not root:
                self._set_status(f"Root column '{self.folder_root_column}' is empty for this row.", True)
                return
        else:
            if not self.folder_root:
                self._set_status("No root folder set — check step 2.", True)
                return
            root = self.folder_root

        subfolder = row_data.get(self.subfolder_column, "").strip() if self.subfolder_column else ""
        folder = os.path.join(root, subfolder) if subfolder else root

        if not os.path.isdir(folder):
            self._set_status(f"Folder not found: {folder}", True)
            return

        # 2. Resolution subfolder (8k > 4k > flat)
        res_folder = _find_res_folder(folder)

        # 3. Resolve scale
        if self.scale_mode == "tiling":
            try:
                scale_u = float(self.scale_tile_u)
            except ValueError:
                scale_u = 1.0
            try:
                scale_v = float(self.scale_tile_v)
            except ValueError:
                scale_v = 1.0
        else:  # realworld
            metadata = _read_scale_from_metadata(folder) if self.scale_use_metadata else None
            if metadata:
                scale_u, scale_v = metadata
            else:
                scale_u = _parse_size_to_cm(self.scale_default_u)
                scale_v = _parse_size_to_cm(self.scale_default_v)

        # 4. Clone source material — look up by name first (handles are session-specific).
        if not self.source_mat_name:
            self._set_status("No source material captured — use 'Capture Bitmaps' first.", True)
            return
        source_mat = None
        for m in self.rt.sceneMaterials:
            if m.name == self.source_mat_name:
                source_mat = m
                self.source_mat_handle = self.rt.GetHandleByAnim(m)
                break
        if source_mat is None and self.source_mat_handle:
            source_mat = self.rt.GetAnimByHandle(self.source_mat_handle)
        if source_mat is None:
            self._set_status("Source material no longer in scene — re-capture.", True)
            return
        clone = self.rt.copy(source_mat)

        # 5. Swap bitmaps
        overrides = self._read_overrides()
        override_map = {
            ov["bitmap"].lower(): ov["pattern"]
            for ov in overrides
            if ov["bitmap"] and ov["pattern"]
        }
        swapped = _swap_bitmaps(self.rt, clone, override_map, res_folder, self.scale_mode, scale_u, scale_v)

        # 6. Assign to target
        if self.target_mode in ("object", "multisub"):
            # Resolve node by name first — handles are session-specific.
            node = None
            if self.target_node_name:
                node = self.rt.getNodeByName(self.target_node_name)
                if node:
                    self.target_node_handle = self.rt.GetHandleByAnim(node)
            if not node and self.target_node_handle:
                node = self.rt.GetAnimByHandle(self.target_node_handle)
            if not node:
                self._set_status("Target object not found in scene.", True)
                return

        if self.target_mode == "object":
            node.material = clone

        elif self.target_mode == "multisub":
            multi = node.material
            if not multi or self.rt.classOf(multi) != self.rt.MultiMaterial:
                self._set_status("Object does not have a Multi-Sub material.", True)
                return
            if self.multisub_slot > len(multi.materialList):
                multi.numsubs = self.multisub_slot
            multi.materialList[self.multisub_slot - 1] = clone

        elif self.target_mode == "material":
            target_name = self.target_mat_name
            if not target_name:
                self._set_status("Target material not found.", True)
                return
            replaced = 0
            for obj in self.rt.objects:
                try:
                    if self.rt.isValidNode(obj) and self.rt.isProperty(obj, "material"):
                        if obj.material and str(obj.material.name) == target_name:
                            obj.material = clone
                            replaced += 1
                except Exception:
                    pass
            self._set_status(
                f"Replaced '{target_name}' on {replaced} object(s). "
                f"{swapped} bitmap(s) swapped."
            )
            return

        res_label = os.path.basename(res_folder) if res_folder != folder else "root"
        if self.scale_mode == "tiling":
            scale_info = f"tiling {scale_u}×{scale_v}"
        else:
            scale_info = f"RWS {scale_u:.1f}×{scale_v:.1f}cm"
        self._set_status(f"Done.  {swapped} bitmap(s) swapped.  [{res_label}  {scale_info}]")

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _set_status(self, msg, error=False):
        self.lbl_status.setText(msg)
        self.lbl_status.setStyleSheet(f"color: {'#ff6666' if error else '#66ff66'};")
        self.status_changed.emit(msg, error)

    # -----------------------------------------------------------------------
    # Persistence
    # -----------------------------------------------------------------------

    def serialize(self):
        return {
            "source_mat_name":    self.source_mat_name,
            "source_mat_handle":  self.source_mat_handle,
            "folder_root":        self.folder_root,
            "folder_root_mode":   self.folder_root_mode,
            "folder_root_column": self.folder_root_column,
            "subfolder_column":   self.subfolder_column,
            "scale_mode":         self.scale_mode,
            "scale_default_u":    self.scale_default_u,
            "scale_default_v":    self.scale_default_v,
            "scale_use_metadata": self.scale_use_metadata,
            "scale_tile_u":       self.scale_tile_u,
            "scale_tile_v":       self.scale_tile_v,
            "target_mode":        self.target_mode,
            "target_mat_name":    self.target_mat_name,
            "target_mat_handle":  self.target_mat_handle,
            "target_node_name":   self.target_node_name,
            "target_node_handle": self.target_node_handle,
            "multisub_slot":      self.multisub_slot,
            "overrides":          self._read_overrides(),
        }

    def deserialize(self, data):
        self.source_mat_name    = data.get("source_mat_name",    "")
        self.source_mat_handle  = data.get("source_mat_handle",  None)
        self.folder_root        = data.get("folder_root",        "")
        self.folder_root_mode   = data.get("folder_root_mode",   "static")
        self.folder_root_column = data.get("folder_root_column", "")
        self.subfolder_column   = data.get("subfolder_column",   "")
        self.scale_mode         = data.get("scale_mode",         "realworld")
        self.scale_default_u    = data.get("scale_default_u",    "100cm")
        self.scale_default_v    = data.get("scale_default_v",    "100cm")
        self.scale_use_metadata = data.get("scale_use_metadata", True)
        self.scale_tile_u       = data.get("scale_tile_u",       "1")
        self.scale_tile_v       = data.get("scale_tile_v",       "1")
        self.target_mode        = data.get("target_mode",        "object")
        self.target_mat_name    = data.get("target_mat_name",    "")
        self.target_mat_handle  = data.get("target_mat_handle",  None)
        self.target_node_name   = data.get("target_node_name",   "")
        self.target_node_handle = data.get("target_node_handle", None)
        self.multisub_slot      = data.get("multisub_slot",      1)

        self.edit_folder.setText(self.folder_root)
        self.chk_root_from_column.blockSignals(True)
        self.chk_root_from_column.setChecked(self.folder_root_mode == "column")
        self.chk_root_from_column.blockSignals(False)
        self.root_stack.setCurrentIndex(1 if self.folder_root_mode == "column" else 0)
        self.spin_slot.setValue(self.multisub_slot)
        self.edit_scale_default_u.setText(self.scale_default_u)
        self.edit_scale_default_v.setText(self.scale_default_v)
        self.chk_metadata.setChecked(self.scale_use_metadata)
        self.edit_tile_u.setText(self.scale_tile_u)
        self.edit_tile_v.setText(self.scale_tile_v)

        if self.scale_mode == "tiling":
            self.radio_tile.setChecked(True)
        else:
            self.radio_rws.setChecked(True)

        if self.target_mode == "material":
            self.radio_mat.setChecked(True)
        elif self.target_mode == "multisub":
            self.radio_multi.setChecked(True)
        else:
            self.radio_obj.setChecked(True)

        if self.source_mat_name:
            idx = self.combo_source.findText(self.source_mat_name)
            if idx != -1:
                self.combo_source.setCurrentIndex(idx)

        if self.target_node_name:
            lbl   = self.lbl_obj if self.target_mode != "multisub" else self.lbl_multi
            lbl.setText(self.target_node_name)
            lbl.setStyleSheet("color: #66ff66;")

        self.ov_table.setRowCount(0)
        for ov in data.get("overrides", []):
            self._add_override_row(ov.get("bitmap", ""), ov.get("pattern", ""))

        if self.source_mat_name:
            count = self.ov_table.rowCount()
            self.lbl_capture_info.setText(f"{count} bitmap(s) found.")
            self.lbl_capture_info.setStyleSheet("color: #66ff66;" if count else "color: #aaa;")

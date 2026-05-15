from PySide6 import QtWidgets, QtCore
import os

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".exr", ".hdr", ".tga", ".bmp"}

# CoronaPhysicalMaterial property names (MaxScript). Adjust here if a future
# Corona release renames any of these.
PROP_OPACITY      = "opacityLevel"
PROP_ROUGHNESS    = "baseRoughness"
PROP_TRANSLUCENCY = "translucencyFraction"
PROP_SHEEN        = "sheenAmount"
PROP_THIN_MODE    = "useThinMode"


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _parse_slot_range(spec):
    """'1,2,5-7,12' -> [1, 2, 5, 6, 7, 12]. Sorted and deduplicated.
    Tolerates whitespace and empty parts. Raises ValueError on malformed input."""
    out = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            start = int(a.strip())
            end   = int(b.strip())
            if start < 1 or end < start:
                raise ValueError(f"bad range '{part}'")
            out.update(range(start, end + 1))
        else:
            n = int(part)
            if n < 1:
                raise ValueError(f"bad index '{part}'")
            out.add(n)
    return sorted(out)


def _parse_size_to_cm(size_str, default_cm=100.0):
    """Convert '50cm' / '1m' / '300mm' / '31.7' (cm) / '31,7cm' (European) to cm.
    Returns default_cm on parse failure."""
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


def _image_aspect_h_over_w(rt, image_path):
    """Open image_path with rt.openBitMap and return height/width.
    Returns 1.0 on any failure (square fallback)."""
    try:
        bv = rt.openBitMap(image_path)
        if bv and float(bv.width) > 0:
            return float(bv.height) / float(bv.width)
    except Exception:
        pass
    return 1.0


def _find_image(folder, fabric_name):
    """Recursively walk folder. Return the first file whose stem matches
    fabric_name (case-insensitive) and whose extension is an image extension.
    Returns None if not found."""
    if not folder or not os.path.isdir(folder):
        return None
    target = fabric_name.strip().lower()
    if not target:
        return None
    for dirpath, _dirs, files in os.walk(folder):
        for f in files:
            stem, ext = os.path.splitext(f)
            if ext.lower() in IMAGE_EXTS and stem.lower() == target:
                return os.path.join(dirpath, f)
    return None


# ---------------------------------------------------------------------------
# Operator
# ---------------------------------------------------------------------------

class FabricOperator(QtCore.QObject):
    """
    Build a fresh CoronaPhysicalMtl each row from a fabric image
    (CSV name -> recursive folder lookup) with CSV-driven real-world width
    and opacity / roughness / translucency / sheen overrides. Each numeric
    property has a static fallback used when its column is unmapped or its
    cell is empty. thinMode is always on.

    Static fields: fabric folder, target object/material, slot range, and
    the per-property fallback values.
    Driven properties: fabric name (required), width / opacity / roughness /
    translucency / sheen (each optional, with fallback).
    """
    status_changed = QtCore.Signal(str, bool)

    def __init__(self, context=None):
        super().__init__()
        self.rt          = context.get("rt") if context else None
        self.instance_id = context.get("instance_id", "") if context else ""

        self.folder_root = ""

        self.target_mode        = "object"   # "object" | "multisub"
        self.target_node_name   = ""
        self.target_node_handle = None
        self.target_mat_name    = ""
        self.target_mat_handle  = None
        self.slot_range_spec    = ""

        self.col_fabric       = ""
        self.col_width        = ""
        self.col_opacity      = ""
        self.col_roughness    = ""
        self.col_translucency = ""
        self.col_sheen        = ""

        # Per-property static fallback values (used when the column is
        # unmapped or the row's cell is empty). Width has a hard 100cm
        # baseline; numeric props are empty by default = "do not set".
        self.static_width        = "100cm"
        self.static_opacity      = ""
        self.static_roughness    = ""
        self.static_translucency = ""
        self.static_sheen        = ""

        self.main_widget = QtWidgets.QWidget()
        self._setup_ui()

    # -----------------------------------------------------------------------
    # UI
    # -----------------------------------------------------------------------

    def _setup_ui(self):
        root = QtWidgets.QVBoxLayout(self.main_widget)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(0)

        self.lbl_status = QtWidgets.QLabel("")
        self.lbl_status.setWordWrap(True)
        root.addWidget(self.lbl_status)
        root.addSpacing(4)

        # --- Card 1: fabric folder ---
        grp1 = QtWidgets.QGroupBox("1. Fabric Folder")
        lay1 = QtWidgets.QVBoxLayout(grp1)
        lay1.setContentsMargins(16, 12, 16, 12)
        lay1.setSpacing(8)

        lay1.addWidget(QtWidgets.QLabel("Root folder (recursive search):"))
        row_root = QtWidgets.QHBoxLayout()
        self.edit_folder = QtWidgets.QLineEdit()
        self.edit_folder.setPlaceholderText("D:/Fabrics")
        btn_browse = QtWidgets.QPushButton("...")
        btn_browse.setFixedWidth(28)
        row_root.addWidget(self.edit_folder, stretch=1)
        row_root.addWidget(btn_browse)
        lay1.addLayout(row_root)

        root.addWidget(grp1)
        root.addSpacing(8)

        # --- Card 2: target ---
        grp2 = QtWidgets.QGroupBox("2. Target")
        lay2 = QtWidgets.QVBoxLayout(grp2)
        lay2.setContentsMargins(16, 12, 16, 12)
        lay2.setSpacing(8)

        self.radio_obj   = QtWidgets.QRadioButton("Object — replace material")
        self.radio_multi = QtWidgets.QRadioButton("Multi-Sub Material — write to slot(s)")
        self.radio_obj.setChecked(True)
        self.btn_grp = QtWidgets.QButtonGroup(self.main_widget)
        self.btn_grp.addButton(self.radio_obj)
        self.btn_grp.addButton(self.radio_multi)
        lay2.addWidget(self.radio_obj)
        lay2.addWidget(self.radio_multi)

        sep = QtWidgets.QFrame()
        sep.setFrameShape(QtWidgets.QFrame.HLine)
        lay2.addWidget(sep)
        lay2.addSpacing(4)

        row_pick = QtWidgets.QHBoxLayout()
        self.btn_pick   = QtWidgets.QPushButton("Pick from Scene")
        self.lbl_target = QtWidgets.QLabel("Target: (None)")
        row_pick.addWidget(self.btn_pick)
        row_pick.addWidget(self.lbl_target, stretch=1)
        lay2.addLayout(row_pick)

        row_slot = QtWidgets.QHBoxLayout()
        row_slot.addWidget(QtWidgets.QLabel("Slot range:"))
        self.edit_slot = QtWidgets.QLineEdit()
        self.edit_slot.setPlaceholderText("1,2,5-7,12")
        self.edit_slot.setEnabled(False)
        row_slot.addWidget(self.edit_slot, stretch=1)
        lay2.addLayout(row_slot)

        root.addWidget(grp2)
        root.addSpacing(8)

        # --- Card 3: column mapping (with per-property static fallbacks) ---
        grp3 = QtWidgets.QGroupBox("3. Column Mapping")
        lay3 = QtWidgets.QVBoxLayout(grp3)
        lay3.setContentsMargins(16, 12, 16, 12)
        lay3.setSpacing(8)

        # Fabric name — required, no fallback.
        lay3.addWidget(QtWidgets.QLabel("Fabric name (required):"))
        self.combo_fabric = QtWidgets.QComboBox()
        lay3.addWidget(self.combo_fabric)

        sep3 = QtWidgets.QFrame()
        sep3.setFrameShape(QtWidgets.QFrame.HLine)
        lay3.addWidget(sep3)
        lay3.addSpacing(4)

        hint = QtWidgets.QLabel(
            "Each row maps a column and a static fallback. "
            "Cell empty or column unmapped → fallback is used. "
            "Fallback empty → property left at material default."
        )
        hint.setWordWrap(True)
        lay3.addWidget(hint)

        # Numeric/size rows — pair a combo with a small static fallback edit.
        self.combo_width,        self.edit_static_width        = self._build_mapping_row(
            lay3, "Real-world width:", "140cm", "100cm")
        self.combo_opacity,      self.edit_static_opacity      = self._build_mapping_row(
            lay3, "Opacity (0–1):",     "0.85",  "")
        self.combo_roughness,    self.edit_static_roughness    = self._build_mapping_row(
            lay3, "Roughness (0–1):",   "0.5",   "")
        self.combo_translucency, self.edit_static_translucency = self._build_mapping_row(
            lay3, "Translucency (0–1):", "0.0",  "")
        self.combo_sheen,        self.edit_static_sheen        = self._build_mapping_row(
            lay3, "Sheen amount (0–1):", "0.0",  "")

        root.addWidget(grp3)
        root.addStretch()

        # --- Signals ---
        btn_browse.clicked.connect(self._browse_folder)
        self.edit_folder.textChanged.connect(lambda t: setattr(self, "folder_root", t))
        self.radio_obj.toggled.connect(  lambda c: c and self._on_target_mode("object"))
        self.radio_multi.toggled.connect(lambda c: c and self._on_target_mode("multisub"))
        self.btn_pick.clicked.connect(self._pick_target)
        self.edit_slot.textChanged.connect(lambda t: setattr(self, "slot_range_spec", t))

        self.combo_fabric.currentTextChanged.connect(
            lambda t: setattr(self, "col_fabric", "" if t == "-- Select Column --" else t)
        )
        for combo, col_attr in (
            (self.combo_width,        "col_width"),
            (self.combo_opacity,      "col_opacity"),
            (self.combo_roughness,    "col_roughness"),
            (self.combo_translucency, "col_translucency"),
            (self.combo_sheen,        "col_sheen"),
        ):
            combo.currentTextChanged.connect(
                lambda t, a=col_attr: setattr(self, a, "" if t == "-- none --" else t)
            )
        for edit, static_attr in (
            (self.edit_static_width,        "static_width"),
            (self.edit_static_opacity,      "static_opacity"),
            (self.edit_static_roughness,    "static_roughness"),
            (self.edit_static_translucency, "static_translucency"),
            (self.edit_static_sheen,        "static_sheen"),
        ):
            edit.textChanged.connect(
                lambda t, a=static_attr: setattr(self, a, t)
            )

    def _build_mapping_row(self, parent_layout, label, combo_placeholder_hint, static_initial):
        """Build a 'Label: [combo] [static fallback edit]' row inside parent_layout.
        Returns (combo, static_edit). The static edit's placeholder shows the
        expected value format (combo_placeholder_hint), while static_initial
        seeds the field's value (use '' for 'do not set by default')."""
        parent_layout.addWidget(QtWidgets.QLabel(label))
        row = QtWidgets.QHBoxLayout()
        combo = QtWidgets.QComboBox()
        edit  = QtWidgets.QLineEdit(static_initial)
        edit.setFixedWidth(80)
        edit.setPlaceholderText(combo_placeholder_hint)
        edit.setToolTip(
            "Static fallback used when the column above is unmapped or its row cell is empty.\n"
            "Leave empty to skip this property entirely (material default kept)."
        )
        row.addWidget(combo, stretch=1)
        row.addWidget(edit)
        parent_layout.addLayout(row)
        return combo, edit

    # -----------------------------------------------------------------------
    # UI handlers
    # -----------------------------------------------------------------------

    def _browse_folder(self):
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self.main_widget, "Select Fabric Root Folder"
        )
        if folder:
            self.edit_folder.setText(folder)

    def _on_target_mode(self, mode):
        self.target_mode = mode
        self.edit_slot.setEnabled(mode == "multisub")
        self.btn_pick.setText(
            "Pick from Scene" if mode == "object" else "Pick Multi-Sub from Scene"
        )
        if mode == "object":
            self.lbl_target.setText(f"Target: {self.target_node_name or '(None)'}")
        else:
            self.lbl_target.setText(f"Target: {self.target_mat_name or '(None)'}")

    def _pick_target(self):
        if not self.rt:
            self._set_status("3ds Max runtime not available.", True)
            return
        if self.target_mode == "object":
            sel = self.rt.selection
            if not sel:
                self._set_status("Select an object in 3ds Max first.", True)
                return
            obj = sel[0]
            self.target_node_name   = obj.name
            self.target_node_handle = self.rt.GetHandleByAnim(obj)
            self.lbl_target.setText(f"Target: {self.target_node_name}")
            self._set_status("")
        else:
            mats = list(self.rt.getClassInstances(self.rt.MultiMaterial))
            if not mats:
                self._set_status("No Multi-Sub materials in scene.", True)
                return
            mat_dict = {m.name: m for m in mats}
            item, ok = QtWidgets.QInputDialog.getItem(
                self.main_widget, "Select Multi-Sub", "Materials:",
                sorted(mat_dict.keys()), 0, False,
            )
            if not (ok and item):
                return
            target = mat_dict[item]
            self.target_mat_name   = target.name
            self.target_mat_handle = self.rt.GetHandleByAnim(target)
            self.lbl_target.setText(f"Target: {self.target_mat_name}")
            self._set_status("")

    # -----------------------------------------------------------------------
    # Manager interface
    # -----------------------------------------------------------------------

    def get_ui(self):
        return self.main_widget

    def on_columns_changed(self, columns):
        # Required combo (fabric name)
        self.combo_fabric.blockSignals(True)
        self.combo_fabric.clear()
        self.combo_fabric.addItem("-- Select Column --")
        self.combo_fabric.addItems(columns)
        idx = self.combo_fabric.findText(self.col_fabric)
        self.combo_fabric.setCurrentIndex(idx if idx != -1 else 0)
        self.combo_fabric.blockSignals(False)
        cur = self.combo_fabric.currentText()
        self.col_fabric = "" if cur == "-- Select Column --" else cur

        # Optional combos
        for combo, attr in (
            (self.combo_width,        "col_width"),
            (self.combo_opacity,      "col_opacity"),
            (self.combo_roughness,    "col_roughness"),
            (self.combo_translucency, "col_translucency"),
            (self.combo_sheen,        "col_sheen"),
        ):
            combo.blockSignals(True)
            saved = getattr(self, attr)
            combo.clear()
            combo.addItem("-- none --")
            combo.addItems(columns)
            idx = combo.findText(saved)
            combo.setCurrentIndex(idx if idx != -1 else 0)
            combo.blockSignals(False)
            cur = combo.currentText()
            setattr(self, attr, "" if cur == "-- none --" else cur)

    # -----------------------------------------------------------------------
    # Execute
    # -----------------------------------------------------------------------

    def execute(self, row_data):
        if not self.rt:
            self._set_status("3ds Max runtime not available.", True)
            return
        if not self.folder_root:
            self._set_status("No fabric folder set.", True)
            return
        if not self.col_fabric:
            self._set_status("No fabric column selected.", True)
            return
        if self.col_fabric not in row_data:
            self._set_status(f"Column '{self.col_fabric}' missing in row.", True)
            return
        fabric_name = row_data[self.col_fabric].strip()
        if not fabric_name:
            self._set_status("Fabric name cell is empty.", True)
            return
        image_path = _find_image(self.folder_root, fabric_name)
        if not image_path:
            self._set_status(
                f"Image '{fabric_name}' not found under '{self.folder_root}'.", True
            )
            return

        # --- Resolve target ---
        node = None
        multi = None
        slots = []

        if self.target_mode == "object":
            if self.target_node_name:
                node = self.rt.getNodeByName(self.target_node_name)
                if node:
                    self.target_node_handle = self.rt.GetHandleByAnim(node)
            if not node and self.target_node_handle:
                node = self.rt.GetAnimByHandle(self.target_node_handle)
            if not node:
                self._set_status("Target object not found in scene.", True)
                return
        else:
            if self.target_mat_name:
                for m in self.rt.getClassInstances(self.rt.MultiMaterial):
                    if m.name == self.target_mat_name:
                        multi = m
                        self.target_mat_handle = self.rt.GetHandleByAnim(m)
                        break
            if not multi and self.target_mat_handle:
                multi = self.rt.GetAnimByHandle(self.target_mat_handle)
            if not multi:
                self._set_status("Target Multi-Sub material not found in scene.", True)
                return
            try:
                slots = _parse_slot_range(self.slot_range_spec)
            except ValueError as e:
                self._set_status(f"Invalid slot range: {e}", True)
                return
            if not slots:
                self._set_status("Slot range is empty — set e.g. '1,2,5-7,12'.", True)
                return

        # --- Resolve width (required, hard-fallback to 100cm). ---
        width_raw, width_src = self._resolve_value(
            row_data, self.col_width, self.static_width
        )
        if width_raw is None:
            width_cm = 100.0
            width_src = "hardcoded 100cm"
        else:
            width_cm = _parse_size_to_cm(width_raw, default_cm=-1.0)
            if width_cm <= 0:
                self._set_status(
                    f"Width value '{width_raw}' ({width_src}) is not parseable.", True
                )
                return

        aspect_h = _image_aspect_h_over_w(self.rt, image_path)
        height_cm = width_cm * aspect_h

        # --- Build the fresh material ---
        bmp = self.rt.BitmapTexture(filename=image_path)
        try:
            bmp.coords.realWorldScale  = True
            bmp.coords.realWorldWidth  = self.rt.units.decodeValue(f"{width_cm}cm")
            bmp.coords.realWorldHeight = self.rt.units.decodeValue(f"{height_cm}cm")
        except Exception as e:
            self._set_status(f"Failed to set real-world scale: {e}", True)
            return
        mat = self.rt.CoronaPhysicalMtl()
        safe = "".join(c for c in fabric_name if c.isalnum() or c in "_-")
        mat.name = f"VB_Fabric_{safe}" if safe else "VB_Fabric"
        mat.baseTexmap = bmp
        try:
            setattr(mat, PROP_THIN_MODE, True)
        except Exception as e:
            self._set_status(f"Failed to set {PROP_THIN_MODE}: {e}", True)
            return

        # --- Optional overrides (column wins, else static fallback). ---
        applied = []
        for col_attr, static_attr, prop_name, label in (
            ("col_opacity",      "static_opacity",      PROP_OPACITY,      "opacity"),
            ("col_roughness",    "static_roughness",    PROP_ROUGHNESS,    "roughness"),
            ("col_translucency", "static_translucency", PROP_TRANSLUCENCY, "translucency"),
            ("col_sheen",        "static_sheen",        PROP_SHEEN,        "sheen"),
        ):
            raw, src = self._resolve_value(
                row_data, getattr(self, col_attr), getattr(self, static_attr)
            )
            if raw is None:
                continue
            try:
                value = float(raw.replace(",", "."))
            except ValueError:
                self._set_status(
                    f"{label} value '{raw}' ({src}) is not numeric.", True
                )
                return
            try:
                setattr(mat, prop_name, value)
            except Exception as e:
                self._set_status(f"Failed to set {label} ({prop_name}): {e}", True)
                return
            applied.append(f"{label}={value}")

        # --- Assign ---
        if self.target_mode == "object":
            node.material = mat
            location = f"object '{node.name}'"
        else:
            max_slot = max(slots)
            if max_slot > len(multi.materialList):
                multi.numsubs = max_slot
            for slot in slots:
                multi.materialList[slot - 1] = mat
            slot_summary = ",".join(str(s) for s in slots)
            location = f"slot(s) {slot_summary} of '{multi.name}'"

        size_info = f"{width_cm:.1f}×{height_cm:.1f}cm"
        extra = (" [" + ", ".join(applied) + "]") if applied else ""
        self._set_status(
            f"Applied '{os.path.basename(image_path)}' "
            f"({size_info}) to {location}{extra}."
        )

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _resolve_value(self, row_data, col_name, static_value):
        """Return (raw_string, source_label) from CSV cell or static fallback.
        Cell wins when the column is mapped, present in row_data, and non-empty.
        Returns (None, None) when neither yields anything usable."""
        if col_name and col_name in row_data:
            cell = row_data[col_name].strip()
            if cell:
                return cell, f"column '{col_name}'"
        s = (static_value or "").strip()
        if s:
            return s, "static fallback"
        return None, None

    def _set_status(self, msg, error=False):
        self.lbl_status.setText(msg)
        self.lbl_status.setStyleSheet("color: #ff6666;" if error else "color: #66ff66;")
        self.status_changed.emit(msg, error)

    # -----------------------------------------------------------------------
    # Persistence
    # -----------------------------------------------------------------------

    def serialize(self):
        return {
            "folder_root":         self.folder_root,
            "target_mode":         self.target_mode,
            "target_node_name":    self.target_node_name,
            "target_node_handle":  self.target_node_handle,
            "target_mat_name":     self.target_mat_name,
            "target_mat_handle":   self.target_mat_handle,
            "slot_range_spec":     self.slot_range_spec,
            "col_fabric":          self.col_fabric,
            "col_width":           self.col_width,
            "col_opacity":         self.col_opacity,
            "col_roughness":       self.col_roughness,
            "col_translucency":    self.col_translucency,
            "col_sheen":           self.col_sheen,
            "static_width":        self.static_width,
            "static_opacity":      self.static_opacity,
            "static_roughness":    self.static_roughness,
            "static_translucency": self.static_translucency,
            "static_sheen":        self.static_sheen,
        }

    def deserialize(self, data):
        self.folder_root         = data.get("folder_root",         "")
        self.target_mode         = data.get("target_mode",         "object")
        self.target_node_name    = data.get("target_node_name",    "")
        self.target_node_handle  = data.get("target_node_handle",  None)
        self.target_mat_name     = data.get("target_mat_name",     "")
        self.target_mat_handle   = data.get("target_mat_handle",   None)
        self.slot_range_spec     = data.get("slot_range_spec",     "")
        self.col_fabric          = data.get("col_fabric",          "")
        self.col_width           = data.get("col_width",           "")
        self.col_opacity         = data.get("col_opacity",         "")
        self.col_roughness       = data.get("col_roughness",       "")
        self.col_translucency    = data.get("col_translucency",    "")
        self.col_sheen           = data.get("col_sheen",           "")
        self.static_width        = data.get("static_width",        "100cm")
        self.static_opacity      = data.get("static_opacity",      "")
        self.static_roughness    = data.get("static_roughness",    "")
        self.static_translucency = data.get("static_translucency", "")
        self.static_sheen        = data.get("static_sheen",        "")

        self.edit_folder.setText(self.folder_root)
        self.edit_slot.setText(self.slot_range_spec)
        self.edit_static_width.setText(self.static_width)
        self.edit_static_opacity.setText(self.static_opacity)
        self.edit_static_roughness.setText(self.static_roughness)
        self.edit_static_translucency.setText(self.static_translucency)
        self.edit_static_sheen.setText(self.static_sheen)

        if self.target_mode == "multisub":
            self.radio_multi.setChecked(True)
        else:
            self.radio_obj.setChecked(True)
        # Explicit sync — toggled won't fire if the radio was already checked.
        self._on_target_mode(self.target_mode)

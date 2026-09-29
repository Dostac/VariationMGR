"""
MatFromFolder V2 — one material is both source and target.

* Pick a material, Capture Bitmaps.  Per row its BitmapTexture files are
  swapped IN PLACE from the row's texture folder: no clone, no assignment,
  every object / multi-sub slot using the material updates by itself.  The
  material lives in the scene, so there is nothing to lose when a Slate
  Material Editor view is closed.
* Patterns are derived automatically from the bitmap node names
  (COL, ROUGH, METAL, NRM … any case → 'auto:COL').  A typed glob overrides;
  a blank cell uses the auto pattern; '-' keeps the node unchanged.
* If missing.  Per bitmap row: what to load when the row's folder has no
  matching map — white, mid-gray, black (tiny PNGs generated on demand in the
  local temp folder, so every render worker makes its own) or no change (keep
  the previous row's map).  Defaults by map type: OPAC / AO white,
  METAL / DISP black, everything else no change.
* Texture size from metadata.json (TEXTURE_SIZE.cm) with legacy METADATA.txt
  fallback; highest NNk resolution subfolder picked automatically.
"""
from PySide6 import QtWidgets, QtCore
import os
import re
import json
import zlib
import struct
import fnmatch
import tempfile

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".exr", ".hdr", ".tga", ".bmp"}

_DEMO_BITMAPS = [
    ("oak_diffuse_4k.jpg",   "D:/Textures/Oak/oak_diffuse_4k.jpg"),
    ("oak_rough_4k.jpg",     "D:/Textures/Oak/oak_rough_4k.jpg"),
    ("oak_normal_dx_4k.jpg", "D:/Textures/Oak/oak_normal_dx_4k.jpg"),
    ("oak_metalness_4k.jpg", "D:/Textures/Oak/oak_metalness_4k.jpg"),
    ("oak_ao_4k.jpg",        "D:/Textures/Oak/oak_ao_4k.jpg"),
]


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _collect_bitmaps(rt, node, _seen=None):
    """Walk a material/map graph → [(display_name, filename), …] for every BitmapTexture."""
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
            filename = str(node.filename or "")
            name = str(node.name or "").strip() or os.path.basename(filename)
            return [(name, filename)]
        except Exception:
            return [("", "")]

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


_RES_TAG_RE = re.compile(r"^(\d+)k$", re.IGNORECASE)   # 1K, 2k, 4K, 8K …


def _find_res_folder(path):
    """
    Return the highest-resolution subfolder (8K > 4K > 2K …, any case),
    otherwise the folder itself.  Reawote / Poliigon folders keep one
    subfolder per resolution next to metadata.json and PREVIEW/.
    """
    try:
        entries = os.listdir(path)
    except OSError:
        return path
    best, best_val = None, -1
    for name in entries:
        m = _RES_TAG_RE.match(name)
        if not m or not os.path.isdir(os.path.join(path, name)):
            continue
        val = int(m.group(1))
        if val > best_val:
            best, best_val = name, val
    return os.path.join(path, best) if best else path


def _list_image_files(folder):
    """Sorted image filenames in folder (one listing per run — the NAS is slow)."""
    try:
        return sorted(
            f for f in os.listdir(folder)
            if os.path.splitext(f)[1].lower() in IMAGE_EXTS
        )
    except OSError:
        return []


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


def _load_json_lenient(path):
    """json.load that tolerates the trailing commas some Reawote metadata.json files ship with."""
    with open(path, "r", encoding="utf-8-sig") as f:
        text = f.read()
    try:
        return json.loads(text)
    except ValueError:
        return json.loads(re.sub(r",\s*([}\]])", r"\1", text))


def _read_scale_from_metadata_json(folder_path):
    """
    Physical size from metadata.json (Reawote / Unlit-Manager format):
        {"TEXTURE_SIZE": {"cm": {"width": 21.634, "height": 21.555}, ...}}
    Returns (u_cm, v_cm) or None if absent / unreadable / zero.
    """
    meta = os.path.join(folder_path, "metadata.json")
    if not os.path.isfile(meta):
        return None
    try:
        data = _load_json_lenient(meta)
        cm = (data.get("TEXTURE_SIZE") or {}).get("cm") or {}
        w, h = float(cm.get("width", 0) or 0), float(cm.get("height", 0) or 0)
        if w > 0 and h > 0:
            return w, h
    except Exception as e:
        print(f"[MatFromFolderV2] metadata.json unreadable in {folder_path}: {e}")
    return None


def _read_scale_from_metadata_txt(folder_path):
    """
    Parse physical dimensions from legacy METADATA.txt.
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
            return v

        return to_cm(v1, u1 or "cm"), to_cm(v2, u2 or "cm")
    except Exception:
        return None


def _read_scale_from_metadata(folder_path):
    """
    Texture size in cm from the material folder — metadata.json first, legacy
    METADATA.txt second.  If folder_path itself is a resolution folder (4K/8K)
    the parent is tried as well.  Returns (u_cm, v_cm) or None.
    """
    norm = os.path.normpath(folder_path)
    candidates = [norm]
    if _RES_TAG_RE.match(os.path.basename(norm) or ""):
        candidates.append(os.path.dirname(norm))
    for folder in candidates:
        size = _read_scale_from_metadata_json(folder) or _read_scale_from_metadata_txt(folder)
        if size:
            return size
    return None


# Map-token vocabulary (mirrors Unlit-Manager's pbr_tokens).  One group per
# texture slot; the first entry is the Reawote short name and the display form.
# Groups stay separate where one folder ships both variants
# (ROUGH vs GLOSS, NRM vs NRM16, DISP vs DISP16).
MAP_TOKENS = (
    ("COL", "COLOR", "COLOUR", "DIFF", "DIFFUSE", "BASECOLOR", "ALBEDO"),
    ("AO", "AMBIENTOCCLUSION", "OCCLUSION"),
    ("ROUGH", "ROUGHNESS"),
    ("GLOSS", "GLOSSINESS"),
    ("METAL", "METALNESS", "METALLIC"),
    ("OPAC", "OPACITY", "ALPHA"),
    ("NRM16",),
    ("NRM", "NORMAL", "NORM"),
    ("DISP16", "HEIGHT16"),
    ("DISP", "DISPLACEMENT", "DISPLACE", "HEIGHT"),
    ("REFL", "REFLECTION", "SPEC", "SPECULAR"),
    ("BUMP",),
    ("EMIS", "EMISSIVE", "EMISSION"),
    ("SSS", "TRANSLUCENCY", "TRANSL"),
)
_TOKEN_GROUP = {tok: group for group in MAP_TOKENS for tok in group}
AUTO_PREFIX = "auto:"
SKIP_PATTERN = "-"          # pattern cell value that keeps a node unchanged


def _name_segments(name):
    """Upper-cased alphanumeric segments of a node or file name (image extension dropped)."""
    stem, ext = os.path.splitext(name or "")
    if ext.lower() not in IMAGE_EXTS:
        stem = name or ""
    return [p.upper() for p in re.split(r"[^A-Za-z0-9]+", stem) if p]


def _auto_pattern(node_name):
    """
    Derive an 'auto:TOKEN' pattern from a bitmap node name, or "" if no map
    token is recognised.  Segments are scanned from the right, case-insensitive,
    so "COL", "Wood col", "Diffuse Color" and "Oak_COL_4K.jpg" all give "auto:COL".
    """
    for seg in reversed(_name_segments(node_name)):
        group = _TOKEN_GROUP.get(seg)
        if group:
            return AUTO_PREFIX + group[0]
    return ""


_HIGH_BIT = {"NRM": "NRM16", "DISP": "DISP16"}   # 8-bit token → 16-bit sibling


def _downgrade_high_bit(node_name, pattern):
    """
    Earlier versions filled 'auto:NRM16' / 'auto:DISP16' for a node named e.g.
    'normal' when the template used the 16-bit map.  The 16-bit TIFs are ~8×
    larger and slow to load, so those auto-generated cells go back to the 8-bit
    token (which still falls back to the 16-bit file when no 8-bit one exists).
    A node explicitly named NRM16 / DISP16 keeps its 16-bit pattern.
    """
    auto = _auto_pattern(node_name)
    if not auto or not pattern:
        return pattern
    token = auto[len(AUTO_PREFIX):]
    if token in _HIGH_BIT and pattern.strip().lower() == (AUTO_PREFIX + _HIGH_BIT[token]).lower():
        return auto
    return pattern


def _auto_variants(node_name):
    """Lower-cased auto patterns capture may generate for a node (e.g. auto:nrm and auto:nrm16)."""
    pattern = _auto_pattern(node_name)
    if not pattern:
        return set()
    token = pattern[len(AUTO_PREFIX):]
    return {pattern.lower(), (AUTO_PREFIX + _HIGH_BIT.get(token, token)).lower()}


def _file_token(filename):
    """
    Map token of a texture filename: the last stem segment, or the one before
    it when the last segment is a resolution tag.
        "X_COL_4K.jpg"          → "COL"
        "Wood_4K_Color.png"     → "COLOR"
        "TCom_Y_4K_albedo.tif"  → "ALBEDO"
    """
    segs = _name_segments(filename)
    if len(segs) >= 2 and _RES_TAG_RE.match(segs[-1]):
        return segs[-2]
    return segs[-1] if segs else ""


def _match_token(token, files):
    """
    First file whose map token equals `token` or one of its aliases
    (group order — Reawote short name first).  Falls back to the token as a
    whole segment anywhere in the name, then to a plain substring.
    """
    token = token.strip().upper()
    if not token:
        return None
    group = _TOKEN_GROUP.get(token, (token,))
    aliases = [token] + [a for a in group if a != token]
    by_token = {}
    for f in files:
        by_token.setdefault(_file_token(f), []).append(f)
    for alias in aliases:
        if alias in by_token:
            return by_token[alias][0]
    for f in files:
        if token in _name_segments(f):
            return f
    for f in files:
        if token in f.upper():
            return f
    return None


def _match_file(pattern_str, files):
    """
    Resolve a pattern cell against a file list.  Patterns are '|'-separated
    alternatives tried in order; each is either 'auto:TOKEN' (see _match_token)
    or a case-insensitive fnmatch glob.  Returns the filename or None.
    """
    for pat in (p.strip() for p in pattern_str.split("|")):
        if not pat:
            continue
        if pat.lower().startswith(AUTO_PREFIX):
            hit = _match_token(pat[len(AUTO_PREFIX):], files)
        else:
            hit = next((f for f in files if fnmatch.fnmatch(f.lower(), pat.lower())), None)
        if hit:
            return hit
    return None


# "If missing" choices: key → (label, 8-bit gray value or None for "keep previous").
FALLBACKS = (
    ("keep",    "No change (keep previous)", None),
    ("white",   "White",                     255),
    ("midgray", "Mid-gray",                  128),
    ("black",   "Black",                     0),
)
_FALLBACK_LABEL = {k: label for k, label, _ in FALLBACKS}
_FALLBACK_VALUE = {k: v for k, _, v in FALLBACKS}
_FALLBACK_DIR = os.path.join(tempfile.gettempdir(), "VariationMGR_fallback")

# Default "if missing" per auto token — a map that is absent means "no effect".
_DEFAULT_FALLBACK = {
    "OPAC": "white", "AO": "white",
    "METAL": "black", "DISP": "black", "DISP16": "black",
}


def _default_fallback(pattern):
    """Default 'if missing' for a pattern cell: by auto token, else keep previous."""
    p = (pattern or "").strip()
    if p.lower().startswith(AUTO_PREFIX):
        return _DEFAULT_FALLBACK.get(p[len(AUTO_PREFIX):].strip().upper(), "keep")
    return "keep"


def _write_gray_png(path, value, size=8):
    """Minimal 8-bit grayscale PNG (no PIL needed inside 3ds Max)."""
    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + bytes([value]) * size for _ in range(size))
    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 0, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 9))
           + chunk(b"IEND", b""))
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(png)
    os.replace(tmp, path)           # atomic: parallel rows never read half a file


def _fallback_file(key):
    """Path of the generated fallback image for `key`, or None for 'keep'."""
    value = _FALLBACK_VALUE.get(key)
    if value is None:
        return None
    path = os.path.join(_FALLBACK_DIR, f"fallback_{key}.png")
    try:
        if not os.path.isfile(path) or os.path.getsize(path) == 0:
            os.makedirs(_FALLBACK_DIR, exist_ok=True)
            _write_gray_png(path, value)
    except OSError as e:
        print(f"[MatFromFolderV2] Could not write fallback image {path}: {e}")
        return None
    return path


def _swap_bitmaps(rt, node, override_map, folder, files, scale_mode, scale_u, scale_v, stats, _seen=None):
    """
    Walk the node graph.  For every BitmapTexture whose display name (lower-cased)
    is a key in override_map, resolve its pattern against `files` and update the
    node's filename + UVW coords in place.  No match → the row's 'if missing'
    choice: a generated white / mid-gray / black image, or keep the current file.

    override_map : { "bitmap_display_name_lower": (pattern, fallback_key) }
    files        : image filenames in folder (from _list_image_files)
    scale_mode   : "realworld"  → realWorldScale=True,  scale_u/v in cm
                   "tiling"     → realWorldScale=False, scale_u/v as tile counts
    stats        : lists of node names per outcome
    """
    if _seen is None:
        _seen = set()
    if node is None:
        return
    try:
        handle = rt.GetHandleByAnim(node)
    except Exception:
        return
    if handle in _seen:
        return
    _seen.add(handle)

    if rt.classOf(node) == rt.BitmapTexture:
        try:
            display = str(node.name or "").strip()
            if not display:
                display = os.path.basename(str(node.filename or ""))
        except Exception:
            return

        entry = override_map.get(display.lower())
        if not entry:
            return
        pattern, fallback = entry
        if not pattern:
            return                                  # no pattern → node untouched

        try:
            old_file = str(node.filename or "")
        except Exception:
            old_file = ""

        matched = _match_file(pattern, files)
        if matched:
            new_file, kind = os.path.join(folder, matched), "swapped"
        else:
            new_file = _fallback_file(fallback)
            if new_file is None:
                stats["kept"].append(display)
                return
            kind = "fallback"
        if _same_path(old_file, new_file):
            kind = "unchanged"

        try:
            node.filename = new_file
            if scale_mode == "tiling":
                node.coords.realWorldScale = False
                node.coords.U_tile = float(scale_u)
                node.coords.V_tile = float(scale_v)
            else:  # realworld
                node.coords.realWorldScale  = True
                node.coords.realWorldWidth  = rt.units.decodeValue(f"{scale_u}cm")
                node.coords.realWorldHeight = rt.units.decodeValue(f"{scale_v}cm")
            node.reload()
        except Exception as e:
            stats["failed"].append(display)
            return
        try:
            now = str(node.filename or "")
        except Exception:
            now = ""
        if kind != "unchanged" and not _same_path(now, new_file):
            stats["failed"].append(display)
            return
        stats[kind].append(display)
        return

    try:
        for i in range(1, rt.getNumSubMtls(node) + 1):
            _swap_bitmaps(rt, rt.getSubMtl(node, i), override_map, folder, files, scale_mode, scale_u, scale_v, stats, _seen)
    except Exception:
        pass
    try:
        for i in range(1, rt.getNumSubTexmaps(node) + 1):
            _swap_bitmaps(rt, rt.getSubTexmap(node, i), override_map, folder, files, scale_mode, scale_u, scale_v, stats, _seen)
    except Exception:
        pass


def _same_path(a, b):
    """Case- and separator-insensitive path compare (Windows, UNC)."""
    if not a or not b:
        return False
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


class _NoWheelCombo(QtWidgets.QComboBox):
    """Table-cell combo that ignores the mouse wheel, so scrolling the tab never changes it."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)

    def wheelEvent(self, event):
        event.ignore()


class _ScanOnOpenCombo(QtWidgets.QComboBox):
    """QComboBox that refreshes its contents each time the dropdown is opened."""
    def __init__(self, scan_fn, parent=None):
        super().__init__(parent)
        self._scan_fn = scan_fn

    def showPopup(self):
        self._scan_fn()
        super().showPopup()


def _iter_scene_materials(rt):
    """Every material in the scene, top-level and nested (multi-sub slots, blends …), once each."""
    seen = set()
    stack = []
    try:
        stack = list(rt.sceneMaterials)
    except Exception:
        pass
    stack.reverse()
    while stack:
        m = stack.pop()
        if m is None:
            continue
        try:
            h = rt.GetHandleByAnim(m)
        except Exception:
            continue
        if h in seen:
            continue
        seen.add(h)
        yield m
        try:
            subs = [rt.getSubMtl(m, i) for i in range(1, rt.getNumSubMtls(m) + 1)]
        except Exception:
            subs = []
        stack.extend(reversed(subs))


def _iter_scene_materials_under(rt, mat):
    """All sub-materials below mat (not mat itself)."""
    stack, seen = [], set()
    try:
        stack = [rt.getSubMtl(mat, i) for i in range(1, rt.getNumSubMtls(mat) + 1)]
    except Exception:
        pass
    while stack:
        m = stack.pop()
        if m is None:
            continue
        try:
            h = rt.GetHandleByAnim(m)
        except Exception:
            continue
        if h in seen:
            continue
        seen.add(h)
        yield m
        try:
            stack.extend(rt.getSubMtl(m, i) for i in range(1, rt.getNumSubMtls(m) + 1))
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Operator
# ---------------------------------------------------------------------------

class MatFromFolderV2Operator(QtCore.QObject):
    """
    One material is both source and target.  Per row its BitmapTexture files
    are swapped in place from the row's texture folder, so every object and
    multi-sub slot that uses the material updates without re-assignment.

    Folder path = root_folder / subfolder_column_value
    If no subfolder column is set the root folder is used directly.
    """
    status_changed = QtCore.Signal(str, bool)

    def __init__(self, context=None):
        super().__init__()
        self.rt = context.get("rt") if context else None
        self.instance_id = context.get("instance_id", "") if context else ""

        self.mat_name           = ""         # the material: template and target
        self._ambiguous         = 0          # candidates when re-linking by bitmaps was a tie

        self.folder_root        = ""
        self.folder_root_mode   = "static"   # "static" | "column"
        self.folder_root_column = ""
        self.subfolder_column   = ""

        self.scale_mode         = "realworld"   # "realworld" | "tiling"
        self.scale_default_u    = "100cm"
        self.scale_default_v    = "100cm"
        self.scale_use_metadata = True
        self.scale_tile_u       = "1"
        self.scale_tile_v       = "1"

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

        root.addWidget(self._build_material_group())
        root.addWidget(self._build_folder_group())
        root.addWidget(self._build_overrides_group())

    # ---- Material ----------------------------------------------------------

    def _build_material_group(self):
        grp = QtWidgets.QGroupBox("1.  Material")
        lay = QtWidgets.QHBoxLayout(grp)
        lay.setSpacing(6)

        self.combo_mat = _ScanOnOpenCombo(self._refresh_material_list)
        self.combo_mat.setMinimumWidth(200)
        self.combo_mat.setToolTip(
            "The material whose bitmaps are swapped each row — source and target in one.\n"
            "It is edited in place, so every object and multi-sub slot using it updates.\n"
            "Lists top-level and nested (multi-sub) materials."
        )

        btn_refresh = QtWidgets.QPushButton("↻")
        btn_refresh.setFixedWidth(28)
        btn_refresh.setToolTip("Refresh material list from scene")

        self.btn_capture = QtWidgets.QPushButton("Capture Bitmaps")
        self.btn_capture.setToolTip(
            "List every BitmapTexture of the material in the Overrides table,\n"
            "derive its pattern from the node name and pick an 'If missing' default.\n"
            "Re-capturing keeps typed patterns and 'If missing' choices."
        )

        self.lbl_capture_info = QtWidgets.QLabel("No bitmaps captured.")
        self.lbl_capture_info.setStyleSheet("color: #aaa;")

        lay.addWidget(self.combo_mat, stretch=1)
        lay.addWidget(btn_refresh)
        lay.addWidget(self.btn_capture)
        lay.addWidget(self.lbl_capture_info)

        btn_refresh.clicked.connect(self._refresh_material_list)
        self.btn_capture.clicked.connect(self._capture_bitmaps)
        self.combo_mat.currentTextChanged.connect(self._on_mat_changed)

        return grp

    # ---- Texture folder ----------------------------------------------------

    def _build_folder_group(self):
        grp = QtWidgets.QGroupBox("2.  Texture Folder")
        grp.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)
        lay = QtWidgets.QVBoxLayout(grp)
        lay.setSpacing(5)
        lay.setContentsMargins(8, 8, 8, 8)

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

        sep = QtWidgets.QFrame()
        sep.setFrameShape(QtWidgets.QFrame.HLine)
        sep.setStyleSheet("color: #333;")
        lay.addWidget(sep)

        row_size = QtWidgets.QHBoxLayout()
        row_size.addWidget(QtWidgets.QLabel("Sizing:"))
        self.radio_rws  = QtWidgets.QRadioButton("Real World Scale")
        self.radio_tile = QtWidgets.QRadioButton("Tiling")
        self.radio_rws.setChecked(True)
        row_size.addWidget(self.radio_rws)
        row_size.addWidget(self.radio_tile)
        row_size.addStretch()
        lay.addLayout(row_size)

        self.scale_stack = QtWidgets.QStackedWidget()

        page_rws = QtWidgets.QWidget()
        rws_lay = QtWidgets.QHBoxLayout(page_rws)
        rws_lay.setContentsMargins(0, 0, 0, 0)
        rws_lay.setSpacing(6)
        rws_lay.addSpacing(12)
        rws_lay.addWidget(QtWidgets.QLabel("Default W:"))
        self.edit_scale_default_u = QtWidgets.QLineEdit("100cm")
        self.edit_scale_default_u.setFixedWidth(60)
        self.edit_scale_default_u.setToolTip(
            "Real-world width used when no metadata.json / METADATA.txt is found.\n"
            "Any unit accepted: 50cm  ·  1m  ·  300mm"
        )
        rws_lay.addWidget(self.edit_scale_default_u)
        rws_lay.addWidget(QtWidgets.QLabel("H:"))
        self.edit_scale_default_v = QtWidgets.QLineEdit("100cm")
        self.edit_scale_default_v.setFixedWidth(60)
        self.edit_scale_default_v.setToolTip(
            "Real-world height used when no metadata.json / METADATA.txt is found.\n"
            "Any unit accepted: 50cm  ·  1m  ·  300mm"
        )
        rws_lay.addWidget(self.edit_scale_default_v)
        self.chk_metadata = QtWidgets.QCheckBox("Use texture size from metadata")
        self.chk_metadata.setToolTip(
            "Reads the physical size from the material folder:\n"
            "  metadata.json  →  TEXTURE_SIZE.cm.width / height   (Reawote / Unlit-Manager)\n"
            "  METADATA.txt   →  '31,7 x 31,7 cm'                   (legacy)\n"
            "Falls back to Default W / H when neither is found."
        )
        self.chk_metadata.setChecked(True)
        rws_lay.addWidget(self.chk_metadata)
        rws_lay.addStretch()
        self.scale_stack.addWidget(page_rws)

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

    # ---- Overrides ---------------------------------------------------------

    def _build_overrides_group(self):
        grp = QtWidgets.QGroupBox("3.  Bitmap Overrides")
        lay = QtWidgets.QVBoxLayout(grp)
        lay.setSpacing(4)

        hint = QtWidgets.QLabel(
            "Capture fills a pattern for every bitmap from its node name  "
            "(COL, ROUGH, METAL, NRM …, any case → auto:COL).  "
            "Edit a cell to override: globs with  *  and  |  as OR fallback  (e.g.  *rough*|*gloss*).  "
            "A blank cell uses the auto pattern;  type  -  to keep a node unchanged.  "
            "If missing:  what to load when the row's folder has no matching map."
        )
        hint.setStyleSheet("color: #888; font-size: 11px;")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        self.ov_table = QtWidgets.QTableWidget(0, 3)
        self.ov_table.setHorizontalHeaderLabels(["Bitmap Node", "Pattern(s)", "If missing"])
        hdr = self.ov_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        hdr.setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        hdr.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
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

    def _add_override_row(self, bitmap_name="", pattern="", fallback=None):
        row = self.ov_table.rowCount()
        self.ov_table.insertRow(row)
        dim = self.ov_table.palette().color(self.ov_table.foregroundRole()).darker(130)

        name_item = QtWidgets.QTableWidgetItem(bitmap_name)
        name_item.setToolTip(bitmap_name)
        name_item.setFlags(name_item.flags() & ~QtCore.Qt.ItemIsEditable)
        name_item.setForeground(dim)
        self.ov_table.setItem(row, 0, name_item)

        self.ov_table.setItem(row, 1, QtWidgets.QTableWidgetItem(pattern))

        combo = _NoWheelCombo()
        for key, label, _ in FALLBACKS:
            combo.addItem(label, key)
        key = fallback if fallback in _FALLBACK_LABEL else _default_fallback(pattern or _auto_pattern(bitmap_name))
        combo.setCurrentIndex(max(0, combo.findData(key)))
        combo.setToolTip(
            "Loaded when the row's folder has no file for this pattern:\n"
            "  White / Mid-gray / Black — a flat generated image (8-bit, same gamma as the maps it replaces)\n"
            "  No change — keeps whatever the previous row loaded"
        )
        self.ov_table.setCellWidget(row, 2, combo)

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
            combo    = self.ov_table.cellWidget(row, 2)
            result.append({
                "bitmap":   bmp_item.text() if bmp_item else "",
                "pattern":  pat_item.text() if pat_item else "",
                "fallback": (combo.currentData() if combo else None) or "keep",
            })
        return result

    def _override_map(self):
        """
        { node_name_lower: (pattern, fallback_key) } as executed.  Blank cell →
        auto pattern from the node name; '-' → node skipped.
        """
        result = {}
        for ov in self._read_overrides():
            if not ov["bitmap"]:
                continue
            pattern = ov["pattern"].strip()
            if pattern == SKIP_PATTERN:
                continue
            if not pattern:
                pattern = _auto_pattern(ov["bitmap"])
            result[ov["bitmap"].lower()] = (pattern, ov["fallback"])
        return result

    # -----------------------------------------------------------------------
    # Material
    # -----------------------------------------------------------------------

    def _refresh_material_list(self):
        names = []
        if self.rt:
            seen = set()
            for m in _iter_scene_materials(self.rt):
                try:
                    n = str(m.name)
                except Exception:
                    continue
                if n and n not in seen:
                    seen.add(n)
                    names.append(n)
        else:
            names = ["[Demo] OakParquet", "[Demo] ConcreteWall", "[Demo] MetalPanel"]

        combo = self.combo_mat
        combo.blockSignals(True)
        saved = self.mat_name or combo.currentText()
        combo.clear()
        combo.addItem("-- Select --")
        combo.addItems(names)
        idx = combo.findText(saved)
        if idx == -1 and saved and saved != "-- Select --":
            combo.addItem(saved)                     # keep a saved name visible even if absent
            idx = combo.count() - 1
        combo.setCurrentIndex(idx if idx != -1 else 0)
        combo.blockSignals(False)

    def _on_mat_changed(self, text):
        self.mat_name = "" if text == "-- Select --" else text

    def _find_material(self):
        """First material from _find_materials(), or None."""
        mats = self._find_materials()
        return mats[0] if mats else None

    def _find_materials(self):
        """
        Every scene material (top-level or nested) named mat_name — duplicates
        with the same name are all edited, so it cannot matter which one an
        object carries.  When none matches, fall back to the one material that
        contains the captured bitmap nodes (only if unambiguous), re-link to it
        and show it in the combo.
        """
        if not self.rt:
            return []
        self._ambiguous = 0
        if self.mat_name:
            found = []
            for m in _iter_scene_materials(self.rt):
                try:
                    if str(m.name) == self.mat_name:
                        found.append(m)
                except Exception:
                    pass
            if found:
                return found
        mat = self._infer_material()
        if mat is None:
            return []
        if mat is not None:
            self.mat_name = str(mat.name)
            self._select_in_combo(self.mat_name)
        return [mat]

    def _infer_material(self):
        """
        The single leaf material whose bitmap nodes include every captured node
        name.  Containers (a multi-sub holding the candidate) are dropped.  When
        several materials qualify — likely when every material uses the same
        node names (col, rough …) — return None rather than guess
        (self._ambiguous holds the candidate count).
        """
        self._ambiguous = 0
        wanted = {ov["bitmap"].lower() for ov in self._read_overrides() if ov["bitmap"]}
        if not wanted:
            return None
        cands = []
        for m in _iter_scene_materials(self.rt):
            try:
                names = {n.lower() for n, _ in _collect_bitmaps(self.rt, m)}
                h = self.rt.GetHandleByAnim(m)
            except Exception:
                continue
            if not wanted <= names:
                continue
            subs = {self.rt.GetHandleByAnim(s) for s in _iter_scene_materials_under(self.rt, m)}
            cands.append((m, h, subs))
        handles = {c[1] for c in cands}
        leaves = [c for c in cands if not (c[2] & (handles - {c[1]}))]
        if len(leaves) == 1:
            return leaves[0][0]
        self._ambiguous = len(leaves) if len(leaves) > 1 else 0
        return None

    def _not_found_msg(self):
        shown = self.mat_name or "?"
        if self._ambiguous:
            return (f"Material '{shown}' not found, and {self._ambiguous} materials share these bitmap "
                    "names — pick the right one in step 1.")
        return f"Material '{shown}' not found in scene — pick it in step 1 and re-capture."

    def _select_in_combo(self, name):
        combo = self.combo_mat
        combo.blockSignals(True)
        idx = combo.findText(name)
        if idx == -1:
            combo.addItem(name)
            idx = combo.count() - 1
        combo.setCurrentIndex(idx)
        combo.blockSignals(False)

    def _capture_bitmaps(self):
        current = self.combo_mat.currentText()
        if current and current != "-- Select --":
            self.mat_name = current
        if not self.mat_name:
            self._set_status("Select a material first.", True)
            return
        if self.rt:
            mat = self._find_material()
            if mat is None:
                self._set_status(f"Material '{self.mat_name}' not found in scene.", True)
                return
            bitmaps = _collect_bitmaps(self.rt, mat)
        else:
            bitmaps = list(_DEMO_BITMAPS)

        # Re-capturing keeps patterns typed by hand and the 'If missing' choices.
        typed, fallbacks = {}, {}
        for ov in self._read_overrides():
            key = ov["bitmap"].lower()
            p = ov["pattern"].strip()
            if p and p.lower() not in _auto_variants(ov["bitmap"]):
                typed[key] = p
            fallbacks[key] = ov["fallback"]

        self.ov_table.setRowCount(0)
        for name, filename in bitmaps:
            pattern = typed.get(name.lower()) or _auto_pattern(name)
            self._add_override_row(bitmap_name=name, pattern=pattern, fallback=fallbacks.get(name.lower()))

        count = len(bitmaps)
        no_token = [n for n, _ in bitmaps if not _auto_pattern(n) and n.lower() not in typed]
        self.lbl_capture_info.setText(f"{count} bitmap(s) found.")
        self.lbl_capture_info.setStyleSheet("color: #66ff66;" if count else "color: #ff6666;")
        if not count:
            self._set_status(f"No BitmapTexture nodes found in '{self.mat_name}'.", True)
        elif no_token:
            self._set_status(
                f"Captured {count} bitmap(s).  No map token in: {', '.join(no_token)} — "
                "rename the node (COL, ROUGH …) or type a pattern.", True)
        else:
            self._set_status(f"Captured {count} bitmap(s) from '{self.mat_name}'.")

    # -----------------------------------------------------------------------
    # Folder handlers
    # -----------------------------------------------------------------------

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

        # 2. Resolution subfolder (8K > 4K > … > flat)
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

        # 4. The material — edited in place, so every user of it updates
        if not self.mat_name:
            self._set_status("No material selected — check step 1.", True)
            return
        mats = self._find_materials()
        if not mats:
            self._set_status(self._not_found_msg(), True)
            return

        # 5. Swap bitmaps ('If missing' choice when nothing matches)
        files = _list_image_files(res_folder)
        override_map = self._override_map()
        stats = {"swapped": [], "fallback": [], "unchanged": [], "kept": [], "failed": []}
        seen = set()                       # bitmaps shared between duplicates are touched once
        for mat in mats:
            _swap_bitmaps(self.rt, mat, override_map, res_folder, files,
                          self.scale_mode, scale_u, scale_v, stats, seen)
        try:
            self.rt.redrawViews()
        except Exception:
            pass

        # 6. Report — one line; red only for real problems
        if stats["failed"]:
            self._set_status(f"Could not load: {', '.join(stats['failed'])}.", True)
        elif not files:
            self._set_status(f"No image files in {res_folder}.", True)
        else:
            self._set_status("Material replacement successful.")

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
            "mat_name":           self.mat_name,
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
            "overrides":          self._read_overrides(),
        }

    def deserialize(self, data):
        # Earlier drafts stored the material under other keys.
        self.mat_name           = (data.get("mat_name") or data.get("target_mat_name")
                                   or data.get("source_mat_name") or "")
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

        self.edit_folder.setText(self.folder_root)
        self.chk_root_from_column.blockSignals(True)
        self.chk_root_from_column.setChecked(self.folder_root_mode == "column")
        self.chk_root_from_column.blockSignals(False)
        self.root_stack.setCurrentIndex(1 if self.folder_root_mode == "column" else 0)
        self.edit_scale_default_u.setText(self.scale_default_u)
        self.edit_scale_default_v.setText(self.scale_default_v)
        self.chk_metadata.setChecked(self.scale_use_metadata)
        self.edit_tile_u.setText(self.scale_tile_u)
        self.edit_tile_v.setText(self.scale_tile_v)

        if self.scale_mode == "tiling":
            self.radio_tile.setChecked(True)
        else:
            self.radio_rws.setChecked(True)

        self._refresh_material_list()

        self.ov_table.setRowCount(0)
        for ov in data.get("overrides", []):
            name = ov.get("bitmap", "")
            pattern = _downgrade_high_bit(name, ov.get("pattern", ""))
            self._add_override_row(name, pattern, ov.get("fallback"))

        count = self.ov_table.rowCount()
        if count:
            self.lbl_capture_info.setText(f"{count} bitmap(s) found.")
            self.lbl_capture_info.setStyleSheet("color: #66ff66;")

        # Show the linked material; re-link by captured bitmaps if the name is lost.
        if self.rt and count:
            try:
                if self._find_material() is None:
                    self._set_status(self._not_found_msg(), True)
            except Exception as e:
                print(f"[MatFromFolderV2] Material re-link failed: {e}")
        if self.mat_name:
            self._select_in_combo(self.mat_name)

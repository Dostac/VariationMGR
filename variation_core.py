import os
import importlib.util
import inspect

# Qt is only needed by the preference / operator-instantiation helpers below.
# Keep it as a lazy import so this module is safe to import from contexts
# that don't have PySide6 loaded (e.g. the headless render worker, which only
# needs the row-range parsing helpers).


# ---------------------------------------------------------------------------
# Row-range expression parsing
# ---------------------------------------------------------------------------
# Convention (kept identical to the legacy spinner UI):
#   - Table row 1 is the CSV header. It cannot be rendered.
#   - Table row 2 is the first data row.
#   - Numbers in the expression refer directly to table row numbers, so
#     "2-10" renders the first nine data rows, "6,12" renders rows 6 and 12.
#   - Empty expression  -> render everything (returns None from parse).

def parse_row_range_expr(expr, max_row=None):
    """Expand a row-range expression like '2,4-7,10' into a sorted list of
    table row numbers. Raises ValueError on malformed input.

    Args:
      expr: the expression string, or None / empty.
      max_row: optional upper bound for open-ended parts ('2-' / '-').
               If omitted, an open end is forbidden and raises ValueError.

    Returns:
      None if expr is empty (caller should render all rows), else a sorted
      list of unique integers >= 2.
    """
    if expr is None:
        return None
    expr = expr.strip()
    if not expr:
        return None

    out = set()
    for part in expr.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a_str, _, b_str = part.partition("-")
            a_str = a_str.strip()
            b_str = b_str.strip()
            if a_str:
                start = int(a_str)
            else:
                start = 2
            if b_str:
                end = int(b_str)
            else:
                if max_row is None:
                    raise ValueError(
                        f"open-ended range '{part}' needs a known row count")
                end = int(max_row)
            if start < 2:
                raise ValueError(
                    f"row {start} is the header (data starts at row 2)")
            if end < start:
                raise ValueError(f"bad range '{part}': end < start")
            out.update(range(start, end + 1))
        else:
            n = int(part)
            if n < 2:
                raise ValueError(
                    f"row {n} is the header (data starts at row 2)")
            out.add(n)
    return sorted(out)


def is_valid_row_range_expr(expr):
    """True if `expr` parses without error (open-ended bounds accepted)."""
    if expr is None or not expr.strip():
        return True
    try:
        # Allow open-ended ranges during validation by supplying a large bound.
        parse_row_range_expr(expr, max_row=10**9)
        return True
    except (ValueError, TypeError):
        return False


def format_row_range_expr(start, end):
    """Convert legacy spinner start/end values to an expression string.

    Mapping (0 = unset):
      start=0, end=0   -> ""
      start=N, end=0   -> "N-"
      start=0, end=N   -> "-N"
      start=N, end=M   -> "N-M"
    """
    try:
        s = int(start or 0)
        e = int(end or 0)
    except (TypeError, ValueError):
        return ""
    if s <= 0 and e <= 0:
        return ""
    if s > 0 and e <= 0:
        return f"{s}-"
    if s <= 0 and e > 0:
        return f"-{e}"
    if s == e:
        return f"{s}"
    return f"{s}-{e}"


def load_preferences(ini_path, default_folder):
    """Loads the ops folder from the INI file, or returns default."""
    from PySide6 import QtCore
    settings = QtCore.QSettings(ini_path, QtCore.QSettings.IniFormat)
    saved_path = settings.value("General/OpsFolder")

    if saved_path and os.path.exists(saved_path):
        return os.path.normpath(saved_path)
    return default_folder


def save_preferences(ini_path, ops_folder):
    """Saves the given ops folder to the INI file."""
    from PySide6 import QtCore
    settings = QtCore.QSettings(ini_path, QtCore.QSettings.IniFormat)
    settings.setValue("General/OpsFolder", ops_folder)


def unique_existing_dirs(paths):
    """Returns unique normalized directories from a path list."""
    out = []
    seen = set()
    for p in paths:
        if not p:
            continue
        n = os.path.normpath(p)
        if n in seen:
            continue
        if os.path.isdir(n):
            out.append(n)
            seen.add(n)
    return out


def get_operator_state(op_entry):
    """Compatibility helper for old/new scene schemas."""
    return op_entry.get("settings", op_entry.get("state", {}))


def scan_operators(ops_folder, caller_id):
    """
    Scans the given folder for valid operator classes.
    Operators must implement get_ui() and execute().
    Uses caller_id to avoid module caching collisions.
    """
    available_classes = {}
    if not os.path.exists(ops_folder):
        return available_classes

    files = [f for f in os.listdir(ops_folder) if f.endswith(".py") and f != "__init__.py"]

    for f in files:
        path = os.path.join(ops_folder, f)
        try:
            mod_name = f"vm_op_{f[:-3]}_{caller_id}"
            spec = importlib.util.spec_from_file_location(mod_name, path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            for name, obj in inspect.getmembers(module):
                if inspect.isclass(obj):
                    if obj.__module__ != module.__name__:
                        continue
                    if hasattr(obj, 'get_ui') and hasattr(obj, 'execute'):
                        available_classes[name] = obj
        except Exception as e:
            print(f"VM Core: Failed to load {f}: {e}")

    return available_classes


def resolve_output_name(pattern, row_data, scene_name="Scene", camera_name="Cam", date_str="Date", row_index=0):
    """Resolves the naming scheme pattern based on row data."""
    res = (
        pattern.replace("{Scene}", scene_name)
        .replace("{Camera}", camera_name)
        .replace("{Date}", date_str)
        .replace("{Row}", str(row_index + 1))
    )

    for k, v in row_data.items():
        res = res.replace(f"[{k}]", str(v))

    return res


# ---------------------------------------------------------------------------
# Configuration checks (the warning badge in the Variation Manager)
# ---------------------------------------------------------------------------
# Obvious faults in the scene-level setup: camera mode, naming scheme, row
# range and table structure. Operators report their own problems in their
# tabs and are deliberately not checked here.

CAMERA_COLUMN_PLACEHOLDER = "-- Select Column --"


def _issue(level, message, kind="", **target):
    target["kind"] = kind
    return {"level": level, "message": message, "target": target}


def _row_list(numbers, limit=8):
    shown = ", ".join(str(n) for n in numbers[:limit])
    if len(numbers) > limit:
        shown += f" and {len(numbers) - limit} more"
    return shown


def validate_config(data, scene_cameras=None, corona_cameras=None):
    """Return a list of problems in a VariationManagerData dict, errors first.

    Each problem is {"level": "error"|"warning", "message": str,
    "target": {"kind": ..., ...}}. kind is one of "camera_column", "pattern",
    "row_range", "column" (with column=name), "cell" (with row=data-row index
    and column=name) or "" -- the UI uses it to jump to the cause.

    scene_cameras: names of the camera nodes in the scene, or None to skip the
    camera-existence check. corona_cameras: names of the CoronaCams, or None
    to skip the "All Cameras" checks. Names match case-insensitively, like
    MaxScript's getNodeByName that the renderer uses.

    Errors mean the render visibly fails or renders nothing; warnings mean it
    renders, but probably not what was intended. Row numbers in messages are
    table row numbers (header = row 1, first data row = row 2).
    """
    import re

    issues = []
    headers = [str(h) for h in (data.get("headers") or [])]
    rows = data.get("rows") or []
    mode = data.get("render_camera_mode", "active") or "active"
    cam_col = str(data.get("render_camera_column", "") or "").strip()
    if cam_col == CAMERA_COLUMN_PLACEHOLDER:
        cam_col = ""
    scheme = str(data.get("scheme", "") or "")
    range_expr = str(data.get("render_range_expr", "") or "").strip()

    # Table structure
    counts = {}
    for h in headers:
        key = h.strip()
        if not key:
            issues.append(_issue(
                "error",
                "A column has an empty name. Rename it so operators and the naming scheme can use it.",
                "column", column=h))
            continue
        counts[key] = counts.get(key, 0) + 1
    for name, n in counts.items():
        if n > 1:
            issues.append(_issue(
                "error",
                f"Column name '{name}' is used {n} times. Only one of them reaches the operators and the naming scheme.",
                "column", column=name))
    if not rows:
        issues.append(_issue(
            "warning",
            "The table has no rows, so this scene renders nothing in the batch renderer.",
            ""))

    # Rows that will actually render
    indexed = list(enumerate(rows))
    if range_expr:
        try:
            wanted = parse_row_range_expr(range_expr, max_row=len(rows) + 1)
        except (ValueError, TypeError):
            wanted = None
            issues.append(_issue(
                "error",
                f"Row range '{range_expr}' is not valid. Use e.g. 2,4-7,10 (row 1 is the header).",
                "row_range"))
        if wanted is not None:
            beyond = [n for n in wanted if n > len(rows) + 1]
            wanted_idx = {n - 2 for n in wanted}
            indexed = [(i, r) for i, r in indexed if i in wanted_idx]
            if rows and not indexed:
                issues.append(_issue(
                    "error",
                    f"Row range '{range_expr}' matches none of the data rows (rows 2-{len(rows) + 1}).",
                    "row_range"))
            elif beyond:
                issues.append(_issue(
                    "warning",
                    f"Row range '{range_expr}' asks for rows past the end of the table ({_row_list(beyond)}). Those are skipped.",
                    "row_range"))

    def cell(row_vals, name):
        try:
            return str(row_vals[headers.index(name)]).strip()
        except (ValueError, IndexError):
            return ""

    # Camera
    if mode == "column":
        if not headers:
            issues.append(_issue(
                "error", "Camera mode is 'From Column', but the table has no columns.",
                "camera_column"))
        elif not cam_col:
            issues.append(_issue(
                "error",
                "Camera mode is 'From Column', but no column is selected. Pick the column that holds the camera names.",
                "camera_column"))
        elif cam_col not in headers:
            issues.append(_issue(
                "error",
                f"Camera column '{cam_col}' no longer exists (renamed or deleted). Pick the column that holds the camera names.",
                "camera_column"))
        else:
            empty = [i + 2 for i, r in indexed if not cell(r, cam_col)]
            if empty:
                verb = "has" if len(empty) == 1 else "have"
                issues.append(_issue(
                    "warning",
                    f"Row {_row_list(empty)} {verb} no camera in column '{cam_col}' and won't render.",
                    "cell", row=empty[0] - 2, column=cam_col))
            if scene_cameras is not None:
                known = {c.lower() for c in scene_cameras}
                missing = {}
                for i, r in indexed:
                    v = cell(r, cam_col)
                    if v and v.lower() not in known:
                        missing.setdefault(v, []).append(i + 2)
                for name, nums in sorted(missing.items(), key=lambda kv: kv[1][0]):
                    what = "that row renders" if len(nums) == 1 else "those rows render"
                    issues.append(_issue(
                        "error",
                        f"Camera '{name}' (row {_row_list(nums)}) is not in the scene, so {what} nothing.",
                        "cell", row=nums[0] - 2, column=cam_col))
    elif mode == "all" and corona_cameras is not None and not corona_cameras:
        issues.append(_issue(
            "error", "Camera mode is 'All Cameras', but the scene has no Corona cameras.",
            "camera_column"))

    # Naming scheme
    if not scheme.strip():
        issues.append(_issue("error", "The output naming scheme is empty.", "pattern"))
    else:
        tokens = re.findall(r"\[([^\[\]]+)\]", scheme)
        for t in dict.fromkeys(t for t in tokens if t not in headers):
            issues.append(_issue(
                "error",
                f"The naming scheme uses [{t}], but there is no column '{t}'. It would end up literally in the file name.",
                "pattern"))
        many_cams = corona_cameras is None or len(corona_cameras) > 1
        if mode == "all" and "{Camera}" not in scheme and many_cams:
            issues.append(_issue(
                "warning",
                "Camera mode is 'All Cameras', but the naming scheme has no {Camera}. Every camera writes to the same file name.",
                "pattern"))
        if indexed and "{Row}" not in scheme:
            by_name = {}
            for i, r in indexed:
                name = scheme.replace("{Scene}", "").replace("{Date}", "")
                name = name.replace("{Camera}", cell(r, cam_col) if mode == "column" else "{Camera}")
                for k, v in zip(headers, r):
                    name = name.replace(f"[{k}]", str(v))
                by_name.setdefault(name.strip().lower(), []).append(i + 2)
            clashes = [nums for nums in by_name.values() if len(nums) > 1]
            if clashes:
                first = clashes[0]
                more = ""
                if len(clashes) > 1:
                    more = f" ({len(clashes) - 1} more group{'s' if len(clashes) > 2 else ''} like this)"
                issues.append(_issue(
                    "warning",
                    f"Rows {_row_list(first)} produce the same file name, so later renders overwrite earlier ones{more}. "
                    "Add {Row} or a column that differs to the naming scheme.",
                    "pattern"))

    issues.sort(key=lambda it: 0 if it["level"] == "error" else 1)
    return issues

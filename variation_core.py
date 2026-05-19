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

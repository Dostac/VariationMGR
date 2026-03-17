import os
import importlib.util
import inspect
from PySide6 import QtCore


def load_preferences(ini_path, default_folder):
    """Loads the ops folder from the INI file, or returns default."""
    settings = QtCore.QSettings(ini_path, QtCore.QSettings.IniFormat)
    saved_path = settings.value("General/OpsFolder")

    if saved_path and os.path.exists(saved_path):
        return os.path.normpath(saved_path)
    return default_folder


def save_preferences(ini_path, ops_folder):
    """Saves the given ops folder to the INI file."""
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

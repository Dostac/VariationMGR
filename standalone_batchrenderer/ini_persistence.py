"""INI-based settings persistence for the standalone batch renderer.

Replaces the 3ds Max ``rt.setINISetting`` / ``rt.getINISetting`` calls used
by ``batchrenderer_UI.py`` with pure-Python ``configparser``.
"""

import configparser
import os
from pathlib import Path


def get_ini_dir():
    """Return (and create) the directory that holds the standalone INI file."""
    local_appdata = os.environ.get("LOCALAPPDATA", "").strip()
    if local_appdata:
        base = os.path.join(local_appdata, "VirtualBuilders", "VariationMGR")
    else:
        base = str(
            Path.home() / "AppData" / "Local" / "VirtualBuilders" / "VariationMGR"
        )
    os.makedirs(base, exist_ok=True)
    return base


def get_ini_path():
    """Return the full path to the standalone INI file."""
    return os.path.join(get_ini_dir(), "vb_standalone_batch_renderer.ini")


# -------------------------------------------------------------------------
# Generic helpers
# -------------------------------------------------------------------------

def _read_config(ini_path):
    cfg = configparser.ConfigParser()
    cfg.read(ini_path, encoding="utf-8")
    return cfg


def _ensure_section(cfg, section):
    if not cfg.has_section(section):
        cfg.add_section(section)


def _write_config(ini_path, cfg):
    os.makedirs(os.path.dirname(ini_path), exist_ok=True)
    with open(ini_path, "w", encoding="utf-8") as fh:
        cfg.write(fh)


# -------------------------------------------------------------------------
# High-level API
# -------------------------------------------------------------------------

def save_settings(ini_path, settings_dict):
    """Persist a ``{section: {key: value}}`` dict to the INI file.

    Merges with any existing content so that other sections are preserved.
    """
    cfg = _read_config(ini_path)
    for section, keys in settings_dict.items():
        _ensure_section(cfg, section)
        for key, value in keys.items():
            cfg.set(section, key, str(value))
    _write_config(ini_path, cfg)


def load_settings(ini_path):
    """Return a ``ConfigParser`` instance for *ini_path*."""
    return _read_config(ini_path)


# -------------------------------------------------------------------------
# File-entry helpers  (each entry: {"path": str, "var_json": str})
# -------------------------------------------------------------------------

def save_file_entries(ini_path, file_entries):
    """Persist a list of ``{"path", "var_json"}`` dicts to the INI file."""
    cfg = _read_config(ini_path)
    for section in ("MaxFiles", "VarJson"):
        if cfg.has_section(section):
            cfg.remove_section(section)
        _ensure_section(cfg, section)
    _ensure_section(cfg, "Meta")
    cfg.set("Meta", "count", str(len(file_entries)))
    for i, entry in enumerate(file_entries):
        cfg.set("MaxFiles", f"file{i + 1}", entry.get("path", ""))
        cfg.set("VarJson",  f"file{i + 1}", entry.get("var_json", ""))
    _write_config(ini_path, cfg)


def load_file_entries(ini_path):
    """Return a list of ``{"path": str, "var_json": str}`` dicts."""
    cfg = _read_config(ini_path)
    count = cfg.getint("Meta", "count", fallback=0)
    entries = []
    for i in range(1, count + 1):
        path     = cfg.get("MaxFiles", f"file{i}", fallback="")
        var_json = cfg.get("VarJson",  f"file{i}", fallback="")
        if path:
            entries.append({"path": path, "var_json": var_json})
    return entries


# -------------------------------------------------------------------------
# Format-preference helpers
# -------------------------------------------------------------------------

def save_format_prefs(ini_path, format_prefs):
    """*format_prefs* is ``{fmt: [depth_index, alpha_flag]}``."""
    cfg = _read_config(ini_path)
    _ensure_section(cfg, "FormatPrefs")
    for fmt, prefs in format_prefs.items():
        cfg.set("FormatPrefs", fmt, f"{prefs[0]},{1 if prefs[1] else 0}")
    _write_config(ini_path, cfg)


def load_format_prefs(ini_path, defaults=None):
    """Return ``{fmt: [depth_index, alpha_flag]}``."""
    prefs = dict(defaults) if defaults else {
        "jpg": [0, False],
        "png": [0, True],
        "tif": [1, True],
        "exr": [0, True],
    }
    cfg = _read_config(ini_path)
    for fmt in list(prefs):
        val = cfg.get("FormatPrefs", fmt, fallback="")
        if val:
            parts = val.split(",")
            if len(parts) == 2:
                try:
                    prefs[fmt] = [int(parts[0]), parts[1] == "1"]
                except ValueError:
                    pass
    return prefs

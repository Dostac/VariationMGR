"""Parse an OpenColorIO config file to extract displays, views, and colorspaces.

The 3ds Max default OCIO config is a YAML file with custom OCIO tags
(``!<View>``, ``!<ColorSpace>``, etc.).  This module uses line-based regex
parsing so it works without PyOpenColorIO or PyYAML installed.
"""

import os
import re

from standalone_batchrenderer import max_discovery

# Relative path inside a 3ds Max installation directory.
_OCIO_SUBPATHS = [
    os.path.join(
        "ColorManagement", "ocio_configs",
        "3dsmax_default_ocio", "3dsmax_default_config.ocio",
    ),
    os.path.join(
        "Resources", "OCIO-configs",
        "3dsmax_config", "config.ocio",
    ),
]


# -------------------------------------------------------------------------
# Locate the config file
# -------------------------------------------------------------------------

def find_ocio_config(user_path=""):
    """Return the path to a usable ``.ocio`` config file, or ``""``."""
    if user_path and os.path.isfile(user_path):
        return user_path

    for env_var in ("VB_OCIO_CONFIG", "OCIO"):
        val = os.environ.get(env_var, "").strip()
        if val and os.path.isfile(val):
            return val

    for max_dir in max_discovery.find_3dsmax_install_dirs():
        for subpath in _OCIO_SUBPATHS:
            candidate = os.path.join(max_dir, subpath)
            if os.path.isfile(candidate):
                return candidate

    return ""


# -------------------------------------------------------------------------
# Hardcoded 3ds Max 2026 defaults (fallback when no file is found)
# -------------------------------------------------------------------------

_DEFAULT_DISPLAYS = {
    "sRGB": ["ACES 1.0 SDR-video", "Un-tone-mapped", "Log", "Raw"],
    "Gamma 2.2 / Rec.709": ["ACES 1.0 SDR-video", "Un-tone-mapped", "Log", "Raw"],
    "Rec.1886 / Rec.709 video": ["ACES 1.0 SDR-video", "Un-tone-mapped", "Log", "Raw"],
    "AdobeRGB": ["ACES 1.0 SDR-video", "Un-tone-mapped", "Log", "Raw"],
    "DCI-P3 D65": ["ACES 1.0 SDR-video", "Un-tone-mapped", "Log", "Raw"],
}

_DEFAULT_COLORSPACES = [
    "ACEScg",
    "ACES2065-1",
    "scene-linear Rec.709-sRGB",
    "scene-linear DCI-P3 D65",
    "scene-linear Rec.2020",
    "Raw",
    "ACEScct",
    "ARRI LogC (v3-EI800) / AlexaWideGamut",
    "RED Log3G10 / REDWideGamutRGB",
    "Sony SLog3 / SGamut3",
    "Log film scan (ADX10)",
    "sRGB",
    "Gamma 2.2 / Rec.709",
    "Rec.1886 / Rec.709 video",
    "AdobeRGB",
    "DCI-P3 D65",
]


# -------------------------------------------------------------------------
# Line-based parser
# -------------------------------------------------------------------------

_RE_VIEWS_LIST = re.compile(r"!\s*<Views>\s*\[([^\]]+)\]")
_RE_NAME_VALUE = re.compile(r"^\s+name:\s*(.+)")
_RE_CATEGORIES = re.compile(r"^\s+categories:\s*\[([^\]]*)\]")


def _parse_displays(lines, start):
    """Parse the ``displays:`` block starting after *start* index."""
    displays = {}
    current_display = None
    i = start + 1
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        # A non-indented non-empty line (not a comment) ends the block.
        if stripped and not stripped.startswith("#") and not line[0].isspace():
            break
        # Display name line: "  sRGB:" or "  Gamma 2.2 / Rec.709:"
        if line.startswith("  ") and not line.startswith("    ") and stripped.endswith(":"):
            current_display = stripped[:-1]
            displays[current_display] = []
        # Views list: "    - !<Views> [ACES 1.0 SDR-video, ...]"
        elif current_display is not None:
            m = _RE_VIEWS_LIST.search(stripped)
            if m:
                views = [v.strip() for v in m.group(1).split(",") if v.strip()]
                displays[current_display] = views
        i += 1
    return displays


def _parse_colorspaces(lines, start):
    """Parse a ``colorspaces:`` or ``display_colorspaces:`` block.

    Returns names of colorspaces that have ``file-io`` in their categories.
    """
    names = []
    current_name = ""
    current_has_fileio = False
    i = start + 1
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        # End of block on non-indented non-empty non-comment line.
        if stripped and not stripped.startswith("#") and not line[0].isspace():
            break

        # New colorspace entry starts with "  - !<ColorSpace>"
        if stripped.startswith("- !<ColorSpace>"):
            # Flush previous entry.
            if current_name and current_has_fileio:
                names.append(current_name)
            current_name = ""
            current_has_fileio = False
        else:
            m_name = _RE_NAME_VALUE.match(line)
            if m_name and not current_name:
                current_name = m_name.group(1).strip()
            m_cat = _RE_CATEGORIES.match(line)
            if m_cat:
                cats = m_cat.group(1)
                if "file-io" in cats:
                    current_has_fileio = True
        i += 1

    # Flush last entry.
    if current_name and current_has_fileio:
        names.append(current_name)
    return names


def _parse_config_file(path):
    """Return ``(displays, colorspaces)`` parsed from *path*."""
    with open(path, "r", encoding="utf-8") as fh:
        lines = fh.readlines()

    displays = {}
    colorspaces = []

    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "displays:":
            displays = _parse_displays(lines, idx)
        elif stripped in ("colorspaces:", "display_colorspaces:"):
            colorspaces.extend(_parse_colorspaces(lines, idx))

    return displays, colorspaces


# -------------------------------------------------------------------------
# Public API
# -------------------------------------------------------------------------

class OcioConfig:
    """Provides display, view, and colorspace lists from an OCIO config."""

    def __init__(self, config_path=""):
        self.config_path = config_path or find_ocio_config()
        self._displays = {}
        self._colorspaces = []
        self._loaded = False
        self._load()

    def _load(self):
        if self.config_path and os.path.isfile(self.config_path):
            try:
                self._displays, self._colorspaces = _parse_config_file(
                    self.config_path
                )
                self._loaded = True
                return
            except Exception:
                pass

        # Fallback to hardcoded defaults.
        self._displays = dict(_DEFAULT_DISPLAYS)
        self._colorspaces = list(_DEFAULT_COLORSPACES)
        self._loaded = True

    def reload(self, config_path=""):
        """Re-parse from *config_path* (or the original path)."""
        if config_path:
            self.config_path = config_path
        self._load()

    @property
    def loaded_from_file(self):
        return bool(self.config_path) and os.path.isfile(self.config_path)

    def get_displays(self):
        """Return a list of display names."""
        return list(self._displays.keys())

    def get_views(self, display=""):
        """Return the view list for *display* (or all views if unknown)."""
        if display and display in self._displays:
            return list(self._displays[display])
        # Union of all views, preserving order.
        seen = set()
        result = []
        for views in self._displays.values():
            for v in views:
                if v not in seen:
                    seen.add(v)
                    result.append(v)
        return result

    def get_colorspaces(self):
        """Return file-IO colorspace names."""
        return list(self._colorspaces)

"""Public API for submitter recipes.

A recipe is a small Python file that turns a table of client rows into
VariationMGR rows for one or more scenes. Everything generic (CSV parsing,
folder scans, pooling rows per scene, splitting into jobs, render/output
settings, preview, submit, archiving) lives in ``submitter.py``; a recipe only
declares its scenes and input columns and implements ``build()``.

Recipes import this module under a short alias that the server registers::

    from vb_recipe import *

See docs/SUBMITTER_RECIPES.md for the full contract and worked examples.
"""

# Imported here (not only in recipes) so the frozen Server.exe bundles them:
# PyInstaller only ships stdlib modules that something in the build imports,
# and recipes are exec'd from disk at runtime.
import csv        # noqa: F401
import itertools  # noqa: F401
import json       # noqa: F401
import math       # noqa: F401
import os         # noqa: F401
import random     # noqa: F401
import re         # noqa: F401
import string     # noqa: F401

__all__ = [
    "Scene", "Column", "FolderScan",
    "Choice", "Text", "Folder", "Number", "Toggle",
    "Row", "Jobs", "RecipeError", "unique",
]


class RecipeError(Exception):
    """Raise from build() for a user-facing problem (bad input, missing value).

    The preview shows the message without a traceback and blocks submission.
    """


# ── Declarations ──────────────────────────────────────────────────────────────

class Scene:
    """One .max scene the recipe can emit rows for.

    ``headers`` are the VariationMGR table columns that scene expects, in
    order: every row sent to it becomes one row of its csv_override, and the
    override replaces the scene's whole table, so rows must be complete.

    ``render`` / ``output`` are optional per-scene overrides applied on top of
    the page settings (for example a different resolution for close-ups).
    ``chunk_rows`` overrides the page's "Rows per job" for this scene only
    (0 = never split this scene).
    """

    def __init__(self, path, headers, label="", render=None, output=None, chunk_rows=None):
        self.path = str(path or "")
        self.headers = [str(h) for h in (headers or [])]
        self.label = str(label or "")
        self.render = dict(render or {})
        self.output = dict(output or {})
        self.chunk_rows = None if chunk_rows is None else int(chunk_rows)
        if not self.headers:
            raise ValueError(f"Scene {self.path!r} declares no headers.")
        if len(set(h.lower() for h in self.headers)) != len(self.headers):
            raise ValueError(f"Scene {self.path!r} has duplicate headers: {self.headers}")


class Column:
    """One column of the input grid (the client-facing table).

    ``name`` is the grid heading and the primary CSV header to match.
    ``key`` is how build() reads the value (``row.key`` / ``row["key"]``); it
    defaults to ``name``. ``aliases`` are extra CSV headers that map to this
    column (matched case-insensitively, surrounding spaces ignored).
    ``choices`` turns the cell into a dropdown; values outside the list are
    kept but flagged. ``required`` blocks submission when a row leaves it
    empty. ``swatch`` shows a colour square for hex values (``9EA299``).
    """

    def __init__(self, name, key=None, aliases=(), choices=None, required=False,
                 default="", readonly=False, swatch=False, help=""):
        self.name = str(name)
        self.key = str(key or name)
        self.aliases = [str(a) for a in (aliases or [])]
        self.choices = None if choices is None else [str(c) for c in choices]
        self.required = bool(required)
        self.default = "" if default is None else str(default)
        self.readonly = bool(readonly)
        self.swatch = bool(swatch)
        self.help = str(help or "")

    def to_dict(self):
        return {
            "name": self.name, "key": self.key, "aliases": self.aliases,
            "choices": self.choices, "required": self.required,
            "default": self.default, "readonly": self.readonly,
            "swatch": self.swatch, "help": self.help,
        }


class FolderScan:
    """Offer a "Scan folder" button that fills the grid from a folder listing.

    Each subfolder (or file, with ``files=True``) of the folder in option
    ``option`` becomes one row with its name in column ``column``. Existing
    grid values are kept for names that were already there, so a rescan
    picks up new folders without losing choices made earlier.
    ``pattern`` is an optional regex the name must match.
    """

    def __init__(self, option, column, files=False, pattern=None):
        self.option = str(option)
        self.column = str(column)
        self.files = bool(files)
        self.pattern = pattern

    def to_dict(self):
        return {"option": self.option, "column": self.column, "files": self.files}


class _Option:
    kind = ""

    def __init__(self, key, label=None, default=None, help=""):
        self.key = str(key)
        self.label = str(label or key)
        self.default = default
        self.help = str(help or "")

    def coerce(self, value):
        return value

    def to_dict(self):
        return {"kind": self.kind, "key": self.key, "label": self.label,
                "default": self.default, "help": self.help}


class Choice(_Option):
    """A dropdown. ``choices`` are the values build() sees; ``labels`` (same
    length) are optional display names."""
    kind = "choice"

    def __init__(self, key, label=None, choices=(), default=None, labels=None, help=""):
        choices = [str(c) for c in choices]
        if not choices:
            raise ValueError(f"Choice option {key!r} needs at least one choice.")
        super().__init__(key, label, choices[0] if default is None else str(default), help)
        self.choices = choices
        self.labels = [str(l) for l in labels] if labels else list(choices)
        if len(self.labels) != len(self.choices):
            raise ValueError(f"Choice option {key!r}: labels and choices differ in length.")

    def coerce(self, value):
        value = "" if value is None else str(value)
        return value if value in self.choices else self.default

    def to_dict(self):
        d = super().to_dict()
        d["choices"] = self.choices
        d["labels"] = self.labels
        return d


class Text(_Option):
    kind = "text"

    def __init__(self, key, label=None, default="", help=""):
        super().__init__(key, label, str(default or ""), help)

    def coerce(self, value):
        return "" if value is None else str(value).strip()


class Folder(Text):
    """A folder path (Browse… button inside the server window)."""
    kind = "folder"

    def coerce(self, value):
        text = super().coerce(value)
        if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
            text = text[1:-1].strip()
        return text.replace("\\", "/")


class Number(_Option):
    kind = "number"

    def __init__(self, key, label=None, default=0, min=None, max=None, step=1, help=""):
        super().__init__(key, label, default, help)
        self.min, self.max, self.step = min, max, step

    def coerce(self, value):
        try:
            num = float(value)
        except (TypeError, ValueError):
            return self.default
        if self.min is not None:
            num = max(num, self.min)
        if self.max is not None:
            num = min(num, self.max)
        return int(num) if float(self.step).is_integer() and num.is_integer() else num

    def to_dict(self):
        d = super().to_dict()
        d.update(min=self.min, max=self.max, step=self.step)
        return d


class Toggle(_Option):
    kind = "toggle"

    def __init__(self, key, label=None, default=False, help=""):
        super().__init__(key, label, bool(default), help)

    def coerce(self, value):
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)


# ── Runtime objects handed to build() ─────────────────────────────────────────

class Row(dict):
    """One grid row, keyed by Column.key. Attribute access works too
    (``row.name``); a missing key reads as "". ``row.number`` is the row's
    position in the grid (1-based, counting every row, ticked or not)."""

    def __init__(self, values, number=0):
        super().__init__(values)
        self.number = number

    def __getattr__(self, item):
        if item.startswith("__"):
            raise AttributeError(item)
        return self.get(item, "")


class _Opts(dict):
    def __getattr__(self, item):
        if item.startswith("__"):
            raise AttributeError(item)
        try:
            return self[item]
        except KeyError:
            raise AttributeError(f"Recipe has no option {item!r}") from None


class Jobs:
    """Collects the rows build() emits, per scene key.

    ``add(scene, row)`` appends one VariationMGR row to that scene. ``row`` is
    a dict keyed by the scene's headers (matched case-insensitively) or a
    list/tuple in header order. Rows for the same scene are pooled into one
    table and split into jobs by the framework afterwards.
    """

    def __init__(self, scenes):
        self._scenes = scenes
        self.rows = {}          # scene key -> [[cell, ...], ...] in emit order
        self.warnings = []
        self.logs = []
        self._missing_seen = set()

    def add(self, scene, row):
        if scene not in self._scenes:
            raise RecipeError(
                f"add(): unknown scene {scene!r}. Declared scenes: {', '.join(self._scenes)}"
            )
        headers = self._scenes[scene].headers
        if isinstance(row, dict):
            lookup = {str(k).strip().lower(): v for k, v in row.items()}
            known = {h.lower() for h in headers}
            unknown = [k for k in row if str(k).strip().lower() not in known]
            if unknown:
                raise RecipeError(
                    f"add({scene!r}): unknown column(s) {unknown}. "
                    f"Scene headers are {headers}."
                )
            cells = []
            for h in headers:
                if h.lower() not in lookup:
                    if (scene, h) not in self._missing_seen:
                        self._missing_seen.add((scene, h))
                        self.warn(f"{scene}: column '{h}' not set by the recipe; sent empty.")
                    cells.append("")
                else:
                    cells.append(_cell(lookup[h.lower()]))
        elif isinstance(row, (list, tuple)):
            if len(row) != len(headers):
                raise RecipeError(
                    f"add({scene!r}): got {len(row)} values, scene has {len(headers)} "
                    f"headers {headers}."
                )
            cells = [_cell(v) for v in row]
        else:
            raise RecipeError(f"add({scene!r}): row must be a dict or a list, got {type(row).__name__}.")
        self.rows.setdefault(scene, []).append(cells)

    def warn(self, message):
        """Show a warning in the preview. Warnings never block submission."""
        self.warnings.append(str(message))

    def log(self, message):
        """Add a line to the preview's recipe log."""
        self.logs.append(str(message))


def _cell(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def unique(rows, key):
    """First row per distinct value of ``key`` (order kept). Useful for scenes
    that must render once per fabric even when the client lists it twice."""
    seen = set()
    out = []
    for r in rows:
        v = r.get(key, "") if isinstance(r, dict) else getattr(r, key, "")
        if v in seen:
            continue
        seen.add(v)
        out.append(r)
    return out

"""Recipe submitter: client tables -> pooled, split render jobs.

A *recipe* (a .py file in the recipes folder) declares the scenes it renders,
the columns of the client table and its options, and implements ``build()``,
which turns the ticked table rows into VariationMGR rows per scene. This
module does everything around that, identically for every project:

1. Input: parse an uploaded CSV onto the recipe's columns, or fill the grid
   from a folder scan (``FolderScan``). The page keeps the grid editable.
2. Validate rows (required columns, dropdown values), coerce options.
3. Run ``build()`` in a worker thread with a timeout.
4. Pool: every row a recipe emits for one scene key lands in one table.
5. Split: tables longer than "Rows per job" become several jobs that each
   carry the *full* table plus a ``render_range_expr``, so ``{Row}`` in output
   names stays stable across chunks (the same convention the Batch Renderer's
   server split uses).
6. Resolve settings: schema defaults < recipe DEFAULTS < page settings <
   per-scene overrides, then ``job_schema.normalize_job_request``.
7. Preview (nothing queued) or submit: all jobs under one request id, and the
   inputs plus payloads archived in ``<recipes>/_submissions``.

Recipes are re-read from disk on every call, so edits (from the browser
editor or VS Code) apply without restarting the server.

The same pipeline runs from the command line::

    python -m NetworkRender.server.submitter RECIPE.py client.csv --output-folder X
    python -m NetworkRender.server.submitter RECIPE.py client.csv --output-folder X --submit http://host:8765
"""

import argparse
import base64
import copy
import csv
import datetime
import hashlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import traceback
import uuid
from pathlib import Path

if __package__ is None or __package__ == "":
    _repo_root = Path(__file__).resolve().parents[2]
    if str(_repo_root) not in sys.path:
        sys.path.insert(0, str(_repo_root))

from NetworkRender.shared import job_schema as schema
from NetworkRender.server import recipe_api
from NetworkRender.server.recipe_api import (
    Column, FolderScan, Jobs, RecipeError, Row, Scene, _Opts, _Option,
)

# Recipes write ``from vb_recipe import *``; point that name at the API module.
sys.modules.setdefault("vb_recipe", recipe_api)

RECIPE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,63}$")
ARCHIVE_NAME_RE = re.compile(r"^[A-Za-z0-9_\-]+\.json$")
BUILD_TIMEOUT_SECONDS = 30
SUBMISSIONS_DIRNAME = "_submissions"
TEMPLATE_NAME = "_template.py"
EXAMPLES_DIR = Path(__file__).resolve().with_name("submitter_recipes")


class RecipeLoadError(Exception):
    """The recipe file could not be executed or declares something invalid."""


# ── File helpers ──────────────────────────────────────────────────────────────

def _atomic_write_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def _read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _recipe_traceback(exc, recipe_path):
    """Short traceback: only frames inside the recipe file, then the error."""
    frames = [
        f for f in traceback.extract_tb(exc.__traceback__)
        if os.path.normcase(os.path.abspath(f.filename)) == os.path.normcase(os.path.abspath(recipe_path))
    ]
    lines = [
        f"  {os.path.basename(f.filename)} line {f.lineno}, in {f.name}: {(f.line or '').strip()}"
        for f in frames
    ]
    lines.append(f"{type(exc).__name__}: {exc}")
    return "\n".join(lines)


# ── Loaded recipe ─────────────────────────────────────────────────────────────

class LoadedRecipe:
    def __init__(self, recipe_id, path, source, namespace):
        self.id = recipe_id
        self.path = str(path)
        self.source = source
        self.title = str(namespace.get("TITLE") or recipe_id)
        self.description = str(namespace.get("DESCRIPTION") or "").strip()

        scenes = namespace.get("SCENES")
        if not isinstance(scenes, dict) or not scenes:
            raise RecipeLoadError("SCENES must be a non-empty dict of {key: Scene(...)}.")
        for key, sc in scenes.items():
            if not isinstance(sc, Scene):
                raise RecipeLoadError(f"SCENES[{key!r}] must be a Scene(...), got {type(sc).__name__}.")
            if not sc.path:
                raise RecipeLoadError(f"SCENES[{key!r}] has an empty path.")
        self.scenes = {str(k): v for k, v in scenes.items()}

        columns = namespace.get("COLUMNS")
        if not isinstance(columns, (list, tuple)) or not columns:
            raise RecipeLoadError("COLUMNS must be a non-empty list of Column(...).")
        keys = set()
        for col in columns:
            if not isinstance(col, Column):
                raise RecipeLoadError(f"COLUMNS entries must be Column(...), got {type(col).__name__}.")
            if col.key in keys or col.key.startswith("_"):
                raise RecipeLoadError(f"Column key {col.key!r} is duplicated or starts with '_'.")
            keys.add(col.key)
        self.columns = list(columns)

        options = namespace.get("OPTIONS") or []
        okeys = set()
        for opt in options:
            if not isinstance(opt, _Option):
                raise RecipeLoadError(f"OPTIONS entries must be Choice/Text/Folder/Number/Toggle, got {type(opt).__name__}.")
            if opt.key in okeys:
                raise RecipeLoadError(f"Option key {opt.key!r} is duplicated.")
            okeys.add(opt.key)
        self.options = list(options)

        scan = namespace.get("FOLDER_SCAN")
        if scan is not None:
            if not isinstance(scan, FolderScan):
                raise RecipeLoadError("FOLDER_SCAN must be a FolderScan(...).")
            if scan.option not in okeys:
                raise RecipeLoadError(f"FOLDER_SCAN option {scan.option!r} is not declared in OPTIONS.")
            if self.column(scan.column) is None:
                raise RecipeLoadError(f"FOLDER_SCAN column {scan.column!r} is not declared in COLUMNS.")
        self.folder_scan = scan

        defaults = namespace.get("DEFAULTS") or {}
        if not isinstance(defaults, dict):
            raise RecipeLoadError("DEFAULTS must be a dict.")
        self.defaults = defaults

        build = namespace.get("build")
        if not callable(build):
            raise RecipeLoadError("The recipe must define build(rows, opts, jobs).")
        self.build = build

    def column(self, key_or_name):
        for c in self.columns:
            if c.key == key_or_name or c.name == key_or_name:
                return c
        return None

    def default_settings(self):
        """Schema defaults overlaid with the recipe's DEFAULTS (page settings start here)."""
        base = schema.get_default_job_request()
        render = dict(base["render"])
        output = dict(base["output"])
        ocio = dict(base["ocio"])
        render.update(self.defaults.get("render") or {})
        output.update(self.defaults.get("output") or {})
        ocio.update(self.defaults.get("ocio") or {})
        render["use_variations"] = True
        try:
            chunk_rows = max(0, int(self.defaults.get("chunk_rows", 0) or 0))
        except (TypeError, ValueError):
            chunk_rows = 0
        return {"render": render, "output": output, "ocio": ocio, "chunk_rows": chunk_rows}

    def meta(self):
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "path": self.path,
            "columns": [c.to_dict() for c in self.columns],
            "options": [o.to_dict() for o in self.options],
            "folder_scan": self.folder_scan.to_dict() if self.folder_scan else None,
            "scenes": [
                {"key": k, "label": s.label or k, "path": s.path, "headers": s.headers,
                 "chunk_rows": s.chunk_rows}
                for k, s in self.scenes.items()
            ],
            "settings": self.default_settings(),
        }


def load_recipe_source(recipe_id, path, source):
    namespace = {"__name__": f"vb_recipe_{recipe_id}", "__file__": str(path)}
    try:
        code = compile(source, str(path), "exec")
    except SyntaxError as exc:
        raise RecipeLoadError(f"Syntax error on line {exc.lineno}: {exc.msg}\n  {(exc.text or '').rstrip()}") from None
    try:
        exec(code, namespace)
    except Exception as exc:
        raise RecipeLoadError(_recipe_traceback(exc, path)) from None
    try:
        return LoadedRecipe(recipe_id, path, source, namespace)
    except RecipeLoadError:
        raise
    except Exception as exc:
        raise RecipeLoadError(f"{type(exc).__name__}: {exc}") from None


def load_recipe_file(path, recipe_id=None):
    path = Path(path)
    source = path.read_text(encoding="utf-8")
    return load_recipe_source(recipe_id or path.stem, path, source)


# ── Store (recipes folder on the server machine or the NAS) ───────────────────

class RecipeStore:
    def __init__(self, root):
        self.root = Path(root)
        self.submissions_dir = self.root / SUBMISSIONS_DIRNAME

    def ensure_seeded(self):
        """First run only: create the folder and copy the bundled example recipes.
        A folder that already exists is never touched, even when empty."""
        if self.root.exists():
            return
        self.root.mkdir(parents=True, exist_ok=True)
        if EXAMPLES_DIR.is_dir():
            for src in EXAMPLES_DIR.glob("*.py"):
                if not src.name.startswith("_"):
                    shutil.copy2(src, self.root / src.name)

    def _check_id(self, recipe_id):
        if not RECIPE_ID_RE.match(str(recipe_id or "")):
            raise ValueError("Recipe names use letters, digits, '_' and '-' only (max 64).")
        return str(recipe_id)

    def path_for(self, recipe_id):
        return self.root / f"{self._check_id(recipe_id)}.py"

    def state_path(self, recipe_id):
        return self.root / f"{self._check_id(recipe_id)}.state.json"

    def exists(self, recipe_id):
        return self.path_for(recipe_id).is_file()

    def list(self):
        out = []
        if not self.root.is_dir():
            return out
        for path in sorted(self.root.glob("*.py"), key=lambda p: p.name.lower()):
            if path.name.startswith("_") or not RECIPE_ID_RE.match(path.stem):
                continue
            entry = {"id": path.stem, "title": path.stem, "description": "", "error": ""}
            try:
                r = load_recipe_file(path)
                entry.update(title=r.title, description=r.description)
            except RecipeLoadError as exc:
                entry["error"] = str(exc)
            except OSError as exc:
                entry["error"] = f"Cannot read file: {exc}"
            out.append(entry)
        return out

    def load(self, recipe_id):
        path = self.path_for(recipe_id)
        if not path.is_file():
            raise FileNotFoundError(f"No recipe named {recipe_id!r} in {self.root}.")
        return load_recipe_file(path, recipe_id)

    def read_source(self, recipe_id):
        path = self.path_for(recipe_id)
        return path.read_text(encoding="utf-8"), path.stat().st_mtime

    def save_source(self, recipe_id, source, base_mtime=None, force=False, create=False):
        path = self.path_for(recipe_id)
        if create and path.exists():
            raise FileExistsError(f"A recipe named {recipe_id!r} already exists.")
        if not create and not force and base_mtime is not None and path.exists():
            current = path.stat().st_mtime
            if abs(current - float(base_mtime)) > 0.001:
                return {"conflict": True, "mtime": current}
        _atomic_write_text(path, source)
        return {"conflict": False, "mtime": path.stat().st_mtime}

    def template(self):
        tpl = EXAMPLES_DIR / TEMPLATE_NAME
        if tpl.is_file():
            return tpl.read_text(encoding="utf-8")
        return "from vb_recipe import *\n\nSCENES = {}\nCOLUMNS = []\n\ndef build(rows, opts, jobs):\n    pass\n"

    def read_state(self, recipe_id):
        data = _read_json(self.state_path(recipe_id), {})
        return data if isinstance(data, dict) else {}

    def save_state(self, recipe_id, state):
        _atomic_write_text(self.state_path(recipe_id), json.dumps(state, indent=1, ensure_ascii=False))

    def archive(self, recipe_id, record):
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        name = f"{stamp}_{self._check_id(recipe_id)}_{record['request_id'][:8]}.json"
        _atomic_write_text(self.submissions_dir / name, json.dumps(record, indent=1, ensure_ascii=False))
        return name

    def history(self, recipe_id, limit=20):
        self._check_id(recipe_id)
        if not self.submissions_dir.is_dir():
            return []
        suffix = re.compile(rf"^\d{{8}}-\d{{6}}_{re.escape(recipe_id)}_[0-9a-f]{{8}}\.json$")
        files = sorted((p for p in self.submissions_dir.glob("*.json") if suffix.match(p.name)),
                       key=lambda p: p.name, reverse=True)[:limit]
        out = []
        for p in files:
            rec = _read_json(p, {})
            out.append({
                "file": p.name,
                "submitted_at": rec.get("submitted_at", ""),
                "request_id": rec.get("request_id", ""),
                "source_name": rec.get("source_name", ""),
                "jobs": (rec.get("totals") or {}).get("jobs", 0),
                "rows": (rec.get("totals") or {}).get("rows", 0),
                "input_rows": len(rec.get("rows") or []),
            })
        return out

    def read_archive(self, name):
        if not ARCHIVE_NAME_RE.match(str(name or "")):
            raise ValueError("Bad archive name.")
        path = self.submissions_dir / name
        if not path.is_file():
            raise FileNotFoundError(name)
        return _read_json(path, {})


# ── Input: CSV and folder scan ────────────────────────────────────────────────

def decode_table_bytes(data):
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def parse_csv_text(text):
    """Return (headers, data_rows). Detects ',', ';' (Dutch Excel) or tab."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise RecipeError("The file is empty.")
    first = lines[0]
    delim = max((",", ";", "\t"), key=lambda d: first.count(d))
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    rows = [r for r in reader if any(str(c).strip() for c in r)]
    headers = [str(h).strip() for h in rows[0]]
    return headers, rows[1:]


def canonical_choice(col, value):
    """Snap a value to a dropdown choice when it matches case-insensitively."""
    if col.choices is None or not value or value in col.choices:
        return value
    low = value.strip().lower()
    for c in col.choices:
        if c.lower() == low:
            return c
    return value


def table_to_grid(recipe, headers, data_rows):
    """Map a parsed table onto the recipe's columns. Returns (rows, warnings)."""
    lookup = {}
    for i, h in enumerate(headers):
        lookup.setdefault(h.strip().lower(), i)
    col_index = {}
    missing_required = []
    missing_optional = []
    used = set()
    for col in recipe.columns:
        idx = None
        # Only the heading and aliases: keys are internal names (e.g. "name")
        # and must not capture an unrelated client column.
        for cand in [col.name] + col.aliases:
            idx = lookup.get(cand.strip().lower())
            if idx is not None:
                break
        if idx is None:
            (missing_required if col.required else missing_optional).append(col)
        else:
            col_index[col.key] = idx
            used.add(idx)
    if missing_required:
        parts = [f"'{c.name}' (accepted headers: {', '.join([c.name] + c.aliases)})" for c in missing_required]
        raise RecipeError(
            "The file has no column for " + "; ".join(parts) + f". Its headers are: {', '.join(headers)}."
        )
    warnings = []
    ignored = [h for i, h in enumerate(headers) if i not in used and h]
    if ignored:
        warnings.append(f"Ignored column(s) not used by this recipe: {', '.join(ignored)}.")
    if missing_optional:
        warnings.append("Not in the file, filled with defaults: " + ", ".join(c.name for c in missing_optional) + ".")
    grid = []
    for raw in data_rows:
        row = {"_on": True}
        for col in recipe.columns:
            idx = col_index.get(col.key)
            value = str(raw[idx]).strip() if idx is not None and idx < len(raw) else ""
            row[col.key] = canonical_choice(col, value or col.default)
        if any(row[c.key] for c in recipe.columns):
            grid.append(row)
    if not grid:
        raise RecipeError("The file has headers but no data rows.")
    return grid, warnings


def scan_folder_rows(recipe, options_in, current_rows):
    scan = recipe.folder_scan
    if scan is None:
        raise RecipeError("This recipe has no folder scan.")
    opts = coerce_options(recipe, options_in)
    root = str(opts.get(scan.option) or "").strip()
    if not root:
        raise RecipeError(f"Set '{_option_label(recipe, scan.option)}' first.")
    if not os.path.isdir(root):
        raise RecipeError(f"Folder not found from the server: {root}")
    pattern = re.compile(scan.pattern) if scan.pattern else None
    names = []
    for entry in os.scandir(root):
        if entry.name.startswith("."):
            continue
        if (entry.is_file() if scan.files else entry.is_dir()) and (not pattern or pattern.search(entry.name)):
            names.append(entry.name)
    names.sort(key=str.lower)
    col = recipe.column(scan.column)
    existing = {}
    for r in current_rows or []:
        if isinstance(r, dict) and r.get(col.key):
            existing.setdefault(str(r[col.key]), r)
    rows = []
    for name in names:
        if name in existing:
            row = dict(existing[name])
        else:
            row = {c.key: c.default for c in recipe.columns}
            row["_on"] = True
        row[col.key] = name
        rows.append(row)
    kept = sum(1 for n in names if n in existing)
    dropped = len([k for k in existing if k not in set(names)])
    info = f"Found {len(names)} item(s) in the folder; {kept} kept their values, {len(names) - kept} new."
    if dropped:
        info += f" {dropped} row(s) no longer in the folder were removed."
    return rows, [info]


def _option_label(recipe, key):
    for o in recipe.options:
        if o.key == key:
            return o.label
    return key


# ── Pipeline ──────────────────────────────────────────────────────────────────

def coerce_options(recipe, options_in):
    options_in = options_in if isinstance(options_in, dict) else {}
    out = _Opts()
    for opt in recipe.options:
        out[opt.key] = opt.coerce(options_in.get(opt.key, opt.default))
    return out


def resolve_settings(recipe, settings_in):
    settings = recipe.default_settings()
    settings_in = settings_in if isinstance(settings_in, dict) else {}
    for part in ("render", "output", "ocio"):
        if isinstance(settings_in.get(part), dict):
            settings[part].update(settings_in[part])
    if "chunk_rows" in settings_in:
        try:
            settings["chunk_rows"] = max(0, int(settings_in.get("chunk_rows") or 0))
        except (TypeError, ValueError):
            pass
    # csv_override only reaches the scene when variations are on.
    settings["render"]["use_variations"] = True
    return settings


def prepare_rows(recipe, rows_in):
    """Ticked, non-empty grid rows as Row objects plus row-level problems."""
    errors, warnings, rows = [], [], []
    for number, raw in enumerate(rows_in or [], start=1):
        if not isinstance(raw, dict) or raw.get("_on", True) is False:
            continue
        values = {c.key: str(raw.get(c.key, "") if raw.get(c.key) is not None else "").strip()
                  for c in recipe.columns}
        if not any(values.values()):
            continue
        for c in recipe.columns:
            v = values[c.key]
            if not v and c.default:
                v = c.default
            values[c.key] = v = canonical_choice(c, v)
            if c.required and not v:
                errors.append(f"Row {number}: '{c.name}' is empty.")
            elif v and c.choices is not None and v not in c.choices:
                warnings.append(f"Row {number}: '{c.name}' value '{v}' is not one of {', '.join(c.choices)}.")
        rows.append(Row(values, number=number))
    return rows, errors, warnings


def _run_build(recipe, rows, opts, jobs, timeout):
    box = {}

    def target():
        try:
            recipe.build(rows, opts, jobs)
        except BaseException as exc:  # noqa: BLE001 - reported to the page
            box["exc"] = exc

    t = threading.Thread(target=target, daemon=True, name=f"recipe-{recipe.id}")
    t.start()
    t.join(timeout)
    if t.is_alive():
        return f"build() did not finish within {timeout} s (endless loop?)."
    exc = box.get("exc")
    if exc is None:
        return ""
    if isinstance(exc, RecipeError):
        return str(exc)
    return "build() raised an error:\n" + _recipe_traceback(exc, recipe.path)


def _chunks(n_rows, chunk_rows):
    """Table row ranges (header = row 1, data from row 2, inclusive)."""
    if chunk_rows <= 0 or n_rows <= chunk_rows:
        return [None]
    out = []
    for start in range(0, n_rows, chunk_rows):
        out.append((start + 2, min(start + chunk_rows, n_rows) + 1))
    return out


def run_recipe(recipe, rows_in, options_in=None, settings_in=None, request_id="",
               check_files=True, timeout=BUILD_TIMEOUT_SECONDS):
    """The whole pipeline. Returns a JSON-able result; ``payloads`` are
    normalized job requests ready for JobServerState / POST /submit."""
    rows, errors, warnings = prepare_rows(recipe, rows_in)
    opts = coerce_options(recipe, options_in)
    settings = resolve_settings(recipe, settings_in)
    if not rows and not errors:
        errors.append("No ticked rows with data. Load a CSV, scan a folder or add rows.")
    if not str(settings["output"].get("folder") or "").strip():
        errors.append("Output folder is required.")

    jobs = Jobs(recipe.scenes)
    if rows:
        err = _run_build(recipe, rows, opts, jobs, timeout)
        if err:
            errors.append(err)
    warnings.extend(jobs.warnings)

    scenes_out, payloads = [], []
    total_rows = 0
    if not errors:
        if not jobs.rows:
            errors.append("build() emitted no rows for any scene.")
        for key, scene in recipe.scenes.items():
            table = jobs.rows.get(key)
            if not table:
                continue
            chunk_rows = settings["chunk_rows"] if scene.chunk_rows is None else max(0, scene.chunk_rows)
            render = {**settings["render"], **scene.render, "use_variations": True}
            output = {**settings["output"], **scene.output}
            exists = None
            if check_files:
                try:
                    exists = os.path.isfile(scene.path)
                except OSError:
                    exists = False
                if not exists:
                    warnings.append(f"{key}: scene file not found from the server: {scene.path}")
            ranges = _chunks(len(table), chunk_rows)
            for rng in ranges:
                req = {
                    "schema_version": schema.JOB_SCHEMA_VERSION,
                    "request_id": request_id,
                    "max_files": [scene.path],
                    "load_scene": True,
                    "render": render,
                    "output": output,
                    "ocio": settings["ocio"],
                    "csv_override": {"headers": list(scene.headers), "rows": table},
                    "render_range_expr": f"{rng[0]}-{rng[1]}" if rng else "",
                    # Legacy dict too, so older renderers still slice.
                    "render_range": {"start": rng[0], "end": rng[1]} if rng else None,
                }
                payloads.append(schema.normalize_job_request(req))
            norm = payloads[-1]
            scenes_out.append({
                "key": key,
                "label": scene.label or key,
                "path": scene.path,
                "exists": exists,
                "headers": scene.headers,
                "rows": len(table),
                "chunk_rows": chunk_rows,
                "jobs": len(ranges),
                "ranges": [f"{r[0]}-{r[1]}" for r in ranges if r],
                "resolution": norm["render"]["resolution"] if norm["render"]["override_settings"] else None,
                "pass_limit": norm["render"]["pass_limit"] if norm["render"]["override_settings"] else None,
                "format": norm["output"]["format"],
                "version": norm["output"]["version"],
                "sample": table[:3],
            })
            total_rows += len(table)

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "log": jobs.logs,
        "scenes": scenes_out,
        "payloads": payloads if not errors else [],
        "totals": {"input_rows": len(rows), "scenes": len(scenes_out), "jobs": len(payloads) if not errors else 0,
                   "rows": total_rows},
        "settings": settings,
        "options": dict(opts),
    }


# ── HTTP API (routed from server.py) ──────────────────────────────────────────

class SubmitterAPI:
    """Handles /submitter/api/*. Returns (http_status, json_payload)."""

    def __init__(self, store, job_state):
        self.store = store
        self.job_state = job_state

    def handle(self, method, path, payload):
        parts = [p for p in path[len("/submitter/api/"):].split("/") if p]
        body = payload if isinstance(payload, dict) else {}
        try:
            if method == "GET":
                return self._get(parts)
            return self._post(parts, body)
        except RecipeLoadError as exc:
            return 422, {"error": "recipe_error", "message": str(exc)}
        except RecipeError as exc:
            return 400, {"error": "input_error", "message": str(exc)}
        except FileNotFoundError as exc:
            return 404, {"error": "not_found", "message": str(exc)}
        except FileExistsError as exc:
            return 409, {"error": "exists", "message": str(exc)}
        except ValueError as exc:
            return 400, {"error": "bad_request", "message": str(exc)}

    # GET
    def _get(self, parts):
        if parts == ["recipes"]:
            return 200, {"recipes": self.store.list(), "folder": str(self.store.root)}
        if parts == ["template"]:
            return 200, {"source": self.store.template()}
        if len(parts) == 2 and parts[0] == "recipes":
            rid = parts[1]
            source, mtime = self.store.read_source(rid)
            detail = {"id": rid, "source": source, "mtime": mtime,
                      "state": self.store.read_state(rid), "meta": None, "load_error": ""}
            try:
                detail["meta"] = load_recipe_source(rid, self.store.path_for(rid), source).meta()
            except RecipeLoadError as exc:
                detail["load_error"] = str(exc)
            return 200, detail
        if len(parts) == 3 and parts[0] == "recipes" and parts[2] == "history":
            return 200, {"history": self.store.history(parts[1])}
        if len(parts) == 2 and parts[0] == "submissions":
            return 200, self.store.read_archive(parts[1])
        return 404, {"error": "not_found"}

    # POST
    def _post(self, parts, body):
        if len(parts) != 3 or parts[0] != "recipes":
            return 404, {"error": "not_found"}
        rid, action = parts[1], parts[2]

        if action == "source":
            source = body.get("source")
            create = bool(body.get("create"))
            if create and not isinstance(source, str):
                source = self.store.template()
            if not isinstance(source, str):
                raise ValueError("source must be a string")
            res = self.store.save_source(rid, source, base_mtime=body.get("base_mtime"),
                                         force=bool(body.get("force")), create=create)
            if res["conflict"]:
                return 409, {"error": "changed_on_disk", "mtime": res["mtime"],
                             "message": "The file changed on disk since it was opened."}
            load_error = ""
            try:
                load_recipe_source(rid, self.store.path_for(rid), source)
            except RecipeLoadError as exc:
                load_error = str(exc)
            return 200, {"saved": True, "mtime": res["mtime"], "load_error": load_error}

        if action == "state":
            state = body.get("state")
            if not isinstance(state, dict):
                raise ValueError("state must be an object")
            if not self.store.exists(rid):
                raise FileNotFoundError(rid)
            self.store.save_state(rid, state)
            return 200, {"saved": True}

        recipe = self.store.load(rid)

        if action == "load_csv":
            name = str(body.get("filename") or "")
            if name.lower().endswith((".xlsx", ".xls", ".xlsm")):
                raise RecipeError("Excel files can't be read directly. In Excel use File > Save As > CSV.")
            try:
                data = base64.b64decode(str(body.get("data_b64") or ""), validate=False)
            except Exception:
                raise ValueError("data_b64 is not valid base64")
            headers, data_rows = parse_csv_text(decode_table_bytes(data))
            rows, warnings = table_to_grid(recipe, headers, data_rows)
            return 200, {"rows": rows, "warnings": warnings, "headers": headers}

        if action == "scan":
            rows, warnings = scan_folder_rows(recipe, body.get("options"), body.get("rows"))
            return 200, {"rows": rows, "warnings": warnings}

        if action == "preview":
            result = run_recipe(recipe, body.get("rows"), body.get("options"), body.get("settings"))
            if not body.get("include_payloads"):
                result.pop("payloads", None)
            return 200, result

        if action == "submit":
            request_id = str(uuid.uuid4())
            result = run_recipe(recipe, body.get("rows"), body.get("options"), body.get("settings"),
                                request_id=request_id)
            if not result["ok"]:
                result.pop("payloads", None)
                return 400, {"error": "not_submittable", "message": "; ".join(result["errors"]), "result": result}
            source_name = str(body.get("source_name") or "")
            label = f"{recipe.title}" + (f" · {source_name}" if source_name else "")
            request_id, created = self.job_state.submit_batch(
                result["payloads"], request_id=request_id,
                meta={"source": "submitter", "recipe": rid, "label": label},
            )
            record = {
                "recipe": rid,
                "recipe_title": recipe.title,
                "recipe_sha1": hashlib.sha1(recipe.source.encode("utf-8")).hexdigest(),
                "recipe_source": recipe.source,
                "request_id": request_id,
                "submitted_at": datetime.datetime.now().isoformat(timespec="seconds"),
                "source_name": source_name,
                "rows": body.get("rows") or [],
                "options": result["options"],
                "settings": result["settings"],
                "totals": result["totals"],
                "scenes": result["scenes"],
                "job_ids": [j["job_id"] for j in created],
                "payloads": result["payloads"],
            }
            archive_name = ""
            archive_error = ""
            try:
                archive_name = self.store.archive(rid, record)
            except OSError as exc:
                archive_error = str(exc)
            return 200, {"request_id": request_id, "count": len(created),
                         "job_ids": record["job_ids"], "totals": result["totals"],
                         "archive": archive_name, "archive_error": archive_error,
                         "warnings": result["warnings"]}

        return 404, {"error": "not_found"}


# ── CLI ───────────────────────────────────────────────────────────────────────

def _cli():
    ap = argparse.ArgumentParser(description="Run a submitter recipe on a CSV (preview or submit).")
    ap.add_argument("recipe", help="Path to the recipe .py file")
    ap.add_argument("csv", nargs="?", help="Client CSV (omit for recipes that scan a folder)")
    ap.add_argument("--opt", action="append", default=[], metavar="KEY=VALUE", help="Recipe option (repeatable)")
    ap.add_argument("--output-folder", default=None)
    ap.add_argument("--version", dest="out_version", default=None, help="Output version, e.g. V2")
    ap.add_argument("--chunk-rows", type=int, default=None, help="Rows per job (0 = one job per scene)")
    ap.add_argument("--save-payloads", default="", metavar="FILE", help="Write the job payloads to a JSON file")
    ap.add_argument("--submit", default="", metavar="SERVER_URL", help="POST the jobs to this server")
    args = ap.parse_args()

    recipe = load_recipe_file(args.recipe)
    options = dict(kv.split("=", 1) for kv in args.opt if "=" in kv)
    if args.csv:
        with open(args.csv, "rb") as f:
            headers, data_rows = parse_csv_text(decode_table_bytes(f.read()))
        rows, warns = table_to_grid(recipe, headers, data_rows)
    elif recipe.folder_scan:
        rows, warns = scan_folder_rows(recipe, options, [])
    else:
        ap.error("this recipe needs a CSV")
    settings = {"output": {}}
    if args.output_folder is not None:
        settings["output"]["folder"] = args.output_folder
    if args.out_version is not None:
        settings["output"]["version"] = args.out_version
    if args.chunk_rows is not None:
        settings["chunk_rows"] = args.chunk_rows

    request_id = str(uuid.uuid4()) if args.submit else ""
    result = run_recipe(recipe, rows, options, settings, request_id=request_id)
    for w in warns + result["warnings"]:
        print(f"[warn] {w}")
    for line in result["log"]:
        print(f"[log]  {line}")
    for sc in result["scenes"]:
        split = f" split {', '.join(sc['ranges'])}" if sc["ranges"] else ""
        print(f"  {sc['key']:<16} {sc['rows']:>5} rows  {sc['jobs']:>3} job(s){split}")
    t = result["totals"]
    print(f"{t['input_rows']} input rows -> {t['scenes']} scenes, {t['jobs']} jobs, {t['rows']} variation rows")
    if not result["ok"]:
        for e in result["errors"]:
            print(f"[error] {e}")
        sys.exit(1)
    if args.save_payloads:
        with open(args.save_payloads, "w", encoding="utf-8") as f:
            json.dump(result["payloads"], f, indent=2)
        print(f"Saved {len(result['payloads'])} payload(s) to {args.save_payloads}")
    if args.submit:
        from NetworkRender.shared import server_client
        for p in result["payloads"]:
            server_client.submit_job(args.submit, copy.deepcopy(p), timeout=30.0)
        print(f"Submitted {len(result['payloads'])} job(s) under request {request_id}")


if __name__ == "__main__":
    _cli()

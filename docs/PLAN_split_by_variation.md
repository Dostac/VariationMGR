# Plan: Split by Variation (right-click) + Export/Import buttons in VariationMGR

## Context

Two connected improvements:
1. Let users split a queued scene into N separate batch queue entries (one per variation row)
   so all workers can participate, not just one per scene. Triggered on-demand via right-click
   in the batch renderer queue — only available when a variation JSON override is assigned.
2. Add Export/Import Variation Data buttons to the VariationMGR dialog for easy access,
   without removing the existing standalone scripts.

---

## Approach: Split at Queue Entry Level (no schema changes)

The right-click "Split by Variation" action replaces one queue entry with N entries —
one per variation row — each carrying a single-row `variation_override` dict directly
in memory (no temp files written). Each entry then flows through the existing job-building
path as if it were a normal entry with a var_json already loaded.

This requires no changes to `job_schema.py`, `server.py`, or `networkrender.py`.

---

## Part 1: Split by Variation — `batchrenderer_UI.py`

### Entry dict extension

Add an optional key to the entry dict:
```python
{"path": str, "var_json": str, "variation_override": dict | None}
```
`variation_override` holds a pre-loaded single-row VariationManagerData dict.
When present, it is used directly instead of loading from `var_json`.

### `_collect_scene_jobs()` — check entry override first

```python
# Priority: in-memory override (from split) > var_json file > nothing
if entry.get("variation_override") is not None:
    override = entry["variation_override"]
elif var_json:
    override = self._load_variation_override(var_json, os.path.basename(path))
else:
    override = None

if override is not None:
    request["variation_override"] = override
```

Apply the same priority logic in `submit_to_server()`.

### Right-click menu: add "Split by Variation"

In the context menu builder (currently at lines 718-751), add after "Clear Variation JSON":
```python
act_split = menu.addAction("Split by Variation")
act_split.setEnabled(bool(entry.get("var_json")))  # only when JSON is assigned
```

Wire it:
```python
if chosen == act_split and entry.get("var_json"):
    self._split_entry_by_variation(i)
```

### `_split_entry_by_variation(entry_index)` — new method

```python
def _split_entry_by_variation(self, idx):
    entry = self.file_entries[idx]
    var_data = self._load_variation_override(entry["var_json"], os.path.basename(entry["path"]))
    if var_data is None:
        self.log("Split by Variation: could not load variation JSON.")
        return

    rows = var_data.get("rows", [])
    if not rows:
        self.log("Split by Variation: no rows found in variation data.")
        return

    new_entries = []
    for row_idx, row_vals in enumerate(rows):
        single_row_data = dict(var_data)          # shallow copy of full structure
        single_row_data["rows"] = [row_vals]
        new_entries.append({
            "path":                 entry["path"],
            "var_json":             entry["var_json"],
            "variation_override":   single_row_data,
            "_variation_row_index": row_idx,      # for {Row} token (see core fix)
        })

    self.file_entries[idx:idx + 1] = new_entries  # replace original with N entries
    self._rebuild_tree()
    self.log(f"Split '{os.path.basename(entry['path'])}' into {len(rows)} variation jobs.")
```

### `_refresh_tree_item()` — show split indicator

When `entry.get("variation_override") is not None`, display e.g. `"(split row N)"` in the
Variation Data column so the user can see which entries are split jobs.

### `_rebuild_tree()` — convenience helper

A simple method that clears the tree widget and re-adds all entries from `self.file_entries`.
Used after split (and remove) to keep the tree consistent.

---

## Part 2: `{Row}` token fix — `batchrenderer_core.py`

Without this, all split jobs have `row_idx=0` and every `{Row}` resolves to `"1"`,
causing output filename collisions.

In `render_scene_job()`, after reading `variation_data`:
```python
_row_index_offset = scene_job.get("_variation_row_index", None)
```

In the variation loop:
```python
for _loop_idx, row_vals in enumerate(rows):
    row_idx = (
        _row_index_offset
        if (_row_index_offset is not None and len(rows) == 1)
        else _loop_idx
    )
    # ... rest of loop unchanged
```

This is backward-compatible: non-split jobs have `_row_index_offset=None` → behavior identical to today.

`_variation_row_index` must be threaded through the job payload. In `_collect_scene_jobs()` /
`submit_to_server()`, when building the request from an entry:
```python
if entry.get("_variation_row_index") is not None:
    request["_variation_row_index"] = entry["_variation_row_index"]
```

In `job_schema.normalize_job_request()`, the underscore-prefixed key passes through unchanged
(or explicitly preserve it). Verify this in the normalization code.

---

## Part 3: Export/Import — `variation_core.py` + `VariationMGR.py`

### Design principle

`variation_core.py` is a headless module (runs in batch/worker contexts too).
It must have zero Qt dependency. The two new functions it gains are pure data operations:

```python
def read_variation_data(rt) -> dict | None:
    """Read VariationManagerData from the current scene. Returns dict or None."""

def write_variation_data(rt, data: dict) -> None:
    """Overwrite VariationManagerData in the current scene custom properties."""
```

No file I/O, no dialogs, no parent widgets — just rt + dict in/out.

**Bonus consolidation:** `batchrenderer_core.py` has a private `_read_variation_data()`
instance method doing the same thing. Replace its body with a call to
`variation_core.read_variation_data(self.rt)` to eliminate the duplication.

### `variation_core.py` — two new functions

```python
def read_variation_data(rt):
    """Return the VariationManagerData dict from the current scene, or None."""
    try:
        count = rt.fileProperties.getNumProperties(rt.name("custom"))
        for i in range(1, count + 1):
            if rt.fileProperties.getPropertyName(rt.name("custom"), i) == "VariationManagerData":
                return json.loads(rt.fileProperties.getPropertyValue(rt.name("custom"), i))
    except Exception:
        pass
    return None


def write_variation_data(rt, data):
    """Write data dict as VariationManagerData custom property in the current scene."""
    raw = json.dumps(data)
    count = rt.fileProperties.getNumProperties(rt.name("custom"))
    for i in range(count, 0, -1):
        if rt.fileProperties.getPropertyName(rt.name("custom"), i) == "VariationManagerData":
            rt.fileProperties.deleteProperty(rt.name("custom"), i)
            break
    rt.fileProperties.addProperty(rt.name("custom"), "VariationManagerData", raw)
```

### `VariationMGR.py` — thin UI wrappers only

All dialog and feedback logic lives here; the data work is delegated to `variation_core`.

**Toolbar buttons** — insert after "⬆ Export CSV", before separator:
```python
self.btn_export_var = QtWidgets.QPushButton("📤 Export Var JSON")
self.btn_import_var = QtWidgets.QPushButton("📥 Import Var JSON")
# connect: self.btn_export_var.clicked.connect(self._export_variation_data)
#          self.btn_import_var.clicked.connect(self._import_variation_data)
```

**`_export_variation_data()`:**
```python
def _export_variation_data(self):
    data = variation_core.read_variation_data(self.rt)
    if data is None:
        QtWidgets.QMessageBox.warning(self.main_widget, "Export", "No variation data in scene.")
        return
    scene_name = os.path.splitext(self.rt.maxFileName)[0] if self.rt.maxFileName else "scene"
    default_path = os.path.join(self.rt.maxFilePath or "", f"{scene_name}_VariationManagerData.json")
    path, _ = QtWidgets.QFileDialog.getSaveFileName(
        self.main_widget, "Export Variation Data", default_path, "JSON (*.json)"
    )
    if not path:
        return
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    QtWidgets.QMessageBox.information(self.main_widget, "Export", f"Saved to:\n{path}")
```

**`_import_variation_data()`:**
```python
def _import_variation_data(self):
    path, _ = QtWidgets.QFileDialog.getOpenFileName(
        self.main_widget, "Import Variation Data", "", "JSON (*.json)"
    )
    if not path:
        return
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        QtWidgets.QMessageBox.warning(self.main_widget, "Import", "Invalid variation data file.")
        return
    variation_core.write_variation_data(self.rt, data)
    self._load_from_scene()   # refresh table/operators in UI
    QtWidgets.QMessageBox.information(self.main_widget, "Import", "Imported and UI refreshed.")
```

### Standalone scripts — slim down to delegates

`export_variation_data.py` and `import_variation_data.py` currently contain 50-80 lines
of duplicated logic. Update them to import from `variation_core` and handle only their own
file dialog and print output. They remain fully standalone; no dependency on VariationMGR.

---

## Files to Modify

| File | Changes |
|---|---|
| `variation_core.py` | Add `read_variation_data(rt)` and `write_variation_data(rt, data)` |
| `batchrenderer_core.py` | Replace `_read_variation_data()` body with `variation_core.read_variation_data(self.rt)`; add `_variation_row_index` hint to variation loop |
| `batchrenderer_UI.py` | Right-click "Split by Variation"; `_split_entry_by_variation()`; entry dict extension; `_collect_scene_jobs()` / `submit_to_server()` override priority; tree refresh |
| `VariationMGR.py` | Two toolbar buttons + thin UI wrapper methods calling `variation_core` |
| `export_variation_data.py` | Slim to delegate: call `variation_core.read_variation_data()`, keep own file dialog |
| `import_variation_data.py` | Slim to delegate: call `variation_core.write_variation_data()`, keep own file dialog |
| `NetworkRender/shared/job_schema.py` | Read-only verify: confirm `_variation_row_index` passes through `normalize_job_request` unchanged |

No changes to: `job_schema.py` (root shim), `server.py`, `networkrender.py`, `worker.py`.

---

## Verification

1. In VariationMGR, configure 3 variation rows, save scene data.
2. Click "📤 Export Var JSON" → confirm JSON file saved with 3 rows.
3. In Batch Renderer, add the scene to the queue and assign the exported JSON via
   "Assign Variation JSON...".
4. Right-click the entry → "Split by Variation" should now be enabled.
5. Click it → confirm the one entry becomes 3 entries in the queue, each labeled with
   row indicator in Variation Data column.
6. Submit to network with multiple workers → confirm 3 separate jobs appear in server queue.
7. Confirm renders output with correct `{Row}` values (1, 2, 3 — not all 1).
8. Test "📥 Import Var JSON" in VariationMGR — confirm table refreshes without reopening dialog.
9. Confirm standalone `export_variation_data.py` and `import_variation_data.py` still work
   independently via the Python listener.

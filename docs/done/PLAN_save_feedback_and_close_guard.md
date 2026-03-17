# Plan: Save Confirmation Dialog + Unsaved-Changes Close Guard

## Context

`VariationMGR.py` currently silently prints to the console when the user saves variation data into the scene, giving no visible feedback. Additionally, the window can be closed at any time with no check for unsaved changes, risking data loss after the user has edited the table or operator settings without saving.

This plan adds:
1. A visible success dialog after saving.
2. A close-guard that detects unsaved changes and prompts the user before closing.

---

## Critical File

- `VariationMGR.py` — only file changed.

---

## Implementation Steps

### Step 1 — Extract `_build_current_data() -> dict`

The save-dict assembly is currently inline inside `save_to_max_file` (lines 401–433). Extract it into a private method so both `save_to_max_file` and the new `closeEvent` can call it without duplicating the table-walk logic.

```python
def _build_current_data(self) -> dict:
    hdr = self.table.horizontalHeader()
    headers = [self.table.horizontalHeaderItem(hdr.logicalIndex(v)).text()
               for v in range(self.table.columnCount())]
    rows = []
    for r in range(self.table.rowCount()):
        row_vals = []
        for v in range(self.table.columnCount()):
            item = self.table.item(r, hdr.logicalIndex(v))
            row_vals.append(item.text() if item else "")
        rows.append(row_vals)

    saved_ops = []
    for op in self.active_ops_instances:
        inst = op["instance"]
        settings = inst.serialize() if hasattr(inst, 'serialize') else {}
        saved_ops.append({
            "class_name": op["name"],
            "settings": settings,
            "ops_folder": self.ops_folder,
        })

    return {
        "scheme": self.edt_pattern.text(),
        "render_camera_mode": self.render_camera_mode,
        "render_camera_column": self.render_camera_column,
        "ops_folder": self.ops_folder,
        "headers": headers,
        "rows": rows,
        "operators": saved_ops,
    }
```

### Step 2 — Add `_read_saved_data() -> dict | None`

A lightweight helper that reads the raw JSON blob from `rt.fileProperties` and returns the parsed dict (or `None` if not found / invalid). No UI side-effects.

```python
def _read_saved_data(self):
    prop_count = rt.fileProperties.getNumProperties(rt.name('custom'))
    for i in range(1, prop_count + 1):
        if rt.fileProperties.getPropertyName(rt.name('custom'), i) == "VariationManagerData":
            try:
                return json.loads(rt.fileProperties.getPropertyValue(rt.name('custom'), i))
            except Exception:
                return None
    return None
```

### Step 3 — Simplify `save_to_max_file`

Replace the inline dict-build with `_build_current_data()`, and swap the `print` with a `QMessageBox.information` popup.

```python
def save_to_max_file(self):
    data = self._build_current_data()
    rt.fileProperties.addProperty(rt.name('custom'), "VariationManagerData", json.dumps(data))
    QMessageBox.information(self, "Variation Manager", "Data saved successfully.")
```

### Step 4 — Add `closeEvent`

Override `closeEvent` to compare the current UI state against the last saved scene blob. Use `json.dumps` with `sort_keys=True` for a stable string comparison (avoids false positives from dict key ordering).

If they differ, show a Yes / No / Cancel prompt:
- **Yes** → save then close
- **No** → close without saving
- **Cancel** → abort close

```python
def closeEvent(self, event):
    saved = self._read_saved_data()
    current = self._build_current_data()

    saved_str   = json.dumps(saved,   sort_keys=True) if saved   is not None else None
    current_str = json.dumps(current, sort_keys=True)

    if saved_str != current_str:
        reply = QMessageBox.question(
            self,
            "Unsaved Changes",
            "You have unsaved variation data.\nSave to scene before closing?",
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
            QMessageBox.Yes,
        )
        if reply == QMessageBox.Yes:
            rt.fileProperties.addProperty(
                rt.name('custom'), "VariationManagerData", json.dumps(current)
            )
        elif reply == QMessageBox.Cancel:
            event.ignore()
            return

    super().closeEvent(event)
```

---

## Edge Cases

- **No scene data saved yet** (`_read_saved_data` returns `None`): `None != current_str` is always `True`, so the prompt fires even on first close after entering data. This is correct — the user has unsaved work.
- **Empty table, no operators, fresh open**: `current` will equal whatever was in the scene (possibly both empty), so no prompt fires when closing a clean/unchanged state.
- **Operator `serialize()` missing**: already guarded with `hasattr` (matches existing pattern in `save_to_max_file`).

---

## Verification

1. Open Variation Manager, add a row, close without saving → prompt appears.
2. Choose **Cancel** → window stays open.
3. Choose **No** → window closes, data not saved (reopen confirms old data).
4. Choose **Yes** → window closes, data saved (reopen confirms new data).
5. Save via **Save Data** button → success popup appears; close immediately → no prompt (data matches).
6. Open with no prior scene data, make no changes, close → prompt fires once (no saved data exists); click No to close cleanly.

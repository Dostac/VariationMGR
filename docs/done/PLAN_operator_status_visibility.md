# Plan: Operator Status Visibility in VariationMGR

## Context
Operator errors are currently only visible inside each operator's own tab via `lbl_status` at the bottom of the widget. When multiple operators are active, it's not obvious **which** tab has an error without clicking through each one. Two changes address this:

1. **Move `lbl_status` to the top** of each operator's UI so errors are immediately visible.
2. **Add tab warning icons** — when an operator reports an error, its tab title gets a ⚠ prefix.

## Approach

### Signal pattern (added to every operator)
- Declare `status_changed = QtCore.Signal(str, bool)` as a class attribute.
- Emit it at the end of `_set_status()`: `self.status_changed.emit(msg, error)`.
- In batch renderer context, no one connects → emit is a no-op. Fully backward-compatible.

### VariationMGR.py changes
- In `add_operator_tab()` (line 338), after `self.tabs.addTab(widget, op_class_name)`:
  ```python
  if hasattr(op_instance, 'status_changed'):
      op_instance.status_changed.connect(
          lambda msg, err, w=widget: self._on_operator_status(w, msg, err)
      )
  ```
- New method `_on_operator_status(self, widget, msg, is_error)`:
  - Look up `self.tabs.indexOf(widget)` (handles reordering).
  - Find the base name from `self.active_ops_instances`.
  - If `is_error and msg`: `self.tabs.setTabText(idx, f"⚠ {base_name}")`.
  - Otherwise: `self.tabs.setTabText(idx, base_name)` (clear prefix).

### Status label relocation (every operator)
Move `lbl_status` from bottom (above `addStretch()`) to top (right after root layout setup, before first card/group). Add `setWordWrap(True)` and a small spacing after it.

## Files to modify

### `VariationMGR.py`
- Add signal connection in `add_operator_tab()` after line 338.
- Add `_on_operator_status()` method.

### `Operators/layer_visibility.py`
- Add `status_changed = QtCore.Signal(str, bool)` class attribute.
- `_setup_ui()`: Move `lbl_status` from lines 44-45 to after line 27, add `setWordWrap(True)`.
- `_set_status()`: Add `self.status_changed.emit(msg, error)`.

### `Operators/HexColorOperator.py`
- Add `status_changed` signal.
- `_setup_ui()`: Move `lbl_status` from bottom to top of layout.
- `_set_status()`: Add emit after existing print line.

### `Operators/FloorGeneratorOperator.py`
- Add `status_changed` signal.
- `_setup_ui()`: Move `lbl_status` from lines ~218-221 to top of `content_root` (after line ~91, before Card 1).
- `_set_status()`: Add emit.

### `Operators/mat_from_folder.py`
- Add `status_changed` signal.
- `_setup_ui()`: Move `lbl_status` from bottom to top of `root` layout.
- `_set_status()`: Add emit.

### `Operators/matlib_replacement.py` (MultiSubLibOperator)
- Add `status_changed` signal.
- `_setup_ui()`: Move `lbl_status` to top.
- `_set_status()`: Add emit.

### `Operators/unlit_colors.py`
- Add `status_changed` signal.
- `_setup_ui()`: Move `lbl_status` to top.
- `_set_status()`: Add emit.

### `Operators/OPERATORS.md`
- Add `status_changed` signal to class skeleton.
- Update `_set_status` section to include `emit`.
- Update "Status Label Placement" section: top of root layout instead of bottom.

## Backwards Compatibility
- The `status_changed` signal is **optional**. `hasattr(op_instance, 'status_changed')` guards the connection in `add_operator_tab()` — old/third-party operators without the signal work exactly as before (no tab icon, no error).
- The 5 required operator methods (`get_ui`, `execute`, `serialize`, `deserialize`, `on_columns_changed`) are unchanged. No API break.
- Old operators keep their `lbl_status` at whatever position they have — we only relocate it in the built-in operators we control.
- OPERATORS.md will document the signal as **recommended** (for tab icon support) but not required.

## Verification
1. Open VariationMGR in 3ds Max.
2. Add two operators (e.g. LayerVisibility + HexColor).
3. Configure one correctly and leave the other misconfigured.
4. Click "RUN SELECTED ROW" → the misconfigured operator's tab should show `⚠ OperatorName`, and the status message should appear at the top of that operator's panel.
5. Fix the configuration and re-run → warning prefix clears.
6. Reorder tabs by dragging → warning still tracks the correct tab.

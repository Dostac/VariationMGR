# Operator Development Guide

Operators are the plugin units of the Variation Manager. Each operator is a self-contained Python
class that reads one row of variation data and applies a targeted change to the 3ds Max scene.
This document defines the full contract, conventions, and patterns to follow when writing a new
operator. Read an existing simple operator (e.g. `layer_visibility.py`) alongside this guide.

---

## File and Class Naming

- One operator per `.py` file. Place the file directly in the `Operators/` folder.
- The class name and the filename should clearly describe what the operator does.
- There are no naming restrictions, but avoid generic names — be specific
  (`HexColorOperator`, not `ColorOperator`).

---

## Required Interface

Every operator class **must** implement these five methods. The Variation Manager calls them
by name; missing any will raise an `AttributeError` at runtime.

| Method | When called | Purpose |
|---|---|---|
| `get_ui()` | Once, on operator add | Returns the operator's config widget. |
| `on_columns_changed(columns)` | On CSV load/change | Refreshes column-mapped dropdowns. |
| `execute(row_data)` | Once per variation row | Applies the scene change. |
| `serialize()` | On scene save | Returns a JSON-serialisable dict of current state. |
| `deserialize(data)` | On scene load | Restores state from a previously serialised dict. |

---

## Class Skeleton

```python
from PySide6 import QtWidgets, QtCore

class MyOperator(QtCore.QObject):
    """
    One-line description of what this operator does.

    Static Fields: the user-configured settings that don't change per row.
    Properties (Driven): which CSV columns drive scene changes at render time.
    """
    status_changed = QtCore.Signal(str, bool)

    def __init__(self, context=None):
        super().__init__()
        self.rt = context.get("rt") if context else None
        self.instance_id = context.get("instance_id", "") if context else ""

        # --- Persistent state (static fields) ---
        # Set Python-side defaults here. These are what serialize() saves.
        self.my_setting = ""

        # --- Column mappings (driven properties) ---
        # These hold the name of the CSV column the user has selected.
        self.my_column = ""

        self.main_widget = QtWidgets.QWidget()
        self._setup_ui()

    # -----------------------------------------------------------------------
    # UI
    # -----------------------------------------------------------------------

    def _setup_ui(self):
        root = QtWidgets.QVBoxLayout(self.main_widget)
        root.setContentsMargins(12, 12, 12, 12)  # MD3 outer margin
        root.setSpacing(0)  # spacing between cards is added explicitly

        # Status label at top — visible without scrolling.
        self.lbl_status = QtWidgets.QLabel("")
        self.lbl_status.setWordWrap(True)
        root.addWidget(self.lbl_status)
        root.addSpacing(4)

        # Group every distinct config section into a QGroupBox (MD3 card).
        grp = QtWidgets.QGroupBox("1. ...")
        lay = QtWidgets.QVBoxLayout(grp)
        lay.setContentsMargins(16, 12, 16, 12)  # MD3 card interior padding
        lay.setSpacing(8)
        # ... widgets ...
        root.addWidget(grp)

        root.addSpacing(8)  # gap between cards

        grp2 = QtWidgets.QGroupBox("2. Column Mapping")
        lay2 = QtWidgets.QVBoxLayout(grp2)
        lay2.setContentsMargins(16, 12, 16, 12)
        lay2.setSpacing(8)
        self.combo_col = QtWidgets.QComboBox()
        lay2.addWidget(QtWidgets.QLabel("Drive property with column:"))
        lay2.addWidget(self.combo_col)
        root.addWidget(grp2)

        root.addStretch()

        # Wire signals to keep Python state in sync with the UI.
        self.combo_col.currentTextChanged.connect(lambda t: setattr(self, "my_column", t))

    # -----------------------------------------------------------------------
    # Manager interface
    # -----------------------------------------------------------------------

    def get_ui(self):
        return self.main_widget

    def on_columns_changed(self, columns):
        """Refresh all column-mapped QComboBoxes from a new column list."""
        self.combo_col.blockSignals(True)
        self.combo_col.clear()
        self.combo_col.addItem("-- Select Column --")
        self.combo_col.addItems(columns)
        idx = self.combo_col.findText(self.my_column)
        self.combo_col.setCurrentIndex(idx if idx != -1 else 0)
        self.combo_col.blockSignals(False)
        # Always sync internal state back from the combo after rebuilding.
        self.my_column = self.combo_col.currentText()

    def execute(self, row_data):
        # Guard: require 3ds Max runtime.
        if not self.rt:
            self._set_status("3ds Max runtime not available.", True)
            return

        # Guard: require configuration.
        if not self.my_setting:
            self._set_status("Not configured.", True)
            return

        # Guard: require column mapping.
        if not self.my_column or self.my_column == "-- Select Column --":
            self._set_status("No column selected.", True)
            return
        if self.my_column not in row_data:
            self._set_status(f"Column '{self.my_column}' missing.", True)
            return

        value = row_data[self.my_column].strip()

        # --- Do work ---

        self._set_status(f"Applied '{value}'.")

    # -----------------------------------------------------------------------
    # Persistence
    # -----------------------------------------------------------------------

    def serialize(self):
        return {
            "my_setting": self.my_setting,
            "my_column":  self.my_column,
        }

    def deserialize(self, data):
        # 1. Restore Python state first.
        self.my_setting = data.get("my_setting", "")
        self.my_column  = data.get("my_column",  "")

        # 2. Sync widgets that don't depend on the column list.
        #    (Column combos are populated later by on_columns_changed.)

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _set_status(self, msg, error=False):
        self.lbl_status.setText(msg)
        self.lbl_status.setStyleSheet("color: #ff6666;" if error else "color: #66ff66;")
        self.status_changed.emit(msg, error)
```

---

## Context and the `rt` Object

`context` is a dict passed by the Variation Manager at instantiation time:

```python
{"rt": <pymxs runtime>, "instance_id": "a1b2c3d4"}
```

`self.rt` is the `pymxs` runtime object. It gives access to the full MAXScript API.
Always guard against `None` — operators may be instantiated in environments where
3ds Max is unavailable (e.g. during a UI-only load or headless worker startup before
the scene is ready).

```python
if not self.rt:
    self._set_status("3ds Max runtime not available.", True)
    return
```

---

## Instance ID

Every operator instance receives a unique `instance_id` string (8-character hex) via
`context["instance_id"]`. The Variation Manager generates this ID when the operator is
first added and persists it alongside the operator's `class_name` in the scene JSON. The
same ID is restored on scene load, so it is stable across sessions.

```python
def __init__(self, context=None):
    super().__init__()
    self.rt = context.get("rt") if context else None
    self.instance_id = context.get("instance_id", "") if context else ""
```

**When to use it:** Only when your operator creates helper objects in the 3ds Max scene
(dummies, point helpers, etc.) that it needs to find and clean up on subsequent executions.
Name the helper with a predictable pattern that includes the instance ID:

```python
dummy_name = f"VB_MyOperator_{self.instance_id}"
```

This ensures that multiple instances of the same operator class each track their own
helper objects without collisions.

**Most operators do not need this.** If your operator only modifies existing scene objects
(materials, layers, maps, etc.), you can ignore `instance_id` entirely.

---

## Referencing Scene Objects

Never store a direct Python reference to a 3ds Max node or material. These references
become invalid immediately. Use **name + handle** together, but treat **name as the primary
lookup**. Handles are session-specific — they become stale every time a `.max` scene is
opened, which means they will always be wrong on the first `execute()` call after a scene
load (including every iteration of a batch render job).

```python
# Capture (in a pick/select handler):
self.target_node_name   = obj.name
self.target_node_handle = self.rt.GetHandleByAnim(obj)   # refreshed each session

# Resolve (in execute) — name first, handle as fallback only:
node = None
if self.target_node_name:
    node = self.rt.getNodeByName(self.target_node_name)
    if node:
        self.target_node_handle = self.rt.GetHandleByAnim(node)  # refresh
if not node and self.target_node_handle:
    node = self.rt.GetAnimByHandle(self.target_node_handle)
if not node:
    self._set_status("Target object not found in scene.", True)
    return
```

For materials and map nodes, use the equivalent name-first pattern with
`rt.sceneMaterials` or `rt.getClassInstances(ClassName)` respectively.

Both `target_node_name` and `target_node_handle` should be in `serialize()` /
`deserialize()`. The early guard in `execute()` should check the name, not the handle:

```python
if not self.target_node_name: return   # ✓ correct
if not self.target_node_handle: return # ✗ will always fail after scene reload
```

---

## Column Dropdowns — `on_columns_changed`

Follow this pattern exactly for every column-mapped `QComboBox`:

```python
def on_columns_changed(self, columns):
    self.combo_col.blockSignals(True)      # prevent premature state update
    self.combo_col.clear()
    self.combo_col.addItem("-- Select Column --")
    self.combo_col.addItems(columns)
    idx = self.combo_col.findText(self.my_column)  # restore from internal state
    self.combo_col.setCurrentIndex(idx if idx != -1 else 0)
    self.combo_col.blockSignals(False)
    self.my_column = self.combo_col.currentText()  # sync back after rebuild
```

Key points:
- Use `self.my_column` (internal state) — **not** `self.combo_col.currentText()` — as the
  source of truth for restoration. The combo may be empty or stale at restore time.
- Always call `blockSignals(True/False)` around the rebuild to avoid spurious signal fires.
- Always sync the internal attribute back from the combo *after* `blockSignals(False)`.
- The sentinel placeholder is `"-- Select Column --"` for required columns.
  Use `"-- none --"` for optional/nullable column mappings.

**Do not set column combo indexes in `deserialize()`**. The column list is populated
by the parent UI later, via `on_columns_changed`. Only restore non-column widgets
(text fields, checkboxes, spin boxes, labels) in `deserialize()`.

---

## Execute — Guard Order

Structure `execute()` with guards from outermost to innermost:

1. Runtime available (`self.rt`)
2. Required static targets configured (handle, path, etc.)
3. Required column mapping selected and present in `row_data`
4. Value is parseable / valid
5. Scene object resolved by handle
6. Do work

Return early at the first failed guard and call `_set_status` with a clear message.
Do not raise exceptions from `execute()` — the batch renderer wraps each operator in a
try-except, but a descriptive status message is more useful than a traceback in the logs.

---

## Status Feedback — `_set_status`

Every operator must have this helper method:

```python
def _set_status(self, msg, error=False):
    self.lbl_status.setText(msg)
    self.lbl_status.setStyleSheet("color: #ff6666;" if error else "color: #66ff66;")
    self.status_changed.emit(msg, error)
```

- Error (red `#ff6666`): call with `error=True`.
- Success (green `#66ff66`): call with `error=False` (default).
- The `status_changed` signal is **recommended** but not required. When present, the
  Variation Manager connects to it and shows a ⚠ prefix on the operator's tab when an
  error is reported. Operators without this signal work normally — no tab icon, no error.
- Add `print(f"MyOperator ERROR: {msg}")` for errors if the operator performs
  non-trivial scene mutations that are hard to diagnose from the UI alone.
- Clear the status at the start of a successful pick action by calling `_set_status("")`.

---

## Serialisation

`serialize()` returns a flat `dict` with JSON-serialisable values only
(strings, numbers, booleans, lists, dicts — no Python objects, no `None` handles unless
truly optional).

`deserialize(data)` uses `.get(key, default)` for every key — never assume a key is present.
This ensures backward compatibility when new fields are added to an operator.

```python
def serialize(self):
    return {
        "my_setting":         self.my_setting,
        "target_node_name":   self.target_node_name,
        "target_node_handle": self.target_node_handle,
        "my_column":          self.my_column,
    }

def deserialize(self, data):
    self.my_setting         = data.get("my_setting",         "")
    self.target_node_name   = data.get("target_node_name",   "")
    self.target_node_handle = data.get("target_node_handle", None)
    self.my_column          = data.get("my_column",          "")

    # Restore non-column widgets immediately.
    if self.target_node_name:
        self.lbl_target.setText(f"Target: {self.target_node_name}")
    # Column combos: restored later by on_columns_changed.
```

---

## Module-Level Helpers

For operators that involve complex scene graph traversal (recursive material/map walking,
file system scanning, metadata parsing), extract the logic into **module-level functions**
rather than instance methods. This:

- Makes the logic independently testable.
- Keeps the class body focused on the operator contract.
- Avoids capturing `self` unintentionally in recursive calls.

```python
# Module level — no self
def _walk_material_graph(rt, node, _seen=None):
    if _seen is None:
        _seen = set()
    ...

class MyOperator(QtCore.QObject):
    def execute(self, row_data):
        result = _walk_material_graph(self.rt, node)
```

Use a `_seen` set (keyed by handle) to guard against infinite loops in cyclic graphs.

---

## UI Layout — Material Design 3 Through Structure

The entire suite follows **Material Design 3** principles. The constraint is that we run inside
both native PySide6 processes and inside 3ds Max's embedded Qt instance (`qtmax`). Heavy
`setStyleSheet()` calls override the host application's widget rendering in unpredictable ways
and must be avoided entirely.

The approach is: achieve MD3's visual hierarchy and spatial rhythm through **layout structure,
margins, spacing, and widget sizing only** — exactly like writing semantic HTML where layout
conveys structure without inline styles.

### The Only Acceptable Stylesheet Use

The single permitted `setStyleSheet()` call is in `_set_status`, where color communicates
semantic state (error vs. success). This is an MD3 principle — error states are red, confirmations
are a positive colour — and there is no layout-only alternative for it.

```python
def _set_status(self, msg, error=False):
    self.lbl_status.setText(msg)
    self.lbl_status.setStyleSheet("color: #ff6666;" if error else "color: #66ff66;")
```

Do not add any other `setStyleSheet()` calls anywhere in an operator.

---

### Spacing Scale (4dp Grid)

MD3 is built on a 4dp base grid. Map it directly to pixels:

| Token | Value | Use |
|---|---|---|
| `xs` | `4px` | Between tightly coupled elements (icon + label inline) |
| `sm` | `8px` | Between form rows; within a group |
| `md` | `12px` | GroupBox internal top/bottom padding |
| `lg` | `16px` | Root widget margin; GroupBox left/right padding |
| `xl` | `24px` | Between independent card groups |

```python
layout.setContentsMargins(16, 16, 16, 16)   # root: lg on all sides
grp_layout.setContentsMargins(16, 12, 16, 12)  # card interior: lg h, md v
layout.setSpacing(8)                         # sm — standard row gap within a section
layout.addSpacing(8)                         # sm — between cards in root layout
```

---

### Cards — `QGroupBox` as MD3 Surface

Use `QGroupBox` for every distinct configuration section. The group title maps to MD3's
"label large" text that identifies the card. Number the titles to make setup steps scannable.

```python
grp = QtWidgets.QGroupBox("1. Target Object")
lay = QtWidgets.QVBoxLayout(grp)
lay.setContentsMargins(16, 12, 16, 12)
lay.setSpacing(8)
```

- Simple operators with only 1–2 settings may skip `QGroupBox` and use a flat `QVBoxLayout`
  with manual `addSpacing(16)` between sections.
- The root `main_widget` layout always uses `setContentsMargins(12, 12, 12, 12)` and
  `setSpacing(0)` — spacing between cards is added explicitly with `addSpacing(8)`.

---

### Component Sizing

Never set arbitrary heights on standard input widgets — let the system render them at their
natural size. Apply explicit sizing only to these cases:

| Widget | Rule | Code |
|---|---|---|
| Icon-action buttons (`...`, `↻`, `X`) | Fixed square | `btn.setFixedWidth(28)` |
| Standard action buttons | Natural width unless inline | — |
| `QSpinBox`, `QLineEdit` (inline, short) | Fixed width to prevent overflow | `w.setFixedWidth(60)` |
| Full-width inputs | Stretch to fill | `layout.addWidget(w)` or `addWidget(w, stretch=1)` |

---

### Form Row Patterns

**Full-width input (primary field):**
```python
layout.addWidget(QtWidgets.QLabel("Root Folder:"))
row = QtWidgets.QHBoxLayout()
self.edit_path = QtWidgets.QLineEdit()
btn = QtWidgets.QPushButton("...")
btn.setFixedWidth(28)
row.addWidget(self.edit_path, stretch=1)
row.addWidget(btn)
layout.addLayout(row)
```

**Inline picker (pick button + state label):**
```python
row = QtWidgets.QHBoxLayout()
self.btn_pick = QtWidgets.QPushButton("Pick from Scene")
self.lbl_target = QtWidgets.QLabel("Target: (None)")
row.addWidget(self.btn_pick)
row.addWidget(self.lbl_target, stretch=1)
layout.addLayout(row)
```

**Inline pair (two short inputs):**
```python
row = QtWidgets.QHBoxLayout()
row.addWidget(QtWidgets.QLabel("W:"))
self.edit_w = QtWidgets.QLineEdit()
self.edit_w.setFixedWidth(60)
row.addWidget(self.edit_w)
row.addWidget(QtWidgets.QLabel("H:"))
self.edit_h = QtWidgets.QLineEdit()
self.edit_h.setFixedWidth(60)
row.addWidget(self.edit_h)
row.addStretch()
layout.addLayout(row)
```

**Column dropdown (full width):**
```python
layout.addWidget(QtWidgets.QLabel("Drive with column:"))
self.combo_col = QtWidgets.QComboBox()
layout.addWidget(self.combo_col)
```

---

### Dividers

Use `QFrame` with `HLine` to create MD3-style dividers between sub-sections inside a card.
Do not style it — it will inherit the system's separator colour automatically.

```python
sep = QtWidgets.QFrame()
sep.setFrameShape(QtWidgets.QFrame.HLine)
layout.addWidget(sep)
layout.addSpacing(4)
```

---

### Status Label Placement

Always place `lbl_status` at the **top** of the root layout, right after the layout setup
and before the first card/group. This ensures errors are immediately visible without
scrolling:

```python
self.lbl_status = QtWidgets.QLabel("")
self.lbl_status.setWordWrap(True)
layout.addWidget(self.lbl_status)
layout.addSpacing(4)
```

---

### Updated Skeleton (`_setup_ui`)

The skeleton from the Class Skeleton section should be written like this:

```python
def _setup_ui(self):
    root = QtWidgets.QVBoxLayout(self.main_widget)
    root.setContentsMargins(12, 12, 12, 12)
    root.setSpacing(0)   # control spacing explicitly between groups

    # --- Status (top, visible without scrolling) ---
    self.lbl_status = QtWidgets.QLabel("")
    self.lbl_status.setWordWrap(True)
    root.addWidget(self.lbl_status)
    root.addSpacing(4)

    # --- Card 1 ---
    grp1 = QtWidgets.QGroupBox("1. Target")
    lay1 = QtWidgets.QVBoxLayout(grp1)
    lay1.setContentsMargins(16, 12, 16, 12)
    lay1.setSpacing(8)

    self.btn_pick = QtWidgets.QPushButton("Pick from Scene")
    self.lbl_target = QtWidgets.QLabel("Target: (None)")
    row = QtWidgets.QHBoxLayout()
    row.addWidget(self.btn_pick)
    row.addWidget(self.lbl_target, stretch=1)
    lay1.addLayout(row)

    root.addWidget(grp1)
    root.addSpacing(8)

    # --- Card 2 ---
    grp2 = QtWidgets.QGroupBox("2. Column Mapping")
    lay2 = QtWidgets.QVBoxLayout(grp2)
    lay2.setContentsMargins(16, 12, 16, 12)
    lay2.setSpacing(8)

    lay2.addWidget(QtWidgets.QLabel("Drive property with column:"))
    self.combo_col = QtWidgets.QComboBox()
    lay2.addWidget(self.combo_col)

    root.addWidget(grp2)
    root.addStretch()

    # Signals
    self.btn_pick.clicked.connect(self._pick_target)
    self.combo_col.currentTextChanged.connect(lambda t: setattr(self, "my_column", t))
```

---

## What NOT to Do

- **Do not use `setStyleSheet()` anywhere except `_set_status`.** Not for colours, fonts,
  borders, backgrounds, padding, or border-radius. These override the host application's
  widget rendering in both native PySide6 and inside 3ds Max's embedded Qt.
- **Do not import `requests`, `httpx`, or any third-party HTTP library.** The project
  uses `urllib` only.
- **Do not import from `legacy/`** or any path outside the `Operators/` folder and the
  standard library.
- **Do not store direct `pymxs` node references** as instance variables. Use handles.
- **Do not call `self.combo_col.setCurrentIndex()` inside `deserialize()`** for column
  combos — the items are not populated yet at that point.
- **Do not raise exceptions from `execute()`** — return early with `_set_status` instead.
- **Do not use PyQt or any Qt binding other than PySide6.**

# PLAN: Batch Renderer UX Improvements

## 1. Remove "Assign JSON" Toolbar Button

**Problem:** `btn_assign_json` is a power-user-only action that clutters the main toolbar. The
right-click context menu on the queue tree already has "Assign Variation JSON..." (line 961 of
`batchrenderer_UI.py`) which calls the same `_assign_var_json()` handler.

**Fix:** Remove the button definition and its `file_bar` entry. Keep the right-click menu entry
and `_assign_var_json()` method unchanged.

Lines to remove in `batchrenderer_UI.py`:

```python
# Line 104 — remove:
self.btn_assign_json = _ctrl(QtWidgets.QPushButton("📄 Assign JSON"))

# Line 114 — remove:
file_bar.addWidget(self.btn_assign_json)

# Line 327 — remove:
self.btn_assign_json.clicked.connect(self._assign_var_json)
```

No other changes needed. The `_assign_var_json` method and right-click wiring are untouched.

---

## 2. Render/Submit Confirmation Dialog

**Problem:** Clicking "Render Current Scene", "Start Batch Render", or "Submit to Server"
immediately starts the operation. A mis-configured output folder or wrong resolution can waste
hours. Users need a fast sanity-check before the job fires, but cannot be shown an overwhelming
settings dump or they'll stop reading it.

**Fix:** Add a `_confirm_render` helper that shows a compact confirmation dialog. Each of the
three button handlers calls it before proceeding. If the user cancels, the handler returns early.

### Dialog content

| Line | Content |
|------|---------|
| Header | Action-specific sentence (see below) |
| — | `Variation: **Enabled**` / `Variation: **Disabled**` |
| — | `Resolution: **5000 px**` |
| — | `Format: **jpg** (8-bit, alpha DISABLED)` |
| Large | `OUTPUT FOLDER:` label |
| Large | the full output folder path |

Header sentences:
- Render current scene → `"This will render the current scene file."`
- Batch render N files → `"This will render 3 file(s) in batch mode."`
- Submit N jobs → `"This will submit 3 job(s) to the server."`

### Implementation

Add this method to `BatchRendererUI`:

```python
def _confirm_render(self, action_label: str, file_count: int) -> bool:
    """
    Show a compact confirmation dialog before starting a render operation.
    Returns True if the user confirmed, False if cancelled.
    """
    fmt        = self.cmb_ext.currentText()
    depth      = self.cmb_depth.currentText()
    alpha      = "ENABLED" if self.chk_alpha.isChecked() else "DISABLED"
    resolution = self.spn_res.value()
    variation  = "Enabled" if self.chk_use_variations.isChecked() else "Disabled"
    folder     = self.le_path.text().strip() or "(not set)"

    if file_count == 1:
        header = f"This will render the current scene file."
    elif action_label == "submit":
        header = f"This will submit {file_count} job(s) to the server."
    else:
        header = f"This will render {file_count} file(s) in batch mode."

    dlg = QtWidgets.QDialog(self)
    dlg.setWindowTitle("Confirm Render")
    dlg.setMinimumWidth(420)
    layout = QtWidgets.QVBoxLayout(dlg)
    layout.setSpacing(12)
    layout.setContentsMargins(20, 16, 20, 16)

    layout.addWidget(QtWidgets.QLabel(header))

    sep = QtWidgets.QFrame()
    sep.setFrameShape(QtWidgets.QFrame.HLine)
    layout.addWidget(sep)

    form = QtWidgets.QFormLayout()
    form.setSpacing(6)
    form.addRow("Variation:",   QtWidgets.QLabel(variation))
    form.addRow("Resolution:",  QtWidgets.QLabel(f"{resolution} px"))
    form.addRow("Format:",      QtWidgets.QLabel(f"{fmt}  ({depth}, alpha {alpha})"))
    layout.addLayout(form)

    sep2 = QtWidgets.QFrame()
    sep2.setFrameShape(QtWidgets.QFrame.HLine)
    layout.addWidget(sep2)

    lbl_folder_title = QtWidgets.QLabel("OUTPUT FOLDER:")
    font = lbl_folder_title.font()
    font.setPointSize(font.pointSize() + 3)
    font.setBold(True)
    lbl_folder_title.setFont(font)
    layout.addWidget(lbl_folder_title)

    lbl_folder = QtWidgets.QLabel(folder)
    lbl_folder.setWordWrap(True)
    font2 = lbl_folder.font()
    font2.setPointSize(font2.pointSize() + 2)
    lbl_folder.setFont(font2)
    layout.addWidget(lbl_folder)

    btns = QtWidgets.QDialogButtonBox(
        QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
    btns.accepted.connect(dlg.accept)
    btns.rejected.connect(dlg.reject)
    layout.addWidget(btns)

    return dlg.exec() == QtWidgets.QDialog.Accepted
```

### Wiring into each handler

**`render_current_scene` (line 1153)** — insert before the final `self._run_job_request` call:

```python
def render_current_scene(self):
    ...
    if not self._confirm_render("current", 1):
        return
    self._run_job_request(request)
```

**`run_batch` (line 1170)** — insert before `self._run_scene_jobs`:

```python
def run_batch(self):
    ...
    if not self._confirm_render("batch", len(self.file_entries)):
        return
    self._run_scene_jobs(scene_jobs)
```

**`submit_to_server` (line 1204)** — insert before the submission loop, after server health
check passes:

```python
def submit_to_server(self):
    entries = self._get_submit_entries()
    ...
    # after health check:
    if not self._confirm_render("submit", len(entries)):
        return
    # existing submission loop continues
    total_jobs = 0
    for entry in entries:
        ...
```

### Notes

- No stylesheet is used — font size is set via `QFont.setPointSize` which is safe inside 3ds Max's
  embedded Qt.
- The dialog is parented to `self` so it centers on the batch renderer window.
- Alpha checkbox visibility is format-dependent (hidden for jpg). When hidden, `self.chk_alpha`
  still returns a valid `isChecked()` value, so no guard is needed.
- The `depth` label reads `self.cmb_depth.currentText()` which reflects the active format's
  populated items (e.g. `"8-bit (Fixed)"` for jpg, `"16-bit Half"` for exr).

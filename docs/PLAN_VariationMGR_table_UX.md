# PLAN: VariationMGR Table UX Improvements

## 1. Faster Submenu Popup

**Problem:** `btn_edit_csv` (line 220) and `btn_save_max` (line 231) in `VariationMGR.py` use
`QToolButton.DelayedPopup`. Qt's built-in delay is ~600 ms and has no public setter.

**Fix:** Switch both buttons to `MenuButtonPopup` mode.

```python
# VariationMGR.py lines 220, 231 — change both occurrences:
self.btn_edit_csv.setPopupMode(QToolButton.MenuButtonPopup)
self.btn_save_max.setPopupMode(QToolButton.MenuButtonPopup)
```

`MenuButtonPopup` renders a split button: the left part triggers the default action immediately,
the right arrow immediately opens the menu with zero delay. This is better UX than a shorter
timer — the user always gets what they clicked with no wait.

---

## 2. Direct Cell Copy-Paste (No Edit Mode Required)

**Problem:** The table (`QTableWidget`, `VariationMGR.py` line 247) uses Qt's default edit
triggers (double-click / F2). Users must enter edit mode, select all, copy, navigate to another
cell, enter edit mode, and paste. There is no keyboard shortcut that reads/writes a cell without
entering edit mode.

**Fix:** Install an event filter on `self.table` that intercepts Ctrl+C and Ctrl+V at the table
level, operating on the selected cell(s) directly — no edit mode required.

### Where to add it

In `VariationMGR.py`, after the table is created (after line 260), add:

```python
self.table.installEventFilter(self)
```

Then add/extend `eventFilter` on the dialog class:

```python
def eventFilter(self, obj, event):
    if obj is self.table and event.type() == QtCore.QEvent.KeyPress:
        if event.matches(QtGui.QKeySequence.Copy):
            self._table_copy()
            return True
        if event.matches(QtGui.QKeySequence.Paste):
            self._table_paste()
            return True
    return super().eventFilter(obj, event)
```

### Helper methods

```python
def _table_copy(self):
    item = self.table.currentItem()
    if item:
        QtWidgets.QApplication.clipboard().setText(item.text())

def _table_paste(self):
    text = QtWidgets.QApplication.clipboard().text().strip()
    if not text:
        return
    self.table.blockSignals(True)
    for sel_item in self.table.selectedItems():
        sel_item.setText(text)
    self.table.blockSignals(False)
    # Fire a single _on_cell_changed for preview update
    if self.table.currentItem():
        self._on_cell_changed(self.table.currentItem())
```

### Notes

- `blockSignals` wraps the multi-cell paste so `_on_cell_changed` doesn't fire once per cell.
- A single manual call at the end keeps the naming preview in sync.
- No subclassing required — event filter on the existing widget is sufficient.
- Multi-cell paste: all selected cells receive the same clipboard value (useful for setting the
  same material/variation name across a block of rows).

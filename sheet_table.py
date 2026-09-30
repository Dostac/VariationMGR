"""Spreadsheet-style table for the Variation Manager.

``SheetTable`` is a QTableWidget that behaves like Excel for the things people
reach for without thinking:

- Two states per cell: *selected* (highlighted, current cell outlined) and
  *editing* (double-click, F2, or just start typing, which replaces the
  content). Copy/paste/delete act on the selection while not editing; while
  editing, the cell's text editor handles them itself.
- Ctrl+C copies the selection as tab-separated text (Excel/Sheets compatible).
- Ctrl+V pastes, anchored at the top-left cell of the selection:
  * one value fills every selected cell;
  * a block larger than one cell pastes down/right from the anchor, adding
    rows when needed (columns are never added: they need headers);
  * a selection that is an exact multiple of the block is tiled, like Excel;
  * multi-line text (a list) becomes one cell per line.
- Ctrl+X cuts, Delete/Backspace clears the selected cells.
- Ctrl+Z / Ctrl+Y (or Ctrl+Shift+Z) undo/redo edits, pastes and clears.
- Enter moves down (Shift+Enter up), also after finishing an edit.
- Escape is swallowed so it doesn't close the surrounding dialog.

All coordinates follow the *visual* column order, so dragging a column header
changes what copy and paste see, exactly like it looks on screen.

3ds Max registers application shortcuts (Ctrl+V is Clone, Delete deletes
objects). The table accepts ``ShortcutOverride`` for the keys it handles so
Qt delivers them to the table instead of firing Max's actions.
"""

import csv
import io

from PySide6 import QtCore, QtGui, QtWidgets


def sanitize_cell(text):
    """Cell text as the Variation Manager stores it: one line, no control chars."""
    text = str(text if text is not None else "")
    text = text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ").replace("\t", " ")
    return "".join(c for c in text if ord(c) >= 32)


def parse_clipboard(text):
    """Clipboard text -> list of rows (lists of cells).

    Tab-separated, one row per line. Excel wraps cells that contain line
    breaks or quotes in double quotes; that form is decoded with the csv
    module. Plain text (a list typed elsewhere) is split as-is, so a stray
    quote inside a value (12" pipe) is kept literally.
    """
    if text is None:
        return []
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if text.endswith("\n"):
        text = text[:-1]
    if text == "":
        return [[""]]
    rows = None
    if '"' in text:
        try:
            rows = list(csv.reader(io.StringIO(text), delimiter="\t", strict=True))
        except csv.Error:
            rows = None
    if rows is None:
        rows = [line.split("\t") for line in text.split("\n")]
    rows = [r if r else [""] for r in rows]
    return [[sanitize_cell(c) for c in r] for r in rows]


class _CurrentCellDelegate(QtWidgets.QStyledItemDelegate):
    """Draws an outline around the current cell, so "selected" is visible
    as its own state next to "editing" (like Excel's active-cell border)."""

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        view = self.parent()
        if view is None or index != view.currentIndex():
            return
        color = option.palette.color(QtGui.QPalette.Highlight).lighter(150)
        painter.save()
        pen = QtGui.QPen(color, 2)
        pen.setJoinStyle(QtCore.Qt.MiterJoin)
        painter.setPen(pen)
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawRect(QtCore.QRectF(option.rect).adjusted(1, 1, -1, -1))
        painter.restore()


class SheetTable(QtWidgets.QTableWidget):
    # Emitted once after a bulk change (paste, cut, clear, undo, redo). Those
    # write with signals blocked, so itemChanged does not fire per cell.
    cellsEdited = QtCore.Signal()

    _UNDO_LIMIT = 100
    _SHORTCUTS = (
        QtGui.QKeySequence.Copy, QtGui.QKeySequence.Cut, QtGui.QKeySequence.Paste,
        QtGui.QKeySequence.Undo, QtGui.QKeySequence.Redo, QtGui.QKeySequence.SelectAll,
    )

    def __init__(self, rows=0, columns=0, parent=None):
        super().__init__(rows, columns, parent)
        self.setItemDelegate(_CurrentCellDelegate(self))
        self.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectItems)
        self.setEditTriggers(
            QtWidgets.QAbstractItemView.DoubleClicked
            | QtWidgets.QAbstractItemView.EditKeyPressed
            | QtWidgets.QAbstractItemView.AnyKeyPressed
        )
        self._undo = []
        self._redo = []
        self._own_structure_change = 0
        self._edit_old = None      # (row, col, text) of the cell being edited
        m = self.model()
        for sig in (m.rowsInserted, m.rowsRemoved, m.columnsInserted,
                    m.columnsRemoved, m.modelReset):
            sig.connect(self._on_structure_changed)

    # ── Coordinates ──────────────────────────────────────────────────────────

    def _logical(self, visual_col):
        return self.horizontalHeader().logicalIndex(visual_col)

    def _visual(self, logical_col):
        return self.horizontalHeader().visualIndex(logical_col)

    def _text(self, row, col):
        it = self.item(row, col)
        return it.text() if it is not None else ""

    def selected_cells(self):
        """Selected cells as (row, visual_col); the current cell if nothing is selected."""
        cells = {(i.row(), self._visual(i.column())) for i in self.selectedIndexes()}
        if not cells:
            cur = self.currentIndex()
            if cur.isValid():
                cells = {(cur.row(), self._visual(cur.column()))}
        return cells

    # ── Undo / redo ──────────────────────────────────────────────────────────

    def _on_structure_changed(self, *args):
        # Rows/columns added or removed elsewhere (row menu, import, load):
        # recorded cell coordinates no longer line up, so drop the history.
        if not self._own_structure_change:
            self._undo.clear()
            self._redo.clear()

    def _push(self, op):
        self._undo.append(op)
        if len(self._undo) > self._UNDO_LIMIT:
            self._undo.pop(0)
        self._redo.clear()

    def _write(self, changes, use_new):
        """Write [(row, col, old, new), ...] with signals blocked."""
        was = self.blockSignals(True)
        try:
            for r, c, old, new in changes:
                value = new if use_new else old
                it = self.item(r, c)
                if it is None:
                    if value == "":
                        continue
                    self.setItem(r, c, QtWidgets.QTableWidgetItem(value))
                else:
                    it.setText(value)
        finally:
            self.blockSignals(was)

    def _add_rows(self, n):
        self._own_structure_change += 1
        try:
            for _ in range(n):
                self.insertRow(self.rowCount())
        finally:
            self._own_structure_change -= 1

    def _remove_last_rows(self, n):
        self._own_structure_change += 1
        try:
            for _ in range(n):
                self.removeRow(self.rowCount() - 1)
        finally:
            self._own_structure_change -= 1

    def undo(self):
        if not self._undo:
            return
        op = self._undo.pop()
        self._write(op["cells"], use_new=False)
        if op.get("added_rows"):
            self._remove_last_rows(op["added_rows"])
        self._redo.append(op)
        self._select_cells(op.get("select", []))
        self.cellsEdited.emit()

    def redo(self):
        if not self._redo:
            return
        op = self._redo.pop()
        if op.get("added_rows"):
            self._add_rows(op["added_rows"])
        self._write(op["cells"], use_new=True)
        self._undo.append(op)
        self._select_cells(op.get("select", []))
        self.cellsEdited.emit()

    def _apply(self, changes, added_rows=0, select=None):
        """Apply a bulk change as one undoable step."""
        changes = [(r, c, old, new) for r, c, old, new in changes if old != new]
        if not changes and not added_rows:
            if select:
                self._select_cells(select)
            return
        if added_rows:
            self._add_rows(added_rows)
        self._write(changes, use_new=True)
        self._push({"cells": changes, "added_rows": added_rows, "select": list(select or [])})
        if select:
            self._select_cells(select)
        self.cellsEdited.emit()

    # Record single-cell edits made through the editor.
    def edit(self, index, trigger=None, event=None):
        if trigger is None:
            return super().edit(index)
        opened = super().edit(index, trigger, event)
        if opened and index.isValid():
            self._edit_old = (index.row(), index.column(), self._text(index.row(), index.column()))
        return opened

    def commitData(self, editor):
        before = self._edit_old
        super().commitData(editor)
        if before is None:
            return
        r, c, old = before
        if r < self.rowCount() and c < self.columnCount():
            new = self._text(r, c)
            if new != old:
                self._push({"cells": [(r, c, old, new)], "added_rows": 0,
                            "select": [(r, self._visual(c))]})
                self._edit_old = (r, c, new)

    def closeEditor(self, editor, hint):
        super().closeEditor(editor, hint)
        self._edit_old = None
        if hint == QtWidgets.QAbstractItemDelegate.SubmitModelCache:   # Enter
            up = bool(QtWidgets.QApplication.keyboardModifiers() & QtCore.Qt.ShiftModifier)
            self._move_vertical(-1 if up else 1)

    # ── Clipboard ────────────────────────────────────────────────────────────

    def copy_selection(self):
        cells = self.selected_cells()
        if not cells:
            return
        rows = [r for r, _ in cells]
        cols = [c for _, c in cells]
        top, bottom, left, right = min(rows), max(rows), min(cols), max(cols)
        lines = []
        for r in range(top, bottom + 1):
            vals = []
            for v in range(left, right + 1):
                vals.append(self._text(r, self._logical(v)) if (r, v) in cells else "")
            lines.append("\t".join(vals))
        QtWidgets.QApplication.clipboard().setText("\n".join(lines))

    def clear_selection_cells(self):
        cells = sorted(self.selected_cells())
        changes = [(r, self._logical(v), self._text(r, self._logical(v)), "") for r, v in cells]
        self._apply(changes, select=cells)

    def cut_selection(self):
        self.copy_selection()
        self.clear_selection_cells()

    def paste_text(self, text):
        """Paste clipboard-style text at the selection (see module docstring).
        Returns a short note when something didn't fit, else ""."""
        if self.columnCount() == 0:
            return "Add a column first."
        block = parse_clipboard(text)
        if not block:
            return ""
        height = len(block)
        width = max(len(r) for r in block)
        block = [r + [""] * (width - len(r)) for r in block]

        cells = self.selected_cells() or {(0, 0)}
        rows = [r for r, _ in cells]
        cols = [c for _, c in cells]
        top, left = min(rows), min(cols)
        sel_h = max(rows) - top + 1
        sel_w = max(cols) - left + 1
        full_rect = len(cells) == sel_h * sel_w

        targets = {}   # (row, visual_col) -> value
        if height == 1 and width == 1:
            for cell in cells:
                targets[cell] = block[0][0]
        elif full_rect and (sel_h > height or sel_w > width) \
                and sel_h % height == 0 and sel_w % width == 0:
            for dr in range(sel_h):
                for dc in range(sel_w):
                    targets[(top + dr, left + dc)] = block[dr % height][dc % width]
        else:
            for dr in range(height):
                for dc in range(width):
                    targets[(top + dr, left + dc)] = block[dr][dc]

        ncols = self.columnCount()
        dropped = {v for (_, v) in targets if v >= ncols}
        targets = {k: val for k, val in targets.items() if k[1] < ncols}
        needed_rows = max(r for r, _ in targets) + 1 if targets else 0
        added = max(0, needed_rows - self.rowCount())
        changes = []
        for (r, v), val in sorted(targets.items()):
            c = self._logical(v)
            old = self._text(r, c) if r < self.rowCount() else ""
            changes.append((r, c, old, val))
        self._apply(changes, added_rows=added, select=sorted(targets))
        if dropped:
            n = len(dropped)
            return f"{n} column{'s' if n > 1 else ''} didn't fit and {'were' if n > 1 else 'was'} skipped (columns need a header first)."
        return ""

    def paste_clipboard(self):
        note = self.paste_text(QtWidgets.QApplication.clipboard().text())
        if note:
            rect = self.visualRect(self.currentIndex())
            pos = self.viewport().mapToGlobal(rect.bottomLeft() if rect.isValid() else QtCore.QPoint(0, 0))
            QtWidgets.QToolTip.showText(pos, note, self)

    # ── Selection helpers ────────────────────────────────────────────────────

    def _select_cells(self, cells):
        """Select [(row, visual_col), ...] and make the top-left one current."""
        cells = [(r, v) for r, v in cells if r < self.rowCount() and v < self.columnCount()]
        if not cells:
            return
        sm = self.selectionModel()
        selection = QtCore.QItemSelection()
        for r, v in cells:
            idx = self.model().index(r, self._logical(v))
            selection.select(idx, idx)
        top = min(cells)
        top_idx = self.model().index(top[0], self._logical(top[1]))
        sm.setCurrentIndex(top_idx, QtCore.QItemSelectionModel.NoUpdate)
        sm.select(selection, QtCore.QItemSelectionModel.ClearAndSelect)
        self.scrollTo(top_idx)

    def _move_vertical(self, step):
        cur = self.currentIndex()
        if not cur.isValid():
            return
        row = min(max(cur.row() + step, 0), self.rowCount() - 1)
        self.setCurrentCell(row, cur.column())

    # ── Keys ─────────────────────────────────────────────────────────────────

    def _handles(self, event):
        if any(event.matches(k) for k in self._SHORTCUTS):
            return True
        mods = event.modifiers() & (QtCore.Qt.ControlModifier | QtCore.Qt.AltModifier | QtCore.Qt.MetaModifier)
        # Plain keys (letters that start editing, Delete, arrows, Enter, F2…)
        # belong to the table while it has focus, not to Max's hotkeys.
        return not mods

    def event(self, event):
        if event.type() == QtCore.QEvent.ShortcutOverride \
                and self.state() != QtWidgets.QAbstractItemView.EditingState \
                and self._handles(event):
            event.accept()
            return True
        return super().event(event)

    def keyPressEvent(self, event):
        if self.state() == QtWidgets.QAbstractItemView.EditingState:
            return super().keyPressEvent(event)
        if event.matches(QtGui.QKeySequence.Copy):
            self.copy_selection()
        elif event.matches(QtGui.QKeySequence.Cut):
            self.cut_selection()
        elif event.matches(QtGui.QKeySequence.Paste):
            self.paste_clipboard()
        elif event.matches(QtGui.QKeySequence.Undo):
            self.undo()
        elif event.matches(QtGui.QKeySequence.Redo):
            self.redo()
        elif event.key() in (QtCore.Qt.Key_Delete, QtCore.Qt.Key_Backspace) and not event.modifiers() & QtCore.Qt.ControlModifier:
            self.clear_selection_cells()
        elif event.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
            self._move_vertical(-1 if event.modifiers() & QtCore.Qt.ShiftModifier else 1)
        elif event.key() == QtCore.Qt.Key_Escape:
            pass   # don't let Escape close the dialog
        else:
            return super().keyPressEvent(event)
        event.accept()

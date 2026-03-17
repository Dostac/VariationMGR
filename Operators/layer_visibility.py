from PySide6 import QtWidgets, QtCore


class LayerVisibilityOperator(QtCore.QObject):
    """
    Static Field: Parent Layer (by name).
    Property (Driven): Child layer name to make visible (from CSV column).

    On execute: hides all direct children of the parent layer,
    then shows the one whose name matches the column value.
    If no match, all children are left hidden.
    """
    status_changed = QtCore.Signal(str, bool)

    def __init__(self, context=None):
        super().__init__()
        self.rt = context.get("rt") if context else None

        self.parent_layer_name = ""
        self.mapped_column = ""

        self.main_widget = QtWidgets.QWidget()
        self._setup_ui()

    def _setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self.main_widget)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(8)

        self.lbl_status = QtWidgets.QLabel("")
        self.lbl_status.setWordWrap(True)
        layout.addWidget(self.lbl_status)

        # 1. Parent Layer
        layout.addWidget(QtWidgets.QLabel("1. Parent Layer:"))
        btn_row = QtWidgets.QHBoxLayout()
        self.btn_pick = QtWidgets.QPushButton("Pick from Scene")
        self.lbl_parent = QtWidgets.QLabel("Parent: (None)")
        self.lbl_parent.setStyleSheet("color: #aaa;")
        btn_row.addWidget(self.btn_pick)
        btn_row.addWidget(self.lbl_parent, stretch=1)
        layout.addLayout(btn_row)

        # 2. Column mapping
        layout.addWidget(QtWidgets.QLabel("2. Active Layer Column:"))
        self.combo_col = QtWidgets.QComboBox()
        layout.addWidget(self.combo_col)

        layout.addStretch()

        self.btn_pick.clicked.connect(self._pick_parent_layer)
        self.combo_col.currentTextChanged.connect(lambda t: setattr(self, 'mapped_column', t))

    # --- Logic ---

    def _pick_parent_layer(self):
        if not self.rt:
            return
        names = []
        for i in range(self.rt.layerManager.count):
            layer = self.rt.layerManager.getLayer(i)
            if layer is not None:
                names.append(layer.name)
        if not names:
            self._set_status("No layers found in scene.", True)
            return
        item, ok = QtWidgets.QInputDialog.getItem(
            None, "Select Parent Layer", "Choose a layer:", sorted(names), 0, False
        )
        if ok and item:
            self.parent_layer_name = item
            self.lbl_parent.setText(f"Parent: {item}")
            self.lbl_parent.setStyleSheet("")

    def _get_direct_children(self, parent_name):
        """Returns all layers whose immediate parent matches parent_name."""
        children = []
        for i in range(self.rt.layerManager.count):
            layer = self.rt.layerManager.getLayer(i)
            if not layer:
                continue
            try:
                p = layer.getParent()
                if p and p.name == parent_name:
                    children.append(layer)
            except Exception:
                continue
        return children

    def get_ui(self):
        return self.main_widget

    def on_columns_changed(self, columns):
        self.combo_col.blockSignals(True)
        self.combo_col.clear()
        self.combo_col.addItem("-- Select Column --")
        self.combo_col.addItems(columns)
        idx = self.combo_col.findText(self.mapped_column)
        self.combo_col.setCurrentIndex(idx if idx != -1 else 0)
        self.combo_col.blockSignals(False)
        self.mapped_column = self.combo_col.currentText()

    def execute(self, row_data):
        if not self.rt:
            self._set_status("3ds Max runtime not available.", True)
            return
        if not self.parent_layer_name:
            self._set_status("No parent layer selected.", True)
            return
        if not self.mapped_column or self.mapped_column == "-- Select Column --":
            self._set_status("No active layer column selected.", True)
            return
        if self.mapped_column not in row_data:
            self._set_status(f"Column '{self.mapped_column}' missing.", True)
            return

        parent_layer = self.rt.layerManager.getLayerFromName(self.parent_layer_name)
        if not parent_layer:
            self._set_status(f"Parent '{self.parent_layer_name}' not found.", True)
            return

        # Multiple layers can be activated using & as separator: "child1&child2"
        raw = row_data.get(self.mapped_column, "").strip()
        targets = {t.strip() for t in raw.split("&") if t.strip()}

        children = self._get_direct_children(self.parent_layer_name)
        if not children:
            self._set_status(f"No children under '{self.parent_layer_name}'.", True)
            return

        matched = set()
        for child in children:
            if child.name in targets:
                child.on = True
                matched.add(child.name)
            else:
                child.on = False

        missing = targets - matched
        if missing:
            self._set_status(f"Not found: {', '.join(sorted(missing))} — skipped.", True)
        elif matched:
            self._set_status(f"Active: {', '.join(sorted(matched))}")
        else:
            self._set_status("No target specified — all children hidden.", True)

    def _set_status(self, msg, error=False):
        self.lbl_status.setText(msg)
        self.lbl_status.setStyleSheet("color: #ff6666;" if error else "color: #66ff66;")
        self.status_changed.emit(msg, error)

    # --- Persistence ---

    def serialize(self):
        return {
            "parent_layer_name": self.parent_layer_name,
            "mapped_column": self.mapped_column,
        }

    def deserialize(self, data):
        self.parent_layer_name = data.get("parent_layer_name", "")
        self.mapped_column = data.get("mapped_column", "")
        if self.parent_layer_name:
            self.lbl_parent.setText(f"Parent: {self.parent_layer_name}")
            self.lbl_parent.setStyleSheet("")
        idx = self.combo_col.findText(self.mapped_column)
        if idx != -1:
            self.combo_col.setCurrentIndex(idx)

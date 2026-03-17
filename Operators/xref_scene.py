import os

from PySide6 import QtWidgets, QtCore


def _find_max_file(folder_root, filename_stem, search_subfolders):
    """Locate a .max file by stem name in *folder_root*.

    Returns the full path on success, ``None`` otherwise.
    """
    stem = filename_stem.strip()
    if stem.lower().endswith(".max"):
        stem = stem[:-4]
    if not stem:
        return None

    target = f"{stem}.max"

    # Direct check in root folder (case-insensitive).
    try:
        for name in os.listdir(folder_root):
            if name.lower() == target.lower() and os.path.isfile(os.path.join(folder_root, name)):
                return os.path.join(folder_root, name)
    except OSError:
        return None

    if search_subfolders:
        for dirpath, _dirs, files in os.walk(folder_root):
            for name in files:
                if name.lower() == target.lower():
                    return os.path.join(dirpath, name)

    return None


class XRefSceneOperator(QtCore.QObject):
    """Merge a .max scene file as an XRef Scene, optionally positioned at an origin object.

    Static Fields: root folder, search-subfolders flag, origin object.
    Properties (Driven): filename column from CSV.
    """

    status_changed = QtCore.Signal(str, bool)

    def __init__(self, context=None):
        super().__init__()
        self.rt = context.get("rt") if context else None
        self.instance_id = context.get("instance_id", "") if context else ""

        # --- Persistent state (static fields) ---
        self.folder_root = ""
        self.search_subfolders = False
        self.origin_node_name = ""
        self.origin_node_handle = None

        # --- Column mappings (driven properties) ---
        self.filename_column = ""

        self.main_widget = QtWidgets.QWidget()
        self._setup_ui()

    # -------------------------------------------------------------------
    # UI
    # -------------------------------------------------------------------

    def _setup_ui(self):
        root = QtWidgets.QVBoxLayout(self.main_widget)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(0)

        # --- Status ---
        self.lbl_status = QtWidgets.QLabel("")
        self.lbl_status.setWordWrap(True)
        root.addWidget(self.lbl_status)
        root.addSpacing(4)

        # --- Card 1: Scene Folder ---
        grp1 = QtWidgets.QGroupBox("1. Scene Folder")
        lay1 = QtWidgets.QVBoxLayout(grp1)
        lay1.setContentsMargins(16, 12, 16, 12)
        lay1.setSpacing(8)

        lay1.addWidget(QtWidgets.QLabel("Root Folder:"))
        row_folder = QtWidgets.QHBoxLayout()
        self.edit_folder = QtWidgets.QLineEdit()
        self.edit_folder.setPlaceholderText("D:/Scenes/XRefs")
        btn_browse = QtWidgets.QPushButton("...")
        btn_browse.setFixedWidth(28)
        row_folder.addWidget(self.edit_folder, stretch=1)
        row_folder.addWidget(btn_browse)
        lay1.addLayout(row_folder)

        self.chk_subfolders = QtWidgets.QCheckBox("Search Subfolders")
        lay1.addWidget(self.chk_subfolders)

        root.addWidget(grp1)
        root.addSpacing(8)

        # --- Card 2: Scene Origin (Optional) ---
        grp2 = QtWidgets.QGroupBox("2. Scene Origin (Optional)")
        lay2 = QtWidgets.QVBoxLayout(grp2)
        lay2.setContentsMargins(16, 12, 16, 12)
        lay2.setSpacing(8)

        row_pick = QtWidgets.QHBoxLayout()
        self.btn_pick = QtWidgets.QPushButton("Pick from Scene")
        self.lbl_origin = QtWidgets.QLabel("Origin: (None)")
        btn_clear = QtWidgets.QPushButton("X")
        btn_clear.setFixedWidth(28)
        row_pick.addWidget(self.btn_pick)
        row_pick.addWidget(self.lbl_origin, stretch=1)
        row_pick.addWidget(btn_clear)
        lay2.addLayout(row_pick)

        root.addWidget(grp2)
        root.addSpacing(8)

        # --- Card 3: Column Mapping ---
        grp3 = QtWidgets.QGroupBox("3. Column Mapping")
        lay3 = QtWidgets.QVBoxLayout(grp3)
        lay3.setContentsMargins(16, 12, 16, 12)
        lay3.setSpacing(8)

        lay3.addWidget(QtWidgets.QLabel("Filename column:"))
        self.combo_filename_col = QtWidgets.QComboBox()
        lay3.addWidget(self.combo_filename_col)

        root.addWidget(grp3)
        root.addStretch()

        # --- Signals ---
        btn_browse.clicked.connect(self._browse_folder)
        self.edit_folder.textChanged.connect(self._on_folder_changed)
        self.chk_subfolders.toggled.connect(lambda v: setattr(self, "search_subfolders", v))
        self.btn_pick.clicked.connect(self._pick_origin)
        btn_clear.clicked.connect(self._clear_origin)
        self.combo_filename_col.currentTextChanged.connect(
            lambda t: setattr(self, "filename_column", t)
        )

    # -------------------------------------------------------------------
    # Manager interface
    # -------------------------------------------------------------------

    def get_ui(self):
        return self.main_widget

    def on_columns_changed(self, columns):
        self.combo_filename_col.blockSignals(True)
        self.combo_filename_col.clear()
        self.combo_filename_col.addItem("-- Select Column --")
        self.combo_filename_col.addItems(columns)
        idx = self.combo_filename_col.findText(self.filename_column)
        self.combo_filename_col.setCurrentIndex(idx if idx != -1 else 0)
        self.combo_filename_col.blockSignals(False)
        self.filename_column = self.combo_filename_col.currentText()

    def execute(self, row_data):
        # Guard: runtime
        if not self.rt:
            self._set_status("3ds Max runtime not available.", True)
            return

        # Guard: folder configured
        if not self.folder_root:
            self._set_status("No root folder set.", True)
            return
        if not os.path.isdir(self.folder_root):
            self._set_status(f"Folder not found: {self.folder_root}", True)
            return

        # Guard: column mapped
        if not self.filename_column or self.filename_column == "-- Select Column --":
            self._set_status("No filename column selected.", True)
            return
        if self.filename_column not in row_data:
            self._set_status(f"Column '{self.filename_column}' missing from row.", True)
            return

        filename_stem = row_data[self.filename_column].strip()
        if not filename_stem:
            self._set_status("Empty filename value in row.", True)
            return

        # Find the .max file
        filepath = _find_max_file(self.folder_root, filename_stem, self.search_subfolders)
        if not filepath:
            self._set_status(f"File '{filename_stem}.max' not found.", True)
            return

        # Cleanup previous XRef owned by this operator instance
        self._cleanup_previous()

        # Create dummy at world origin
        dummy_name = f"VB_XRef_{self.instance_id}"
        dummy = self.rt.Dummy()
        dummy.name = dummy_name
        dummy.boxSize = self.rt.Point3(0, 0, 0)

        # Add XRef Scene
        xref = self.rt.xrefs.addNewXRefFile(filepath)
        if not xref:
            self.rt.delete(dummy)
            self._set_status("Failed to add XRef scene.", True)
            return

        # Link XRef to dummy first (parenting is relative — captures
        # subsequent transforms, not the current absolute position)
        xref.parent = dummy

        # Position the dummy and optionally parent it to the origin object
        if self.origin_node_name:
            origin = self._resolve_origin()
            if origin:
                # Move dummy to the origin's world transform first so that
                # after parenting the local transform is identity (dummy sits
                # exactly at the origin's pivot and follows all its moves).
                dummy.transform = origin.transform
                dummy.parent = origin
            else:
                self._set_status(
                    f"XRef added but origin '{self.origin_node_name}' not found.", True
                )
                return

        # Freeze so the dummy cannot be accidentally moved in the viewport
        dummy.isFrozen = True

        self._set_status(f"XRef: {os.path.basename(filepath)}")

    # -------------------------------------------------------------------
    # Persistence
    # -------------------------------------------------------------------

    def serialize(self):
        return {
            "folder_root": self.folder_root,
            "search_subfolders": self.search_subfolders,
            "origin_node_name": self.origin_node_name,
            "origin_node_handle": self.origin_node_handle,
            "filename_column": self.filename_column,
        }

    def deserialize(self, data):
        self.folder_root = data.get("folder_root", "")
        self.search_subfolders = data.get("search_subfolders", False)
        self.origin_node_name = data.get("origin_node_name", "")
        self.origin_node_handle = data.get("origin_node_handle", None)
        self.filename_column = data.get("filename_column", "")

        # Restore non-column widgets
        self.edit_folder.setText(self.folder_root)
        self.chk_subfolders.setChecked(self.search_subfolders)
        if self.origin_node_name:
            self.lbl_origin.setText(f"Origin: {self.origin_node_name}")
        # Column combo restored later by on_columns_changed

    # -------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------

    def _set_status(self, msg, error=False):
        self.lbl_status.setText(msg)
        self.lbl_status.setStyleSheet("color: #ff6666;" if error else "color: #66ff66;")
        self.status_changed.emit(msg, error)
        if error and msg:
            print(f"XRefSceneOperator ERROR: {msg}")

    def _browse_folder(self):
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self.main_widget, "Select Scene Folder"
        )
        if folder:
            self.edit_folder.setText(os.path.normpath(folder))

    def _on_folder_changed(self, text):
        self.folder_root = os.path.normpath(text) if text.strip() else ""

    def _pick_origin(self):
        if not self.rt:
            self._set_status("3ds Max runtime not available.", True)
            return
        selection = self.rt.selection
        if len(selection) == 0:
            self._set_status("Select an object in 3ds Max first.", True)
            return
        obj = selection[0]
        self.origin_node_name = obj.name
        self.origin_node_handle = self.rt.GetHandleByAnim(obj)
        self.lbl_origin.setText(f"Origin: {obj.name}")
        self._set_status("")

    def _clear_origin(self):
        self.origin_node_name = ""
        self.origin_node_handle = None
        self.lbl_origin.setText("Origin: (None)")

    def _resolve_origin(self):
        """Resolve the origin node using name-first, handle-fallback."""
        node = None
        if self.origin_node_name:
            node = self.rt.getNodeByName(self.origin_node_name)
            if node:
                self.origin_node_handle = self.rt.GetHandleByAnim(node)
        if not node and self.origin_node_handle:
            node = self.rt.GetAnimByHandle(self.origin_node_handle)
        return node

    def _cleanup_previous(self):
        """Remove XRef Scenes parented to this operator's dummy, then delete the dummy."""
        dummy_name = f"VB_XRef_{self.instance_id}"
        dummy = self.rt.getNodeByName(dummy_name)
        if not dummy:
            return

        # Unfreeze before deletion so parenting and delete operations work cleanly
        dummy.isFrozen = False

        # Iterate XRef Scenes in reverse and delete any parented to our dummy
        count = self.rt.xrefs.getXRefFileCount()
        for i in range(count, 0, -1):
            xref = self.rt.xrefs.getXRefFile(i)
            if xref and xref.parent == dummy:
                self.rt.delete(xref)

        self.rt.delete(dummy)

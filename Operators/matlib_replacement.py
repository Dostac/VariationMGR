from PySide6 import QtWidgets, QtCore
import os

class MultiSubLibOperator(QtCore.QObject):
    """
    Static Fields: Mat Lib Path, Target Multi-Sub Material, Target Slot ID.
    Property (Driven): Material Name (from CSV).
    """
    status_changed = QtCore.Signal(str, bool)

    def __init__(self, context=None):
        super().__init__()
        self.rt = context.get("rt") if context else None
        
        # --- Persistent State (Static Fields) ---
        self.lib_path = ""
        self.target_mat_name = ""
        self.target_mat_handle = None
        self.slot_id = 0  # 0 = All, 1+ = Specific
        
        # --- Property (Driven by Parent/CSV) ---
        self.mapped_column = ""

        self.main_widget = QtWidgets.QWidget()
        self._setup_ui()

    def _setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self.main_widget)
        layout.setContentsMargins(5, 5, 5, 5)

        self.lbl_status = QtWidgets.QLabel("")
        self.lbl_status.setWordWrap(True)
        layout.addWidget(self.lbl_status)

        # 1. Lib Path
        layout.addWidget(QtWidgets.QLabel("1. Material Library (.mat):"))
        path_layout = QtWidgets.QHBoxLayout()
        self.edit_path = QtWidgets.QLineEdit()
        btn_browse = QtWidgets.QPushButton("...")
        btn_browse.setFixedWidth(30)
        path_layout.addWidget(self.edit_path)
        path_layout.addWidget(btn_browse)
        layout.addLayout(path_layout)

        # 2. Target Multi-Sub
        layout.addWidget(QtWidgets.QLabel("2. Target Multi-Sub Object:"))
        self.btn_select_mat = QtWidgets.QPushButton("Pick Multi-Sub from Scene")
        self.lbl_mat_info = QtWidgets.QLabel("Target: (None)")
        self.lbl_mat_info.setStyleSheet("color: #aaa;")
        layout.addWidget(self.btn_select_mat)
        layout.addWidget(self.lbl_mat_info)

        # 3. Slot Configuration
        slot_layout = QtWidgets.QHBoxLayout()
        slot_layout.addWidget(QtWidgets.QLabel("3. Slot ID (0 for All):"))
        self.spin_slot = QtWidgets.QSpinBox()
        self.spin_slot.setRange(0, 1000)
        slot_layout.addWidget(self.spin_slot)
        layout.addLayout(slot_layout)

        # 4. CSV Column Mapping
        layout.addWidget(QtWidgets.QLabel("4. Material Name Column:"))
        self.combo_col = QtWidgets.QComboBox()
        layout.addWidget(self.combo_col)

        layout.addStretch()

        # Connections
        btn_browse.clicked.connect(self._browse_lib)
        self.btn_select_mat.clicked.connect(self._pick_multi_sub)
        self.edit_path.textChanged.connect(lambda t: setattr(self, 'lib_path', t))
        self.spin_slot.valueChanged.connect(lambda v: setattr(self, 'slot_id', v))
        self.combo_col.currentTextChanged.connect(self._set_mapping)

    # --- Logic ---

    def _browse_lib(self):
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            None, "Select Material Library", "", "Mat Lib (*.mat)"
        )
        if file_path:
            self.edit_path.setText(file_path)

    def _pick_multi_sub(self):
        if not self.rt: return
        # Get all MultiMaterial instances in the scene
        mats = self.rt.getClassInstances(self.rt.MultiMaterial)
        if not mats:
            self._set_status("No Multi-Sub materials in scene.", True)
            return

        mat_dict = {f"{m.name}": m for m in mats}
        item, ok = QtWidgets.QInputDialog.getItem(
            None, "Select Multi-Sub", "Materials:", sorted(mat_dict.keys()), 0, False
        )
        if ok and item:
            target = mat_dict[item]
            self.target_mat_name = target.name
            self.target_mat_handle = self.rt.GetHandleByAnim(target)
            self.lbl_mat_info.setText(f"Target: {self.target_mat_name}")

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

    def execute(self, row_data):
        if not self.rt or not self.target_mat_name: return

        # 1. Resolve Column
        mat_lookup_name = row_data.get(self.mapped_column, "").strip()
        if not mat_lookup_name: return

        # 2. Access the Multi-Sub — look up by name first (handles are session-specific).
        multi_mat = None
        for m in self.rt.getClassInstances(self.rt.MultiMaterial):
            if m.name == self.target_mat_name:
                multi_mat = m
                self.target_mat_handle = self.rt.GetHandleByAnim(m)
                break
        if not multi_mat and self.target_mat_handle:
            multi_mat = self.rt.GetAnimByHandle(self.target_mat_handle)
        if not multi_mat:
            self._set_status("Target Multi-Sub missing!", True)
            return

        # 3. Load Library
        if not os.path.exists(self.lib_path):
            self._set_status("Library path invalid.", True)
            return
            
        self.rt.loadMaterialLibrary(self.lib_path)
        lib = self.rt.currentMaterialLibrary
        
        # 4. Find Material in Lib
        found_mat = None
        for m in lib:
            if m.name.lower() == mat_lookup_name.lower():
                found_mat = m
                break
        
        if not found_mat:
            self._set_status(f"'{mat_lookup_name}' not in library.", True)
            return

        # 5. Apply to Slots
        # In MaxScript, multi_mat.numsubs or multi_mat.materialList.count
        try:
            if self.slot_id == 0:
                # Apply to every existing slot
                for i in range(len(multi_mat.materialList)):
                    multi_mat.materialList[i] = found_mat
                self._set_status(f"Applied '{found_mat.name}' to all slots.")
            else:
                # Ensure the slot exists (resize if needed)
                if self.slot_id > len(multi_mat.materialList):
                    multi_mat.numsubs = self.slot_id
                
                # MaterialList is 0-indexed in pymxs but corresponds to ID 1
                multi_mat.materialList[self.slot_id - 1] = found_mat
                self._set_status(f"Applied to slot {self.slot_id}.")
        except Exception as e:
            self._set_status(f"Error: {str(e)}", True)

    def _set_mapping(self, text):
        self.mapped_column = text

    def _set_status(self, msg, error=False):
        self.lbl_status.setText(msg)
        self.lbl_status.setStyleSheet("color: #ff6666;" if error else "color: #66ff66;")
        self.status_changed.emit(msg, error)

    # --- Persistence ---
    def serialize(self):
        return {
            "lib_path": self.lib_path,
            "target_mat_handle": self.target_mat_handle,
            "target_mat_name": self.target_mat_name,
            "slot_id": self.slot_id,
            "mapped_column": self.mapped_column
        }

    def deserialize(self, data):
        self.lib_path = data.get("lib_path", "")
        self.target_mat_handle = data.get("target_mat_handle", None)
        self.target_mat_name = data.get("target_mat_name", "")
        self.slot_id = data.get("slot_id", 0)
        self.mapped_column = data.get("mapped_column", "")
        
        self.edit_path.setText(self.lib_path)
        self.spin_slot.setValue(self.slot_id)
        if self.target_mat_name:
            self.lbl_mat_info.setText(f"Target: {self.target_mat_name}")
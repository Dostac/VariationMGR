from PySide6 import QtWidgets, QtCore

class HexColorOperator(QtCore.QObject):
    """
    Drives a color map node directly from a CSV hex column.
    """
    status_changed = QtCore.Signal(str, bool)

    def __init__(self, context=None):
        super().__init__()
        self.rt = context.get("rt") if context else None
        self.target_map_name = ""   
        self.target_map_handle = None
        self.mapped_column = ""

        self.main_widget = QtWidgets.QWidget()
        self.lbl_target = QtWidgets.QLabel("Target Map: (None)")
        self.lbl_target.setStyleSheet("font-weight: bold; color: #ccc;")
        
        self.btn_select_map = QtWidgets.QPushButton("Select Map from Scene...")
        self.btn_clear = QtWidgets.QPushButton("X")
        self.btn_clear.setFixedWidth(30)
        
        self.combo_col = QtWidgets.QComboBox()
        self.lbl_status = QtWidgets.QLabel("")

        self._setup_ui()

    def _setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self.main_widget)
        layout.setContentsMargins(5,5,5,5)

        self.lbl_status.setWordWrap(True)
        layout.addWidget(self.lbl_status)

        # Section 1: Map Selection
        layout.addWidget(QtWidgets.QLabel("1. Target CoronaColor Map:"))
        
        sel_layout = QtWidgets.QHBoxLayout()
        sel_layout.addWidget(self.btn_select_map)
        sel_layout.addWidget(self.btn_clear)
        layout.addLayout(sel_layout)
        
        layout.addWidget(self.lbl_target)

        layout.addSpacing(10)

        # Section 2: CSV Mapping
        layout.addWidget(QtWidgets.QLabel("2. Drive Color with Column:"))
        layout.addWidget(self.combo_col)

        layout.addStretch()

        # Connections
        self.btn_select_map.clicked.connect(self._show_map_selector)
        self.btn_clear.clicked.connect(self._clear_target)
        self.combo_col.currentTextChanged.connect(self._set_mapping)

    # --- Manager Interface ---

    def get_ui(self):
        return self.main_widget

    def on_columns_changed(self, columns):
        """
        Called when the CSV columns change. 
        FIX: We use self.mapped_column (the internal truth) to restore selection,
        instead of reading the current UI text which might be empty during load.
        """
        target = self.mapped_column
        
        self.combo_col.blockSignals(True)
        self.combo_col.clear()
        self.combo_col.addItem("-- Select Column --")
        self.combo_col.addItems(columns)
        
        # Try to find the saved column in the new list
        idx = self.combo_col.findText(target)
        if idx != -1:
            self.combo_col.setCurrentIndex(idx)
        else:
            self.combo_col.setCurrentIndex(0)
        
        self.combo_col.blockSignals(False)
        
        # Ensure internal state matches result
        self.mapped_column = self.combo_col.currentText()

    def execute(self, row_data):
        if not self.rt:
            self._set_status("3ds Max runtime not available.", error=True)
            return
        
        # Validate Target — look up by name first (handles are session-specific).
        if not self.target_map_name:
            self._set_status("No map selected.", error=True)
            return
        target_map = None
        for m in list(self.rt.getClassInstances(self.rt.CoronaColor)) + list(self.rt.getClassInstances(self.rt.Color_Correction)):
            if m.name == self.target_map_name:
                target_map = m
                self.target_map_handle = self.rt.GetHandleByAnim(m)
                break
        if not target_map and self.target_map_handle:
            target_map = self.rt.GetAnimByHandle(self.target_map_handle)
        if not target_map:
            self._set_status("Map node not found (deleted?).", error=True)
            return

        # Validate Column
        col_key = self.mapped_column
        if not col_key or col_key == "-- Select Column --":
            self._set_status("No color column selected.", error=True)
            return
        if col_key not in row_data:
            self._set_status(f"Column '{col_key}' missing.", error=True)
            return

        # Parse Hex
        hex_val = row_data[col_key].strip()
        try:
            r, g, b = self._hex_to_rgb(hex_val)
        except ValueError:
            self._set_status(f"Invalid Hex: {hex_val}", error=True)
            return

        max_color = self.rt.color(r, g, b)
        
        # Apply Color
        applied = False
        
        # Check for CoronaColor property "color"
        if hasattr(target_map, "color"):
             target_map.color = max_color
             applied = True
        # Check for standard Max Color map property "color"
        elif hasattr(target_map, "solidColor"): 
             target_map.solidColor = max_color
             applied = True
        # CoronaLegacy "color_color" param
        elif hasattr(target_map, "color_color"):
             target_map.color_color = max_color
             applied = True

        if applied:
            self._set_status(f"Set {target_map.name} to {hex_val}")
        else:
            self._set_status(f"Map {target_map.name} has no recognized color property.", error=True)

    def serialize(self):
        return {
            "target_map_name": self.target_map_name,
            "target_map_handle": self.target_map_handle,
            "mapped_column": self.mapped_column
        }

    def deserialize(self, data):
        self.target_map_name = data.get("target_map_name", "")
        self.target_map_handle = data.get("target_map_handle", None)
        self.mapped_column = data.get("mapped_column", "")
        
        if self.target_map_name:
            self.lbl_target.setText(f"Target: {self.target_map_name}")
            
        # Note: We don't set the combobox index here, because the items 
        # haven't been added yet. 'on_columns_changed' will handle it.

    # --- Internal Logic ---

    def _show_map_selector(self):
        """Finds all CoronaColor maps and shows a selection dialog."""
        if not self.rt: return

        # Gather Maps
        maps = []
        corona_maps = self.rt.getClassInstances(self.rt.CoronaColor)
        std_maps = self.rt.getClassInstances(self.rt.Color_Correction) 
        
        all_found = list(corona_maps) + list(std_maps)
        
        if not all_found:
            self._set_status("No CoronaColor maps found in scene.", error=True)
            return

        map_dict = {} 
        for m in all_found:
            name = m.name if hasattr(m, "name") else "Unnamed Map"
            handle = self.rt.GetHandleByAnim(m)
            map_dict[f"{name} (ID: {handle})"] = (m, handle)

        item, ok = QtWidgets.QInputDialog.getItem(
            self.main_widget, 
            "Select Map", 
            "Found Maps:", 
            sorted(map_dict.keys()), 
            0, 
            False
        )
        
        if ok and item:
            selected_map, handle = map_dict[item]
            self.target_map_name = selected_map.name
            self.target_map_handle = handle
            self.lbl_target.setText(f"Target: {self.target_map_name}")
            self._set_status("")

    def _clear_target(self):
        self.target_map_name = ""
        self.target_map_handle = None
        self.lbl_target.setText("Target: (None)")

    def _set_mapping(self, text):
        self.mapped_column = text

    def _set_status(self, msg, error=False):
        self.lbl_status.setText(msg)
        self.lbl_status.setStyleSheet("color: #ff6666;" if error else "color: #66ff66;")
        if error and msg:
            print(f"HexColorOp ERROR: {msg}")
        self.status_changed.emit(msg, error)

    @staticmethod
    def _hex_to_rgb(hex_str):
        hex_str = hex_str.lstrip("#")
        if len(hex_str) != 6:
            raise ValueError("Hex value must be 6 characters")
        return tuple(int(hex_str[i:i+2], 16) for i in (0, 2, 4))

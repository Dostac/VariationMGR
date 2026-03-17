"""
Import VariationManagerData JSON into the current scene and overwrite existing scene data.

Run from the 3ds Max Python listener:
    import importlib.util, sys
    spec = importlib.util.spec_from_file_location("import_variation_data",
        r"\\vb_nas\nas\Database\3ds_Max\Plugins_Scripts\VirtualBuilders\VariationMGR\import_variation_data.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

Behavior:
- Opens an Explorer file picker for a .json variation data file
- Validates JSON payload
- Overwrites scene custom property "VariationManagerData"
"""

import json
import pymxs
from PySide6 import QtWidgets

rt = pymxs.runtime

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
json_path, _ = QtWidgets.QFileDialog.getOpenFileName(
    None,
    "Import Variation Data JSON",
    "",
    "JSON Files (*.json)",
)

if not json_path:
    print("import_variation_data: Import canceled.")
    raise SystemExit

try:
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
except Exception as exc:
    print(f"import_variation_data: Failed to read JSON - {exc}")
    raise SystemExit

if not isinstance(data, dict):
    print("import_variation_data: Invalid format - top-level JSON must be an object.")
    raise SystemExit

payload = json.dumps(data)

# Overwrite existing scene property.
try:
    rt.fileProperties.deleteProperty(rt.name("custom"), "VariationManagerData")
except Exception:
    pass

rt.fileProperties.addProperty(rt.name("custom"), "VariationManagerData", payload)
print(f"import_variation_data: Imported and overwrote VariationManagerData from {json_path}")
print("import_variation_data: Reopen VariationMGR UI (or run load) to refresh table/operators from scene.")

"""
Export VariationManagerData from the current scene to a JSON file.

Run from the 3ds Max Python listener:
    import importlib.util, sys
    spec = importlib.util.spec_from_file_location("export_variation_data",
        r"\\vb_nas\nas\Database\3ds_Max\Plugins_Scripts\VirtualBuilders\VariationMGR\export_variation_data.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

Behavior:
- Opens a Save dialog at the scene folder (or Desktop for unsaved scenes)
- Prefills filename as <SceneName>_VariationManagerData.json
- Lets you change folder and filename before saving
"""

import json
import os
import pymxs
from PySide6 import QtWidgets

rt = pymxs.runtime

# ---------------------------------------------------------------------------
# 1. Build default output path
# ---------------------------------------------------------------------------
scene_name = str(rt.getFilenameFile(rt.maxFileName)) or "unsaved_scene"
scene_path = str(rt.maxFilePath).replace("\\", "/").rstrip("/")

if scene_path:
    out_dir = scene_path
else:
    out_dir = os.path.join(os.path.expanduser("~"), "Desktop")

default_out_path = os.path.join(out_dir, f"{scene_name}_VariationManagerData.json")

# ---------------------------------------------------------------------------
# 2. Read VariationManagerData from scene file properties
# ---------------------------------------------------------------------------
json_str = ""
count = rt.fileProperties.getNumProperties(rt.Name("custom"))
for i in range(1, count + 1):
    if rt.fileProperties.getPropertyName(rt.Name("custom"), i) == "VariationManagerData":
        json_str = str(rt.fileProperties.getPropertyValue(rt.Name("custom"), i))
        break

if not json_str:
    print("export_variation_data: NO VariationManagerData found in this scene - nothing exported.")
    raise SystemExit

# ---------------------------------------------------------------------------
# 3. Parse JSON first (fail early)
# ---------------------------------------------------------------------------
try:
    data = json.loads(json_str)
except Exception as exc:
    print(f"export_variation_data: JSON parse error - {exc}")
    raise SystemExit

# ---------------------------------------------------------------------------
# 4. Ask user where to save (Explorer dialog with prefilled name)
# ---------------------------------------------------------------------------
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
out_path, _ = QtWidgets.QFileDialog.getSaveFileName(
    None,
    "Export Variation Data JSON",
    default_out_path,
    "JSON Files (*.json)",
)
if not out_path:
    print("export_variation_data: Export canceled.")
    raise SystemExit

if not out_path.lower().endswith(".json"):
    out_path += ".json"

# ---------------------------------------------------------------------------
# 5. Write pretty JSON
# ---------------------------------------------------------------------------
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

print(f"export_variation_data: Exported {len(json_str)} chars -> {out_path}")

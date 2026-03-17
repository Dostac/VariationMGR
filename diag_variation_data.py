"""
VariationMGR Diagnostic
Run via the MaxScript Listener:
    fileIn @"\\vb_nas\nas\Database\3ds_Max\Plugins_Scripts\VirtualBuilders\VariationMGR\diag_variation_data.ms"

Prints:
  - Scene name and path
  - All CoronaCam names in the scene
  - The embedded naming scheme and CSV rows
  - Every resolved output name with a flag for Windows-illegal characters
"""

import json
import pymxs

rt = pymxs.runtime

# Characters that make filenames unwriteable: illegal printable chars + control chars
NEWLY_FIXED = set('*?"<>|') | set(chr(i) for i in range(32))

SEP = "-" * 60

# -----------------------------------------------------------------------
# 1. Scene basics
# -----------------------------------------------------------------------
print(SEP)
scene_name = str(rt.getFilenameFile(rt.maxFileName)) or "(unsaved)"
scene_path = str(rt.maxFilePath) or "(unsaved)"
print(f"Scene name : {scene_name}")
print(f"Scene path : {scene_path}")

# -----------------------------------------------------------------------
# 2. CoronaCam objects
# -----------------------------------------------------------------------
print(SEP)
cams = [obj for obj in rt.objects if rt.isKindOf(obj, rt.CoronaCam)]
print(f"CoronaCams found: {len(cams)}")
for c in cams:
    print(f"  CAM: {c.name}")

# -----------------------------------------------------------------------
# 3. Read VariationManagerData from scene file properties
# -----------------------------------------------------------------------
print(SEP)
json_str = ""
count = rt.fileProperties.getNumProperties(rt.Name("custom"))
for i in range(1, count + 1):
    if rt.fileProperties.getPropertyName(rt.Name("custom"), i) == "VariationManagerData":
        json_str = str(rt.fileProperties.getPropertyValue(rt.Name("custom"), i))
        break

if not json_str:
    print("NO VariationManagerData found in this scene.")
    raise SystemExit

print(f"JSON length: {len(json_str)} chars")

try:
    data = json.loads(json_str)
except Exception as exc:
    print(f"JSON PARSE ERROR: {exc}")
    print("First 500 chars of raw string:")
    print(json_str[:500])
    raise SystemExit

# -----------------------------------------------------------------------
# 4. Summarise variation data
# -----------------------------------------------------------------------
headers  = data.get("headers", [])
rows     = data.get("rows", [])
scheme   = data.get("scheme", "{Scene}_{Camera}")
cam_mode = data.get("render_camera_mode", "active")
cam_col  = data.get("render_camera_column", "")

print(SEP)
print("VARIATION DATA SUMMARY")
print(f"  Naming scheme : {scheme!r}")
print(f"  Camera mode   : {cam_mode}")
print(f"  Camera column : {cam_col!r}")
print(f"  Headers       : {headers}")
print(f"  Row count     : {len(rows)}")

# -----------------------------------------------------------------------
# 5. Resolve every output name and flag illegal characters
# -----------------------------------------------------------------------
print(SEP)
print("RESOLVED OUTPUT NAMES  (* = would have caused TIFFOpenW before the fix)")

cam_names = [c.name for c in cams] if cams else ["<CAM>"]
any_flagged = False

for row_idx, row_vals in enumerate(rows):
    row_data = dict(zip(headers, row_vals))

    for cam_name in cam_names:
        name = scheme
        name = name.replace("{Scene}",  scene_name)
        name = name.replace("{Camera}", cam_name)
        name = name.replace("{Date}",   "DATE")
        name = name.replace("{Row}",    str(row_idx + 1))
        for k, v in row_data.items():
            name = name.replace(f"[{k}]", str(v))

        bad = [c for c in name if c in NEWLY_FIXED]
        flag = f"  *** ILLEGAL: {bad}" if bad else ""
        if bad:
            any_flagged = True
        print(f"  row {row_idx + 1:>3} / {cam_name:<20} -> {name}{flag}")

    # Show which column values contain illegal chars
    for k, v in row_data.items():
        bad = [c for c in str(v) if c in NEWLY_FIXED]
        if bad:
            print(f"             column [{k}] = {v!r}  *** contains: {bad}")

print(SEP)
if any_flagged:
    print("RESULT: Illegal characters found - these rows would have failed before the fix.")
else:
    print("RESULT: No illegal characters found in resolved names.")
    print("        The cause of the error may be elsewhere (permissions, disk space, locked file).")

# -----------------------------------------------------------------------
# 6. Scene-level render settings (compare working vs broken scene)
# -----------------------------------------------------------------------
print(SEP)
print("SCENE RENDER SETTINGS")

scene_output = str(rt.rendOutputFilename)
print(f"  Scene render output path : {scene_output!r}")
print(f"  Scene output path exists : {rt.doesFileExist(rt.getFilenamePath(rt.rendOutputFilename)) if scene_output else 'N/A'}")

re_mgr = rt.maxOps.GetCurRenderElementMgr()
if re_mgr is not None:
    re_active = re_mgr.GetElementsActive()
    re_count  = re_mgr.numRenderElements()
    print(f"  Render elements active   : {re_active}")
    print(f"  Render element count     : {re_count}")
    for i in range(re_count):
        el = re_mgr.getRenderElement(i)
        el_path = re_mgr.GetRenderElementFilename(i)
        print(f"    [{i}] {el.elementname} -> {el_path!r}")
else:
    print("  Render elements manager  : unavailable")

try:
    w = rt.renderWidth
    h = rt.renderHeight
    print(f"  Render resolution        : {w} x {h}")
except Exception:
    print("  Render resolution        : (unavailable)")

print(SEP)

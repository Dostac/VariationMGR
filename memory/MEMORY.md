# VariationMGR Project Memory

## Critical Pattern: Stale Handles After Scene Reload

**Problem:** `rt.GetHandleByAnim()` / `rt.GetAnimByHandle()` handles are session-specific in 3ds Max.
They become invalid every time a `.max` scene is opened (including during batch rendering where
scenes are opened in succession). Serializing a handle and restoring it on next load will always fail.

**Fix pattern (applied to all operators):** Look up by name first; refresh the handle as a side-effect.
Fall back to handle only if name is absent (shouldn't normally happen).

```python
# Scene node (use rt.getNodeByName):
node = None
if self.target_node_name:
    node = self.rt.getNodeByName(self.target_node_name)
    if node:
        self.target_node_handle = self.rt.GetHandleByAnim(node)
if not node and self.target_node_handle:
    node = self.rt.GetAnimByHandle(self.target_node_handle)

# Scene material (iterate rt.sceneMaterials):
mat = None
for m in self.rt.sceneMaterials:
    if m.name == self.source_mat_name:
        mat = m
        self.source_mat_handle = self.rt.GetHandleByAnim(m)
        break
if not mat and self.source_mat_handle:
    mat = self.rt.GetAnimByHandle(self.source_mat_handle)

# Material class instance (use rt.getClassInstances):
mat = None
for m in self.rt.getClassInstances(self.rt.MultiMaterial):
    if m.name == self.target_mat_name:
        mat = m
        self.target_mat_handle = self.rt.GetHandleByAnim(m)
        break
if not mat and self.target_mat_handle:
    mat = self.rt.GetAnimByHandle(self.target_mat_handle)

# Map node (use rt.getClassInstances):
target_map = None
for m in self.rt.getClassInstances(self.rt.CoronaColor):
    if m.name == self.target_map_name:
        target_map = m
        self.target_map_handle = self.rt.GetHandleByAnim(m)
        break
if not target_map and self.target_map_handle:
    target_map = self.rt.GetAnimByHandle(self.target_map_handle)
```

**Also update early guards:** Change `if not self.target_node_handle: return` →
`if not self.target_node_name: return` (and equivalents for mat/map).

**Operators fixed (2026-03-03):**
- `FloorGeneratorOperator.py` — target_node_handle
- `matlib_replacement.py` — target_mat_handle (MultiMaterial)
- `mat_from_folder.py` — source_mat_handle, target_mat_handle, target_node_handle
- `HexColorOperator.py` — target_map_handle (CoronaColor / Color_Correction)
- `unlit_colors.py` — target_map_handle (CoronaColor)
- `layer_visibility.py` — already clean (uses getLayerFromName by name directly)

## Key File Locations
- Operators: `Operators/*.py`
- Operator contract: `get_ui()`, `execute(row_data)`, `serialize()`, `deserialize(data)`, `on_columns_changed(columns)`
- Scene state serialized to `.max` custom property `VariationManagerData` as JSON

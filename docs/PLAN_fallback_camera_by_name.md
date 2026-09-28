# PLAN: Fallback Camera Mode — "Render Camera By Name" (loose match)

## Status: IMPLEMENTED (matcher + schema unit-tested; in-Max render test pending)

## Goal

Add a third fallback camera mode that finds one camera per scene by a
user-supplied name using loose matching. Scenes from different projects name
the same shot differently ("Detailbeeld" vs "Detail", "Hoofdbeeld" vs "Main");
a query like "Detail" should resolve to the right camera in each scene without
an exact match, so a whole queue can be rendered with one setting and one
camera per scene — no VariationMGR data, no guessing the active view, no
wasteful all-cameras render.

Scope: fallback path only. The VariationMGR-driven camera modes
(`render_camera_mode`: active/column/all inside scene data) are untouched.

---

## 1. Job schema — `NetworkRender/shared/job_schema.py`

- `_DEFAULT_JOB_REQUEST["render"]`: extend the mode comment to
  `"all" | "active" | "by_name"` and add `"fallback_camera_name": ""`.
- `normalize_job_request()` (~line 178):
  - accept `"by_name"` as a valid `fallback_camera_mode`.
  - read `fallback_camera_name` as a stripped string.
  - consistency rule: if mode is `"by_name"` but the name is empty, coerce
    mode to `"all"` (the long-standing default). This keeps the core free of
    an empty-query special case, and the server's edit endpoint re-normalizes
    every edit through this function so dashboard edits stay valid too.

Because old requests omit the field, everything normalizes exactly as today —
no schema version bump needed.

## 2. Matching + render — `batchrenderer_core.py`

**New pure-Python helper** (module level, no pymxs, so it is testable):

```python
def match_camera_by_name(names, query):
    """Return (index, kind) of the best loose match for query in names, or None."""
```

Case-insensitive scoring, best score wins:

1. **Exact** name == query → immediate winner.
2. **Substring** either direction (query in name — "Detail" → "Detailbeeld";
   name in query — cam "Main" for query "Mainview"). Ranked among themselves
   by `difflib.SequenceMatcher.ratio()` so "Detail" prefers "Detail" over
   "Detailbeeld_old" when both contain it.
3. **Fuzzy** fallback: highest `SequenceMatcher.ratio()` if ≥ 0.6 (catches
   typos/spacing like "Hoofd beeld"); below the threshold → no match.

Ties break on shorter name, then alphabetical, so results are deterministic.

**Fallback branch** (~line 655, `render_cfg["fallback_camera_mode"]`):

```python
elif render_cfg["fallback_camera_mode"] == "by_name":
    query = render_cfg["fallback_camera_name"]
    cams = list(rt.getCoronaCamsInScene())
    hit = match_camera_by_name([c.name for c in cams], query)
    if hit:
        cam = cams[hit[0]]
        self.log(f"  Camera match: '{query}' -> '{cam.name}' ({hit[1]})")
        jobs.append((cam, f"{base_name}_{cam.name}"))
    else:
        self.log(f"  Warning: no camera matching '{query}' "
                 f"(scene has: {', '.join(c.name for c in cams) or 'none'}).")
```

- Output name includes the *actual* matched camera name
  (`{base}_{Detailbeeld}` in one scene, `{base}_{Detail}` in another) so the
  files stay traceable, mirroring the "all" mode convention.
- No match → scene is skipped with the existing "No render jobs" logging;
  listing the scene's cameras in the warning makes the batchrender.log
  self-explanatory.
- Same enumeration as "all" mode (`getCoronaCamsInScene`, CoronaCam only).

## 3. In-Max UI — `batchrenderer_UI.py`

- `cmb_mode` (~line 205): add third item **"Render Camera By Name"**.
- Below it, a `QLineEdit` `le_fallback_cam` (placeholder `e.g. Detail`),
  visible only while index == 2; toggle in a small handler on
  `cmb_mode.currentIndexChanged`. Add a hint label:
  *"Loosely matched per scene — 'Detail' finds 'Detailbeeld' or 'Detail'."*
- Settings persistence: save/load `FallbackCameraName` next to `RenderMode`
  (~lines 986 / 1047).
- Dirty-state hookup (~line 438): register `le_fallback_cam.textChanged`
  alongside `cmb_mode.currentIndexChanged`.
- `build_job_request()` (~line 1190): map index 0/1/2 →
  `"all"/"active"/"by_name"` and emit
  `"fallback_camera_name": self.le_fallback_cam.text().strip()`.

## 4. Standalone UI — `standalone_batchrenderer/batch_panel.py`

Identical changes in its parallel spots: combo items (~line 191), visibility
toggle, config save/load (~lines 760 / 815), `build_job_request()`
(~line 904).

## 5. Server dashboard — `NetworkRender/server/`

- `server.py` (~line 939): include
  `"fallback_camera_name": str(render_settings.get("fallback_camera_name", "") or "")`
  in the job-row render snapshot (edit modal prefill). The edit endpoint needs
  no change — it merges sparse dicts and re-normalizes via the schema.
- `server_dashboard.html` (~line 248): add `<option value="by_name">Render
  Camera By Name</option>` and a `f-camera-name` text-input row shown only
  when the select is `by_name`.
- `server_dashboard.js`:
  - prefill (~line 1039): the current map coerces everything ≠ "active" to
    "all" — extend it to pass `"by_name"` through; `fillInput("f-camera-name", ...)`;
    show/hide the row on select change (same pattern as `syncOverrideBlock`).
  - `computeSave()` (~line 1111):
    `set(render, "fallback_camera_name", pickVal("f-camera-name", v => v.trim()))`.

## 6. Testing

No test infrastructure exists; verify with:

1. Quick REPL run of `match_camera_by_name` against the motivating cases:
   query "Detail" vs `["Hoofdbeeld", "Detailbeeld"]` and `["Main", "Detail"]`;
   query "Main" vs both lists (must *not* fuzzy-match "Hoofdbeeld"); typo
   "Detial"; empty camera list.
2. In-Max batch render of two scenes with differing camera names, mode
   "By Name", confirming matched-camera log lines and output filenames.
3. Dashboard edit modal round-trip: switch a queued job to by_name, set a
   name, save, reopen — values persist; requeue renders the matched camera.

## Out of scope

- Loose matching for the VariationMGR `column` camera mode (exact lookup via
  `getNodeByName` stays as is).
- Matching non-Corona cameras.
- Multiple name queries / comma-separated lists (easy later extension: split
  on comma, one job per resolved camera).

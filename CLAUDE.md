# VariationMGR Code Context

This repository is a Python-based 3ds Max toolset with two connected domains:
- Scene variation authoring inside 3ds Max (`VariationMGR`).
- Local or network batch rendering (`batchrenderer`, `NetworkRender`).

## Runtime Model

The code runs in three environments:
- 3ds Max interactive Python (`pymxs`, `qtmax`, PySide6 UI).
- 3ds Max headless batch process (`3dsmaxbatch.exe`) for worker execution.
- Standard Python process for network server and worker orchestration.

## Entry Points

- `main.py`: plugin loader target. It reloads modules on launch so NAS edits are picked up without restarting 3ds Max.
- `VariationMGR.py`: opens the Variation Manager dialog.
- `batchrenderer.py`: compatibility launcher that reloads `job_schema`, `batchrenderer_core`, then `batchrenderer_UI` in sequence.
- `server.py` and `worker.py`: thin wrappers to `NetworkRender.server.server` and `NetworkRender.worker.worker`.

## Variation Manager Domain

- `VariationMGR.py` provides a table-driven UI for custom variation rows, naming schemes, camera mode selection, CSV import/export, and operator tabs.
- Camera modes: `active` (render camera), `all` (all CoronaCams in scene), `column` (camera name from a table column).
- Scene data is serialized into the `.max` file custom property `VariationManagerData` as JSON.
- Operator classes are loaded dynamically from the operators folder and executed against row data.
- `variation_core.py` contains operator scanning, preference loading/saving, output-name token resolution, and compatibility helpers for saved operator state.
- `variation_core.validate_config(data, scene_cameras, corona_cameras)` is a pure check of the scene-level setup (camera mode/column, naming scheme tokens and file-name clashes, row range, empty/duplicate headers). It feeds the Setup status button and popup at the bottom-left of the dialog (`_refresh_issues`, `_IssuesPopup`, `_goto_issue`). Operators are excluded on purpose, since they report in their own tabs. The camera column placeholder (`CAMERA_COLUMN_PLACEHOLDER`) is display-only and never stored. A deleted camera column stays stored and shows as "(missing)", and a rename carries the binding over.
- `sheet_table.py` (`SheetTable`) is the table widget. It is Excel-like: selected vs editing states, TSV copy/cut/paste anchored at the top-left of the selection (a single value fills the selection, multiples tile, overflow adds rows but never columns), Delete clears, an undo/redo stack, and Enter moves down. Coordinates follow the visual column order. It accepts `ShortcutOverride` for the keys it handles, because 3ds Max's application shortcuts (Ctrl+V = Clone, Delete) otherwise steal them from a plain QTableWidget. Bulk edits write with signals blocked and emit `cellsEdited`. `main.py` reloads it before `VariationMGR`.

## Operator Catalog

Operators live under `Operators/` and must implement `get_ui()`, `execute(row_data)`, `serialize()`, `deserialize(data)`, and `on_columns_changed(columns)`. Current operators:

- `FloorGeneratorOperator`: Drives a FloorGenerator modifier and CoronaMultiMap textures from CSV columns (plank name, dimensions, laying pattern).
- `MatFromFolderOperator`: Clones a source material, swaps its BitmapTexture nodes using file-pattern matching against a texture folder, and assigns the result to a target object/material/multi-sub slot. Supports real-world scale from `metadata.json` (`TEXTURE_SIZE.cm`) or legacy `METADATA.txt`, tiling, a sidecar `.mat` copy of the source material (survives the material leaving the scene/SME), and `auto:TOKEN` patterns derived from bitmap node names (COL, ROUGH, NRM …).
- `MatFromFolderV2Operator`: Simplified MatFromFolder — one material is both source and target. Its BitmapTexture files are swapped in place per row (no clone, no assignment), with patterns derived automatically from the bitmap node names (`auto:COL` …; typed globs override, `-` skips). Per bitmap row an 'If missing' choice (white / mid-gray / black, generated as tiny PNGs in the local temp folder, or keep previous) decides what loads when a folder lacks that map; defaults OPAC/AO white, METAL/DISP black. Same `metadata.json` / `METADATA.txt` sizing.
- `MultiSubLibOperator`: Replaces sub-materials in a Multi-Sub material from a `.mat` library file, driven by a CSV column.
- `LayerVisibilityOperator`: Toggles child layer visibility under a parent layer based on a CSV column value. Supports `&`-separated multi-layer activation.
- `HexColorOperator`: Drives a CoronaColor or Color_Correction map color from a hex column value.
- `UnlitColorsOperator`: Sets a CoronaColor map's HDR color from a CSV colour library (`Color Name, sRGB R, sRGB G, sRGB B`).

## Batch Renderer Domain

- `batchrenderer_UI.py` builds a normalized job request from UI state (output settings, render overrides, camera fallback, OCIO, variation usage).
- Local rendering uses `batchrenderer_core.BatchRendererCore`.
- Network submission uses `NetworkRender.shared.server_client` (`/health`, `/submit`, UDP discovery).
- Batch renderer settings are persisted in `vb_batch_renderer.ini` under the 3ds Max user scripts directory.
- Variation Manager operator folder preferences are persisted separately in `VariationManager.ini`.

- `batchrenderer_core.py` contains the actual render execution logic:
- Validates/normalizes job payloads via `job_schema`.
- Uses embedded MaxScript helpers (string constant `_MXS`) for camera lookup, render settings, render elements, and bitmap format settings.
- Reads `VariationManagerData` from the current or loaded scene.
- Applies optional operator pipeline per row, resolves output names, and renders cameras per variation mode.
- Supports fallback rendering when variation data is absent.

## Shared Job Contract

- Canonical schema: `NetworkRender/shared/job_schema.py`.
- Root `job_schema.py` is a compatibility shim that re-exports the shared schema.
- Schema normalization supports legacy keys and coerces a request into one or more scene jobs.

## Network Render Domain

- `NetworkRender/server/server.py` runs a threaded HTTP job server with persisted queue state and worker lifecycle endpoints. It also serves the web dashboard; `--ui` wraps that same dashboard in a native pywebview window (no separate desktop UI).
- `NetworkRender/server/server_dashboard.*` is the web dashboard (HTML/CSS/JS) for workers/jobs, queue pause, and cleanup actions — the single UI for the server.
- `NetworkRender/worker/worker.py` runs a worker loop with discovery, registration, heartbeat, claim, execute, and status updates. Supports `--ui` flag for dashboard mode.
- `NetworkRender/worker/networkrender.py` executes one scene job inside 3ds Max batch runtime.
- `NetworkRender/worker/worker_ui.py` is a dashboard for worker status/logs and duplicate-worker cleanup.
- `NetworkRender/shared/server_client.py` implements HTTP JSON calls and UDP broadcast discovery.

## Persistence and Artifacts

- Server state: `server_state.json` (default under `%LOCALAPPDATA%\VirtualBuilders\VariationMGR`, with local fallback).
- Worker identity: `worker_identity.json` under the same local app data root (temp-dir fallback).
- Scene-embedded state: `VariationManagerData` in `.max` custom properties.
- Build outputs and bundled executables live under `build*` and `dist*` directories.

## Conventions and Constraints

- UI toolkit is PySide6 everywhere. Do not use PyQt or other Qt bindings.
- HTTP client uses stdlib `urllib` only (`NetworkRender/shared/server_client.py`). Do not introduce `requests` or other HTTP libraries.
- MaxScript helpers are embedded as Python string constants in `batchrenderer_core.py`, not separate `.ms` files.
- File paths stored in JSON or transmitted over the network use forward slashes.
- Operator modules are scanned from a user-configurable folder. Module names are prefixed with a caller-specific hash to avoid caching collisions.
- `dist/`, `dist_new/`, and `build*/` directories contain frozen build artifacts. Do not edit files inside them directly; changes should be made in the source files.
- `legacy/` contains deprecated code preserved for reference. Do not import from it in new code.
- Singleton window pattern: UI dialogs store their instance on `QApplication` attributes (e.g., `app._vb_variation_manager`) and close the previous instance before opening a new one.

## Operator Development

@Operators/OPERATORS.md

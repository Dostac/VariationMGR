# Git Preparation Plan

## Phase 1: Immediate Cleanup (do first)

### 1. Add a `.gitignore`

This is the most critical step. ~338MB of build artifacts should never be tracked.

```gitignore
# Python
__pycache__/
*.pyc
*.pyo

# Build artifacts
packaging/build/
packaging/dist/

# Server runtime state
server_state.json

# Claude Code local settings
.claude/settings.local.json
memory/

# Web portal (moved to separate repo)
web-portal/

# Legacy
legacy/

# OS
Thumbs.db
Desktop.ini
.DS_Store
```

### 2. Delete `web-portal/`

It lives in a separate repo now. Remove it entirely before the first commit so its
history (especially `node_modules/`) doesn't bloat the repo.

### 3. Delete `server_state.json`

Runtime state, not source.

### 4. Delete all `__pycache__/` directories

---

## Phase 2: Source Restructuring

The main issue is that everything is flat in the root. Entry points, core modules,
diagnostic scripts, shim files, and docs are all mixed together.

### Proposed layout

```
VariationMGR/
├── .gitignore
├── CLAUDE.md
├── main.py                          # keep — plugin loader entry point
├── server.py                        # keep — thin wrapper
├── worker.py                        # keep — thin wrapper
├── batchrenderer.py                 # keep — compatibility launcher
├── job_schema.py                    # keep — compatibility shim
│
├── src/                             # NEW — core library code
│   ├── __init__.py
│   ├── variation_mgr.py             # renamed from VariationMGR.py
│   ├── variation_core.py            # moved from root
│   ├── batchrenderer_core.py        # moved from root
│   └── batchrenderer_ui.py          # renamed from batchrenderer_UI.py
│
├── Operators/                       # keep as-is (plugin folder, user-configurable)
│   ├── OPERATORS.md
│   ├── FloorGeneratorOperator.py
│   ├── HexColorOperator.py
│   ├── layer_visibility.py
│   ├── mat_from_folder.py
│   ├── matlib_replacement.py
│   └── unlit_colors.py
│
├── NetworkRender/                   # keep as-is (already well-structured)
│   ├── server/
│   ├── worker/
│   └── shared/
│
├── standalone_batchrenderer/        # keep as-is (already a proper package)
│
├── tools/                           # NEW — diagnostic/utility scripts
│   ├── export_variation_data.py
│   ├── import_variation_data.py
│   ├── diag_variation_data.py
│   └── diag_variation_data.ms
│
├── packaging/                       # keep structure, dist/ and build/ are gitignored
│   ├── build.py
│   ├── build.txt
│   ├── BatchRenderer.spec
│   ├── Server.spec
│   └── Worker.spec
│
├── docs/
└── legacy/                          # gitignored, or delete entirely
```

### Key decisions and rationale

| Change | Why |
|---|---|
| Move core modules into `src/` | Separates library code from entry points. The root stays clean with just launchers. |
| `tools/` for diagnostics | These are run-from-listener utility scripts, not part of the main import chain. Grouping them signals "not imported at runtime." |
| Keep `Operators/` at root level | User-configurable plugin folder. Moving it deeper would break the convention that users can point to a custom folder. |
| Keep entry points at root | 3ds Max plugin loader and PyInstaller specs target these by path. Moving them would break the plugin loader. |
| Keep `job_schema.py` shim at root | Imported as `import job_schema` by batch renderer modules. After moving those to `src/`, update the shim or the imports. |

---

## Phase 3: Import Path Fixes (required after Phase 2)

After moving files into `src/`, update:

1. **`main.py`** — change `_fresh("VariationMGR")` to `_fresh("src.variation_mgr")` (or adjust `sys.path`)
2. **`batchrenderer.py`** — update module names in `_fresh_module()` calls
3. **`batchrenderer_ui.py`** — update `import batchrenderer_core as brcore` to relative import
4. **`batchrenderer_core.py`** — update `import job_schema as schema` to use the shared location
5. **`job_schema.py`** shim — may still be needed for backward compat, or can be removed if all consumers are updated
6. **PyInstaller `.spec` files** — update paths to new source locations

---

## Phase 4: Additional Git Best Practices

### 5. Add a `README.md`

Include:
- What the project is
- How to install/load it in 3ds Max
- How to build the standalone executables
- Link to OPERATORS.md for plugin development

### 6. Decide on `legacy/`

Consider deleting entirely rather than gitignoring. If it's truly deprecated, removing
it before the initial commit means it never enters git history. It can always be found
on the NAS if needed.

### 7. PyInstaller spec files

The `.spec` files are source and should be tracked. The `build/` and `dist/` outputs
should not.

---

## Priority / Risk Assessment

### Do now (high value, low risk)
- `.gitignore` — absolutely essential
- Delete `web-portal/`, `legacy/`, `server_state.json`, `__pycache__/`
- Move diagnostic scripts to `tools/`

### Consider carefully (medium value, medium risk)
- Moving core modules to `src/` — improves structure but requires updating every import
  path and testing in 3ds Max. The current flat layout works and 3ds Max's `sys.path`
  manipulation makes nested packages slightly tricky.

### Alternative to `src/`
If the import path changes feel too risky given 3ds Max's loading model, keep the flat
layout but rename files to follow Python conventions (lowercase with underscores) and add
the `.gitignore` + `tools/` folder. That gets 80% of the benefit with 20% of the risk.

# PLAN: Batch Renderer UX Improvements

## Status: DONE (committed 3c82043)

---

## 1. Remove "Assign JSON" Toolbar Button ✅

Removed `btn_assign_json` from the toolbar. Right-click context menu entry and
`_assign_var_json()` method kept intact.

---

## 2. Render/Submit Confirmation Dialog ✅

Added `_confirm_render()` helper showing variation state, resolution, format/depth/alpha,
and output folder before any of the three render/submit actions fire.

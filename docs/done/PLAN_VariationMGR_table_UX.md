# PLAN: VariationMGR Table UX Improvements

## Status: DONE (committed 3c82043)

---

## 1. Faster Submenu Popup ✅

Plan called for `MenuButtonPopup`. Implemented instead as a custom `_HoldMenuFilter`
event filter (short click = default action, hold ≥75 ms = menu). This avoids Qt's
split-button arrow rendering and fixes click behavior inside 3ds Max's embedded Qt,
where `DelayedPopup` and `MenuButtonPopup` both have issues.

---

## 2. Direct Cell Copy-Paste ✅

Ctrl+C / Ctrl+V intercepted via `eventFilter` on `self.table`. Copy reads current item;
paste writes clipboard text to all selected cells and fires one `_on_cell_changed` for
preview sync.

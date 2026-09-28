# PLAN: Dashboard Job Creator ("New Job" in the server UI)

## Status: IMPLEMENTED (2026-09-28)

Shipped as described below, with these deviations:

- One modal, two modes: the Edit Job modal itself is reused (`modalMode`
  "edit" / "new") instead of cloning its fieldsets, so the forms can't drift.
- Row Range **is** included: a single `render_range_expr` applied to every
  scene in the submission. It is just a string the schema already accepts, so
  it needed no upload handling. It stays hidden in edit mode because
  `/admin/jobs/update` doesn't take it.
- Render/output settings from the last submission are remembered per browser
  in `localStorage` (`vb_new_job_form`); the scene list and row range are not.
- Lines that don't end in `.max` are flagged in the hint and confirmed on
  submit rather than blocked.
- Inside the `--ui` window, **Browse…** buttons open native Explorer dialogs
  (scenes: multi-select `.max`; output: folder) via pywebview `js_api`. They
  stay hidden in a plain browser, which cannot expose full paths. The window
  now runs with `private_mode=False` so the remembered settings persist.
- OCIO overrides and per-scene variation JSON / CSV overrides remain out of
  scope, as planned.

## Goal

Let jobs be created straight from the server dashboard, mimicking the Python
batch renderer UI: add multiple scene files, set render params, toggle
VariationMGR integration, choose the output folder — then submit. Today the
only way onto the queue is through the in-Max or standalone Python UI.

## Why it's cheap

The backend already exists: `POST /submit` ([server.py](../NetworkRender/server/server.py)
`submit_request`, ~line 269) accepts a raw job request, runs it through
`schema.normalize_job_request()`, and fans `max_files` out into one queued job
per scene. The dashboard's edit modal already renders nearly every field the
creator needs. This is dashboard HTML/JS work plus form reuse — no new
endpoints, no worker changes.

---

## 1. UI — `server_dashboard.html` / `server_dashboard.css`

- **"➕ New Job" button** in the jobs toolbar, next to the existing admin
  actions.
- **Create modal**, structured like the Python UI's panel order and reusing
  the edit modal's form-section styling:
  1. **Scene Files** — a textarea, one UNC path per line (the browser has no
     NAS file picker; paste-from-Explorer is the realistic workflow). Live
     line count + per-line validation flag for entries not ending in `.max`.
  2. **Render Settings** — override toggle + collapsible Longest Side / Pass
     Limit / Noise Limit block, Fallback Camera Mode (all / active / by name
     + name field, per PLAN_fallback_camera_by_name).
  3. **VariationMGR Integration** — "Use VariationMGR scene data" checkbox
     with the same hint text as the Python UI.
  4. **Output** — folder (UNC path input), version select, format /
     depth / alpha / render-elements (reusing the existing PNG guard logic
     from the edit modal, `syncRenderElementsAvailability`).
- Shared markup strategy: extract the render/output fieldsets the edit modal
  uses into markup both modals share (`c-` prefixed ids for the creator, or a
  small template cloned into each), so the two never drift.

## 2. Logic — `server_dashboard.js`

- `openCreateModal()` prefills sensible defaults matching
  `_DEFAULT_JOB_REQUEST` (jpg, 4000 px, variations on, fallback all).
- On submit, build a full job request:

```js
{
  request_id: "",              // server mints a uuid
  max_files: lines,            // non-empty trimmed lines, / separators
  load_scene: true,
  output:  { folder, version, format, depth_index, save_alpha, save_render_elements },
  render:  { override_settings, resolution, pass_limit, noise_limit,
             use_variations, fallback_camera_mode, fallback_camera_name },
}
```

- `POST /submit`, then `loadData()` to show the new queued rows; keep the
  modal open with an inline error on failure (the endpoint raises when no
  scene files are given).
- Client-side validation only blocks empty scene list / empty output folder;
  everything else is normalized server-side exactly like a Python-UI submit.

## 3. Server — `server.py`

- No required changes: `/submit` and the schema do all the work.
- Optional nicety (server runs with NAS access): validate scene paths in
  `submit_request` or a tiny `POST /admin/validate_paths` helper so typos
  surface at submit time instead of as worker failures. V1 can ship without
  it — a bad path fails the job with a clear error already.

## 4. Testing

1. Create a 2-scene job from the dashboard; confirm two queued rows, correct
   render/output values via the edit modal prefill.
2. Round-trip check: submit from dashboard, render on a worker, compare the
   folder's batchrender.log against a Python-UI submission of the same
   scenes.
3. Failure paths: empty scene list, non-`.max` line flagged, unreachable
   scene path (worker reports the error on the job row).

## Out of scope (v1)

- OCIO overrides — the Python UI populates its display/view dropdowns from
  the local OCIO config, which the browser can't enumerate. Jobs submit with
  OCIO defaults (no override); revisit if needed.
- Variation JSON/CSV override upload and row ranges — the Python UI assigns
  these per queue entry from local files; a dashboard equivalent needs file
  upload handling and is its own feature.
- A server-side NAS file browser for picking scenes.

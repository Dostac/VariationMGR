# Submitter Recipes

A **recipe** is a small Python file that turns a client's table into render
jobs. The server's **Submitter** page (`http://<server>:8765/submitter`, or the
**Submitter** button on the dashboard) runs it. Everything that is the same for
every project is built in:

- reading the client CSV and scanning folders
- the editable grid with tick boxes, bulk edit and randomize
- output and render settings
- pooling rows per scene and splitting them into jobs
- a live preview, then submitting everything as one request
- archiving each submission

A recipe only says which scenes exist, what the client columns are, and how
one table becomes rows per scene.

Hand this file plus a client example to an AI (see
[Asking an AI for a recipe](#asking-an-ai-for-a-recipe)) and it can write the
recipe for you.

## Where recipes live

Recipes are `.py` files in the server's recipes folder. The dashboard shows the
path in the Submitter's top bar.

- The default location is a `recipes` folder next to the server state file:
  `%LOCALAPPDATA%\VirtualBuilders\VariationMGR\recipes` on the server machine.
- Start the server with `--recipes-dir "\\vb_nas\nas\...\SubmitterRecipes"` to
  keep them on the NAS, where you can edit them in VS Code and version them.
- The first start creates the folder and copies in the two example recipes
  (`tcmm_swift.py`, `wehkamp_gordijnen.py`). An existing folder is never
  touched.
- Files are re-read on every preview, so edits apply without a restart.

Next to each recipe the server keeps:

| File | Contents |
|---|---|
| `<recipe>.state.json` | The page's working copy: grid rows, options, settings. Shared by everyone. |
| `_submissions/<date>_<recipe>_<id>.json` | One per submission: inputs, a copy of the recipe source, and every job payload. |

Files starting with `_` are not listed as recipes.

## Anatomy of a recipe

```python
from vb_recipe import *

TITLE = "TCMM Swift"                       # name in the recipe picker
DESCRIPTION = "Master CSV -> 5 scenes."    # one line under the picker

SCENES = {                                 # required
    "LS1":      Scene("//nas/.../Lifestyle-01.max", ["Fabric name", "width", "cam", "color"]),
    "HEADRAIL": Scene("//nas/.../Headrail.max",     ["Fabric name", "Curtain"]),
}

COLUMNS = [                                # required: the client table
    Column("Fabric name", key="name", required=True),
    Column("Lifestyle", key="lifestyle", choices=["LS1", "LS2"]),
    Column("Wall color", key="color", aliases=["color", "colour"]),
]

OPTIONS = [                                # optional: extra controls on the page
    Choice("mode", "Render mode", ["regular", "studio_only"]),
]

DEFAULTS = {                               # optional: starting settings
    "render": {"override_settings": True, "resolution": 1200, "pass_limit": 18},
    "output": {"version": "V2", "format": "jpg"},
    "chunk_rows": 40,
}

def build(rows, opts, jobs):               # required
    for r in rows:
        for cam in ("hero", "detail"):
            jobs.add(r.lifestyle, {"Fabric name": r.name, "width": "140",
                                   "cam": f"{r.lifestyle}_{cam}", "color": r.color})
```

### `Scene(path, headers, label="", render=None, output=None, chunk_rows=None)`

One `.max` file the recipe can emit rows for, under a short key you choose.

- `headers` must match the scene's **VariationMGR table columns exactly**. The
  rows you add become that scene's table (a CSV override). The override
  replaces the scene's whole table, so every row must fill every column. The
  scene's operators and naming scheme stay as they are in the file.
- `label` is a friendlier name for the preview.
- `render` and `output` override the page settings for this scene only, for
  example `render={"resolution": 2500}` for close-ups.
- `chunk_rows` overrides "Rows per job" for this scene. Use `0` to never split
  it.

Use forward slashes or UNC paths the workers can reach. The preview warns when
the server cannot see a scene file.

### `Column(name, key=None, aliases=(), choices=None, required=False, default="", readonly=False, swatch=False, help="")`

One column of the grid: what the client fills in.

| Argument | Meaning |
|---|---|
| `name` | Grid heading and the CSV header to match. |
| `key` | How `build()` reads it (`row.key`). Defaults to `name`. Use a short identifier when `name` has spaces. |
| `aliases` | Other CSV headers accepted for this column. Matching ignores case and surrounding spaces. The key itself is not matched. |
| `choices` | Makes the cell a dropdown. Loaded values that match a choice except for case are corrected (`ls2` becomes `LS2`). Other values are kept and flagged. |
| `required` | A ticked row with this cell empty blocks submission. A CSV without this column is rejected. |
| `default` | Used for empty cells and new rows. |
| `readonly` | The grid shows the value but does not let you edit it (e.g. names from a folder scan). |
| `swatch` | Shows a colour square for hex values such as `9EA299`. |
| `help` | Tooltip on the heading. |

### Options

Extra controls in the page's **Recipe options** panel, read in `build()` as
`opts.<key>`:

| Class | Control | Value type |
|---|---|---|
| `Choice(key, label, choices, default=None, labels=None)` | dropdown (labels shown, choices returned) | str |
| `Text(key, label, default="")` | text field | str |
| `Folder(key, label, default="")` | path field with Browse… in the server window | str, forward slashes, quotes stripped |
| `Number(key, label, default=0, min=None, max=None, step=1)` | number field | int or float |
| `Toggle(key, label, default=False)` | checkbox | bool |

All of them accept `help="..."` for a hint line.

### `FOLDER_SCAN = FolderScan(option, column, files=False, pattern=None)`

Adds a **Scan folder** button. It lists the folder in option `option` and adds
one row per subfolder (or per file with `files=True`), with the name in
`column`. `pattern` is an optional regex filter. A rescan keeps the values of
rows whose name was already in the grid, adds new ones with defaults, and
drops names that disappeared.

### `DEFAULTS`

Starting values for the **Output & render** panel:

- `render`: `override_settings`, `resolution`, `pass_limit`, `noise_limit`,
  `fallback_camera_mode`, `fallback_camera_name`
- `output`: `folder`, `version`, `format` (`jpg`/`png`/`tif`/`exr`),
  `depth_index`, `save_alpha`, `save_render_elements`
- `ocio`: same keys as the Batch Renderer's OCIO block (not editable on the page)
- `chunk_rows`: the default "Rows per job" (`0` = one job per scene)

The page saves its own values once someone edits them. **Reset** on the panel
goes back to these defaults. `use_variations` is always on: without it the
scene would ignore the rows.

### `build(rows, opts, jobs)`

Called with the **ticked, non-empty** rows each time the preview refreshes and
once more on submit.

- `rows` is a list of `Row`. Read cells as `row.name` or `row["name"]`. A
  missing key reads as `""`. `row.number` is the row's position in the grid,
  for error messages.
- `opts` holds the option values, already converted to the types above.
- `jobs.add(scene_key, row)` appends one VariationMGR row to a scene. Pass a
  dict keyed by that scene's headers (case-insensitive) or a list in header
  order. An unknown scene key or column is an error. A header you leave out
  is sent empty, with a warning.
- `jobs.warn("...")` shows a warning without blocking.
- `jobs.log("...")` adds a line to the preview's **Recipe log**.
- `raise RecipeError("...")` stops with a clear message and no traceback. Use
  it for bad client input.
- `unique(rows, "name")` returns the first row per distinct value. Use it for
  scenes that must render once per product even when the client lists it
  twice.

Emit rows in the order you want them in each table. `build()` must finish
within 30 seconds, and it runs on the server with its NAS access. Anything
else it raises shows in the preview with the recipe line number.

## What happens after `build()`

1. **Pooling.** Everything added to one scene key becomes one table, whatever
   client row it came from. One scene equals one table equals at least one
   job.
2. **Splitting.** A table longer than "Rows per job" becomes several jobs. Each
   job carries the **full** table plus a row range (`2-41`, `42-81`, …; row 1
   is the header). Row numbers, and so `{Row}` in output names, are identical
   whether a table is split or not.
3. **Settings.** Each job gets its settings in this order, later ones winning:
   schema defaults, recipe `DEFAULTS`, page settings, then the scene's
   `render`/`output` overrides. The result is normalised by the same code as
   every other submission.
4. **Submit.** All jobs go into the queue under **one request id**, tagged with
   the recipe name. The inputs, a copy of the recipe source and all payloads
   are archived. **Recent submissions** can load an archived run back into the
   page.

The preview shows per scene the row count, jobs, split ranges and effective
render settings. Hover a row to see its headers and first rows.

## Validation at a glance

| Blocks submission | Warning only |
|---|---|
| No output folder | CSV columns the recipe doesn't use |
| No ticked rows with data | Optional columns missing from the CSV |
| Required cell empty on a ticked row | Dropdown value not in `choices` |
| `RecipeError`, exception or timeout in `build()` | Scene file not visible from the server |
| Unknown scene key or column in `jobs.add` | Scene header never set by `build()` |
| Recipe file fails to load | `jobs.warn(...)` |

## Command line

The same pipeline runs without the server UI. Use it for dry runs or scripting:

```
set R=%LOCALAPPDATA%\VirtualBuilders\VariationMGR\recipes
python -m NetworkRender.server.submitter %R%\tcmm_swift.py client.csv --output-folder "\\vb_nas\...\Renders" --chunk-rows 20
python -m NetworkRender.server.submitter %R%\tcmm_swift.py client.csv --opt mode=studio_only --output-folder X --save-payloads jobs.json
python -m NetworkRender.server.submitter %R%\tcmm_swift.py client.csv --output-folder X --submit http://192.168.1.10:8765
```

Run it from the VariationMGR folder so the `NetworkRender` package is found. `--submit` posts every job to `/submit`
under one shared request id. Recipes with a folder scan can omit the CSV and
pass the folder with `--opt`.

## Asking an AI for a recipe

Give it this file, one of the example recipes, and something like:

> Write a submitter recipe for client X. Their CSV has these columns:
> `<paste the header row and 3 sample rows>`.
> Our scenes and their VariationMGR headers are:
> `<scene path>`: `<headers>` (repeat per scene).
> Per client row we need: `<e.g. 6 rows in the lifestyle scene named by the
> Lifestyle column, one per camera SWIFT_{LS}_{suffix}; 4 rows in the headrail
> scene, once per fabric>`.
> Defaults: 1200 px, 18 passes, V2, jpg, 40 rows per job.

Paste the result into **+ New recipe**, or save it in the recipes folder, then
load the client CSV and check the preview before submitting.

## Tips and pitfalls

- **Headers are the contract.** Copy them from the scene's VariationMGR table
  (Export CSV gives you the header row). A typo in `jobs.add` is caught. A typo
  in `Scene(..., headers)` only shows as the scene not picking up that column.
- **Keep rows complete.** The override replaces the scene's table, so columns
  the scene's operators read must be present, even when empty.
- **Split for workers, not for size.** Around 10–40 rows per job keeps all
  workers busy. A job always carries the whole table, so huge tables make the
  queue state file larger, but not the renders slower.
- **Excel.** Semicolon (Dutch Excel), comma and tab CSVs all work, in UTF-8 or
  Windows encoding. `.xlsx` must be saved as CSV first.
- **Shared working copy.** The grid is saved on the server per recipe. Two
  people editing the same recipe's grid at the same time overwrite each
  other's changes.

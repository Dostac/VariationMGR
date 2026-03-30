# VariationMGR Suite User Manual

This guide is for artists and production users who want to use the VariationMGR suite well, not for developers.

It assumes the suite is already installed correctly and that you can already open:

- `VariationMGR`
- the `Batch Renderer`
- the `Server`
- the `Worker`

The server also provides a web monitoring page, accessible from any browser on the local network. It does not need to be installed separately.

It does not cover installation.

## What This Suite Actually Does

The suite is built around one simple idea:

Instead of making many separate `.max` files for every option, you keep one master scene and describe the differences as rows in a variation table.

One row might mean:

- oak floor
- black kitchen
- warm wall color
- camera `Cam_Livingroom_01`

The next row might mean:

- walnut floor
- white kitchen
- cool wall color
- camera `Cam_Livingroom_02`

VariationMGR applies those row values to the scene. The Batch Renderer turns those rows into renders. The Server and Workers let multiple machines share the work across your local network.

That means the suite can be used in two very different ways:

1. As a true variation pipeline for options, finishes, layouts, XRefs, colors, and cameras.
2. As a clean batch renderer for many `.max` files, even if you do not use variations at all.

## The Four Main Parts

### 1. VariationMGR

This is where you define the variation logic:

- your variation table
- your operators
- your naming scheme
- your camera mode
- your row range

This is the creative control center.

### 2. Batch Renderer

This is where you decide how to render:

- current scene or many files
- local render or server submission
- output folder and format
- overrides for render settings
- whether to use embedded variation data
- per-file row range and job splitting

### 3. Server

This is the queue manager on your local network.

It receives jobs, tracks progress, and hands work to workers.

### 4. Worker

A worker is a render machine that connects to the server, claims jobs, and renders them.

If you only render locally, you may never need the server and worker at all.

## The Big-Picture Workflow

Most teams will use the suite in this order:

1. Build and test the variation setup in `VariationMGR`.
2. Save the variation data into the scene.
3. Optionally export CSV for editing and/or server splitting.
4. Define a naming scheme that makes the output self-explanatory.
5. Open the server.
6. Open one or more workers on other machines.
7. Use the Batch Renderer to render locally or submit to the server.

If you do not want variations, the workflow is even simpler:

1. Open the Batch Renderer.
2. Add one or more `.max` files.
3. Choose output folder and format.
4. Pick camera behavior.
5. Start the batch render or submit it to the server.

## Part 1: VariationMGR

### What A Variation Really Is

Think of the table as a list of render scenarios.

- Columns = the kinds of things that can change
- Rows = one complete option set

Example:

| Kitchen | Floor | Camera | WallColor |
|---|---|---|---|
| Black | Oak | Cam_01 | WarmWhite |
| White | Walnut | Cam_02 | Sand |
| Green | Oak | Cam_03 | LightGrey |

Each row is a full instruction set for one result.

### Typical First Session

A very good first setup usually looks like this:

1. Add columns to drive the operators.
2. Add a few rows for actual sellable combinations.
3. Add operators that connect those columns to the scene.
4. Test all rows with `Run Selected Row`.
5. Set the naming scheme.
6. Save to scene.
7. Open the Batch Renderer using the button at the bottom of the VariationMGR window.

That is the core loop.

### The Variation Table

The table is where most of your work happens.

#### Key buttons

- `+ Row`: add another variation.
- `+ Column`: add another property you want to control.
- `Edit CSV`: open the table in a temporary CSV file for live editing. The dropdown arrow on this button also gives you `Import CSV` and `Export CSV` for moving table data in and out of VariationMGR.
- `Save to Scene`: store the current setup inside the `.max` file. The dropdown arrow on this button gives you `Import Variation Config` and `Export Variation Config` for portable JSON snapshots of the full variation setup.
- `Reset`: clear the current variation setup from both the UI and the scene file. This cannot be undone.

#### Practical advice

- Keep column names human-readable. They become tokens in the naming scheme.
- Use one column per business decision, not one column per tiny technical detail.
- Duplicate rows when building close variants. It is faster and safer than rebuilding from scratch.
- Right-click rows to duplicate or delete them.
- Right-click columns to rename or delete them.

### Operators: How Rows Actually Change The Scene

Rows do nothing by themselves. Operators are what make the scene respond to the row values.

You add operators with `+ Add Operator`.

The built-in operators cover the main production cases:

- `LayerVisibilityOperator`: show one child layer option from a column value.
- `HexColorOperator`: drive a color map from a hex color column.
- `UnlitColorsOperator`: use a named color from a color-library CSV.
- `MultiSubLibOperator`: swap materials from a `.mat` library.
- `MatFromFolderOperator`: build material results from texture folders.
- `XRefSceneOperator`: load scene content from external `.max` files.
- `FloorGeneratorOperator`: drive floor and plank variations from table values.

For each operator:

1. Pick the target inside the scene.
2. Configure any other settings required by the operator.
3. Link one or more operator fields to table columns.
4. Test a row.

### `Run Selected Row`: What It Is For

`Run Selected Row` is a test button, not a render button.

It applies the selected row to the scene so you can confirm that:

- the right materials change
- the right layers show
- the right XRef loads
- the right floor settings apply
- the row values actually do what you expect

Use this heavily before you batch render.

It is the fastest way to catch bad column names, wrong scene targets, and rows that do not match your operator setup.

### The Output Naming Scheme

This is one of the most important features in the whole suite.

The naming scheme decides what every render is called.

Default example:

`{Scene}_{Row}_{Camera}`

Available built-in tokens:

- `{Scene}`
- `{Row}`
- `{Camera}`
- `{Date}`

You can also insert table properties, which appear like:

- `[Kitchen]`
- `[Floor]`
- `[Colorway]`

#### Why this is so powerful

A strong naming scheme makes renders easy to organize and catalogue. The flexibility of the naming scheme also allows for client-requested naming conventions, without the artist having to manually rename renders. VariationMGR takes care of as many administrative tasks as possible.

Instead of getting files like:

- `render001.jpg`
- `render002.jpg`

you can get files like:

- `Livingroom_3_Cam_01_BlackKitchen_OakFloor`
- `Livingroom_4_Cam_02_WhiteKitchen_WalnutFloor`

That matters because it:

- makes review faster
- reduces wrong deliveries
- helps clients and producers understand files without opening them
- makes rerenders safer
- keeps local and network renders organized

#### Good naming habits

Use naming to describe what the image means, not just when it was made.

Good:

- `{Scene}_{Camera}_[Kitchen]_[Floor]`
- `{Scene}_{Row}_[Style]_[Colorway]`
- `{Scene}_{Date}_{Camera}_[Option]`

Less useful:

- `{Scene}_{Date}`

That is fine for quick tests, but weak for production. With multiple rows, it would not produce unique names, causing renders to overwrite each other and valuable render time to go completely to waste.

The default naming scheme always produces unique names as it covers every possible variation type: `{Scene}_{Row}_{Camera}`

You can change these defaults, but always double-check that the scheme will produce unique names for every row.

#### The preview

VariationMGR shows a live preview under the naming field.

### Render Settings Inside VariationMGR

VariationMGR also stores rendering intent for variation jobs.

#### Camera mode

You can choose:

- `Active Camera`
- `All Cameras`
- `From Column`

Use `Active Camera` when every row should render from the current render camera.

Use `All Cameras` when each row should be rendered from every Corona camera in the scene.

Use `From Column` when the row itself decides which camera to use. This is one of the most powerful setups, because it lets your table describe both the scene state and the view.

#### Row range

You can also define a row range.

This is useful when you want to render only part of a large table, for example:

- only rows 2 to 10
- only the new options you added today
- only the rows that failed last night

In this system, the header is considered row 1, and your first data row starts at row 2. Entering row 1 as a range start is not valid and will be corrected to row 2 automatically.

### Saving Your Work Properly

This matters:

`Save to Scene` is what makes the variation setup travel with the `.max` file.

If you forget to save to scene, the Batch Renderer and the network may still see the old setup, not your latest changes.

A safe habit is:

1. test rows
2. confirm naming
3. click `Save to Scene`
4. then open the Batch Renderer

### CSV And JSON: When To Use Which

#### CSV

CSV is best when you want to work on the table as data.

Use it for:

- fast table editing
- spreadsheet cleanup
- copying values in bulk
- planning combinations
- sharing variation rows with non-technical teammates

The `Edit CSV` button is especially useful because it opens a temporary CSV and syncs the table back into VariationMGR as you save.

#### JSON (Variation Config)

The full variation config export is a portable JSON snapshot of the complete setup.

It carries:

- naming scheme
- camera mode
- row range
- headers
- rows
- operator setup

Access it via the dropdown arrow on the `Save to Scene` button: `Import Variation Config` and `Export Variation Config`.

Use it when you want:

- a portable snapshot of the variation setup
- a backup outside the scene
- a clean handoff between scenes or users
- server-side row splitting in the Batch Renderer

For most artists:

- save to scene always
- export CSV often
- export variation config when you want portability or advanced control

### A Good Real-World Variation Example

Imagine you are rendering apartment options for sales visuals.

You create columns like:

- `Kitchen`
- `Floor`
- `WallColor`
- `Camera`
- `XRefSet`

Then you add operators:

- one to show the right kitchen layer
- one to swap or rebuild the floor material
- one to drive a color map
- one to load a furnishing or layout XRef

Then you set the naming scheme to:

`{Scene}_[Kitchen]_[Floor]_[WallColor]_{Camera}`

Now every render says exactly what it is.

That is when VariationMGR starts paying for itself.

## Part 2: Batch Renderer

The Batch Renderer is where scene setups become actual output.

It supports two kinds of users equally well:

- people using full VariationMGR-driven scenes
- people who just want to batch render a list of `.max` files

### The Batch Queue

The queue is the list of files you want to render or submit.

#### Key buttons

- `+ Add Files`: add `.max` scenes.
- `Assign JSON`: attach a variation config JSON override to selected files.
- `Assign CSV`: attach a CSV row override to selected files.
- `Split for Server`: split one file's variation rows into many server jobs.
- `Remove`: remove selected files.
- `Clear`: clear the entire queue.

You can also right-click queued files for useful actions like:

- open the scene
- assign or clear JSON
- assign or clear CSV
- set or clear row range
- split or clear split settings
- remove from queue

### Output & Naming

Here you set:

- output folder
- optional version label

#### Important note about versioning

If you are rendering without VariationMGR, the version field is a quick way to separate output sets.

If you are rendering with VariationMGR naming, your main naming control is the naming scheme you created in VariationMGR. In practice, that is where you should put the important business meaning.

### Render Settings

This section controls global render behavior.

#### `Override scene render settings`

Use this when the batch job should force its own values for:

- longest side
- pass limit
- noise limit

This is useful for:

- quick draft batches
- network tests
- lower-cost review renders
- forcing consistency across many files

#### `Fallback Camera Mode`

This is mainly for scenes without usable VariationMGR data.

You can choose:

- `Render All Cameras`
- `Render Active View Only`

This makes the Batch Renderer useful even for plain scenes with no variation system.

### VariationMGR Integration

This section connects the renderer to the saved scene data.

#### `Use VariationMGR scene data`

Turn this on when the queued scenes already contain saved VariationMGR data.

When enabled, the renderer will use the embedded scene setup for:

- variation rows
- naming scheme
- camera behavior
- operators

If no variation data is found, the renderer falls back to the camera mode above.

#### How embedded variation data appears in the queue

If no JSON is assigned, the queue shows variation data as:

`(scene data)`

That means it will use whatever was saved into the `.max` file.

### JSON Override vs CSV Override

These are very important.

#### JSON override

Use `Assign JSON` when you want to replace the scene's embedded variation setup with a different full setup.

This is the right choice when you want to change:

- rows
- naming
- camera mode
- operators

without opening and re-saving the original scene first.

#### CSV override

Use `Assign CSV` when the scene setup is correct, but the row data needs to change.

This is ideal for:

- revised variation lists
- alternate row sets for the same scene
- production planning coming from Excel

Think of it like this:

- JSON changes the full variation recipe.
- CSV changes the table contents feeding that recipe.

### Per-File Row Range

`Set Range...` lets you render only a slice of the variation rows for selected files.

This is great for:

- rerendering failed ranges
- testing a small subset
- sending only part of a large set to the farm

Again, row numbering starts at 2 for the first data row.

### Split For Server

This is one of the strongest advanced features in the suite.

`Split for Server` breaks a large variation set into smaller server jobs, such as:

- 3 rows per job
- 5 rows per job
- 30 rows per job

Why this matters:

- workers can share one large scene more efficiently
- a failed chunk is easier to rerender than a large monolithic job
- long overnight queues become more balanced

#### Very important limitation

Server splitting only works when a JSON or CSV override is assigned to the queue entry. The split button is disabled otherwise, because the Batch Renderer needs to know the full row count before it can divide the work.

So even if your scene already has embedded variation data, the recommended workflow for split rendering is:

1. Export CSV from VariationMGR.
2. Add the `.max` file to the Batch Renderer.
3. Assign the CSV to the queue entry.
4. Use `Split for Server`.

The optimal split size is: total rows divided by the number of available workers.

For example: 3 workers and 12 rows → split size of 4.

This minimizes scene startup overhead. The mental model is: every machine gets the largest possible chunk of work without having to restart its 3ds Max session, while every worker is still populated evenly.

### Format Configuration

You can choose:

- `jpg`
- `png`
- `tif`
- `exr`

And then control:

- bit depth
- alpha
- render elements

### Color Management

The `Color Management (Output Only)` section lets you override the output transform for the render output.

This is useful when:

- the scene is correct but the output delivery needs a different transform
- you want a predictable display or view output
- you need a specific output color space conversion

If you do not need that, leave it alone. The render will use the default color settings embedded in each scene.

### Process Log

Read the log.

It is the fastest place to understand:

- what the renderer is doing
- which file is being opened
- whether variation overrides were picked up
- whether row ranges were applied
- whether a render or submit failed

### The Three Main Render Buttons

#### `RENDER CURRENT SCENE`

Use this when you are already inside the scene you want to render and you do not want to build a queue first.

This is ideal for:

- testing
- small iteration loops
- final checks before a bigger batch

#### `START BATCH RENDER`

Use this for local rendering from the queue on the current machine.

This is the simplest multi-file workflow.

#### `SUBMIT TO SERVER`

Use this when the server is running and workers are available.

The Batch Renderer will package the queued files into jobs and send them to the server queue.

If the queue is empty but your current scene is saved, it can still be submitted as a server job.

## Part 3: Local Rendering Without Variations

Not everybody needs VariationMGR all the time.

If you simply want to render a stack of `.max` files with a single camera strategy:

1. Open the Batch Renderer.
2. Add the files.
3. Choose the output folder.
4. Pick format and render settings.
5. Leave `Use VariationMGR scene data` off, or just ignore it.
6. Choose `Render All Cameras` or `Render Active View Only`.
7. Start the batch render or submit to the server.

This is a completely valid use of the suite.

You do not have to use variations to benefit from it.

## Part 4: Network Rendering

### The Intended Network Model

This system is designed for local network use.

Typical setup:

- one server machine
- one or more worker machines
- one or more artist machines submitting jobs
- optional phones, tablets, or laptops watching the web dashboard

### Start Order

The healthiest order is:

1. open the server
2. confirm the server address
3. open the workers
4. confirm workers appear in the server
5. submit from the Batch Renderer

### Workers Must Match The Main Environment

This is the most important network rule in the whole suite:

Workers need near-perfect parity with the machine that prepared the scene.

In plain English, that means the workers should not be "almost the same." They should be properly equivalent.

That includes things like:

- the same 3ds Max setup
- the same renderer availability
- the same plugins
- the same licenses
- the same custom operators
- the same access to scene assets, XRefs, textures, and libraries
- the same network paths

If a worker is missing something, the job may:

- fail outright
- skip parts of the variation logic
- render differently from your local machine

So before trusting overnight farm output, do a short real test on each worker.

### Server UI: What It Is For

The server window is a control room.

It shows:

- current server address
- whether the queue is paused
- overall progress
- connected workers
- queued, running, done, and failed jobs

#### Useful server controls

- `Refresh`: update the view immediately.
- `Pause/Resume`: stop or resume assigning queued jobs to workers.
- `Repair State`: fix stale or mismatched queue state.
- `Requeue Stale`: put abandoned running jobs back into the queue.
- `Remove Done`: clean finished jobs.
- `Remove Failed`: clean failed jobs.
- `Clear Queue`: remove only queued jobs.
- `Clear All`: wipe all jobs from the server.

Use these when you are managing a live queue, not just submitting into it.

### Worker UI: What It Is For

The worker window shows:

- worker name
- host machine
- server URL
- current status
- current job
- recent log activity

#### Useful worker controls

- `Start Worker`
- `Stop Worker`
- `Discover Server`
- `Refresh`

If discovery works, the worker can find the server on the local network automatically.

If not, the server URL can be entered manually when the worker is launched through the normal team workflow.

### The Web Dashboard

The server exposes a web page for monitoring.

This is useful because other devices on the same network can check progress without opening 3ds Max. Open the server address in a browser from any device on the local network.

The page shows:

- queue status
- total progress
- worker health
- recent jobs

It refreshes automatically, so it is perfect for:

- a laptop next to you
- a tablet on your desk
- a phone check during long runs

Think of it as a live status board, not a control panel.

## Practical Case-Based Workflows

### Case 1: "I have one scene with many finish options"

Use this:

1. Build columns for the finish decisions.
2. Add operators that connect those values to the scene.
3. Test rows with `Run Selected Row`.
4. Create a descriptive naming scheme.
5. Save to scene.
6. Open the Batch Renderer.
7. Turn on `Use VariationMGR scene data`.
8. Render locally or submit to server.

This is the ideal VariationMGR workflow.

### Case 2: "I want to edit rows quickly in Excel"

Use this:

1. Build the base setup in VariationMGR.
2. Export CSV or use `Edit CSV`.
3. Adjust the rows externally.
4. Re-import or let the temporary CSV sync back in.
5. Save to scene again.

This is great when the row list comes from production planning rather than from the artist directly.

### Case 3: "I need to rerender only rows 42 to 60"

Use this:

1. Keep the variation setup as-is.
2. In VariationMGR or the Batch Renderer, define the row range you need.
3. Render only that slice.

This is much cleaner than duplicating scenes.

### Case 4: "I want to use the network efficiently on a large variation table"

If you only have one scene containing hundreds of variations, only one worker will render it at a time. This is wasteful when your network has many workers available.

Use this:

1. Export CSV from VariationMGR.
2. Add the `.max` file to the Batch Renderer.
3. Assign the CSV to the queue entry.
4. Use `Split for Server`. The ideal split size = total rows / available workers. This minimizes scene startup overhead.
5. Submit to server.
6. Monitor progress in the server UI or the browser dashboard.

By dividing the work on one scene into separate jobs, you can put every worker to use simultaneously.

### Case 5: "I do not want variations at all"

Use this:

1. Open the Batch Renderer.
2. Add one or more `.max` files.
3. Choose output folder, format, and render settings.
4. Choose a fallback camera mode.
5. Start batch render or submit to the server.

If scenes do not contain variation data, they will be rendered normally. If they do contain variation data but you want to ignore it, turn off `Use VariationMGR scene data`.

This is the right workflow when you just need dependable batch rendering with network support.

## Recommended Habits

- Save to scene before leaving VariationMGR.
- Use `Run Selected Row` before committing to a full batch render.
- Export CSV when you want bulk editing.
- Export variation config when you want portability.
- Test each worker with a real production scene before trusting it.
- Watch the process log instead of guessing.
- Use row ranges for rerenders instead of creating duplicate scenes.

## Common Mistakes To Avoid

- Building a great variation setup and forgetting `Save to Scene`.
- Sending a single scene with many variations to a network of workers without splitting it first. Without splitting, only one worker will pick it up.
- Sending jobs to workers that do not have matching plugins, licenses, or scene access.
- Using a naming scheme that does not produce unique output names. Non-unique names cause renders to overwrite each other. The default `{Scene}_{Row}_{Camera}` always produces unique names.

## Final Mental Model

If you remember only one thing, remember this:

VariationMGR defines meaning.

The Batch Renderer turns that meaning into output.

The Server and Workers scale that output across the local network.

Once that clicks, the whole suite becomes much easier to use with confidence.

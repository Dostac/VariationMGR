"""New recipe. Contract and examples: docs/SUBMITTER_RECIPES.md.

A recipe turns the client table (the grid on the Submitter page) into
VariationMGR rows per scene. The server pools rows per scene, splits them
into jobs ("Rows per job") and applies the page's render/output settings.
"""
from vb_recipe import *

TITLE = "New recipe"
DESCRIPTION = "One line shown under the recipe picker."

# Scenes this recipe can render. Headers must match the scene's VariationMGR
# table columns exactly: the rows you add replace the scene's whole table.
SCENES = {
    "MAIN": Scene("//vb_nas02/nas/Klanten/CLIENT/PROJECT/Scenes/scene.max",
                  ["Fabric", "WallColor"]),
}

# The client-facing table. `aliases` are other CSV headers accepted for a
# column; `choices` makes the cell a dropdown.
COLUMNS = [
    Column("Fabric name", key="fabric", required=True),
    Column("Wall color", key="wall", aliases=["color", "colour"], default=""),
]

# Extra controls on the page, read in build() as opts.<key>.
OPTIONS = [
    # Choice("mode", "Render mode", ["all", "hero_only"], labels=["Everything", "Hero shots only"]),
]

# Starting values for the page's Output & render panel.
DEFAULTS = {
    "render": {"override_settings": True, "resolution": 3000, "pass_limit": 25, "noise_limit": 4.0},
    "output": {"version": "V1", "format": "jpg"},
    "chunk_rows": 20,          # rows per job; 0 = one job per scene
}


def build(rows, opts, jobs):
    """rows: ticked grid rows (row.fabric, row["wall"]); opts: OPTIONS values;
    jobs.add(scene_key, {header: value}) emits one VariationMGR row."""
    for r in rows:
        jobs.add("MAIN", {"Fabric": r.fabric, "WallColor": r.wall})

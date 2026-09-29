"""TCMM Swift: one client row (a fabric in one lifestyle) becomes renders in
five scenes. Port of Klanten/TCMM/260029 - TCMM - Swift/Assets/SubmitterV2.py.

Per fabric:
  - 6 rows in its lifestyle scene (one per camera angle)
  - 4 rows in the headrail scene (one per curtain type)
  - 1 row in the closeup-flat scene (PDP 11 / swatch)
  - 1 row in the closeup-fold scene (PDP 3)
Studio scenes (headrail + closeups) render once per unique fabric, even when
the client lists a fabric in several lifestyle rows.
"""
from vb_recipe import *

TITLE = "TCMM Swift"
DESCRIPTION = ("Master CSV (Fabric name, Width, Opacity, Lifestyle, color) -> "
               "lifestyle, headrail and close-up scenes.")

ROOT = "//vb_nas02/nas/Klanten/TCMM/260029 - TCMM - Swift/Scenes"

LIFESTYLE_HEADERS = ["Fabric name", "width", "cam", "Opacity", "State", "color"]
STUDIO_HEADERS = ["Fabric name", "width", "Opacity"]

SCENES = {
    "LS1": Scene(f"{ROOT}/260029_Swift_Lifestyle-01.max", LIFESTYLE_HEADERS, label="Lifestyle 1"),
    "LS2": Scene(f"{ROOT}/260029_Swift_Lifestyle-02.max", LIFESTYLE_HEADERS, label="Lifestyle 2"),
    "LS3": Scene(f"{ROOT}/260029_Swift_Lifestyle-03.max", LIFESTYLE_HEADERS, label="Lifestyle 3"),
    "LS4": Scene(f"{ROOT}/260029_Swift_Lifestyle-04.max", LIFESTYLE_HEADERS, label="Lifestyle 4"),
    "HEADRAIL": Scene(f"{ROOT}/260029_Headrail-Scenes.max",
                      ["Fabric name", "width", "Opacity", "Curtain"], label="Headrail"),
    "CLOSEUP_FLAT": Scene(f"{ROOT}/260029_Closeup-flat.max", STUDIO_HEADERS, label="Close-up flat"),
    "CLOSEUP_FOLD": Scene(f"{ROOT}/260029_Closeup-fold.max", STUDIO_HEADERS, label="Close-up fold"),
}
LIFESTYLES = ["LS1", "LS2", "LS3", "LS4"]

# Camera per lifestyle row: SWIFT_{LS}_{cam_suffix}.
LIFESTYLE_VARIANTS = [
    ("plp_base",    "OPEN"),    # headrail-hidden framing
    ("life_open",   "OPEN"),    # PDP 1
    ("life_closed", "CLOSED"),  # PDP 10
    ("wide_open",   "OPEN"),    # PDP 8
    ("fab_hang",    "OPEN"),    # PDP 2
    ("fab_floor",   "OPEN"),    # PDP 9
]
HEADRAIL_VARIANTS = ["Pencil Pleat", "Eyelet", "Pinch Pleat", "Wave"]

COLUMNS = [
    Column("Fabric name", key="name", required=True),
    Column("Width", key="width", aliases=["Fabric width"], required=True),
    Column("Opacity", key="opacity", aliases=["Fabric opacity"], required=True),
    Column("Lifestyle", key="lifestyle", choices=LIFESTYLES,
           help="Ignored in the 'all lifestyles', 'studio only' and 'close-up flat only' modes."),
    Column("Wall color", key="color", aliases=["color", "colour", "wall colour"],
           help="Overrides the lifestyle wall color. Blank = the scene's own color."),
]

OPTIONS = [
    Choice("mode", "Render mode",
           ["regular", "all_lifestyles", "studio_only", "closeup_flat_only"],
           labels=["Regular (use Lifestyle column)",
                   "All lifestyles + studio scenes",
                   "Studio only (headrail + close-ups)",
                   "Close-up flat only (PDP 11 / swatch)"]),
]

DEFAULTS = {
    "render": {"override_settings": True, "resolution": 1200, "pass_limit": 18, "noise_limit": 4.0},
    "output": {"version": "V2", "format": "jpg"},
    "chunk_rows": 40,
}


def build(rows, opts, jobs):
    fabrics = unique(rows, "name")

    if opts.mode == "closeup_flat_only":
        for f in fabrics:
            jobs.add("CLOSEUP_FLAT", [f.name, f.width, f.opacity])
        return

    if opts.mode != "studio_only":
        if opts.mode == "all_lifestyles":
            pairs = [(ls, f) for f in fabrics for ls in LIFESTYLES]
        else:
            pairs = []
            for r in rows:
                ls = r.lifestyle.strip().upper()
                if ls not in LIFESTYLES:
                    raise RecipeError(
                        f"Row {r.number} ({r.name}): Lifestyle '{r.lifestyle}' is not one of "
                        f"{', '.join(LIFESTYLES)}. Fix the row or pick 'All lifestyles'.")
                pairs.append((ls, r))
        for ls, f in pairs:
            for cam_suffix, state in LIFESTYLE_VARIANTS:
                jobs.add(ls, [f.name, f.width, f"SWIFT_{ls}_{cam_suffix}", f.opacity, state, f.color])

    for f in fabrics:
        for curtain in HEADRAIL_VARIANTS:
            jobs.add("HEADRAIL", [f.name, f.width, f.opacity, curtain])
        jobs.add("CLOSEUP_FLAT", [f.name, f.width, f.opacity])
        jobs.add("CLOSEUP_FOLD", [f.name, f.width, f.opacity])

    if len(fabrics) < len(rows):
        jobs.log(f"{len(rows) - len(fabrics)} repeated fabric row(s): studio scenes render each fabric once.")

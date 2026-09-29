"""Wehkamp Gordijnen: one row per fabric subfolder, with a StyleSet and a wall
color picked per row. Port of RANDOMCODE/Wehkamp script/WehkampSubmitter.py.

Fill the grid with "Scan folder" (Fabrics root), then pick values per row, or
tick rows and use Bulk edit (set or randomize). The grid is saved on the
server, so a rescan keeps the choices already made for known fabrics.
"""
from vb_recipe import *

TITLE = "Wehkamp Gordijnen"
DESCRIPTION = "Fabric subfolders x StyleSet x Muurkleur, one scene."

SCENES = {
    "MAIN": Scene("//vb_nas02/nas/Klanten/Wehkamp/GORDIJNEN_Projectbestanden/Scenes/Scene.max",
                  ["Gordijn", "stylesets", "muurkleur", "mat_folder"], label="Gordijnen"),
}

STYLESETS = ["StyleSet 1", "StyleSet 2", "StyleSet 8", "StyleSet 24"]
MUURKLEUREN = ["9EA299", "A4937B", "B6B2A6", "EEE8DB"]

COLUMNS = [
    Column("Gordijn", key="gordijn", required=True, readonly=True,
           help="Fabric subfolder name (filled by Scan folder)."),
    Column("StyleSet", key="styleset", aliases=["stylesets"], choices=STYLESETS,
           default=STYLESETS[0], required=True),
    Column("Muurkleur", key="muurkleur", choices=MUURKLEUREN,
           default=MUURKLEUREN[0], required=True, swatch=True),
]

OPTIONS = [
    Folder("fabrics_root", "Fabrics root",
           default="//vb_nas02/nas/Klanten/Wehkamp/250032 - Wehkamp - Gordijnen batch 4/Assets/Fabrics",
           help="Each subfolder is one fabric. Also sent to the scene as mat_folder."),
]

FOLDER_SCAN = FolderScan(option="fabrics_root", column="gordijn")

DEFAULTS = {
    "render": {"override_settings": True, "resolution": 5000, "pass_limit": 10, "noise_limit": 4.0},
    "output": {"version": "V2", "format": "jpg",
               "folder": "//vb_nas02/nas/Klanten/Wehkamp/250032 - Wehkamp - Gordijnen batch 4/Renders"},
    "chunk_rows": 5,
}


def build(rows, opts, jobs):
    for r in rows:
        jobs.add("MAIN", {
            "Gordijn": r.gordijn,
            "stylesets": r.styleset,
            "muurkleur": r.muurkleur,
            "mat_folder": opts.fabrics_root,
        })

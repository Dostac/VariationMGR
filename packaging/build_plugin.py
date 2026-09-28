"""Stage the 3ds Max plugin files into a clean directory for the installer.

Usage (standalone):
    python packaging/build_plugin.py              # stage to packaging/staging/plugin
    python packaging/build_plugin.py --output D:\somewhere\plugin

Called by build.py as part of the ``installer`` target.
"""

import argparse
import os
import shutil
from pathlib import Path

PACKAGING_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGING_DIR.parent
DEFAULT_STAGING = PACKAGING_DIR / "staging" / "plugin"

# Files copied from the project root into the staging plugin folder.
ROOT_FILES = [
    "main.py",
    "VariationMGR.py",
    "variation_core.py",
    "batchrenderer.py",
    "batchrenderer_UI.py",
    "batchrenderer_core.py",
    "render_logger.py",
    "job_schema.py",
]

# Directories copied recursively.  Paths are relative to PROJECT_ROOT.
# Each entry is (source_relative, dest_relative_inside_staging).
DIRECTORIES = [
    ("Operators", "Operators"),
    ("NetworkRender/shared", "NetworkRender/shared"),
]

# Ensure NetworkRender is a proper package in the staged output.
INIT_FILES = [
    "NetworkRender/__init__.py",
]

# Patterns to exclude when copying directories.
EXCLUDE_PATTERNS = {"__pycache__", ".pyc", ".pyo"}


def _should_skip(name):
    return any(name.endswith(pat) or name == pat for pat in EXCLUDE_PATTERNS)


def _copy_tree(src, dst):
    """Copy a directory tree, skipping __pycache__ and bytecode."""
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        if _should_skip(item.name):
            continue
        target = dst / item.name
        if item.is_dir():
            _copy_tree(item, target)
        else:
            shutil.copy2(item, target)


def stage(output_dir=None):
    """Copy plugin files into the staging directory and return the path."""
    staging = Path(output_dir) if output_dir else DEFAULT_STAGING

    # Clean previous staging.
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    # Copy root-level files.
    for name in ROOT_FILES:
        src = PROJECT_ROOT / name
        if not src.exists():
            print(f"  WARNING: missing {src}")
            continue
        shutil.copy2(src, staging / name)

    # Copy directory trees.
    for src_rel, dst_rel in DIRECTORIES:
        src = PROJECT_ROOT / src_rel
        if not src.exists():
            print(f"  WARNING: missing directory {src}")
            continue
        _copy_tree(src, staging / dst_rel)

    # Ensure __init__.py files exist so packages are importable.
    for rel in INIT_FILES:
        init = staging / rel
        init.parent.mkdir(parents=True, exist_ok=True)
        if not init.exists():
            src = PROJECT_ROOT / rel
            if src.exists():
                shutil.copy2(src, init)
            else:
                init.write_text("")

    # --- Future: obfuscation step would go here ---
    # e.g. subprocess.run(["pyarmor", "gen", "--output", str(staging),
    #                       str(staging / "VariationMGR.py"),
    #                       str(staging / "variation_core.py")])

    count = sum(1 for _ in staging.rglob("*") if _.is_file())
    print(f"  Staged {count} files -> {staging}")
    return staging


def main():
    parser = argparse.ArgumentParser(description="Stage VariationMGR plugin files")
    parser.add_argument("--output", "-o", help="Output directory (default: packaging/staging/plugin)")
    args = parser.parse_args()
    stage(args.output)


if __name__ == "__main__":
    main()

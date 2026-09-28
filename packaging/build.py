"""Build VariationMGR distributable executables and installer.

Usage:
    python packaging/build.py                  # build the targets enabled by the
                                               #   BUILD_* toggles below (no installer)
    python packaging/build.py server           # build Server only
    python packaging/build.py worker           # build Worker only
    python packaging/build.py batchrenderer    # build BatchRenderer only
    python packaging/build.py installer        # installer only (assumes server+worker already built)

The no-arg run honors the BUILD_SERVER / BUILD_WORKER / BUILD_BATCHRENDERER
toggles and does NOT run Inno Setup, so you can disable a target (e.g. a worker
whose exe is locked by a running instance) and rebuild just the rest. Build the
installer explicitly with the `installer` target once its binaries exist.
"""

import shutil
import subprocess
import sys
from pathlib import Path

PACKAGING_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGING_DIR.parent

# Default build selection (used when no CLI target is provided).
BUILD_SERVER = True
BUILD_WORKER = False
BUILD_BATCHRENDERER = False

# PyInstaller targets — each maps to a .spec file.
PYINSTALLER_TARGETS = {
    "server":        PACKAGING_DIR / "Server.spec",
    "worker":        PACKAGING_DIR / "Worker.spec",
    "batchrenderer": PACKAGING_DIR / "BatchRenderer.spec",
}

DEFAULT_ENABLED_TARGETS = {
    "server": BUILD_SERVER,
    "worker": BUILD_WORKER,
    "batchrenderer": BUILD_BATCHRENDERER,
}

COMMON_FLAGS = [
    "--clean",
    "--noconfirm",
    "--workpath", str(PACKAGING_DIR / "build"),
    "--distpath", str(PACKAGING_DIR / "dist"),
]

INNO_SETUP_SCRIPT = PACKAGING_DIR / "installer.iss"


def build_pyinstaller(name: str, spec: Path) -> bool:
    print(f"\n{'='*60}")
    print(f"  Building: {name}")
    print(f"{'='*60}")
    cmd = [sys.executable, "-m", "PyInstaller"] + COMMON_FLAGS + [str(spec)]
    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    if result.returncode != 0:
        print(f"\n[FAILED] {name} (exit code {result.returncode})")
        return False
    print(f"\n[OK] {name}")
    return True


def find_inno_setup() -> str | None:
    """Locate the Inno Setup compiler (iscc.exe)."""
    candidates = [
        Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
        Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
    ]
    iscc = shutil.which("iscc")
    if iscc:
        return iscc
    for p in candidates:
        if p.exists():
            return str(p)
    return None


def build_installer(skip_pyinstaller=False) -> bool:
    """Build the installer.

    When *skip_pyinstaller* is True the Server/Worker PyInstaller builds are
    skipped — useful when they were already built separately and you just want
    to re-package the installer quickly.
    """
    from build_plugin import stage

    print(f"\n{'='*60}")
    print(f"  Stage: plugin files")
    print(f"{'='*60}")
    stage()

    if not skip_pyinstaller:
        # Build server and worker (required by the installer).
        failures = []
        for name in ("server", "worker"):
            spec = PYINSTALLER_TARGETS[name]
            if not build_pyinstaller(name, spec):
                failures.append(name)

        if failures:
            print(f"\n[FAILED] Installer aborted — failed prerequisite(s): {', '.join(failures)}")
            return False

    # Run Inno Setup compiler.
    iscc = find_inno_setup()
    if not iscc:
        print("\n[FAILED] Inno Setup not found. Install from https://jrsoftware.org/isinfo.php")
        print("         or add ISCC.exe to PATH.")
        return False

    if not INNO_SETUP_SCRIPT.exists():
        print(f"\n[FAILED] Inno Setup script not found: {INNO_SETUP_SCRIPT}")
        return False

    print(f"\n{'='*60}")
    print(f"  Building: Installer (Inno Setup)")
    print(f"{'='*60}")
    result = subprocess.run([iscc, str(INNO_SETUP_SCRIPT)], cwd=str(PACKAGING_DIR))
    if result.returncode != 0:
        print(f"\n[FAILED] Inno Setup (exit code {result.returncode})")
        return False

    print(f"\n[OK] Installer")
    return True


def build_targets(names) -> bool:
    """Run the PyInstaller build for each target name in *names* (in order).

    Returns True only if every build succeeded.
    """
    failures = []
    for name in names:
        spec = PYINSTALLER_TARGETS[name]
        if not build_pyinstaller(name, spec):
            failures.append(name)
    if failures:
        print(f"\n{'='*60}")
        print(f"FAILED: {', '.join(failures)}")
        return False
    return True


def main():
    requested = [a.lower() for a in sys.argv[1:]]

    # No arguments → build only the targets enabled in DEFAULT_ENABLED_TARGETS
    # (the BUILD_* toggles at the top of this file). The installer is NOT run on
    # the no-arg path; build it explicitly with `build.py installer` once the
    # binaries it needs exist. This lets you disable a target (e.g. the worker,
    # whose exe/DLLs are locked while a worker is running) and rebuild just the
    # rest without tripping over the lock or the Inno step.
    if not requested:
        enabled = [name for name, on in DEFAULT_ENABLED_TARGETS.items() if on]
        if not enabled:
            print("No targets enabled. Set BUILD_SERVER / BUILD_WORKER / "
                  "BUILD_BATCHRENDERER at the top of build.py, or pass a target "
                  "name (server / worker / batchrenderer / installer).")
            sys.exit(1)
        print(f"Default build targets (from BUILD_* toggles): {', '.join(enabled)}")
        ok = build_targets(enabled)
        print(f"\n{'='*60}")
        if ok:
            print(f"Build succeeded. Output: {PACKAGING_DIR / 'dist'}")
            print("Note: installer not built on the no-arg path. "
                  "Run `python packaging/build.py installer` to package it.")
        else:
            print("Build FAILED.")
            sys.exit(1)
        return

    # Explicit "installer" → stage plugin + Inno Setup only (skip PyInstaller).
    if "installer" in requested:
        ok = build_installer(skip_pyinstaller=True)
        print(f"\n{'='*60}")
        if ok:
            print(f"Installer build succeeded. Output: {PACKAGING_DIR / 'dist'}")
        else:
            print("Installer build FAILED.")
            sys.exit(1)
        return

    # Explicit PyInstaller targets (server, worker, batchrenderer), built in the
    # canonical order regardless of how they were listed on the command line.
    target_names = [name for name in PYINSTALLER_TARGETS if name in requested]

    if not target_names:
        known = ", ".join(list(PYINSTALLER_TARGETS) + ["installer"])
        print(f"Unknown target(s): {sys.argv[1:]}. Known: {known}")
        sys.exit(1)

    ok = build_targets(target_names)
    print(f"\n{'='*60}")
    if ok:
        print(f"All builds succeeded. Output: {PACKAGING_DIR / 'dist'}")
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()

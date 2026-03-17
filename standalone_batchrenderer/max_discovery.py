"""Locate 3ds Max installations and the 3dsmaxbatch.exe executable."""

import os
import subprocess


def find_3dsmax_install_dirs():
    """Return a list of 3ds Max installation directories, newest version first."""
    roots = [
        os.path.join(
            os.environ.get("ProgramW6432", r"C:\Program Files"), "Autodesk"
        ),
        os.path.join(
            os.environ.get("ProgramFiles", r"C:\Program Files"), "Autodesk"
        ),
    ]
    found = []
    seen = set()
    for root in roots:
        if not os.path.isdir(root):
            continue
        try:
            for name in os.listdir(root):
                if not name.lower().startswith("3ds max"):
                    continue
                full = os.path.join(root, name)
                norm = os.path.normcase(os.path.normpath(full))
                if norm not in seen:
                    seen.add(norm)
                    found.append(full)
        except Exception:
            pass
    found.sort(reverse=True)
    return found


def find_3dsmaxbatch_exe():
    """Return the path to ``3dsmaxbatch.exe``, or an empty string."""
    env_val = os.environ.get("VB_MAX_BATCH_EXE", "").strip()
    if env_val and os.path.isfile(env_val):
        return env_val

    try:
        probe = subprocess.run(
            ["where", "3dsmaxbatch.exe"],
            capture_output=True,
            text=True,
            timeout=2.0,
        )
        if probe.returncode == 0:
            for line in (probe.stdout or "").splitlines():
                cand = line.strip().strip('"')
                if cand and os.path.isfile(cand):
                    return cand
    except Exception:
        pass

    for max_dir in find_3dsmax_install_dirs():
        exe = os.path.join(max_dir, "3dsmaxbatch.exe")
        if os.path.isfile(exe):
            return exe

    return ""

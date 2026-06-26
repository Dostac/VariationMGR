"""
batch.py - Batch Renderer entry point.

Twin of main.py: point a second Unlit Toolbox / 3ds Max shortcut at this file
to launch straight into the Batch Renderer, skipping the Variation Manager.

3ds Max runs this via rt.python.executeFile(), which execs the file as a string
with no __file__ and without putting its directory on sys.path. So we resolve
our own directory first (same fallback as main.py), then import main and call
its batch launcher. main's own module-level setup re-adds the path and the
_fresh() reload keeps the live NAS hot-reload behaviour identical to main.py.
"""

import os
import sys

try:
    _root = os.path.dirname(os.path.abspath(__file__))
except NameError:
    import inspect
    _root = os.path.dirname(os.path.abspath(
        inspect.getfile(inspect.currentframe())))

if _root not in sys.path:
    sys.path.insert(0, _root)

import main

main.launch_batch_renderer()

"""
main.py - VirtualBuilders / VariationMGR suite entry point.

This is the single file the Unlit Toolbox plugin loader targets.
Core Max scripts live alongside this file; network modules live under NetworkRender/.

Layout:
    VariationMGR/
        main.py             <- plugin loader target
        VariationMGR.py
        batchrenderer.py    <- compatibility shim
        batchrenderer_UI.py
        batchrenderer_core.py
        job_schema.py        <- compatibility shim
        variation_core.py
        NetworkRender/
            server/
                server.py
            shared/
                job_schema.py
            worker/
                worker.py
        VariationManager.ini
        Operators/
        legacy/
"""

import os
import sys
import importlib

# ---------------------------------------------------------------------------
# Root resolution â€” same directory as this file.
# 3ds Max can exec scripts in ways that leave __file__ undefined, so we fall
# back to inspect when necessary.
# ---------------------------------------------------------------------------
try:
    _root = os.path.dirname(os.path.abspath(__file__))
except NameError:
    import inspect
    _root = os.path.dirname(os.path.abspath(
        inspect.getfile(inspect.currentframe())))

if _root not in sys.path:
    sys.path.insert(0, _root)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fresh(module_name):
    """Import or force-reload a module so live NAS edits are always picked up."""
    if module_name in sys.modules:
        return importlib.reload(sys.modules[module_name])
    return importlib.import_module(module_name)


# ---------------------------------------------------------------------------
# Public launchers  (called by the plugin loader or by UI buttons)
# ---------------------------------------------------------------------------

def launch_variation_manager():
    _fresh("variation_core")
    vm = _fresh("VariationMGR")
    vm.main()


def launch_batch_renderer():
    br = _fresh("batchrenderer")
    br.main()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    launch_variation_manager()


if __name__ == "__main__":
    main()


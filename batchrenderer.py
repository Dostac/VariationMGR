import importlib
import sys


def _fresh_module(module_name):
    if module_name in sys.modules:
        return importlib.reload(sys.modules[module_name])
    return importlib.import_module(module_name)


def _fresh_batch_modules():
    # Reload schema first, then core, then UI.
    _fresh_module("job_schema")
    _fresh_module("batchrenderer_core")
    return _fresh_module("batchrenderer_UI")


def main():
    ui = _fresh_batch_modules()
    ui.main()


if __name__ == "__main__":
    main()

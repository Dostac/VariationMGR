import importlib
import sys


def _fresh_module(module_name):
    if module_name in sys.modules:
        return importlib.reload(sys.modules[module_name])
    return importlib.import_module(module_name)


def _fresh_batch_modules():
    # Reload dependencies first, then core, then UI. Every first-party module
    # the core/UI import must be listed here: a reloaded core re-runs its
    # imports, but `import x` returns the cached module from sys.modules, so
    # anything not reloaded explicitly stays stale for the whole Max session.
    _fresh_module("job_schema")
    _fresh_module("variation_core")
    _fresh_module("render_logger")
    _fresh_module("NetworkRender.shared.server_client")
    _fresh_module("batchrenderer_core")
    return _fresh_module("batchrenderer_UI")


def main():
    ui = _fresh_batch_modules()
    ui.main()


if __name__ == "__main__":
    main()

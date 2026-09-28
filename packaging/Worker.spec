# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

SPEC_PATH = Path(globals().get('SPEC', 'packaging/Worker.spec')).resolve()
SPEC_DIR = SPEC_PATH.parent
PROJECT_ROOT = SPEC_DIR.parent

a = Analysis(
    [str(PROJECT_ROOT / 'NetworkRender' / 'worker' / 'worker_ui.py')],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=[
        (str(PROJECT_ROOT / 'NetworkRender' / 'worker' / 'networkrender.py'), 'NetworkRender\\worker'),
        (str(PROJECT_ROOT / 'batchrenderer_core.py'), '.'),
        (str(PROJECT_ROOT / 'render_logger.py'), '.'),
        (str(PROJECT_ROOT / 'job_schema.py'), '.'),
        (str(PROJECT_ROOT / 'variation_core.py'), '.'),
        (str(PROJECT_ROOT / 'NetworkRender' / 'shared'), 'NetworkRender\\shared'),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Worker',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Worker',
)

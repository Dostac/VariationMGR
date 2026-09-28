# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

SPEC_PATH = Path(globals().get('SPEC', 'packaging/Server.spec')).resolve()
SPEC_DIR = SPEC_PATH.parent
PROJECT_ROOT = SPEC_DIR.parent

a = Analysis(
    [str(PROJECT_ROOT / 'NetworkRender' / 'server' / 'server.py')],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=[
        (str(PROJECT_ROOT / 'NetworkRender' / 'server' / 'server_dashboard.py'),   'NetworkRender\\server'),
        (str(PROJECT_ROOT / 'NetworkRender' / 'server' / 'server_dashboard.html'), 'NetworkRender\\server'),
        (str(PROJECT_ROOT / 'NetworkRender' / 'server' / 'server_dashboard.css'),  'NetworkRender\\server'),
        (str(PROJECT_ROOT / 'NetworkRender' / 'server' / 'server_dashboard.js'),   'NetworkRender\\server'),
        (str(PROJECT_ROOT / 'NetworkRender' / 'shared'), 'NetworkRender\\shared'),
    ],
    # The desktop dashboard is the web UI wrapped in pywebview (Edge WebView2 on
    # Windows). pywebview ships its own PyInstaller hook, but we pin the Windows
    # backend explicitly so the frozen build doesn't miss it.
    hiddenimports=['webview', 'webview.platforms.winforms'],
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
    name='Server',
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
    name='Server',
)

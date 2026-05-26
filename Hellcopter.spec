# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['E:\\world\\python\\chess\\uci_engine.py'],
    pathex=[],
    binaries=[],
    datas=[('E:\\world\\python\\chess\\engine_core.dll', '.'), ('E:\\world\\python\\chess\\opening_book.json', '.')],
    hiddenimports=['chess', 'engine', 'engine_wrapper'],
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
    a.binaries,
    a.datas,
    [],
    name='Hellcopter',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# -*- mode: python ; coding: utf-8 -*-
import os

data_files = [('resource', 'resource')]
if os.path.exists('version.txt'):
    data_files.append(('version.txt', '.'))

a = Analysis(
    ['main_window.py'],
    pathex=[],
    binaries=[],
    datas=data_files,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

splash = Splash(
    'resource\\splash.png',
    binaries=a.binaries,
    datas=a.datas,
    text_pos=(30,75),
    text_size=12,
    minify_script=True,
    always_on_top=False,
)

exe = EXE(
    pyz,
    a.scripts,
    [],
    splash,
    splash.binaries,
    exclude_binaries=True,
    name='NeoSSH',
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
    icon=['resource\\icons\\icon.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='NeoSSH',
)
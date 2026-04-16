# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Coe College Academic Advising Tool — Windows build
# Build with:   pyinstaller advisor_windows.spec --clean --noconfirm
#
# Uses onedir mode (not onefile) to reduce antivirus false positives.
# The onefile self-extractor pattern triggers SmartScreen / heuristic scanners.
# The CI workflow zips the output directory for distribution.

import os
from pathlib import Path
import customtkinter

HERE = Path(SPECPATH)

block_cipher = None

a = Analysis(
    [str(HERE / 'advisor.py')],
    pathex=[str(HERE)],
    binaries=[],
    datas=[
        (str(HERE / 'data'), 'data'),
        (Path(customtkinter.__file__).parent, 'customtkinter'),
    ],
    hiddenimports=[
        'tkinter',
        'tkinter.ttk',
        'tkinter.messagebox',
        'tkinter.filedialog',
        'customtkinter',
        'advisor_core',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib', 'numpy', 'scipy', 'pandas',
        'PIL', 'cv2', 'PyQt5', 'PyQt6', 'wx',
        'unittest', 'test', 'xmlrpc', 'pydoc',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='CoeAdvisor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=str(HERE / 'version_info.txt'),
    # UAC manifest: request no elevation (asInvoker) to signal
    # to SmartScreen that this is a normal user-mode app.
    uac_admin=False,
    uac_uiaccess=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='CoeAdvisor',
)

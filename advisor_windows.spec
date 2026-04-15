# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Coe College Academic Advising Tool — Windows build
# Build with:   pyinstaller advisor_windows.spec

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
        # Bundle the entire data/ tree so JSON and CSV files are available at runtime
        (str(HERE / 'data'), 'data'),
        # CustomTkinter assets (themes, images) must travel with the app
        (Path(customtkinter.__file__).parent, 'customtkinter'),
    ],
    hiddenimports=[
        'tkinter',
        'tkinter.ttk',
        'tkinter.messagebox',
        'tkinter.filedialog',
        'customtkinter',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib', 'numpy', 'scipy', 'pandas',
        'PIL', 'cv2', 'PyQt5', 'PyQt6', 'wx',
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
    a.binaries,   # included here (not in COLLECT) → onefile mode
    a.datas,      # ditto
    [],
    name='CoeAdvisor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,        # no terminal window; GUI-only
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # No COLLECT step → PyInstaller bundles everything into a single CoeAdvisor.exe
)

# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Coe College Academic Advising Tool
# Build with:   pyinstaller advisor.spec

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
    [],
    exclude_binaries=True,
    name='CoeAdvisor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,        # no terminal window; GUI-only
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
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

app = BUNDLE(
    coll,
    name='CoeAdvisor.app',
    icon=None,
    bundle_identifier='edu.coe.advising-tool',
    info_plist={
        'CFBundleName':             'Coe Advising Tool',
        'CFBundleDisplayName':      'Coe Advising Tool',
        'CFBundleShortVersionString': '1.2.0',
        'CFBundleVersion':          '1.2.0',
        'NSHighResolutionCapable':  True,
        'LSMinimumSystemVersion':   '10.13.0',
        'NSHumanReadableCopyright': '© Coe College',
        'LSApplicationCategoryType': 'public.app-category.education',
        'NSSupportsAutomaticGraphicsSwitching': True,
    },
)

# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

block_cipher = None
project_root = Path(SPECPATH)
icon_file = project_root / "assets" / "icons" / "barq.ico"

a = Analysis(
    ['barq_app.py'],
    pathex=[str(project_root)],
    binaries=[],
    datas=[
        ('src', 'src'),
        ('browser_integration', 'browser_integration'),
        (str(project_root / 'assets' / 'icons' / 'barq.ico'), 'assets/icons'),
        (str(project_root / 'assets' / 'icons' / 'barq_256.png'), 'assets/icons'),
        ('logo.png', '.'),
    ],
    hiddenimports=[
        'aiohttp',
        'asyncio',
        'PyQt6',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',
        'PyQt6.QtNetwork',
        'pyqtgraph',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='Barq',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # Embed Windows PE icon
    icon=str(icon_file),
)

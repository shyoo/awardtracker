# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

# Include necessary static files, templates, migrations, default valuations, and dynamic plugins
added_files = [
    ('templates', 'templates'),
    ('static', 'static'),
    ('migrations', 'migrations'),
    ('plugins', 'plugins'),
    ('valuations.json', '.'),
    ('settings.json', '.'),
]

a = Analysis(
    ['tray.py'],
    pathex=[],
    binaries=[],
    datas=added_files,
    hiddenimports=[
        'sqlalchemy',
        'flask_sqlalchemy',
        'flask_migrate',
        'cryptography',
        'apscheduler',
        'seleniumbase',
        'pystray',
        'PIL',
        'PIL.Image',
        'PIL.ImageDraw',
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
    name='awardtracker',
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
    icon=None,
)

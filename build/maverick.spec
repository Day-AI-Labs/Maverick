# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

# Bundle the .dist-info metadata so `maverick version` can read the
# installed package versions from inside the frozen binary.
_datas = collect_data_files('maverick_dashboard')
for _dist in (
    'maverick-agent', 'maverick-shield', 'maverick-channels',
    'maverick-dashboard', 'maverick-mcp-server', 'maverick-installer',
):
    try:
        _datas += copy_metadata(_dist)
    except Exception:
        pass  # not every dist is installed in every build env

a = Analysis(
    ['pyinstaller_entry.py'],
    pathex=[],
    binaries=[],
    datas=_datas,
    hiddenimports=[
        'sqlite3',
        '_sqlite3',
        'sqlite3.dbapi2',
        'hashlib',
        'hmac',
        'base64',
        'secrets',
        'tomllib',
        'email.mime.base',
        'email.mime.multipart',
        'email.mime.nonmultipart',
        'email.mime.text',
        'asyncio.events',
        'asyncio.queues',
        'asyncio.subprocess',
        'multipart',
    ] + collect_submodules('maverick')
      # The maverick_* siblings are separate top-level packages imported only
      # inside function bodies (cli.py: `from maverick_dashboard...`), which
      # PyInstaller's static analysis doesn't follow -- so collect_submodules('maverick')
      # alone shipped a binary where `maverick dashboard/mcp` failed at runtime.
      + collect_submodules('maverick_dashboard')
      + collect_submodules('maverick_mcp')
      + collect_submodules('maverick_channels')
      + collect_submodules('maverick_shield')
      + collect_submodules('maverick_installer'),
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
    name='maverick',
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

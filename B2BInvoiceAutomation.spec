# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_submodules


block_cipher = None

hiddenimports = (
    collect_submodules("b2bdoc")
    + collect_submodules("keyring.backends")
    + collect_submodules("win32ctypes")
    + [
        "googleapiclient.discovery",
        "google_auth_oauthlib.flow",
        "google_auth_httplib2",
        "httplib2",
        "PIL._tkinter_finder",
        "socketserver",
        "http.server",
        "email.mime",
        "email.mime.multipart",
        "email.mime.text",
        "email.mime.base",
        "base64",
        "uuid",
    ]
)

a = Analysis(
    ["packaging/desktop_launcher.py"],
    pathex=["src"],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "streamlit",
        "pytest",
        "tests",
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
    name="B2B Invoice Automation",
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
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="B2B Invoice Automation",
)

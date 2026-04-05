# -*- mode: python ; coding: utf-8 -*-
# Только exe: pyinstaller --noconfirm --clean LocalMusicBot.spec  →  dist/LMB.exe
# exe + zip (папка Local_Music_Bot_<APP_VERSION>/LMB.exe):  python build_release.py
# libopus подхватывается с диска из установленного discord.

from pathlib import Path

import discord
from PyInstaller.utils.hooks import collect_all

block_cipher = None

_root = Path(discord.__file__).resolve().parent
_bin = _root / "bin"
_discord_opus_datas = []
if _bin.is_dir():
    for _dll in sorted(_bin.glob("libopus-0.*.dll")):
        _discord_opus_datas.append((str(_dll), "discord/bin"))
if not _discord_opus_datas:
    raise RuntimeError(
        "Не найдены libopus-0.*.dll в discord/bin. Установите зависимости: pip install -r requirements.txt"
    )

_qd, _qb, _qh = collect_all("PyQt6")

a = Analysis(
    ["Local_Music_Bot.pyw"],
    pathex=[],
    binaries=list(_qb),
    datas=[("icon.ico", ".")] + list(_qd) + _discord_opus_datas,
    hiddenimports=[
        "discord.ext.commands",
        "discord.app_commands",
        "aiohttp",
        "aiohttp.web",
        "mutagen",
        "taglib",
        "nacl",
        "nacl.bindings",
        "_cffi_backend",
    ]
    + list(_qh),
    hookspath=["."],
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
    name="LMB",
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
    icon=["icon.ico"],
)

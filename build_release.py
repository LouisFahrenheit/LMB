#!/usr/bin/env python3
"""
Сборка релиза: PyInstaller (LocalMusicBot.spec) → dist/LMB.exe → архив
dist/Local_Music_Bot_<APP_VERSION>.zip с содержимым Local_Music_Bot_<версия>/LMB.exe.

Версия берётся из Local_Music_Bot.pyw (строка APP_VERSION = "...").

GitHub Actions дублирует эту логику в .github/workflows/release.yml (скрипт в репозиторий не обязателен для CI).

  python build_release.py

Только exe без zip:
  pyinstaller --noconfirm --clean LocalMusicBot.spec
"""
from __future__ import annotations

import re
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PYW = ROOT / "Local_Music_Bot.pyw"
SPEC = ROOT / "LocalMusicBot.spec"


def read_app_version() -> str:
    text = PYW.read_text(encoding="utf-8")
    m = re.search(r'^APP_VERSION\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)
    if not m:
        raise RuntimeError(f"Не найден APP_VERSION в {PYW.name}")
    v = m.group(1).strip()
    if not v:
        raise RuntimeError("APP_VERSION пустой")
    # имя папки в zip: без символов, недопустимых в Windows
    safe = re.sub(r'[<>:"/\\|?*]', "_", v)
    return safe


def main() -> int:
    if not SPEC.is_file():
        print(f"Нет файла {SPEC}", file=sys.stderr)
        return 1
    version = read_app_version()
    folder = f"Local_Music_Bot_{version}"

    subprocess.check_call(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", str(SPEC)],
        cwd=ROOT,
    )

    exe = ROOT / "dist" / "LMB.exe"
    if not exe.is_file():
        print(f"Не найден {exe}", file=sys.stderr)
        return 1

    dist_dir = ROOT / "dist"
    zip_path = dist_dir / f"{folder}.zip"
    if zip_path.is_file():
        zip_path.unlink()

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(exe, arcname=f"{folder}/LMB.exe")

    print(f"OK: {exe}")
    print(f"OK: {zip_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

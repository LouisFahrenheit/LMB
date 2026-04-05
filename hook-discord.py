# PyInstaller: discord кладёт libopus в discord/bin/*.dll — без этого в EXE будет OpusNotLoaded.
# Сборка: pyinstaller ... --additional-hooks-dir "папка_с_этим_файлом"
from PyInstaller.utils.hooks import collect_data_files

datas = collect_data_files("discord")

import sys
import os
import shutil
import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import random
import datetime
import json
import traceback
import re
import logging
from logging.handlers import RotatingFileHandler
import taglib
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QGridLayout, QPushButton, QTextEdit, QTextBrowser, QTabWidget, 
                             QListWidget, QLabel, QLineEdit, QGroupBox, 
                             QCheckBox, QFileDialog, QMessageBox,
                             QComboBox, QSlider, QFrame, QSplitter, QProgressBar,
                             QListWidgetItem, QMenu, QDialog, QDialogButtonBox,
                             QFormLayout, QScrollArea, QWidgetAction, QSizePolicy,
                             QSystemTrayIcon)
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QTimer, QPropertyAnimation, QEasingCurve, QPoint, QSize
from PyQt6.QtGui import QFont, QFontMetrics, QTextCursor, QPixmap, QPainter, QColor, QLinearGradient, QBrush, QPen, QAction, QIcon
from PyQt6.QtCore import QByteArray
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtCore import QUrl
from io import BytesIO
from typing import Optional

CONFIG_FILE = "bot_settings.json"
APP_VERSION = "1.0"

LOG_FILE_NAME = "local_music_bot.log"
LOG_MAX_BYTES = 2 * 1024 * 1024
LOG_BACKUP_COUNT = 5
_file_logging_initialized = False


def resource_path(relative_name):
    """Возвращает путь к файлу рядом с .exe (после сборки) или рядом со скриптом (при запуске из исходников)."""
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, relative_name)


def ensure_app_file_logging():
    """Один раз настраивает RotatingFileHandler рядом с exe/скриптом."""
    global _file_logging_initialized
    logger = logging.getLogger("LocalMusicBot")
    if _file_logging_initialized:
        return logger
    _file_logging_initialized = True
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    try:
        path = resource_path(LOG_FILE_NAME)
        fh = RotatingFileHandler(
            path, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding="utf-8"
        )
        fh.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
        )
        logger.addHandler(fh)
    except Exception:
        pass
    return logger


def find_ffmpeg() -> str:
    import shutil

    candidates = []

    # ── 1. ffmpeg-static через Node / npm ────────────────────────────────
    # npm install ffmpeg-static кладёт бинарник в node_modules/ffmpeg-static/
    script_dir = resource_path("")
    for rel in [
        os.path.join("node_modules", "ffmpeg-static", "ffmpeg.exe"),
        os.path.join("node_modules", "ffmpeg-static", "ffmpeg"),
        os.path.join("..", "node_modules", "ffmpeg-static", "ffmpeg.exe"),
        os.path.join("..", "node_modules", "ffmpeg-static", "ffmpeg"),
    ]:
        candidates.append(os.path.normpath(os.path.join(script_dir, rel)))

    try:
        import subprocess
        result = subprocess.run(
            ["node", "-e", "process.stdout.write(require('ffmpeg-static'))"],
            capture_output=True, text=True, timeout=3
        )
        if result.returncode == 0 and result.stdout.strip():
            node_path = result.stdout.strip()
            if os.path.isfile(node_path):
                return node_path
    except Exception:
        pass

    for name in ["ffmpeg.exe", "ffmpeg"]:
        candidates.append(resource_path(name))

    for path in candidates:
        if os.path.isfile(path):
            return path

    found = shutil.which("ffmpeg")
    if found:
        return found

    return "ffmpeg"


def set_taskbar_icon(icon_path):
    if sys.platform != 'win32':
        return
    try:
        import ctypes
        import ctypes.wintypes

        # Уникальный App User Model ID — Windows группирует кнопки taskbar по нему
        app_id = "LocalMusicBot.App.1.0"
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)

        if not os.path.isfile(icon_path):
            return

        import tempfile
        from PyQt6.QtGui import QIcon, QPixmap

        pixmap = QPixmap(icon_path)
        if pixmap.isNull():
            return

        tmp = tempfile.NamedTemporaryFile(suffix='.ico', delete=False)
        tmp_path = tmp.name
        tmp.close()
        pixmap.save(tmp_path, 'ICO')

        # Константы WinAPI
        IMAGE_ICON   = 1
        LR_LOADFROMFILE = 0x00000010
        LR_DEFAULTSIZE  = 0x00000040
        ICON_SMALL  = 0
        ICON_BIG    = 1
        WM_SETICON  = 0x0080
        GWL_STYLE   = -16
        WS_EX_APPWINDOW = 0x00040000

        hicon_big = ctypes.windll.user32.LoadImageW(
            None, tmp_path, IMAGE_ICON,
            256, 256, LR_LOADFROMFILE
        )
        hicon_small = ctypes.windll.user32.LoadImageW(
            None, tmp_path, IMAGE_ICON,
            16, 16, LR_LOADFROMFILE
        )

        try:
            os.unlink(tmp_path)
        except Exception:
            pass

        return (hicon_big, hicon_small)
    except Exception:
        return None


def apply_taskbar_icon(hwnd, icons):
    if sys.platform != 'win32' or not icons:
        return
    try:
        import ctypes
        WM_SETICON = 0x0080
        ICON_SMALL = 0
        ICON_BIG   = 1
        hicon_big, hicon_small = icons
        if hicon_big:
            ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG,   hicon_big)
        if hicon_small:
            ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon_small)
    except Exception:
        pass


def _compact_settings_combo(combo, min_w=0, max_w=0):
    combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
    combo.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
    if min_w:
        combo.setMinimumWidth(min_w)
    if max_w:
        combo.setMaximumWidth(max_w)


class Translator:
    def __init__(self, language='en'):
        self.language = language
        self.translations = {
            'ru': {
                # Основные элементы интерфейса
                'window_title': "Local Music Bot",
                'not_playing': "",
                'now_playing': "",
                'no_cover': "",
                'time_elapsed': "Прошло",
                'time_total': "Всего",
                'bot_running': "Запущен",
                'bot_stopped_status': "Остановлен",
                
                # Кнопки управления
                'start': "СТАРТ",
                'stop': "СТОП",
                'pause': "ПАУЗА",
                'resume': "ПРОДОЛЖИТЬ",
                'skip': "ПРОПУСТИТЬ",
                'clear_queue': "ОЧИСТИТЬ ОЧЕРЕДЬ",
                'refresh': "Обновить",
                'browse': "Обзор",
                'clear_errors': "Очистить ошибки",
                
                # Группы и вкладки
                'playback_control': "Управление воспроизведением",
                'events': "События",
                'now_playing_group': "Сейчас играет",
                'music_tab': "Музыка",
                'settings_tab': "Настройки",
                'info_tab': "Инфо",
                'errors_tab': "Ошибки",
                
                # Поиск и статистика
                'search': "Поиск:",
                'search_placeholder': "Введите название...",
                'total_files': "Всего файлов: {}",
                
                # Настройки
                'settings_group': "Настройки",
                'settings_cat_interface': "Интерфейс",
                'settings_cat_discord': "Discord",
                'settings_cat_library': "Плеер",
                'settings_cat_playback': "Воспроизведение",
                'settings_cat_appearance': "Оформление",
                'settings_cat_ui_web': "Интерфейс",
                'bot_token': "Токен бота:",
                'music_folder': "Папка с музыкой:",
                'music_folder_open_tooltip': "Нажмите, чтобы открыть папку в проводнике",
                'ffmpeg_open_tooltip': "Нажмите, чтобы открыть папку с FFmpeg",
                'wallpaper_open_tooltip': "Нажмите, чтобы открыть папку с файлом обоев",
                'ffmpeg_open_failed': "Не удалось найти FFmpeg по этому пути или в PATH",
                'folder_not_selected': "Папка не выбрана",
                'folder_not_found': "Папка не найдена",
                'found_files': "Найдено {} файлов",
                'ffmpeg': "FFmpeg:",
                'volume': "Громкость:",
                'enable_autoplay': "Включить автоплейлист",
                'autoplay_mode': "Режим автоплейлиста:",
                'shuffle': "Перемешивание",
                'sequential': "По порядку",
                'language': "Язык / Language:",
                'autostart': "Автостарт при запуске программы",
                'show_album_art': "Показывать обложки альбомов",
                'enable_wallpaper': "Включить обои",
                'wallpaper_file': "Файл обоев:",
                
                # Ролевая защита
                'role_protection': "Ролевая защита",
                'enable_role_protection': "Включить защиту по ролям",
                'control_role': "Роль управления (play/pause/etc):",
                'admin_role': "Админ роль (stop/delete):",
                'no_permission': "❌ У вас нет прав на использование этой команды!",
                'invalid_role_id': "ID роли должен быть числом!",
                
                # Сообщения об ошибках и предупреждения
                'error': "Ошибка",
                'warning': "Предупреждение",
                'enter_token': "Введите токен!",
                'select_folder': "Укажите существующую папку с музыкой!",
                'bot_not_running': "Бот не запущен!",
                'track_not_found': "Не удалось найти файл трека!",
                'initializing': "</> Инициализация...",
                'bot_stopped': "🛑 Бот остановлен",
                'pause_from_gui': "Пауза",
                'resumed_from_gui': "Продолжено",
                'volume_changed': "🔊 Громкость {}%",
                'autostart_enabled': "Автостарт...",
                'autostart_failed': "❌ Не удалось запустить бот при автостарте: {}",
                
                # Discord сообщения
                'not_in_voice': "❌ Вы не в голосовом канале!",
                'file_not_found': "❌ Файл не найден: {}",
                'playback_error': "❌ Ошибка воспроизведения",
                'now_playing_discord': "▶️ {}",
                'paused_discord': "⏸️ Пауза",
                'resumed_discord': "▶️ Продолжить",
                'skipping': "⏭️ {}",
                'playback_stopped': "Воспроизведение остановлено",
                'nothing_playing': "❌ Сейчас ничего не играет",
                'stopped_and_cleared': "⏹️ Остановлено и очереди очищены",
                'queue_empty': "Очередь пуста",
                'queue_cleared': "🧹 Очередь очищена (удалено: {} песен)",
                'current_volume': "🔊 Текущая громкость: **{}%**",
                'volume_changed_discord': "🔊 Громкость изменена с **{}%** на **{}%**",
                'volume_set': "🔊 Громкость установлена на **{}%**",
                'volume_range': "❌ Громкость должна быть от **0** до **100**",
                'autoplay_enabled': "♪ Автоплейлист **включен**",
                'autoplay_disabled': "♪ Автоплейлист **выключен**",
                'shuffle_mode': "🎲 Режим автоплейлиста: **Перемешивание**",
                'sequential_mode': "📋 Режим автоплейлиста: **По порядку**",
                
                # Очередь воспроизведения
                'queue_header': "**📋 Очередь воспроизведения:**",
                'now_header': "**▶️ Сейчас:**",
                'user_queue_header': "**👤 Заказ ({}):**",
                'auto_queue_header': "**♪ Автоплейлист ({}):**",
                'and_more': "...и еще {}",
                'track_added': "➕ **{}** добавлен в очередь",
                'track_added_next': "➕ **{}** будет следующим!",
                'track_play_now': "⏯️ **{}** играет сейчас!",
                
                # Поиск и выбор треков
                'search_results': "**Найденные треки:**",
                'enter_number': "📝 Введите номер (или 'отмена'):",
                'cancelled': "❌ Отменено",
                'invalid_number': "❌ Неверный номер",
                'timeout': "⏰ Время вышло",
                'no_tracks': "❌ Нет доступных треков!",
                'tracks_not_found': "❌ Треки с '{}' не найдены",
                'folder_not_specified': "❌ Папка с музыкой не указана!",
                
                # Команды (help)
                'help_title': "**♪ Команды музыкального бота**",
                'help_intro': "Играет **ваши локальные файлы** с папки из настроек. Перед `!play` зайдите в **голосовой канал**.",
                'help_main': "**Основные:**",
                'help_queue': "**Очередь:**",
                'help_settings': "**Воспроизведение:**",
                'help_footer': "**Портал:** https://discord.com/developers/home → своё приложение.\n**OAuth2** → **URL Generator:** сначала в **Scopes** — `bot` и `applications.commands`; **ниже на этой же странице** появится **Bot Permissions** — отметьте:\n**General:** View Channels\n**Text:** Send Messages, Embed Links, Read Message History, Use Slash Commands\n**Voice:** Connect, Speak, Use Voice Activity\nВнизу скопируйте ссылку и пригласите бота.\n**Bot** (вкладка приложения) → **Privileged Gateway Intents** → включите **Message Content Intent** (иначе не работают команды `!`).\n**Роли:** при защите в приложении — роль управления и админ для stop/delete.\n**GitHub:** https://github.com/LouisFahrenheit/LMB",
                'help_alias_or': "или",
                'help_plus_query': "+ текст",
                'cmd_play_random': "`!play` / `!p` — случайный трек",
                'cmd_play_search': "`!play` + фрагмент названия — поиск",
                'cmd_playnext': "`!playnext текст` - Добавить трек вперед очереди",
                'cmd_skip': "`!skip` - Пропустить текущий трек",
                'cmd_stop': "`!stop` - Остановить и выйти",
                'cmd_pause': "`!pause` - Пауза",
                'cmd_resume': "`!resume` - Продолжить",
                'cmd_queue': "`!queue` - Показать очередь",
                'cmd_current': "`!current` - Информация о текущем треке",
                'cmd_clear': "`!clear` - Очистить очередь",
                'cmd_volume': "`!volume [0-100]` - Показать/установить громкость",
                'cmd_shuffle': "`!shuffle` - Режим перемешивания для автоплейлиста",
                'cmd_sequential': "`!sequential` - Последовательный режим для автоплейлиста",
                'cmd_autoplay': "`!autoplay` - Вкл/Выкл Автоплейлист",
                'cmd_help': "`!help` - Показать это сообщение",
                'cmd_delete': "`!delete` - Удалить текущий трек",
                'help_shorts': "**Коротко:** `!p` play, `!s`/`!n` skip, `!pn` playnext, `!q` queue, `!c`/`!np` current, `!v` volume, `!ap` autoplay, `!del` delete",
                'help_slash': "**Слэш-команды:** те же действия через `/play`, `/skip`, `/stop`, … — полный список в подсказках Discord.",
                'pick_track_placeholder': "Выберите трек…",
                'slash_pick_track_prompt': "**Несколько совпадений** — выберите трек в списке ниже.",
                'slash_playnext_need_query': "❌ Укажите фрагмент названия трека.",
                'delete_button_confirm': "Удалить навсегда",
                'delete_button_cancel': "Отмена",
                'log_slash_synced': "✔️ Slash-команды синхронизированы: {}",
                'log_slash_sync_fail': "❌ Ошибка синхронизации slash-команд: {}",
                'slash_user_error': "❌ Ошибка команды. Подробности в логе приложения.",
                
                # Команда удаления
                'delete_confirm': "⚠️ Вы уверены, что хотите удалить **{}**? Это действие необратимо! (да/нет)",
                'delete_cancelled': "❌ Удаление отменено",
                'delete_timeout': "⏰ Время подтверждения истекло",
                'delete_success': "✅ Файл **{}** успешно удален",
                'delete_error': "❌ Ошибка при удалении файла: {}",
                'delete_file_not_found': "❌ Файл не найден на диске",
                'delete_current': "🗑️ Удаление текущего трека...",
                
                # Логи и статусы
                'bot_not_active': '⚠️ Бот не активен или нет активной гильдии',
                'guild_not_found': '⚠️ Гильдия не найдена',
                'nothing_playing_log': '⚠️ Ничего не играет',
                'error_pausing': '❌ Ошибка при паузе: {}',
                'not_paused': '⚠️ Не на паузе',
                'error_resuming': '❌ Ошибка при продолжении: {}',
                'no_context_skip': '⚠️ Нет контекста для пропуска',
                'error_skipping': '❌ Ошибка при пропуске: {}',
                'no_context_clear': '⚠️ Нет контекста для очистки очереди',
                'error_clearing': '❌ Ошибка при очистке очереди: {}',
                'bot_not_active_volume': '⚠️ Бот не активен, громкость будет применена при следующем запуске',
                'volume_channel': '🔊 Громкость изменена на {}% в канале {}',
                'volume_updated_channels': '🔊 Обновлена громкость в {} голосовых каналах',
                'volume_no_connections': '🔊 Громкость {}% (нет активных соединений)',
                'error_updating_volume': '❌ Ошибка при изменении громкости: {}',
                'bot_not_active_track': '⚠️ Бот не активен, трек не может быть добавлен',
                'track_added_queue': '➕ [{} в очереди] {} добавлен',
                'track_playing_gui': '▶️ Играет {} в {} (запрос из GUI)',
                'no_context_playback': '⚠️ Нет контекста для воспроизведения в {}',
                'no_voice_connections': 'Нет активных голосовых каналов',
                'error_adding_track': '❌ Ошибка при добавлении трека из GUI: {}',
                'error_scanning_folder': 'Ошибка при сканировании папки: {}',
                'track_added_auto': '➕ [{}] {} (автоплейлист)',
                'skipping_auto': '⏭️ Пропускаем авто {} - есть пользовательские треки в очереди',
                'file_not_found_log': '❌ Файл не найден: {}',
                'playback_error_log': '❌ Ошибка воспроизведения: {}',
                'context_not_found': '❌ Контекст не найден для гильдии {}',
                'stop_command_issued': '⏹️ Команда stop - пропускаем автоплейлист',
                'no_tracks_autoplay': '📭 Нет треков для автоплейлиста',
                'playback_finished': '⏹️ Воспроизведение завершено',
                'queue_status': ' | Очередь: {} польз. + {} авто',
                'playing': '▶️ Играет: {} {}',
                'skipping_log': '⏭️ Пропускаю: {}',
                'stopped_and_cleared_log': '⏹️ Остановлено и очереди очищены',
                'queue_cleared_log': '🧹 Очередь очищена (удалено: {} песен)',
                'volume_updated_all': '🔊 Обновлена громкость во всех {} активных каналах',
                'error_updating_all_volume': '❌ Ошибка при обновлении громкости во всех каналах: {}',
                'bot_ready': '✔️ Бот: {}',
                'music_folder_log': '✔️ Папка с музыкой: {}',
                'volume_log': '✔️ Громкость: {}%',
                'found_files_log': 'Добавлено {} файла',
                'selecting_random': '🎲 Выбираем случайный трек',
                'random_added_queue': '➕ Случайный трек добавлен в очередь: {}',
                'track_added_queue_log': '➕ Трек добавлен в очередь: {}',
                'track_added_next_log': '➕ Трек добавлен следующим: {}',
                'volume_changed_track': '🔊 Громкость изменена на {}% (текущий трек)',
                'volume_set_next': '🔊 Громкость установлена на {}% (для следующих треков)',
                'paused_log': '⏸️ Пауза',
                'resumed_log': '▶️ Продолжено',
                'shuffle_mode_log': '🎲 Режим автоплейлиста изменен на Перемешивание',
                'sequential_mode_log': '📋 Режим автоплейлиста изменен на По порядку',
                'auto_mode_log': "✔️ Автоплейлист - {}",
                'autoplay_enabled_log': '♪ Автоплейлист включен',
                'autoplay_disabled_log': '♪ Автоплейлист выключен',
                'token_not_specified': '❌ Токен не указан!',
                'starting_bot': 'Запуск бота...',
                'start_error': '❌ Ошибка запуска: {}',
                'critical_error': '❌ Критическая ошибка: {}',
                'stopping_bot': 'Остановка бота...',
                'stopped': 'Остановлено',
                
                # Информационная вкладка
                'how_to_use': "Быстрый старт",
                'first_step': "Настроить программу",
                'first_step_desc': "Вкладка <b>«Настройки»</b>: вставьте <b>токен бота</b> (берётся в Discord Developer Portal) и выберите <b>папку с музыкой</b> на этом компьютере. По желанию задайте автоподключение к каналам и роли (см. блок про роли ниже).",
                'second_step': "Запустить бота",
                'second_step_desc': "Нажмите <b>СТАРТ</b>. Дождитесь сообщения в логе, что бот в сети — только после этого команды на сервере начнут обрабатываться.",
                'third_step': "Запустить музыку в Discord",
                'third_step_desc': "На сервере зайдите в <b>голосовой канал</b>. В текстовом чате: <code>!play</code> или <code>/play</code> — случайный трек; то же с текстом после команды — поиск по имени файла. Либо во вкладке <b>«Музыка»</b> дважды щёлкните по треку — он добавится в очередь.",
                'fourth_step': "Дальнейшее управление",
                'fourth_step_desc': "Используйте кнопки в этом окне или команды в Discord. Справка в чате: <code>!help</code> или <code>/help</code>.",
                'info_where_title': "Где взять бота",
                'info_where_body': "Исходный код и релизы: <a href='https://github.com/LouisFahrenheit/LMB'>github.com/LouisFahrenheit/LMB</a>. Это десктопное приложение: вы запускаете его у себя и подключаете своего бота.",
                'info_perms_title': "Настроить бота в Discord",
                'info_perms_step1': "Откройте <a href='https://discord.com/developers/home'>Discord Developer Portal</a> и выберите приложение (или создайте новое).",
                'info_perms_step2': "<b>OAuth2</b> → <b>URL Generator</b>: в блоке <b>Scopes</b> отметьте <code>bot</code> и <code>applications.commands</code>.",
                'info_perms_step3': "Ниже на <b>этой же странице</b> появится <b>Bot Permissions</b> — в колонках General, Text, Voice отметьте пункты из списка ниже, затем скопируйте ссылку внизу страницы и пригласите бота.",
                'info_perms_step4': "Отдельно: В <b>Bot</b> → <b>Privileged Gateway Intents</b> → включите <b>Message Content Intent</b>.",
                'info_perms_col_general': "General — общие",
                'info_perms_col_text': "Text — текстовый чат",
                'info_perms_col_voice': "Voice — голос",
                'info_perm_view_channels': "доступ к каналам сервера",
                'info_perm_send_messages': "ответы бота в чат",
                'info_perm_embed_links': "встроенные блоки в ответах",
                'info_perm_read_history': "чтение истории (команды с !)",
                'info_perm_slash': "слэш-команды (/play, /help, …)",
                'info_perm_connect': "вход в голосовой канал",
                'info_perm_speak': "воспроизведение музыки",
                'info_perm_voice_activity': "передача звука (Use Voice Activity)",
                'info_roles_title': "Кто может использовать команды (роли)",
                'info_roles_body': "<b>«Настройки»</b> → Discord → <b>«Включить защиту по ролям»</b> и два поля для ID ролей.<br><br><b>Если защита выключена</b> — пользоваться ботом в чате может любой участник сервера (как обычно в Discord).<br><br><b>Если защита включена</b> — команды смогут вызывать только те, у кого есть нужная роль. Нужно указать два ID:<ul style='margin:8px 0; padding-left:20px;'><li style='margin:6px 0;'><b>Роль управления</b> — воспроизведение и очередь: play, pause, resume, skip, очередь, громкость, автоплей, shuffle и всё подобное.</li><li style='margin:6px 0;'><b>Админ-роль</b> — «опасные» действия: полная остановка (<code>!stop</code> / <code>/stop</code>) и <b>удаление текущего файла с диска</b> (<code>!delete</code> / <code>/delete</code>).</li></ul><b>Как узнать ID роли:</b> в Discord включите режим разработчика → правый клик по роли на сервере → «Копировать идентификатор роли».",
                'commands_title': "Все команды и сокращения",
                'formats_title': "Форматы файлов",
                'version': "Версия",
                'github': "GitHub",
                'info_title': "Discord Local Music Bot",
                'info_commands_intro_title': "Как вызывать команды",
                'info_commands_intro_body': "Работают <b>слэш-команды</b> (введите <code>/</code> в чате сервера — например <code>/play</code>, <code>/help</code>) и команды с <b>префиксом</b> <code>!</code> (например <code>!play</code>, <code>!p</code>). Это одни и те же действия, выберите удобный способ. Перед <code>!play</code> или <code>/play</code> зайдите в голосовой канал; текст после команды — поиск трека по имени файла.",
                'info_cmd_table_col_slash': "Слэш",
                'info_cmd_table_col_exclam': "! и сокращения",
                'info_delete_track_short': "Удалить текущий трек с диска (только админ-роль)",
                'info_cmd_help_desc': "Показать список команд в чате",
                'info_first_request': "Первый запрос должен быть от пользователя, находящегося в голосовом канале.",
                'info_control': "Управление доступно из чата дискорда и непосредственно в этом окне.",
                'info_double_click': "Двойной клик по треку во вкладке \"Музыка\" добавляет его в очередь.",
                'info_commands': "Команды:",
                'info_command': "Команда",
                'info_description_col': "Описание",
                'info_random_track': "Случайный трек",
                'info_search_track': "Поиск трека",
                'info_add_next': "Добавить трек следующим после текущего",
                'info_skip': "Пропустить текущий",
                'info_stop': "Остановить и отключиться",
                'info_pause': "Пауза",
                'info_resume': "Продолжить",
                'info_show_queue': "Показать очередь",
                'info_current_track': "Информация о текущем треке",
                'info_clear_queue': "Очистить очередь",
                'info_volume': "Громкость (0-100)",
                'info_shuffle_mode': "Режим перемешивания для автоплейлиста",
                'info_sequential_mode': "Последовательный режим для автоплейлиста",
                'info_toggle_autoplay': "Вкл/Выкл автоплейлист",
                'info_formats': "Форматы:",
                'info_formats_list': "MP3, FLAC, M4A, WAV, OGG, AAC, MP4",
                
                # Диалоги подтверждения
                'confirm_close_title': "Подтверждение закрытия",
                'confirm_close_message': "Бот все еще запущен. Вы уверены, что хотите закрыть программу?",
                'yes': "Да",
                'no': "Нет",
                
                # Статусы и индикаторы
                'autoplay_status': "Авто",
                
                # Настройки каналов
                'default_channel': "Канал по умолчанию",
                'enable_auto_connect': "Автоподключение к каналу при старте",
                'select_server': "Выберите сервер:",
                'select_voice_channel': "Выберите голосовой канал:",
                'select_text_channel': "Выберите текстовый канал:",
                'refresh_channels': "Обновить",
                'no_voice_channels': "❌ На сервере нет голосовых каналов",
                'connected_to_channel': "✔️ Подключён к {} в {}",
                'discord_connected_to_channel': "✅ Подключён к голосовому каналу",
                'failed_connect_channel': "❌ Не удалось подключиться к каналу: {}",
                'select_server_and_channel': "Выберите сервер, голосовой и текстовый каналы для автоподключения",
                'channel_saved': "✔️ {}",
                'server_not_found': "⚠️ Сервер с ID {} не найден",
                'selected_channel_not_found': "Выбранный канал не найден",
                'channel_not_voice': "⚠️ Указанный канал не является голосовым",
                'channel_not_text': "⚠️ Указанный канал не является текстовым",
                'saved_channel_not_found': "⚠️ Сохраненный канал не найден",
                'saved_server_not_found': "⚠️ Сохраненный сервер не найден",
                'delete_confirm': "Вы уверены, что хотите удалить **{}**?",
                
                # Исключение повторов
                'exclude_repeats': "Исключать повторы песен",
                'exclude_repeats_desc': "Создавать временный список из всех песен для воспроизведения без повторов",
                'playlist_reset': "✔️ Создан новый плейлист без повторов",
                'all_songs_played': "Все песни сыграны, начинаем новый цикл",
                
                # Текстовые каналы
                'text_channel': "Текстовый канал:",
                'select_text_channel_placeholder': "Выберите текстовый канал...",
                'text_channel_for_messages': "Текстовый канал для сообщений",
                'same_as_voice': "(голосовой)",
                'auto_connect_enabled': "Автоподключение к серверу...",
                
                # Контекстное меню
                'add_to_queue': "➕ Добавить в очередь",
                'add_next': "➕ Добавить вне очереди",
                'play_now': "⏯️ Играть сейчас",
                'track_info': "ℹ️ Информация",
                'delete_file': "🗑️ Удалить",
                'show_in_folder': "📂 Показать в папке",
                'title': "Название:",
                'artist': "Исполнитель:",
                'album': "Альбом:",
                'duration': "Длительность:",
                'file': "Файл:",
                'seconds': "сек",
                'close': "Закрыть",
                # Поведение и UI (новые ключи)
                'behaviour_group': "Поведение",
                'reconnect_check_lbl': "Авто-реконнект при вылете бота",
                'reconnect_delay_lbl': "Задержка (с):",
                'reconnect_max_lbl': "Попыток макс:",
                'empty_ch_action_lbl': "Пустой канал:",
                'empty_ch_none': "Ничего не делать",
                'empty_ch_pause': "Поставить на паузу",
                'empty_ch_disconnect': "Отключиться",
                'empty_ch_timeout_lbl': "через (мин):",
                'empty_ch_hint': "Пауза: возобновит автоматически когда кто-то вернётся в канал",
                'web_enable': "Web-интерфейс",
                'web_port_lbl': "Порт:",
                'web_open_btn': "Открыть",
                'ffmpeg_auto_btn': "Авто",
                'ffmpeg_ok_in_path': "ffmpeg найден в PATH: {}",
                'ffmpeg_not_found': "ffmpeg не найден — укажите путь или установите ffmpeg-static",
                'ffmpeg_file_not_found': "Файл не найден: {}",
                'tray_show': "Показать",
                'tray_pause': "⏸  Пауза",
                'tray_resume': "▶  Продолжить",
                'tray_skip': "⏭  Пропустить",
                'tray_quit': "Выход",
                'tray_minimized': "Приложение свёрнуто в трей. Двойной клик или меню для открытия.",
                'log_no_voice': "⚠️ Нет голосового соединения — очередь приостановлена",
                'log_disconnected_intentional': "⏹️ Отключён от «{}»",
                'log_kicked': "⚠️ Бот выброшен из канала «{}»",
                'log_reconnect_voice': "🔄 Переподключение к каналу через {} с...",
                'log_no_saved_channel': "ℹ️ Авто-переподключение к каналу отключено (нет сохранённого канала)",
                'log_reconnect_disabled': "ℹ️ Авто-реконнект выключен — ожидаю ручного подключения",
                'log_moved': "📢 Бот перемещён: «{}» → «{}»",
                'log_channel_empty': "👤 Канал «{}» пуст — действие через {} мин",
                'log_user_returned': "👤 {} вернулся в «{}» — таймер отменён",
                'log_resuming': "▶️ Возобновляю — {} вернулся",
                'log_resuming_discord': "▶️ {} вернулся — возобновляю воспроизведение!",
                'log_discord_error': "❌ Discord ошибка в {}: {}",
                'log_discord_disconnected': "⚠️ Discord: соединение разорвано",
                'log_discord_resumed': "✔️ Discord: соединение восстановлено",
                'log_empty_pause': "⏸ Канал «{}» пуст {} мин — пауза",
                'log_empty_pause_discord': "⏸ Канал пуст уже **{} мин** — поставил на паузу.",
                'log_empty_disconnect': "🔌 Канал «{}» пуст {} мин — отключаюсь",
                'log_empty_disconnect_discord': "🔌 Канал пуст уже **{} мин** — отключаюсь.",
                'log_empty_error': "❌ Ошибка empty_channel_watch: {}",
                'log_reconnect_attempt': "🔄 Переподключение (попытка {}/{})",
                'log_invalid_token': "❌ Неверный токен: {}",
                'log_connection_lost': "⚠️ Соединение потеряно: {}",
                'log_reconnect_exceeded': "❌ Превышено число попыток реконнекта — бот остановлен",
                'log_retry': "⏳ Повтор через {} с. (попытка {}/{})",
                'log_retry_short': "⏳ Повтор через {} с.",
                'log_critical_bot': "❌ Критическая ошибка бота: {}",
                'log_privileged_intents_hint': "→ Включите Message Content Intent: Discord Developer Portal → ваше приложение → вкладка Bot → Privileged Gateway Intents → Message Content Intent (нужен для команд с префиксом !).",
                'log_aiohttp_missing': "⚠️ aiohttp не установлен — web-интерфейс недоступен",
                'reconnect_status': "Реконнект {}/{}...",
                'log_web_started': "🌐 Web-интерфейс: http://localhost:{}",
                'log_web_failed': "❌ Web-сервер не запустился: {}",
            },
            
            'en': {
                # Основные элементы интерфейса
                'window_title': "Local Music Bot",
                'not_playing': "",
                'now_playing': "",
                'no_cover': "",
                'time_elapsed': "Elapsed",
                'time_total': "Total",
                'bot_running': "Running",
                'bot_stopped_status': "Stopped",
                
                # Кнопки управления
                'start': "START",
                'stop': "STOP",
                'pause': "PAUSE",
                'resume': "RESUME",
                'skip': "SKIP",
                'clear_queue': "CLEAR QUEUE",
                'refresh': "Refresh",
                'browse': "Browse",
                'clear_errors': "Clear errors",
                
                # Группы и вкладки
                'playback_control': "Playback Control",
                'events': "Events",
                'now_playing_group': "Now Playing",
                'music_tab': "Music",
                'settings_tab': "Settings",
                'info_tab': "Info",
                'errors_tab': "Errors",
                
                # Поиск и статистика
                'search': "Search:",
                'search_placeholder': "Enter track name...",
                'total_files': "Total files: {}",
                
                # Настройки
                'settings_group': "Settings",
                'settings_cat_interface': "Interface",
                'settings_cat_discord': "Discord",
                'settings_cat_library': "Player",
                'settings_cat_playback': "Playback",
                'settings_cat_appearance': "Appearance",
                'settings_cat_ui_web': "Interface",
                'bot_token': "Bot Token:",
                'music_folder': "Music folder:",
                'music_folder_open_tooltip': "Click to open this folder in the file manager",
                'ffmpeg_open_tooltip': "Click to open the folder containing FFmpeg",
                'wallpaper_open_tooltip': "Click to open the folder containing the wallpaper file",
                'ffmpeg_open_failed': "Could not find FFmpeg at this path or in PATH",
                'folder_not_selected': "Folder not selected",
                'folder_not_found': "Folder not found",
                'found_files': "Found {} files",
                'ffmpeg': "FFmpeg:",
                'volume': "Volume:",
                'enable_autoplay': "Enable autoplay",
                'autoplay_mode': "Autoplay mode:",
                'shuffle': "Shuffle",
                'sequential': "Sequential",
                'language': "Language / Язык:",
                'autostart': "Auto-start when program launches",
                'show_album_art': "Show album covers",
                'enable_wallpaper': "Enable wallpaper",
                'wallpaper_file': "Wallpaper image:",
                
                # Ролевая защита
                'role_protection': "Role Protection",
                'enable_role_protection': "Enable role protection",
                'control_role': "Control role (play/pause/etc):",
                'admin_role': "Admin role (stop/delete):",
                'no_permission': "❌ You don't have permission to use this command!",
                'invalid_role_id': "Role ID must be a number!",
                
                # Сообщения об ошибках и предупреждения
                'error': "Error",
                'warning': "Warning",
                'enter_token': "Enter token!",
                'select_folder': "Select existing music folder!",
                'bot_not_running': "Bot is not running!",
                'track_not_found': "Could not find track file!",
                'initializing': "</> Initializing...",
                'bot_stopped': "🛑 Bot stopped",
                'pause_from_gui': "Pause",
                'resumed_from_gui': "Resumed",
                'volume_changed': "🔊 Volume {}%",
                'autostart_enabled': "Auto-start...",
                'autostart_failed': "❌ Failed to start bot on auto-start: {}",
                
                # Discord сообщения
                'not_in_voice': "❌ You are not in a voice channel!",
                'file_not_found': "❌ File not found: {}",
                'playback_error': "❌ Playback error",
                'now_playing_discord': "▶️ {}",
                'paused_discord': "⏸️ Pause",
                'resumed_discord': "▶️ Resume",
                'skipping': "⏭️ {}",
                'playback_stopped': "Playback stopped",
                'nothing_playing': "❌ Nothing is playing",
                'stopped_and_cleared': "⏹️ Stopped and queues cleared",
                'queue_empty': "Queue is empty",
                'queue_cleared': "🧹 Queue cleared (removed: {} tracks)",
                'current_volume': "🔊 Current volume: **{}%**",
                'volume_changed_discord': "🔊 Volume changed from **{}%** to **{}%**",
                'volume_set': "🔊 Volume set to **{}%**",
                'volume_range': "❌ Volume must be from **0** to **100**",
                'autoplay_enabled': "♪ Autoplay **enabled**",
                'autoplay_disabled': "♪ Autoplay **disabled**",
                'shuffle_mode': "🎲 Auto mode: **Shuffle**",
                'sequential_mode': "📋 Auto mode: **Sequential**",
                
                # Очередь воспроизведения
                'queue_header': "**📋 Playback queue:**",
                'now_header': "**▶️ Now:**",
                'user_queue_header': "**👤 User ({}):**",
                'auto_queue_header': "**♪ Auto ({}):**",
                'and_more': "...and {} more",
                'track_added': "➕ **{}** added to queue",
                'track_added_next': "➕ **{}** will be next!",
                'track_play_now': "⏯️ **{}** playing now!",
                
                # Поиск и выбор треков
                'search_results': "**Found tracks:**",
                'enter_number': "📝 Enter number (or 'cancel'):",
                'cancelled': "❌ Cancelled",
                'invalid_number': "❌ Invalid number",
                'timeout': "⏰ Timeout",
                'no_tracks': "❌ No tracks available!",
                'tracks_not_found': "❌ Tracks with '{}' not found",
                'folder_not_specified': "❌ Music folder not specified!",
                
                # Команды (help)
                'help_title': "**♪ Music bot commands**",
                'help_intro': "Plays **your local files** from the folder in Settings. Join a **voice channel** before `!play`.",
                'help_main': "**Main:**",
                'help_queue': "**Queue:**",
                'help_settings': "**Playback:**",
                'help_footer': "**Portal:** https://discord.com/developers/home → your application.\n**OAuth2** → **URL Generator:** first under **Scopes** — `bot` and `applications.commands`; **below on the same page**, **Bot Permissions** appears — enable:\n**General:** View Channels\n**Text:** Send Messages, Embed Links, Read Message History, Use Slash Commands\n**Voice:** Connect, Speak, Use Voice Activity\nCopy the URL at the bottom to invite the bot.\n**Bot** (app tab) → **Privileged Gateway Intents** → enable **Message Content Intent** (required for `!` commands).\n**Roles:** with app role protection, control + admin for stop/delete.\n**GitHub:** https://github.com/LouisFahrenheit/LMB",
                'help_alias_or': "or",
                'help_plus_query': "+ text",
                'cmd_play_random': "`!play` / `!p` — random track",
                'cmd_play_search': "`!play` + part of the filename — search",
                'cmd_playnext': "`!playnext text` - Add track as next in queue",
                'cmd_skip': "`!skip` - Skip current track",
                'cmd_stop': "`!stop` - Stop and disconnect",
                'cmd_pause': "`!pause` - Pause",
                'cmd_resume': "`!resume` - Resume",
                'cmd_queue': "`!queue` - Show queue",
                'cmd_current': "`!current` - Current track info",
                'cmd_clear': "`!clear` - Clear queue",
                'cmd_volume': "`!volume [0-100]` - Show/set volume",
                'cmd_shuffle': "`!shuffle` - Shuffle mode for autoplay",
                'cmd_sequential': "`!sequential` - Sequential mode for autoplay",
                'cmd_autoplay': "`!autoplay` - Toggle autoplay",
                'cmd_help': "`!help` - Show this message",
                'cmd_delete': "`!delete` - Delete current track from disk",
                'help_shorts': "**Short:** `!p` play, `!s`/`!n` skip, `!pn` playnext, `!q` queue, `!c`/`!np` current, `!v` volume, `!ap` autoplay, `!del` delete",
                'help_slash': "**Slash:** same actions via `/play`, `/skip`, `/stop`, … — full list in Discord’s command hints.",
                'pick_track_placeholder': "Pick a track…",
                'slash_pick_track_prompt': "**Multiple matches** — choose a track from the list below.",
                'slash_playnext_need_query': "❌ Enter part of the track name.",
                'delete_button_confirm': "Delete permanently",
                'delete_button_cancel': "Cancel",
                'log_slash_synced': "✔️ Slash commands synced: {}",
                'log_slash_sync_fail': "❌ Slash sync failed: {}",
                'slash_user_error': "❌ Command failed. See the application log for details.",
                
                # Команда удаления
                'delete_confirm': "⚠️ Are you sure you want to delete **{}**? This action cannot be undone! (yes/no)",
                'delete_cancelled': "❌ Deletion cancelled",
                'delete_timeout': "⏰ Confirmation timeout",
                'delete_success': "✅ File **{}** successfully deleted",
                'delete_error': "❌ Error deleting file: {}",
                'delete_file_not_found': "❌ File not found on disk",
                'delete_current': "🗑️ Deleting current track...",
                
                # Логи и статусы
                'bot_not_active': '⚠️ Bot not active or no active guild',
                'guild_not_found': '⚠️ Guild not found',
                'nothing_playing_log': '⚠️ Nothing is playing',
                'error_pausing': '❌ Error pausing: {}',
                'not_paused': '⚠️ Not paused',
                'error_resuming': '❌ Error resuming: {}',
                'no_context_skip': '⚠️ No context for skip',
                'error_skipping': '❌ Error skipping: {}',
                'no_context_clear': '⚠️ No context for clear queue',
                'error_clearing': '❌ Error clearing queue: {}',
                'bot_not_active_volume': '⚠️ Bot not active, volume will be applied on next start',
                'volume_channel': '🔊 Volume changed to {}% in {}',
                'volume_updated_channels': '🔊 Updated volume in {} voice channels',
                'volume_no_connections': '🔊 Volume {}% (no active connections)',
                'error_updating_volume': '❌ Error updating volume: {}',
                'bot_not_active_track': '⚠️ Bot not active, track cannot be added',
                'track_added_queue': '➕ [{} in queue] {} added',
                'track_playing_gui': '▶️ Playing {} in {}',
                'no_context_playback': '⚠️ No context for playback in {}',
                'no_voice_connections': '⚠️ No active voice connections to add track',
                'error_adding_track': '❌ Error adding track from GUI: {}',
                'error_scanning_folder': 'Error scanning folder: {}',
                'track_added_auto': '➕ [{}] {} (autoplay)',
                'skipping_auto': '⏭️ Skipping auto {} - user tracks in queue',
                'file_not_found_log': '❌ File not found: {}',
                'playback_error_log': '❌ Playback error: {}',
                'context_not_found': '❌ Context not found for guild {}',
                'stop_command_issued': '⏹️ Stop command - skipping autoplay',
                'no_tracks_autoplay': '📭 No tracks for autoplay',
                'playback_finished': '⏹️ Playback finished',
                'queue_status': ' | Queue: {} user + {} auto',
                'playing': '▶️ Playing: {} {}',
                'skipping_log': '⏭️ Skipping: {}',
                'stopped_and_cleared_log': '⏹️ Stopped and queues cleared',
                'queue_cleared_log': '🧹 Queue cleared (removed: {} tracks)',
                'volume_updated_all': '🔊 Updated volume in all {} active channels',
                'error_updating_all_volume': '❌ Error updating volume in all channels: {}',
                'bot_ready': '✔️ Bot: {}',
                'music_folder_log': '✔️ Music folder: {}',
                'volume_log': '✔️ Volume: {}%',
                'found_files_log': 'Found {} files',
                'selecting_random': '🎲 Selecting random track',
                'random_added_queue': '➕ Random track added to queue: {}',
                'track_added_queue_log': '➕ Track added to queue: {}',
                'track_added_next_log': '➕ Track added as next: {}',
                'volume_changed_track': '🔊 Volume changed to {}%',
                'volume_set_next': '🔊 Volume set to {}% (for next tracks)',
                'paused_log': 'Pause',
                'resumed_log': 'Resumed',
                'shuffle_mode_log': '🎲 Auto mode changed to Shuffle',
                'sequential_mode_log': '📋 Auto mode changed to Sequential',
                'autoplay_enabled_log': '♪ Autoplay enabled',
                'autoplay_disabled_log': '♪ Autoplay disabled',
                'auto_mode_log': '✔️ Autoplay - {}',
                'token_not_specified': '❌ Token not specified!',
                'starting_bot': 'Starting bot...',
                'start_error': '❌ Start error: {}',
                'critical_error': '❌ Critical error: {}',
                'stopping_bot': 'Stopping bot...',
                'stopped': 'Stopped',
                
                # Информационная вкладка
                'how_to_use': "Quick start",
                'first_step': "Configure the app",
                'first_step_desc': "Open the <b>Settings</b> tab: paste your <b>bot token</b> (from the Discord Developer Portal) and choose the <b>music folder</b> on this PC. Optionally set auto-connect to channels and roles (see the roles section below).",
                'second_step': "Start the bot",
                'second_step_desc': "Click <b>START</b>. Wait until the log shows the bot is online — only then will Discord commands start working.",
                'third_step': "Play music in Discord",
                'third_step_desc': "On your server, join a <b>voice channel</b>. In text chat, use <code>!play</code> or <code>/play</code> for a random track, or add text after the command to search by filename. Or double-click a track in the <b>Music</b> tab to queue it.",
                'fourth_step': "Everything else",
                'fourth_step_desc': "Use the buttons in this window or commands in Discord. List in chat: <code>!help</code> or <code>/help</code>.",
                'info_where_title': "Where to get it",
                'info_where_body': "Source and releases: <a href='https://github.com/LouisFahrenheit/LMB'>github.com/LouisFahrenheit/LMB</a>. This is a desktop app: you run it on your machine with your own bot.",
                'info_perms_title': "Set up the bot in Discord",
                'info_perms_step1': "Open the <a href='https://discord.com/developers/home'>Discord Developer Portal</a> and select your application (or create one).",
                'info_perms_step2': "<b>OAuth2</b> → <b>URL Generator</b>: under <b>Scopes</b>, enable <code>bot</code> and <code>applications.commands</code>.",
                'info_perms_step3': "Further <b>down the same page</b>, <b>Bot Permissions</b> will show — in the General, Text, and Voice columns enable the items listed below, then copy the URL at the bottom and invite the bot.",
                'info_perms_step4': "Also: In <b>Bot</b> → <b>Privileged Gateway Intents</b> → enable <b>Message Content Intent</b>.",
                'info_perms_col_general': "General",
                'info_perms_col_text': "Text",
                'info_perms_col_voice': "Voice",
                'info_perm_view_channels': "see server channels",
                'info_perm_send_messages': "bot replies in chat",
                'info_perm_embed_links': "embeds in responses",
                'info_perm_read_history': "read history (prefix commands)",
                'info_perm_slash': "slash commands (/play, /help, …)",
                'info_perm_connect': "join voice channel",
                'info_perm_speak': "play audio",
                'info_perm_voice_activity': "transmit audio (voice activity)",
                'info_roles_title': "Who can use bot commands (roles)",
                'info_roles_body': "<b>Settings</b> → Discord → <b>Enable role protection</b> and the two role ID fields.<br><br><b>If protection is off</b> — any server member can use the bot in chat (normal Discord behaviour).<br><br><b>If protection is on</b> — only members with the right role can run commands. You set two IDs:<ul style='margin:8px 0; padding-left:20px;'><li style='margin:6px 0;'><b>Control role</b> — playback and queue: play, pause, resume, skip, queue, volume, autoplay, shuffle, and similar.</li><li style='margin:6px 0;'><b>Admin role</b> — “dangerous” actions: full stop (<code>!stop</code> / <code>/stop</code>) and <b>deleting the current track file from disk</b> (<code>!delete</code> / <code>/delete</code>).</li></ul><b>How to get a role ID:</b> enable Developer Mode in Discord → right-click the role in the server → Copy Role ID.",
                'commands_title': "All commands and shortcuts",
                'formats_title': "File formats",
                'version': "Version",
                'github': "GitHub",
                'info_title': "Discord Local Music Bot",
                'info_commands_intro_title': "How to use commands",
                'info_commands_intro_body': "Both <b>slash commands</b> (type <code>/</code> in a server channel — e.g. <code>/play</code>, <code>/help</code>) and <b>prefix</b> <code>!</code> commands (e.g. <code>!play</code>, <code>!p</code>) work. They do the same thing; use whichever you prefer. Join a voice channel before <code>!play</code> or <code>/play</code>; text after the command searches the track by filename.",
                'info_cmd_table_col_slash': "Slash",
                'info_cmd_table_col_exclam': "! and aliases",
                'info_delete_track_short': "Delete the current track from disk (admin role only)",
                'info_cmd_help_desc': "Show the command list in chat",
                'info_first_request': "The first request must be from a user in voice.",
                'info_control': "Control is available from the discord chat and directly in this window.",
                'info_double_click': "Double-click on a track in the \"Music\" tab adds it to the queue.",
                'info_commands': "Commands:",
                'info_command': "Command",
                'info_description_col': "Description",
                'info_random_track': "Random track",
                'info_search_track': "Search track",
                'info_add_next': "Add track as next after current",
                'info_skip': "Skip current",
                'info_stop': "Stop and disconnect",
                'info_pause': "Pause",
                'info_resume': "Resume",
                'info_show_queue': "Show queue",
                'info_current_track': "Current track info",
                'info_clear_queue': "Clear queue",
                'info_volume': "Volume (0-100)",
                'info_shuffle_mode': "Shuffle mode for autoplay",
                'info_sequential_mode': "Sequential mode for autoplay",
                'info_toggle_autoplay': "Toggle autoplay",
                'info_formats': "Formats:",
                'info_formats_list': "MP3, FLAC, M4A, WAV, OGG, AAC, MP4",
                
                # Диалоги подтверждения
                'confirm_close_title': "Confirm Close",
                'confirm_close_message': "Bot is still running. Are you sure you want to close the program?",
                'yes': "Yes",
                'no': "No",
                
                # Статусы и индикаторы
                'autoplay_status': "Auto",
                
                # Настройки каналов
                'default_channel': "Default channel",
                'enable_auto_connect': "Auto-connect to channel on start",
                'select_server': "Select server:",
                'select_voice_channel': "Select voice channel:",
                'select_text_channel': "Select text channel:",
                'refresh_channels': "Refresh",
                'no_voice_channels': "❌ No voice channels on this server",
                'connected_to_channel': "✔️ Connected to {} in {}",
                'discord_connected_to_channel': "✅ Connected to voice channel",
                'failed_connect_channel': "❌ Failed to connect to channel: {}",
                'select_server_and_channel': "Select server, voice and text channels for auto-connect",
                'channel_saved': "✔️ {}",
                'server_not_found': "⚠️ Server with ID {} not found",
                'selected_channel_not_found': "Selected channel not found",
                'channel_not_voice': "⚠️ Specified channel is not a voice channel",
                'channel_not_text': "⚠️ Specified channel is not a text channel",
                'saved_channel_not_found': "⚠️ Saved channel not found",
                'saved_server_not_found': "⚠️ Saved server not found",
                'delete_confirm': "Are you sure you want to delete **{}**?",
                
                # Исключение повторов
                'exclude_repeats': "Exclude repeats",
                'exclude_repeats_desc': "Create temporary playlist of all songs to play without repeats",
                'playlist_reset': "✔️ New no-repeat playlist created",
                'all_songs_played': "All songs played, starting new cycle",
                
                # Текстовые каналы
                'text_channel': "Text channel:",
                'select_text_channel_placeholder': "Select text channel...",
                'text_channel_for_messages': "Text channel for messages",
                'same_as_voice': "(voice)",
                'auto_connect_enabled': "Auto connect to server...",
                
                # Контекстное меню
                'add_to_queue': "➕ Add to queue",
                'add_next': "➕ Add next",
                'play_now': "⏯️ Play now",
                'track_info': "ℹ️ Track info",
                'delete_file': "🗑️ Delete",
                'show_in_folder': "📂 Show in folder",
                'title': "Title:",
                'artist': "Artist:",
                'album': "Album:",
                'duration': "Duration:",
                'file': "File:",
                'seconds': "sec",
                'close': "Close",
                # Behaviour and UI (new keys)
                'behaviour_group': "Behaviour",
                'reconnect_check_lbl': "Auto-reconnect on bot crash",
                'reconnect_delay_lbl': "Delay (s):",
                'reconnect_max_lbl': "Max attempts:",
                'empty_ch_action_lbl': "Empty channel:",
                'empty_ch_none': "Do nothing",
                'empty_ch_pause': "Pause playback",
                'empty_ch_disconnect': "Disconnect",
                'empty_ch_timeout_lbl': "after (min):",
                'empty_ch_hint': "Pause: resumes automatically when someone returns",
                'web_enable': "Web interface",
                'web_port_lbl': "Port:",
                'web_open_btn': "Open",
                'ffmpeg_auto_btn': "Auto",
                'ffmpeg_ok_in_path': "ffmpeg found in PATH: {}",
                'ffmpeg_not_found': "ffmpeg not found — set path or install ffmpeg-static",
                'ffmpeg_file_not_found': "File not found: {}",
                'tray_show': "Show",
                'tray_pause': "⏸  Pause",
                'tray_resume': "▶  Resume",
                'tray_skip': "⏭  Skip",
                'tray_quit': "Quit",
                'tray_minimized': "App minimised to tray. Double-click or use the menu to open.",
                'log_no_voice': "⚠️ No voice connection — queue paused",
                'log_disconnected_intentional': "⏹️ Disconnected from «{}»",
                'log_kicked': "⚠️ Bot kicked from channel «{}»",
                'log_reconnect_voice': "🔄 Reconnecting to channel in {} s...",
                'log_no_saved_channel': "ℹ️ Auto voice-reconnect disabled (no saved channel)",
                'log_reconnect_disabled': "ℹ️ Auto-reconnect off — waiting for manual connection",
                'log_moved': "📢 Bot moved: «{}» → «{}»",
                'log_channel_empty': "👤 Channel «{}» empty — action in {} min",
                'log_user_returned': "👤 {} returned to «{}» — timer cancelled",
                'log_resuming': "▶️ Resuming — {} returned",
                'log_resuming_discord': "▶️ {} returned — resuming playback!",
                'log_discord_error': "❌ Discord error in {}: {}",
                'log_discord_disconnected': "⚠️ Discord: connection lost",
                'log_discord_resumed': "✔️ Discord: connection restored",
                'log_empty_pause': "⏸ Channel «{}» empty {} min — pausing",
                'log_empty_pause_discord': "⏸ Channel empty for **{} min** — paused.",
                'log_empty_disconnect': "🔌 Channel «{}» empty {} min — disconnecting",
                'log_empty_disconnect_discord': "🔌 Channel empty for **{} min** — disconnecting.",
                'log_empty_error': "❌ Empty channel watch error: {}",
                'log_reconnect_attempt': "🔄 Reconnecting (attempt {}/{})",
                'log_invalid_token': "❌ Invalid token: {}",
                'log_connection_lost': "⚠️ Connection lost: {}",
                'log_reconnect_exceeded': "❌ Reconnect attempts exceeded — bot stopped",
                'log_retry': "⏳ Retry in {} s (attempt {}/{})",
                'log_retry_short': "⏳ Retry in {} s.",
                'log_critical_bot': "❌ Critical bot error: {}",
                'log_privileged_intents_hint': "→ Enable Message Content Intent: Discord Developer Portal → your application → Bot tab → Privileged Gateway Intents → Message Content Intent (required for prefix commands like !play).",
                'log_aiohttp_missing': "⚠️ aiohttp not installed — web interface unavailable",
                'reconnect_status': "Reconnecting {}/{}...",
                'log_web_started': "🌐 Web interface: http://localhost:{}",
                'log_web_failed': "❌ Web server failed to start: {}",
            }
        }
    
    def set_language(self, language):
        if language in self.translations:
            self.language = language
    
    def t(self, key, *args):
        if key in self.translations[self.language]:
            text = self.translations[self.language][key]
            return text.format(*args) if args else text
        return key

class CustomAction(QWidgetAction):
    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.text = text
    
    def createWidget(self, parent):
        widget = QWidget(parent)
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(5, 2, 5, 2)
        layout.setSpacing(10)
        
        # Текст
        text_label = QLabel(self.text)
        text_label.setStyleSheet("color: white; padding: 5px;")
        layout.addWidget(text_label)
        
        layout.addStretch()
        
        widget.setStyleSheet("""
            QWidget:hover {
                background-color: #4a4a4a;
            }
        """)
        
        return widget

def get_track_name_from_file(file_path):
    try:
        with taglib.File(file_path) as song:
            title = song.tags.get('TITLE', [None])[0]
            artist = song.tags.get('ARTIST', [None])[0]
            album = song.tags.get('ALBUM', [None])[0]
            if title and artist:
                return f"{artist} - {title}"
            elif title:
                return title
            else:
                filename = os.path.basename(file_path)
                return re.sub(r'^\d+[\s\.\-_]*', '', os.path.splitext(filename)[0]).strip() or os.path.splitext(filename)[0]
    except Exception:
        filename = os.path.basename(file_path)
        return re.sub(r'^\d+[\s\.\-_]*', '', os.path.splitext(filename)[0]).strip() or os.path.splitext(filename)[0]

def get_track_info(file_path):
    info = {
        'title': '—',
        'artist': '—',
        'album': '—',
        'duration': 0,
        'file': file_path
    }
    try:
        with taglib.File(file_path) as song:
            info['title'] = song.tags.get('TITLE', ['—'])[0]
            info['artist'] = song.tags.get('ARTIST', ['—'])[0]
            info['album'] = song.tags.get('ALBUM', ['—'])[0]
            info['duration'] = int(song.length) if song.length else 0
    except Exception:
        filename = os.path.basename(file_path)
        info['title'] = os.path.splitext(filename)[0]
    return info

def get_album_art(file_path):
    try:
        with taglib.File(file_path) as song:
            if hasattr(song, 'pictures') and song.pictures:
                for picture in song.pictures:
                    if picture.data:
                        pixmap = QPixmap()
                        pixmap.loadFromData(QByteArray(picture.data))
                        return pixmap
    except Exception:
        pass
    return None

class SpectrumWidget(QWidget):
    """Анимированный псевдо-спектроанализатор в цветах UI (#2196F3 / #1976D2)."""
    BAR_COUNT  = 24
    BAR_GAP    = 2
    COLOR_LOW  = QColor(0x21, 0x96, 0xF3)   # #2196F3
    COLOR_HIGH = QColor(0x09, 0x61, 0xAA)   # #0961aa

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(40)
        self._bars    = [0.0] * self.BAR_COUNT
        self._targets = [0.0] * self.BAR_COUNT
        self._active  = False
        self._timer   = QTimer(self)
        self._timer.setInterval(50)   # 20 fps
        self._timer.timeout.connect(self._tick)

    def set_active(self, active: bool):
        self._active = active
        if active:
            self._timer.start()
        else:
            self._timer.stop()
            self._bars = [0.0] * self.BAR_COUNT
            self.update()

    def _tick(self):
        import math, random
        t = __import__('time').time()
        for i in range(self.BAR_COUNT):
            # Псевдо-спектр: несколько синусоид с разными частотами + шум
            wave = (math.sin(t * 3.7 + i * 0.7)
                  + math.sin(t * 2.1 + i * 1.3)
                  + math.sin(t * 5.0 + i * 0.4)) / 3.0
            self._targets[i] = max(0.05, (wave + 1) / 2 * 0.85 + random.uniform(0, 0.15))
            # Плавное приближение к цели
            speed = 0.35
            self._bars[i] += (self._targets[i] - self._bars[i]) * speed
        self.update()

    def paintEvent(self, event):
        if not self._active and all(b < 0.01 for b in self._bars):
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        bar_w = max(2, (w - (self.BAR_COUNT + 1) * self.BAR_GAP) / self.BAR_COUNT)
        for i, val in enumerate(self._bars):
            x = self.BAR_GAP + i * (bar_w + self.BAR_GAP)
            bar_h = max(2, val * h)
            y = h - bar_h
            # Градиент снизу-вверх: LOW → HIGH
            grad = QLinearGradient(x, h, x, y)
            grad.setColorAt(0.0, self.COLOR_LOW)
            grad.setColorAt(1.0, self.COLOR_HIGH)
            painter.setBrush(QBrush(grad))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(int(x), int(y), int(bar_w), int(bar_h), 2, 2)
        painter.end()


class ModernButton(QPushButton):
    def __init__(self, text, parent=None, color="#3c3c3c", hover_color="#4a4a4a"):
        super().__init__(text, parent)
        self.default_color = color
        self.hover_color = hover_color
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(35)
        self.update_style()
    
    def update_style(self):
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {self.default_color};
                color: white;
                border: none;
                border-radius: 5px;
                font-weight: 600;
                font-size: 13px;
                padding: 6px 12px;
            }}
            QPushButton:hover {{
                background-color: {self.hover_color};
            }}
            QPushButton:pressed {{
                background-color: {self.darken_color(self.default_color)};
            }}
            QPushButton:disabled {{
                background-color: #2b2b2b;
                color: #666;
            }}
        """)
    
    def darken_color(self, color):
        if color.startswith('#'):
            r = int(color[1:3], 16)
            g = int(color[3:5], 16)
            b = int(color[5:7], 16)
            r = max(0, r - 20)
            g = max(0, g - 20)
            b = max(0, b - 20)
            return f"#{r:02x}{g:02x}{b:02x}"
        return color


class MusicWallpaperWidget(QWidget):
    """Контейнер списка треков с полупрозрачным фоновым изображением."""
    BASE_BG = QColor(43, 43, 43)
    IMAGE_OPACITY = 0.32

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAutoFillBackground(False)
        self._wallpaper_enabled = False
        self._wallpaper_path = ""
        self._wallpaper_pixmap = None

    def set_wallpaper(self, enabled, path):
        self._wallpaper_enabled = bool(enabled)
        self._wallpaper_path = (path or "").strip()
        self._wallpaper_pixmap = None
        if self._wallpaper_enabled and self._wallpaper_path and os.path.isfile(self._wallpaper_path):
            pm = QPixmap(self._wallpaper_path)
            if not pm.isNull():
                self._wallpaper_pixmap = pm
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.BASE_BG)
        if self._wallpaper_enabled and self._wallpaper_pixmap and not self._wallpaper_pixmap.isNull():
            painter.setOpacity(self.IMAGE_OPACITY)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            sw, sh = self.width(), self.height()
            if sw > 0 and sh > 0:
                scaled = self._wallpaper_pixmap.scaled(
                    sw, sh,
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation
                )
                x = max(0, (scaled.width() - sw) // 2)
                y = max(0, (scaled.height() - sh) // 2)
                painter.drawPixmap(0, 0, scaled, x, y, sw, sh)
        painter.end()


def _shorten_path_for_status(path: str, max_len: int = 70) -> str:
    """Укороченная строка для подписей статуса; полный путь — в toolTip."""
    p = (path or "").strip()
    if len(p) <= max_len:
        return p
    half = (max_len - 1) // 2
    return p[:half] + "…" + p[-half:]


class ClickablePathLabel(QLabel):
    """Отображение пути без редактирования; клик открывает папку в проводнике."""
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._full_path = ""
        self._tooltip_hint = ""
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.setWordWrap(False)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

    def set_tooltip_hint(self, hint: str):
        self._tooltip_hint = (hint or "").strip()
        self._sync_tooltip()

    def set_path(self, path: str):
        self._full_path = (path or "").strip()
        self._refresh_elided()
        self._sync_tooltip()

    def setText(self, text: str):
        self.set_path(text or "")

    def text(self) -> str:
        return self._full_path

    def _sync_tooltip(self):
        parts = []
        if self._tooltip_hint:
            parts.append(self._tooltip_hint)
        if self._full_path:
            parts.append(self._full_path)
        super().setToolTip("\n\n".join(parts) if parts else "")

    def _refresh_elided(self):
        if not self._full_path:
            super().setText("")
            return
        fm = QFontMetrics(self.font())
        w = self.contentsRect().width()
        if w < 12:
            w = max(self.width() - 20, 40)
        w = max(int(w) - 8, 24)
        elided = fm.elidedText(self._full_path, Qt.TextElideMode.ElideMiddle, w)
        super().setText(elided)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_elided()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


_WEB_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Local Music Bot</title>
<style>
  :root{--bg:#2b2b2b;--bg2:#3c3c3c;--bg3:#4a4a4a;--acc:#2196F3;--acc2:#1976D2;--txt:#e0e0e0;--txt2:#888;--red:#c2160a;--green:#00802b}
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:var(--bg);color:var(--txt);font-family:'Segoe UI',sans-serif;min-height:100vh}
  .container{max-width:900px;margin:0 auto;padding:16px}
  h1{font-size:20px;color:var(--acc);margin-bottom:16px;display:flex;align-items:center;gap:10px}
  .badge{font-size:11px;padding:2px 8px;border-radius:10px;background:var(--bg2);color:var(--txt2)}
  .badge.on{background:#00802b22;color:#4CAF50}
  .card{background:var(--bg2);border:1px solid #444;border-radius:8px;padding:14px;margin-bottom:12px}
  .card-title{font-size:11px;color:var(--txt2);text-transform:uppercase;letter-spacing:.5px;margin-bottom:10px}
  .now-playing{font-size:15px;font-weight:700;color:var(--acc);word-break:break-word;min-height:22px}
  .progress-wrap{margin:10px 0 4px}
  .progress-bg{background:#444;border-radius:3px;height:5px;overflow:hidden}
  .progress-fill{height:5px;border-radius:3px;background:linear-gradient(90deg,var(--acc),var(--acc2));transition:width .8s linear}
  .times{display:flex;justify-content:space-between;font-size:11px;color:var(--txt2);font-family:monospace}
  .btns{display:flex;gap:8px;flex-wrap:wrap}
  .btn{padding:8px 16px;border:none;border-radius:5px;font-size:13px;font-weight:600;cursor:pointer;transition:background .15s}
  .btn-primary{background:var(--acc);color:#fff}.btn-primary:hover{background:var(--acc2)}
  .btn-green{background:var(--green);color:#fff}.btn-green:hover{background:#00a036}
  .btn-red{background:var(--red);color:#fff}.btn-red:hover{background:#e31c0d}
  .btn-gray{background:var(--bg3);color:var(--txt)}.btn-gray:hover{background:#555}
  .btn:disabled{opacity:.4;cursor:default}
  .vol-row{display:flex;align-items:center;gap:10px;margin-top:8px}
  .vol-row label{font-size:12px;color:var(--txt2);min-width:60px}
  input[type=range]{flex:1;accent-color:var(--acc)}
  .vol-val{font-size:12px;color:var(--txt);min-width:36px;text-align:right}
  .queue-row{display:flex;gap:20px;font-size:12px;color:var(--txt2);margin-top:6px}
  .queue-row span{color:var(--txt)}
  .search-row{display:flex;gap:8px;margin-bottom:8px}
  .search-row input{flex:1;padding:7px 10px;background:var(--bg3);color:var(--txt);border:1px solid #555;border-radius:4px;font-size:13px}
  .track-list{max-height:260px;overflow-y:auto}
  .track-item{padding:7px 10px;cursor:pointer;border-radius:4px;font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .track-item:hover{background:var(--bg3)}
  .status-dot{width:9px;height:9px;border-radius:50%;display:inline-block;margin-right:5px}
  .dot-on{background:#4CAF50}.dot-off{background:#ff6b6b}
  .reconnect{font-size:11px;color:#FFA500;margin-top:6px;display:none}
  .spectrum{display:flex;align-items:flex-end;gap:2px;height:32px;margin-top:8px}
  .sbar{width:8px;border-radius:2px;background:var(--acc);transition:height .08s ease}
  .lang-switch{margin-left:auto;display:flex;gap:6px;align-items:center}
  .btn-lang{padding:4px 10px;font-size:11px;border:1px solid #555;background:var(--bg2);color:var(--txt);border-radius:4px;cursor:pointer;font-weight:600}
  .btn-lang:hover{background:var(--bg3)}
  .btn-lang.active{background:var(--acc);color:#fff;border-color:var(--acc)}
  @media(max-width:500px){.btns{flex-direction:column}.btn{width:100%}}
</style>
</head>
<body>
<div class="container">
  <h1>
    <span class="status-dot dot-off" id="sdot"></span>
    Local Music Bot
    <span class="badge" id="bname">—</span>
    <span class="lang-switch">
      <button type="button" class="btn-lang" id="btnLangRu" onclick="setWebLang('ru')">RU</button>
      <button type="button" class="btn-lang" id="btnLangEn" onclick="setWebLang('en')">EN</button>
    </span>
  </h1>

  <div class="card">
    <div class="card-title" id="cardNowPlayingTitle">Now Playing</div>
    <div class="now-playing" id="np">—</div>
    <div class="progress-wrap">
      <div class="progress-bg"><div class="progress-fill" id="pf" style="width:0%"></div></div>
    </div>
    <div class="times"><span id="ct">0:00</span><span id="tt">0:00</span></div>
    <div class="spectrum" id="spectrum"></div>
    <div class="queue-row"><span id="queueLbl">Queue</span> 👤 <span id="qu">0</span></div>
    <div class="reconnect" id="reconnect"></div>
  </div>

  <div class="card">
    <div class="card-title" id="cardControlsTitle">Controls</div>
    <div class="btns">
      <button class="btn btn-primary" id="btnPause" onclick="action('pause')">⏸ Pause</button>
      <button class="btn btn-gray" id="btnSkip" onclick="action('skip')">⏭ Skip</button>
      <button class="btn btn-red" id="btnStop" onclick="action('stop')">⏹ Stop</button>
    </div>
    <div class="vol-row">
      <label id="volLab">Volume</label>
      <input type="range" min="0" max="100" id="vol" oninput="setVol(this.value)">
      <span class="vol-val" id="volv">50%</span>
    </div>
  </div>

  <div class="card">
    <div class="card-title" id="cardLibraryTitle">Library</div>
    <div class="search-row">
      <input type="text" id="sq" placeholder="Search tracks..." oninput="searchTracks()">
    </div>
    <div class="track-list" id="tlist"></div>
  </div>
</div>

<script>
const N_BARS = 18;
const WEB_STR={
  ru:{
    pageTitle:'Local Music Bot',
    nowPlaying:'Сейчас играет',
    queue:'Очередь',
    controls:'Управление',
    volume:'Громкость',
    library:'Библиотека',
    searchPh:'Поиск треков...',
    pause:'⏸ Пауза',
    resume:'▶ Продолжить',
    skip:'⏭ Пропустить',
    stop:'⏹ Стоп'
  },
  en:{
    pageTitle:'Local Music Bot',
    nowPlaying:'Now Playing',
    queue:'Queue',
    controls:'Controls',
    volume:'Volume',
    library:'Library',
    searchPh:'Search tracks...',
    pause:'⏸ Pause',
    resume:'▶ Resume',
    skip:'⏭ Skip',
    stop:'⏹ Stop'
  }
};
const LS_KEY='lmb_web_lang';
let webLang='en';
let bars = Array(N_BARS).fill(0);
let playing = false;
let posTimer = null;
let posSeconds = 0;
let totalSeconds = 0;

function applyWebLang(){
  const t=WEB_STR[webLang];
  document.documentElement.lang=webLang;
  document.title=t.pageTitle;
  const g=id=>document.getElementById(id);
  g('cardNowPlayingTitle').textContent=t.nowPlaying;
  g('queueLbl').textContent=t.queue+':';
  g('cardControlsTitle').textContent=t.controls;
  g('volLab').textContent=t.volume;
  g('cardLibraryTitle').textContent=t.library;
  g('sq').placeholder=t.searchPh;
  g('btnSkip').textContent=t.skip;
  g('btnStop').textContent=t.stop;
  g('btnLangRu').classList.toggle('active',webLang==='ru');
  g('btnLangEn').classList.toggle('active',webLang==='en');
}
function setWebLang(code){
  if(code!=='ru'&&code!=='en')return;
  webLang=code;
  try{localStorage.setItem(LS_KEY,code);}catch(e){}
  applyWebLang();
}
function syncWebLangFromServer(serverLang){
  let s=null;
  try{s=localStorage.getItem(LS_KEY);}catch(e){}
  if(s==='ru'||s==='en'){webLang=s;return;}
  webLang=(serverLang==='ru'||serverLang==='en')?serverLang:'en';
}

// Build spectrum bars
const spec = document.getElementById('spectrum');
for(let i=0;i<N_BARS;i++){
  const d=document.createElement('div');
  d.className='sbar';
  d.id='sb'+i;
  spec.appendChild(d);
}

function fmt(s){const m=Math.floor(s/60);return m+':'+(s%60).toString().padStart(2,'0')}

function tickSpectrum(){
  if(!playing){bars=bars.map(b=>b*0.7);} else {
    const t=Date.now()/1000;
    bars=bars.map((b,i)=>{
      const target=Math.max(0.05,((Math.sin(t*3.7+i*.7)+Math.sin(t*2.1+i*1.3)+Math.sin(t*5+i*.4))/3+1)/2*.85+Math.random()*.15);
      return b+(target-b)*.35;
    });
  }
  bars.forEach((b,i)=>{
    const el=document.getElementById('sb'+i);
    if(el) el.style.height=(Math.max(2,b*32))+'px';
  });
}
setInterval(tickSpectrum,50);

async function fetchStatus(){
  try{
    const r=await fetch('/api/status');
    const d=await r.json();
    syncWebLangFromServer(d.language||'en');
    applyWebLang();
    const t=WEB_STR[webLang];
    document.getElementById('sdot').className='status-dot '+(d.running?'dot-on':'dot-off');
    document.getElementById('bname').textContent=d.bot_name||'—';
    document.getElementById('np').textContent=d.now_playing||'—';
    playing=d.is_playing&&!d.is_paused;
    document.getElementById('btnPause').textContent=d.is_paused?t.resume:t.pause;
    document.getElementById('btnPause').onclick=()=>action(d.is_paused?'resume':'pause');
    const vol=d.volume||50;
    document.getElementById('vol').value=vol;
    document.getElementById('volv').textContent=vol+'%';
    document.getElementById('qu').textContent=d.queue_user;
    totalSeconds=d.duration||0;
    document.getElementById('tt').textContent=fmt(totalSeconds);
  }catch(e){}
}

function startProgressTimer(){
  if(posTimer) clearInterval(posTimer);
  posSeconds=0;
  posTimer=setInterval(()=>{
    if(!playing) return;
    posSeconds=Math.min(posSeconds+1,totalSeconds);
    document.getElementById('ct').textContent=fmt(posSeconds);
    const pct=totalSeconds>0?(posSeconds/totalSeconds*100):0;
    document.getElementById('pf').style.width=pct+'%';
  },1000);
}

async function action(a,extra={}){
  await fetch('/api/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:a,...extra})});
  setTimeout(fetchStatus,300);
}
function setVol(v){document.getElementById('volv').textContent=v+'%';action('volume',{value:parseInt(v)});}

let trackData=[];
async function loadTracks(){
  const r=await fetch('/api/tracks');
  trackData=await r.json();
  renderTracks(trackData);
}
function renderTracks(list){
  const el=document.getElementById('tlist');
  el.innerHTML=list.map(t=>{
    const escHtml=t.name.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    return `<div class="track-item" onclick="playTrack('${t.name.replace(/'/g,"\\'")}')">🎵 ${escHtml}</div>`;
  }).join('');
}
function searchTracks(){
  const q=document.getElementById('sq').value.toLowerCase();
  renderTracks(q?trackData.filter(t=>t.name.toLowerCase().includes(q)):trackData);
}
function playTrack(name){action('play',{query:name});}

try{
  const s=localStorage.getItem(LS_KEY);
  if(s==='ru'||s==='en'){webLang=s;applyWebLang();}
}catch(e){}

fetchStatus();
loadTracks();
setInterval(fetchStatus,3000);
startProgressTimer();
</script>
</body>
</html>"""


class BotConfig:
    def __init__(self):
        self.token = ""
        self.ffmpeg_path = find_ffmpeg()
        self.music_folder = ""
        self.volume = 1.0
        self.autoplay_enabled = True
        self.autoplay_mode = "shuffle"
        self.supported_formats = ['.mp3', '.flac', '.m4a', '.wav', '.ogg', '.aac', '.mp4']
        self.language = "en"
        self.autostart = False
        self.show_album_art = True
        self.auto_connect_enabled = False
        self.default_guild_id = None
        self.default_voice_channel_id = None
        self.default_text_channel_id = None
        self.exclude_repeats = True
        self.wallpaper_enabled = False
        self.wallpaper_path = ""
        # Ролевая защита
        self.role_control_enabled = False
        self.control_role_id = None
        self.admin_role_id = None
        # Sleep timer
        # Web-интерфейс
        self.web_enabled = False
        self.web_port = 8080
        # Реконнект
        self.reconnect_enabled = True
        self.reconnect_delay = 5
        self.reconnect_max = 3
        # Действие при пустом канале
        self.empty_channel_action = "pause"   # "none" | "pause" | "disconnect"
        self.empty_channel_timeout = 1        # минут до действия

    def save_to_file(self, filename=CONFIG_FILE):
        data = {
            'token': self.token,
            'ffmpeg_path': self.ffmpeg_path,
            'music_folder': self.music_folder.replace('\\', '/') if self.music_folder else '',
            'volume': self.volume,
            'autoplay_enabled': self.autoplay_enabled,
            'autoplay_mode': self.autoplay_mode,
            'language': self.language,
            'autostart': self.autostart,
            'show_album_art': self.show_album_art,
            'auto_connect_enabled': self.auto_connect_enabled,
            'default_guild_id': self.default_guild_id,
            'default_voice_channel_id': self.default_voice_channel_id,
            'default_text_channel_id': self.default_text_channel_id,
            'exclude_repeats': self.exclude_repeats,
            'wallpaper_enabled': self.wallpaper_enabled,
            'wallpaper_path': self.wallpaper_path.replace('\\', '/') if self.wallpaper_path else '',
            # Ролевая защита
            'role_control_enabled': self.role_control_enabled,
            'control_role_id': self.control_role_id,
            'admin_role_id': self.admin_role_id,
            # Sleep timer
            # Web
            'web_enabled': self.web_enabled,
            'web_port': self.web_port,
            # Reconnect
            'reconnect_enabled': self.reconnect_enabled,
            'reconnect_delay': self.reconnect_delay,
            'reconnect_max': self.reconnect_max,
            # Пустой канал
            'empty_channel_action': self.empty_channel_action,
            'empty_channel_timeout': self.empty_channel_timeout,
        }
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        except Exception:
            pass
    
    def load_from_file(self, filename=CONFIG_FILE):
        if os.path.exists(filename):
            try:
                with open(filename, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.token = data.get('token', '')
                    self.ffmpeg_path = data.get('ffmpeg_path', 'ffmpeg')
                    self.music_folder = data.get('music_folder', '')
                    self.volume = data.get('volume', 0.5)
                    self.autoplay_enabled = data.get('autoplay_enabled', False)
                    self.autoplay_mode = data.get('autoplay_mode', 'shuffle')
                    self.language = data.get('language', 'en')
                    self.autostart = data.get('autostart', False)
                    self.show_album_art = data.get('show_album_art', True)
                    self.auto_connect_enabled = data.get('auto_connect_enabled', False)
                    self.default_guild_id = data.get('default_guild_id', None)
                    self.default_voice_channel_id = data.get('default_voice_channel_id', None)
                    self.default_text_channel_id = data.get('default_text_channel_id', None)
                    self.exclude_repeats = data.get('exclude_repeats', True)
                    self.wallpaper_enabled = data.get('wallpaper_enabled', False)
                    self.wallpaper_path = data.get('wallpaper_path', '')
                    # Ролевая защита
                    self.role_control_enabled = data.get('role_control_enabled', False)
                    self.control_role_id = data.get('control_role_id', None)
                    self.admin_role_id = data.get('admin_role_id', None)
                    # Sleep timer
                    # Web
                    self.web_enabled = data.get('web_enabled', False)
                    self.web_port = data.get('web_port', 8080)
                    # Reconnect
                    self.reconnect_enabled = data.get('reconnect_enabled', True)
                    self.reconnect_delay = data.get('reconnect_delay', 5)
                    self.reconnect_max = data.get('reconnect_max', 3)
                    # Пустой канал
                    self.empty_channel_action = data.get('empty_channel_action', 'pause')
                    self.empty_channel_timeout = data.get('empty_channel_timeout', 1)
                return True
            except Exception:
                pass
        return False

class EmittingStream:
    def __init__(self, signal):
        self.signal = signal
    def write(self, text):
        if text.strip():
            self.signal.emit(text)
    def flush(self):
        pass

class PlaylistQueue:
    def __init__(self):
        self.user_queue = []
        self.auto_queue = []
        self.current_is_user = False
    
    def add_user_track(self, file_path):
        self.user_queue.append(file_path)
    
    def add_user_track_next(self, file_path):
        self.user_queue.insert(0, file_path)
    
    def add_auto_track(self, file_path):
        self.auto_queue.append(file_path)
    
    def get_next_track(self):
        if self.user_queue:
            self.current_is_user = True
            return (self.user_queue.pop(0), True)
        elif self.auto_queue:
            self.current_is_user = False
            return (self.auto_queue.pop(0), False)
        return (None, False)
    
    def clear_user_queue(self):
        count = len(self.user_queue)
        self.user_queue.clear()
        return count
    
    def clear_auto_queue(self):
        count = len(self.auto_queue)
        self.auto_queue.clear()
        return count
    
    def clear_all(self):
        user_count = len(self.user_queue)
        auto_count = len(self.auto_queue)
        self.user_queue.clear()
        self.auto_queue.clear()
        return user_count + auto_count
    
    def get_queue_info(self):
        return {'user': len(self.user_queue), 'auto': len(self.auto_queue), 'current_is_user': self.current_is_user}
    
    def has_user_tracks(self):
        return len(self.user_queue) > 0
    
    def has_auto_tracks(self):
        return len(self.auto_queue) > 0
    
    def get_user_queue_list(self, limit=10):
        return self.user_queue[:limit]
    
    def get_auto_queue_list(self, limit=10):
        return self.auto_queue[:limit]

# Проверка ролей (общая для префиксных команд и slash)
def member_has_roles(member, guild, bot, required_role_id, admin_role_id=None, check_admin=True):
    if not guild:
        return False
    if not hasattr(bot, 'config') or not bot.config.role_control_enabled:
        return True
    if member is not None and not isinstance(member, discord.Member):
        member = guild.get_member(member.id)
    if not member:
        return False
    if admin_role_id:
        for role in member.roles:
            if role.id == admin_role_id:
                return True
    if check_admin:
        return False
    if required_role_id:
        for role in member.roles:
            if role.id == required_role_id:
                return True
    return False


async def check_user_roles(ctx, required_role_id, admin_role_id=None, check_admin=True):
    return member_has_roles(ctx.author, ctx.guild, ctx.bot, required_role_id, admin_role_id, check_admin)


def check_interaction_roles(interaction, required_role_id, admin_role_id=None, check_admin=True):
    if not interaction.guild:
        return False
    return member_has_roles(interaction.user, interaction.guild, interaction.client,
                            required_role_id, admin_role_id, check_admin)


class InteractionReplyContext:
    """Обёртка под commands.Context для interaction: play_audio и очереди шлют ответы через response/followup."""

    __slots__ = ('bot', 'guild', 'author', 'channel', '_interaction')

    def __init__(self, interaction: discord.Interaction):
        self._interaction = interaction
        self.bot = interaction.client
        self.guild = interaction.guild
        self.author = interaction.user
        self.channel = interaction.channel

    async def send(self, content=None, **kwargs):
        inter = self._interaction
        if inter.response.is_done():
            return await inter.followup.send(content, **kwargs)
        return await inter.response.send_message(content, **kwargs)


class TrackPickView(discord.ui.View):
    def __init__(self, bot_thread, matches, *, playnext=False, timeout=60.0):
        super().__init__(timeout=timeout)
        self.bot_thread = bot_thread
        self.matches = matches[:25]
        self.playnext = playnext
        opts = []
        for i, m in enumerate(self.matches):
            raw = (m.get('display_name') or '').strip()
            label = (raw or f"#{i + 1}")[:100]
            opts.append(discord.SelectOption(label=label, value=str(i)))
        self.pick = discord.ui.Select(placeholder=bot_thread.tr.t('pick_track_placeholder'),
                                      min_values=1, max_values=1, options=opts)
        self.pick.callback = self._on_pick
        self.add_item(self.pick)

    async def _on_pick(self, interaction: discord.Interaction):
        if not check_interaction_roles(interaction, self.bot_thread.config.control_role_id,
                                       self.bot_thread.config.admin_role_id, check_admin=False):
            await interaction.response.send_message(self.bot_thread.tr.t('no_permission'), ephemeral=True)
            return
        idx = int(interaction.data['values'][0])
        match = self.matches[idx]
        guild_id = interaction.guild.id
        await interaction.response.defer()
        ctx = InteractionReplyContext(interaction)
        if guild_id not in self.bot_thread.queues:
            self.bot_thread.queues[guild_id] = PlaylistQueue()
        voice_client = interaction.guild.voice_client
        path = match['path']
        display_name = match['display_name']
        if self.playnext:
            if voice_client and voice_client.is_playing():
                self.bot_thread.queues[guild_id].add_user_track_next(path)
                await ctx.send(self.bot_thread.tr.t('track_added_next').format(display_name))
                self.bot_thread.log(self.bot_thread.tr.t('track_added_next_log').format(display_name))
            else:
                await self.bot_thread.play_audio(ctx, path, is_user=True)
        else:
            if voice_client and voice_client.is_playing():
                self.bot_thread.queues[guild_id].add_user_track(path)
                await ctx.send(self.bot_thread.tr.t('track_added').format(display_name))
                self.bot_thread.log(self.bot_thread.tr.t('track_added_queue_log').format(display_name))
            else:
                await self.bot_thread.play_audio(ctx, path, is_user=True)
        for item in self.children:
            item.disabled = True
        try:
            await interaction.edit_original_response(view=self)
        except Exception:
            pass


class DeleteConfirmView(discord.ui.View):
    def __init__(self, bot_thread, display_name, file_path, guild_id, timeout=60.0):
        super().__init__(timeout=timeout)
        self.bot_thread = bot_thread
        self.display_name = display_name
        self.file_path = file_path
        self.guild_id = guild_id
        b_ok = discord.ui.Button(label=bot_thread.tr.t('delete_button_confirm'), style=discord.ButtonStyle.danger, row=0)
        b_no = discord.ui.Button(label=bot_thread.tr.t('delete_button_cancel'), style=discord.ButtonStyle.secondary, row=0)
        b_ok.callback = self._on_confirm
        b_no.callback = self._on_cancel
        self.add_item(b_ok)
        self.add_item(b_no)

    async def _on_confirm(self, interaction: discord.Interaction):
        if not check_interaction_roles(interaction, None, self.bot_thread.config.admin_role_id, check_admin=True):
            await interaction.response.send_message(self.bot_thread.tr.t('no_permission'), ephemeral=True)
            return
        await interaction.response.defer()
        ctx = InteractionReplyContext(interaction)
        await self.bot_thread.delete_current_track_confirmed(ctx, self.file_path, self.display_name, self.guild_id)
        for item in self.children:
            item.disabled = True
        try:
            await interaction.edit_original_response(view=self)
        except Exception:
            pass

    async def _on_cancel(self, interaction: discord.Interaction):
        await interaction.response.edit_message(content=self.bot_thread.tr.t('delete_cancelled'), view=None)

class DiscordBotThread(QThread):
    log_signal = pyqtSignal(str)
    error_signal = pyqtSignal(str)
    music_list_updated = pyqtSignal(list)
    status_changed = pyqtSignal(bool)
    now_playing = pyqtSignal(str, str, int)
    update_volume_signal = pyqtSignal(float)
    add_track_from_gui = pyqtSignal(str, str)
    add_track_next_from_gui = pyqtSignal(str, str)
    play_track_now_from_gui = pyqtSignal(str, str)
    pause_signal = pyqtSignal()
    resume_signal = pyqtSignal()
    skip_signal = pyqtSignal()
    clear_queue_signal = pyqtSignal()
    update_progress_signal = pyqtSignal(int, int)
    bot_info_signal = pyqtSignal(str, bool)
    guilds_updated = pyqtSignal(list)
    pause_state_signal = pyqtSignal(bool)
    reconnect_signal = pyqtSignal(int, int)   # попытка, максимум
    spectrum_signal = pyqtSignal(list)         # список float 0..1 для спектра
    web_stop_requested = pyqtSignal()          # стоп из веб-панели → полная остановка потока (GUI)
    
    def __init__(self, config, translator):
        super().__init__()
        self.config = config
        self.tr = translator
        self.bot = None
        self.loop = None
        self.is_running = False
        self.queues = {}
        self.current_song = {}
        self.played_history = {}
        self.contexts = {}
        self.stop_command_issued = {}
        self._ready = False
        self.current_guild_id = None
        self.progress_timer = None
        self.bot_name = "Unknown"
        self.auto_connect_attempted = False
        # True после паузы; сохраняется при обрыве связи/переподключении. Сброс только при новом запуске потока бота.
        self.session_keep_paused = False
        self.sorted_music_files = []
        self.sorted_music_paths = []
        self.temp_playlist = {}
        self.temp_playlist_index = {}
        # Sleep timer
        # Reconnect
        self._reconnect_attempt = 0
        self._reconnect_task = None
        # Web server
        self._web_server = None
        self._web_runner = None
        # Флаг намеренного отключения (команда stop) — не реконнектиться
        self._intentional_disconnect = False
        # Таймеры пустого канала: guild_id -> asyncio.Task
        self._empty_channel_tasks = {}
        
        self.update_volume_signal.connect(self.on_volume_update)
        self.add_track_from_gui.connect(self.on_add_track_from_gui)
        self.add_track_next_from_gui.connect(self.on_add_track_next_from_gui)
        self.play_track_now_from_gui.connect(self.on_play_track_now_from_gui)
        self.pause_signal.connect(self.on_pause)
        self.resume_signal.connect(self.on_resume)
        self.skip_signal.connect(self.on_skip)
        self.clear_queue_signal.connect(self.on_clear_queue)
    
    def get_sorted_music_files(self):
        """Возвращает список файлов, отсортированный по display_name"""
        if not self.config.music_folder or not os.path.exists(self.config.music_folder):
            return []
        
        files = []
        
        try:
            for root, dirs, filenames in os.walk(self.config.music_folder):
                dirs.sort(key=lambda x: x.lower())
                filenames.sort(key=lambda x: x.lower())
                
                for filename in filenames:
                    if any(filename.lower().endswith(fmt) for fmt in self.config.supported_formats):
                        full_path = os.path.join(root, filename)
                        display_name = get_track_name_from_file(full_path)
                        files.append({
                            'path': full_path,
                            'name': filename,
                            'relative': os.path.relpath(full_path, self.config.music_folder),
                            'display_name': display_name
                        })
            
            files.sort(key=lambda x: x['display_name'].lower())
            self.sorted_music_paths = [f['path'] for f in files]
            self.sorted_music_files = files
            
        except Exception as e:
            self.log(self.tr.t('error_scanning_folder').format(str(e)), is_error=True)
        
        return files
    
    def get_all_music_files(self):
        if not self.sorted_music_files:
            self.get_sorted_music_files()
        return self.sorted_music_files
    
    def get_random_song(self):
        all_files = self.get_all_music_files()
        return random.choice(all_files)['path'] if all_files else None
    
    def get_next_song_no_repeats(self, guild_id):
        if not self.is_running:
            return None
        
        if not self.sorted_music_paths:
            self.get_sorted_music_files()
            if not self.sorted_music_paths:
                return None
        
        if guild_id not in self.temp_playlist:
            self.temp_playlist[guild_id] = self.sorted_music_paths.copy()
            self.temp_playlist_index[guild_id] = 0
            
            if self.config.autoplay_mode == "shuffle":
                random.shuffle(self.temp_playlist[guild_id])
                self.log(self.tr.t('playlist_reset'))
        
        playlist = self.temp_playlist[guild_id]
        
        if self.config.autoplay_mode == "shuffle":
            if not playlist:
                self.log(self.tr.t('all_songs_played'))
                self.temp_playlist[guild_id] = self.sorted_music_paths.copy()
                random.shuffle(self.temp_playlist[guild_id])
                playlist = self.temp_playlist[guild_id]
            
            return playlist.pop(0)
        
        else:
            current_index = self.temp_playlist_index[guild_id]
            
            if current_index >= len(playlist):
                self.log(self.tr.t('all_songs_played'))
                current_index = 0
                self.temp_playlist_index[guild_id] = 0
            
            song_path = playlist[current_index]
            self.temp_playlist_index[guild_id] = current_index + 1
            return song_path
    
    def get_next_auto_song(self, guild_id):
        if not self.config.autoplay_enabled:
            return None

        if not self.is_running:
            return None
        
        if not self.sorted_music_paths:
            self.get_sorted_music_files()
            if not self.sorted_music_paths:
                return None
        
        if self.config.exclude_repeats:
            return self.get_next_song_no_repeats(guild_id)
        
        if guild_id not in self.played_history:
            self.played_history[guild_id] = []
        
        if self.config.autoplay_mode == "shuffle":
            available = [p for p in self.sorted_music_paths if p not in self.played_history[guild_id][-5:]]
            if not available:
                available = self.sorted_music_paths
                self.played_history[guild_id] = []
            selected = random.choice(available)
        else:
            if not self.played_history[guild_id]:
                selected = self.sorted_music_paths[0]
            else:
                last_played = self.played_history[guild_id][-1]
                try:
                    last_index = self.sorted_music_paths.index(last_played)
                    next_index = last_index + 1
                    if next_index < len(self.sorted_music_paths):
                        selected = self.sorted_music_paths[next_index]
                    else:
                        selected = self.sorted_music_paths[0]
                except ValueError:
                    selected = self.sorted_music_paths[0]
        
        self.played_history[guild_id].append(selected)
        return selected
    
    def refresh_music_list(self):
        self.get_sorted_music_files()
        self.temp_playlist.clear()
        self.temp_playlist_index.clear()
        self.played_history.clear()
        return self.sorted_music_files
    
    def reset_temp_playlist(self, guild_id=None):
        if guild_id:
            if guild_id in self.temp_playlist:
                del self.temp_playlist[guild_id]
            if guild_id in self.temp_playlist_index:
                del self.temp_playlist_index[guild_id]
        else:
            self.temp_playlist.clear()
            self.temp_playlist_index.clear()
    
    async def delete_file_from_disk(self, file_path, ctx=None):
        """Удаляет файл с диска и обновляет списки"""
        try:
            if not os.path.exists(file_path):
                if ctx:
                    await ctx.send(self.tr.t('delete_file_not_found'))
                self.log(self.tr.t('delete_file_not_found'), is_error=True)
                return False
            
            # Получаем имя для лога
            display_name = get_track_name_from_file(file_path)
            
            # Удаляем файл
            os.remove(file_path)
            
            # Обновляем списки
            self.refresh_music_list()
            
            # Отправляем обновленный список в GUI
            self.music_list_updated.emit(self.sorted_music_files)
            
            if ctx:
                await ctx.send(self.tr.t('delete_success').format(display_name))
            self.log(self.tr.t('delete_success').format(display_name))
            return True
            
        except Exception as e:
            error_msg = self.tr.t('delete_error').format(str(e))
            if ctx:
                await ctx.send(error_msg)
            self.log(error_msg, is_error=True)
            return False
    
    async def ensure_voice_connection(self, ctx):
        try:
            if not ctx.author.voice:
                await ctx.send(self.tr.t('not_in_voice'))
                return None
            voice_client = ctx.guild.voice_client
            if not voice_client:
                voice_client = await ctx.author.voice.channel.connect()
            elif voice_client.channel != ctx.author.voice.channel:
                await voice_client.move_to(ctx.author.voice.channel)
            return voice_client
        except Exception as e:
            self.log(f"❌ Connection error: {str(e)}", is_error=True)
            return None
    
    async def auto_connect_to_channel(self):
        if not self.config.auto_connect_enabled:
            return False
        
        if not self.config.default_guild_id or not self.config.default_voice_channel_id or not self.config.default_text_channel_id:
            self.log("⚠️ " + self.tr.t('select_server_and_channel'))
            return False
        
        try:
            guild = self.bot.get_guild(int(self.config.default_guild_id))
            if not guild:
                self.log("⚠️ " + self.tr.t('server_not_found').format(self.config.default_guild_id))
                return False
            
            voice_channel = guild.get_channel(int(self.config.default_voice_channel_id))
            if not voice_channel:
                self.log("⚠️ " + self.tr.t('selected_channel_not_found'))
                return False
            
            if not isinstance(voice_channel, discord.VoiceChannel):
                self.log("⚠️ " + self.tr.t('channel_not_voice'))
                return False
            
            text_channel = guild.get_channel(int(self.config.default_text_channel_id))
            if not text_channel:
                self.log("⚠️ " + self.tr.t('selected_channel_not_found'))
                return False
            
            if not hasattr(text_channel, 'send'):
                self.log("⚠️ " + self.tr.t('channel_not_text'))
                return False
            
            voice_client = guild.voice_client
            if not voice_client:
                voice_client = await voice_channel.connect()
            elif voice_client.channel != voice_channel:
                await voice_client.move_to(voice_channel)
            
            self.current_guild_id = guild.id
            
            class FakeContext:
                def __init__(self, bot, guild, text_channel, voice_channel):
                    self.bot = bot
                    self.guild = guild
                    self.author = type('Author', (), {
                        'voice': type('Voice', (), {'channel': voice_channel})
                    })()
                    self.channel = text_channel
                
                async def send(self, message):
                    await self.channel.send(message)
            
            ctx = FakeContext(self.bot, guild, text_channel, voice_channel)
            self.contexts[guild.id] = ctx
            
            self.log(self.tr.t('connected_to_channel').format(voice_channel.name, guild.name))
            
            await ctx.send(f"{self.tr.t('discord_connected_to_channel')}")
            
            if self.config.autoplay_enabled and not self.session_keep_paused:
                random_song = self.get_next_auto_song(guild.id)
                if random_song:
                    await self.play_audio(ctx, random_song, is_user=False)
            
            return True
            
        except Exception as e:
            self.log(self.tr.t('failed_connect_channel').format(str(e)), is_error=True)
            return False
    
    async def play_audio(self, ctx, file_path, is_user=True, force_play=False):
        guild_id = ctx.guild.id
        if guild_id not in self.queues:
            self.queues[guild_id] = PlaylistQueue()
        voice_client = ctx.guild.voice_client
        display_name = get_track_name_from_file(file_path)
        
        # Если force_play=True, останавливаем текущий трек и играем этот
        if force_play and voice_client and voice_client.is_playing():
            voice_client.stop()
            # Очищаем очередь пользователя, чтобы этот трек точно заиграл
            self.queues[guild_id].clear_user_queue()
        
        if voice_client and voice_client.is_playing() and not force_play:
            if is_user:
                self.queues[guild_id].add_user_track(file_path)
                queue_info = self.queues[guild_id].get_queue_info()
                self.log(self.tr.t('track_added_queue').format(queue_info['user'], display_name))
            elif not self.queues[guild_id].has_user_tracks():
                self.queues[guild_id].add_auto_track(file_path)
                queue_info = self.queues[guild_id].get_queue_info()
                #self.log(self.tr.t('track_added_auto').format(queue_info['auto'], display_name))
            else:
                self.log(self.tr.t('skipping_auto').format(display_name))
            return
            
        if not os.path.exists(file_path):
            self.log(self.tr.t('file_not_found_log').format(os.path.basename(file_path)))
            await ctx.send(self.tr.t('file_not_found').format(display_name))
            next_track_info = self.queues[guild_id].get_next_track()
            if next_track_info[0]:
                await self.play_audio(ctx, next_track_info[0], next_track_info[1])
            elif self.config.autoplay_enabled and self.is_running:
                next_song = self.get_next_auto_song(guild_id)
                if next_song:
                    await self.play_audio(ctx, next_song, is_user=False)
            return
            
        voice_client = await self.ensure_voice_connection(ctx)
        if not voice_client:
            return
            
        if guild_id not in self.played_history:
            self.played_history[guild_id] = []
        self.played_history[guild_id].append(file_path)
        self.contexts[guild_id] = ctx
        self.current_guild_id = guild_id
        self.queues[guild_id].current_is_user = is_user
        
        if self.progress_timer:
            self.progress_timer.cancel()
        
        def update_progress():
            if guild_id in self.current_song:
                voice_client = ctx.guild.voice_client
                if voice_client and voice_client.is_playing():
                    total_time = self.current_song[guild_id].get('duration', 0)
                    if total_time > 0:
                        self.update_progress_signal.emit(0, total_time)
                    if self.loop and self.loop.is_running():
                        self.progress_timer = self.loop.call_later(1, update_progress)
        
        def play_next(error=None):
            if error:
                self.log(self.tr.t('playback_error_log').format(str(error)), is_error=True)
            saved_ctx = self.contexts.get(guild_id)
            if not saved_ctx:
                self.log(self.tr.t('context_not_found').format(guild_id))
                return
            if guild_id in self.current_song:
                del self.current_song[guild_id]
            self.update_progress_signal.emit(0, 0)
            if guild_id in self.stop_command_issued:
                self.log(self.tr.t('stop_command_issued'))
                self.now_playing.emit("⏹️ " + self.tr.t('stopped'), "", 0)
                return
            # Если бота нет в голосовом канале — не пытаться переподключиться самостоятельно
            vc = saved_ctx.guild.voice_client
            if not vc or not vc.is_connected():
                self.log(self.tr.t("log_no_voice"))
                self.now_playing.emit("⏹️ " + self.tr.t('stopped'), "", 0)
                return
            next_track_info = self.queues[guild_id].get_next_track()
            if next_track_info[0]:
                next_file, next_is_user = next_track_info
                next_name = get_track_name_from_file(next_file)
                track_type = "user" if next_is_user else "auto"
                future = asyncio.run_coroutine_threadsafe(self.play_audio(saved_ctx, next_file, next_is_user), self.loop)
                try:
                    future.result()
                except Exception:
                    pass
            elif self.config.autoplay_enabled:
                next_song = self.get_next_auto_song(guild_id)
                if next_song:
                    next_name = get_track_name_from_file(next_song)
                    future = asyncio.run_coroutine_threadsafe(self.play_audio(saved_ctx, next_song, is_user=False), self.loop)
                    try:
                        future.result()
                    except Exception:
                        pass
                else:
                    if self.is_running:
                        self.log(self.tr.t('no_tracks_autoplay'))
                        future = asyncio.run_coroutine_threadsafe(saved_ctx.send(self.tr.t('queue_empty')), self.loop)
                        try:
                            future.result()
                        except Exception:
                            pass
                        self.now_playing.emit("⏹️ " + self.tr.t('stopped'), "", 0)
            else:
                self.log(self.tr.t('playback_finished'))
                future = asyncio.run_coroutine_threadsafe(saved_ctx.send("⏹️ " + self.tr.t('playback_finished')), self.loop)
                try:
                    future.result()
                except Exception:
                    pass
                self.now_playing.emit("⏹️ " + self.tr.t('stopped'), "", 0)
        
        try:
            duration = 0
            try:
                import mutagen
                audio = mutagen.File(file_path)
                if audio:
                    duration = int(audio.info.length)
            except Exception:
                pass

            # Запускаем трек обычным образом
            audio_source = discord.FFmpegPCMAudio(file_path, executable=self.config.ffmpeg_path)
            audio_source = discord.PCMVolumeTransformer(audio_source, volume=self.config.volume)
            voice_client.play(audio_source, after=play_next)
            self.current_song[guild_id] = {'path': file_path, 'name': display_name, 'is_user': is_user, 'duration': duration}
            self.now_playing.emit(display_name, file_path, duration)
            if self.session_keep_paused:
                voice_client.pause()
                self.pause_state_signal.emit(True)
            else:
                self.pause_state_signal.emit(False)
            if self.loop and self.loop.is_running():
                self.loop.call_soon_threadsafe(update_progress)
            queue_info = self.queues[guild_id].get_queue_info()
            queue_status = self.tr.t('queue_status').format(queue_info['user'], queue_info['auto']) if queue_info['user'] > 0 or queue_info['auto'] > 0 else ""
            self.log(self.tr.t('playing').format(display_name, queue_status))
            await ctx.send(self.tr.t('now_playing_discord').format(display_name))
        except Exception as e:
            self.log(self.tr.t('playback_error_log').format(str(e)), is_error=True)
            await ctx.send(self.tr.t('playback_error'))
            next_track_info = self.queues[guild_id].get_next_track()
            if next_track_info[0]:
                await self.play_audio(ctx, next_track_info[0], next_track_info[1])
            elif self.config.autoplay_enabled:
                next_song = self.get_next_auto_song(guild_id)
                if next_song:
                    await self.play_audio(ctx, next_song, is_user=False)
    
    async def skip_track(self, ctx):
        guild_id = ctx.guild.id
        voice_client = ctx.guild.voice_client
        if voice_client and voice_client.is_playing():
            current = self.current_song.get(guild_id, {})
            current_name = current.get('name', 'unknown track')
            current_type = "👤 user" if current.get('is_user', False) else "♪ auto"
            self.log(self.tr.t('skipping_log').format(current_name))
            await ctx.send(self.tr.t('skipping').format(current_name))
            self.session_keep_paused = False
            voice_client.stop()
            if guild_id in self.current_song:
                del self.current_song[guild_id]
        elif voice_client and voice_client.is_paused():
            voice_client.stop()
            self.session_keep_paused = False
            self.pause_state_signal.emit(False)
            await ctx.send(self.tr.t('playback_stopped'))
            if guild_id in self.current_song:
                del self.current_song[guild_id]
            self.now_playing.emit("⏹️ " + self.tr.t('stopped'), "", 0)
        else:
            await ctx.send(self.tr.t('nothing_playing'))
    
    async def stop_playback(self, ctx):
        guild_id = ctx.guild.id
        voice_client = ctx.guild.voice_client
        if voice_client:
            if guild_id in self.queues:
                self.queues[guild_id].clear_all()
            self.session_keep_paused = False
            self.pause_state_signal.emit(False)
            self.stop_command_issued[guild_id] = True
            self._intentional_disconnect = True
            voice_client.stop()
            await voice_client.disconnect()
            if guild_id in self.current_song:
                del self.current_song[guild_id]
            self.now_playing.emit("⏹️ " + self.tr.t('stopped'), "", 0)
            self.log(self.tr.t('stopped_and_cleared_log'))
            await ctx.send(self.tr.t('stopped_and_cleared'))
            async def reset_flag():
                await asyncio.sleep(2)
                if guild_id in self.stop_command_issued:
                    del self.stop_command_issued[guild_id]
                self._intentional_disconnect = False
            asyncio.create_task(reset_flag())
    
    async def show_queue(self, ctx):
        guild_id = ctx.guild.id
        if guild_id not in self.queues:
            await ctx.send(self.tr.t('queue_empty'))
            return
        queue_info = self.queues[guild_id].get_queue_info()
        if queue_info['user'] == 0 and queue_info['auto'] == 0:
            await ctx.send(self.tr.t('queue_empty'))
            return
        response = self.tr.t('queue_header') + "\n"
        current = self.current_song.get(guild_id)
        if current:
            current_type = "👤" if current.get('is_user') else "♪"
            response += f"{self.tr.t('now_header')} {current_type} {current['name']}\n\n"
        if queue_info['user'] > 0:
            user_tracks = self.queues[guild_id].get_user_queue_list(10)
            response += self.tr.t('user_queue_header').format(queue_info['user']) + "\n"
            for i, track in enumerate(user_tracks, 1):
                response += f"{i}. {get_track_name_from_file(track)}\n"
            if queue_info['user'] > 10:
                response += self.tr.t('and_more').format(queue_info['user'] - 10) + "\n"
            response += "\n"
        if queue_info['auto'] > 0:
            auto_tracks = self.queues[guild_id].get_auto_queue_list(10)
            response += self.tr.t('auto_queue_header').format(queue_info['auto']) + "\n"
            for i, track in enumerate(auto_tracks, 1):
                response += f"{i}. {get_track_name_from_file(track)}\n"
            if queue_info['auto'] > 10:
                response += self.tr.t('and_more').format(queue_info['auto'] - 10) + "\n"
        await ctx.send(response)
    
    async def clear_queue(self, ctx):
        guild_id = ctx.guild.id
        if guild_id not in self.queues:
            await ctx.send(self.tr.t('queue_empty'))
            return
        user_count = len(self.queues[guild_id].user_queue)
        auto_count = len(self.queues[guild_id].auto_queue)
        total = user_count + auto_count
        if total == 0:
            await ctx.send(self.tr.t('queue_empty'))
            return
        self.queues[guild_id].user_queue.clear()
        self.queues[guild_id].auto_queue.clear()
        await ctx.send(self.tr.t('queue_cleared').format(user_count))
        self.log(self.tr.t('queue_cleared_log').format(user_count))
    
    async def delete_current_track_confirmed(self, ctx, file_path, display_name, guild_id):
        """Удаление текущего трека с диска после подтверждения (префикс или slash)."""
        await ctx.send(self.tr.t('delete_current'))
        voice_client = ctx.guild.voice_client
        if voice_client:
            if voice_client.is_playing() or voice_client.is_paused():
                voice_client.stop()
            if voice_client.source:
                voice_client.source.cleanup()
                voice_client.source = None
            await asyncio.sleep(1)
        if guild_id in self.current_song:
            del self.current_song[guild_id]
        if guild_id in self.queues:
            self.queues[guild_id].user_queue = [f for f in self.queues[guild_id].user_queue if f != file_path]
            self.queues[guild_id].auto_queue = [f for f in self.queues[guild_id].auto_queue if f != file_path]
        if guild_id in self.played_history:
            self.played_history[guild_id] = [f for f in self.played_history[guild_id] if f != file_path]
        if guild_id in self.temp_playlist:
            self.temp_playlist[guild_id] = [f for f in self.temp_playlist[guild_id] if f != file_path]
        self.now_playing.emit("⏹️ " + self.tr.t('stopped'), "", 0)
        await asyncio.sleep(0.5)
        try:
            os.remove(file_path)
            self.log(self.tr.t('delete_success').format(display_name))
            await ctx.send(self.tr.t('delete_success').format(display_name))
            self.refresh_music_list()
            self.music_list_updated.emit(self.sorted_music_files)
        except Exception as e:
            error_msg = self.tr.t('delete_error').format(str(e))
            await ctx.send(error_msg)
            self.log(error_msg, is_error=True)
            return
        next_track_info = self.queues[guild_id].get_next_track() if guild_id in self.queues else (None, False)
        if next_track_info[0]:
            await self.play_audio(ctx, next_track_info[0], next_track_info[1])
        elif self.config.autoplay_enabled:
            next_song = self.get_next_auto_song(guild_id)
            if next_song:
                await self.play_audio(ctx, next_song, is_user=False)
    
    async def update_volume_all_channels(self):
        try:
            updated_count = 0
            for guild in self.bot.guilds:
                voice_client = guild.voice_client
                if voice_client and voice_client.source and hasattr(voice_client.source, 'volume'):
                    voice_client.source.volume = self.config.volume
                    updated_count += 1
            if updated_count > 1:
                self.log(self.tr.t('volume_updated_all').format(updated_count))
        except Exception as e:
            self.log(self.tr.t('error_updating_all_volume').format(str(e)), is_error=True)
    
    def get_guilds_and_channels(self):
        guilds_data = []
        if not self.bot or not self._ready:
            return guilds_data
        
        for guild in self.bot.guilds:
            voice_channels = []
            text_channels = []
            
            for channel in guild.channels:
                if isinstance(channel, discord.VoiceChannel):
                    voice_channels.append({
                        'id': channel.id,
                        'name': channel.name,
                        'user_count': len(channel.members)
                    })
                
                if hasattr(channel, 'send'):
                    channel_type = "voice" if isinstance(channel, discord.VoiceChannel) else "text"
                    text_channels.append({
                        'id': channel.id,
                        'name': channel.name,
                        'type': channel_type,
                        'voice_channel': isinstance(channel, discord.VoiceChannel)
                    })
            
            guilds_data.append({
                'id': guild.id,
                'name': guild.name,
                'voice_channels': voice_channels,
                'text_channels': text_channels
            })
        
        return guilds_data
    
    def setup_commands(self):
        self.bot.remove_command('help')
        
        # Добавляем конфиг в бота для доступа из команд
        self.bot.config = self.config
        
        @self.bot.event
        async def on_ready():
            self.bot_name = self.bot.user.name
            self.log(self.tr.t('bot_ready').format(self.bot.user.name))
            self.log(self.tr.t('music_folder_log').format(self.config.music_folder))
            if self.config.autoplay_enabled:
                mode_text = self.tr.t('shuffle') if self.config.autoplay_mode == "shuffle" else self.tr.t('sequential')
                self.log(self.tr.t('auto_mode_log').format(mode_text))
            self.log(self.tr.t('volume_log').format(int(self.config.volume * 100)))
            
            if self.config.auto_connect_enabled:
                self.log(self.tr.t('auto_connect_enabled'))
                await self.auto_connect_to_channel()
            
            await self.bot.change_presence(activity=discord.Game(name="/help | !help | Music"))
            try:
                synced = await self.bot.tree.sync()
                self.log(self.tr.t('log_slash_synced').format(len(synced)))
            except Exception as e:
                self.log(self.tr.t('log_slash_sync_fail').format(e), is_error=True)
            files = self.get_sorted_music_files()
            self.music_list_updated.emit(files)
            self.log(self.tr.t('found_files_log').format(len(files)))
            self.status_changed.emit(True)
            self.bot_info_signal.emit(self.bot_name, self.config.autoplay_enabled)
            
            self._ready = True
            guilds_data = self.get_guilds_and_channels()
            self.guilds_updated.emit(guilds_data)
        
        @self.bot.event
        async def on_voice_state_update(member, before, after):
            guild = member.guild
            guild_id = guild.id

            # ── Обработка движений БОТА ──────────────────────────────────
            if member == self.bot.user:
                if before.channel is not None and after.channel is None:
                    # Бот отключён от канала
                    if self._intentional_disconnect:
                        self.log(self.tr.t("log_disconnected_intentional").format(before.channel.name))
                        self._intentional_disconnect = False
                        return
                    if not self.is_running:
                        # Остановка бота (в т.ч. из веба) — не автореконнект
                        return
                    self.log(self.tr.t("log_kicked").format(before.channel.name), is_error=True)
                    if guild_id in self.current_song:
                        del self.current_song[guild_id]
                        self.now_playing.emit("⏹️ " + self.tr.t('stopped'), "", 0)
                    # Отменяем таймер пустого канала
                    task = self._empty_channel_tasks.pop(guild_id, None)
                    if task:
                        task.cancel()
                    # Реконнект к голосовому каналу — только если включён автореконнект
                    # И только если было настроено автоподключение к конкретному каналу
                    if self.config.reconnect_enabled and self.config.auto_connect_enabled:
                        delay = self.config.reconnect_delay
                        self.log(self.tr.t("log_reconnect_voice").format(delay))
                        await asyncio.sleep(delay)
                        await self.auto_connect_to_channel()
                    elif self.config.reconnect_enabled:
                        self.log(self.tr.t("log_no_saved_channel"))
                    else:
                        self.log(self.tr.t("log_reconnect_disabled"))
                elif (before.channel is not None and after.channel is not None
                      and before.channel != after.channel):
                    self.log(self.tr.t("log_moved").format(before.channel.name, after.channel.name))
                return

            # ── Обработка движений ПОЛЬЗОВАТЕЛЕЙ ────────────────────────
            if self.config.empty_channel_action == "none":
                return

            vc = guild.voice_client
            if not vc or not vc.is_connected():
                return

            # Пользователь вышел из канала бота
            if (before.channel is not None and before.channel == vc.channel
                    and (after.channel is None or after.channel != vc.channel)):
                humans = [m for m in vc.channel.members if not m.bot]
                if not humans:
                    # Канал опустел — запускаем таймер
                    old_task = self._empty_channel_tasks.pop(guild_id, None)
                    if old_task:
                        old_task.cancel()
                    mins = self.config.empty_channel_timeout
                    self.log(self.tr.t("log_channel_empty").format(vc.channel.name, mins))
                    task = asyncio.ensure_future(
                        self._empty_channel_watch(guild_id, vc.channel.name))
                    self._empty_channel_tasks[guild_id] = task

            # Пользователь вошёл в канал бота
            elif (after.channel is not None and after.channel == vc.channel
                  and (before.channel is None or before.channel != vc.channel)):
                # Отменяем таймер — канал снова не пуст
                task = self._empty_channel_tasks.pop(guild_id, None)
                if task:
                    task.cancel()
                    self.log(self.tr.t("log_user_returned").format(member.display_name, vc.channel.name))
                # Если стояли на паузе из-за пустого канала — возобновляем
                if (self.config.empty_channel_action == "pause"
                        and vc.is_paused() and self.session_keep_paused):
                    vc.resume()
                    self.session_keep_paused = False
                    self.pause_state_signal.emit(False)
                    self.log(self.tr.t("log_resuming").format(member.display_name))
                    if guild_id in self.contexts:
                        await self.contexts[guild_id].send(
                            self.tr.t("log_resuming_discord").format(member.display_name))

        @self.bot.event
        async def on_error(event, *args, **kwargs):
            import traceback as _tb
            err = _tb.format_exc()
            self.log(self.tr.t("log_discord_error").format(event, err), is_error=True)

        @self.bot.event
        async def on_disconnect():
            if self.is_running:
                self.log(self.tr.t("log_discord_disconnected"), is_error=True)

        @self.bot.event
        async def on_resumed():
            self.log(self.tr.t("log_discord_resumed"))
            self._reconnect_attempt = 0
            self.reconnect_signal.emit(0, self.config.reconnect_max)

        

        @self.bot.command(name='play', aliases=['p', 'pl'])
        async def play(ctx, *, query=None):
            if not await check_user_roles(ctx, self.config.control_role_id, self.config.admin_role_id, check_admin=False):
                await ctx.send(self.tr.t('no_permission'))
                return
            
            if not self.config.music_folder:
                await ctx.send(self.tr.t('folder_not_specified'))
                return
            guild_id = ctx.guild.id
            if guild_id not in self.queues:
                self.queues[guild_id] = PlaylistQueue()
            if not query:
                self.log(self.tr.t('selecting_random'))
                random_song = self.get_next_auto_song(guild_id) if self.config.exclude_repeats else self.get_random_song()
                if random_song:
                    voice_client = ctx.guild.voice_client
                    if voice_client and voice_client.is_playing():
                        self.queues[guild_id].add_user_track(random_song)
                        display_name = get_track_name_from_file(random_song)
                        queue_info = self.queues[guild_id].get_queue_info()
                        await ctx.send(self.tr.t('track_added').format(display_name))
                        self.log(self.tr.t('random_added_queue').format(display_name))
                    else:
                        await self.play_audio(ctx, random_song, is_user=True)
                else:
                    await ctx.send(self.tr.t('no_tracks'))
                return
            all_files = self.get_all_music_files()
            matches = [f for f in all_files if query.lower() in f['display_name'].lower()]
            if not matches:
                await ctx.send(self.tr.t('tracks_not_found').format(query))
                return
            if len(matches) == 1:
                voice_client = ctx.guild.voice_client
                if voice_client and voice_client.is_playing():
                    self.queues[guild_id].add_user_track(matches[0]['path'])
                    queue_info = self.queues[guild_id].get_queue_info()
                    await ctx.send(self.tr.t('track_added').format(matches[0]['display_name']))
                    self.log(self.tr.t('track_added_queue_log').format(matches[0]['display_name']))
                else:
                    await self.play_audio(ctx, matches[0]['path'], is_user=True)
            else:
                response = self.tr.t('search_results') + "\n"
                for i, match in enumerate(matches[:10], 1):
                    response += f"{i}. {match['display_name']}\n"
                if len(matches) > 10:
                    response += self.tr.t('and_more').format(len(matches) - 10) + "\n"
                response += "\n" + self.tr.t('enter_number')
                await ctx.send(response)
                def check(m):
                    return m.author == ctx.author and m.channel == ctx.channel
                try:
                    msg = await self.bot.wait_for('message', timeout=30.0, check=check)
                    if msg.content.lower() in ['cancel', 'отмена']:
                        await ctx.send(self.tr.t('cancelled'))
                        return
                    if msg.content.isdigit():
                        idx = int(msg.content) - 1
                        if 0 <= idx < len(matches[:10]):
                            voice_client = ctx.guild.voice_client
                            if voice_client and voice_client.is_playing():
                                self.queues[guild_id].add_user_track(matches[idx]['path'])
                                queue_info = self.queues[guild_id].get_queue_info()
                                await ctx.send(self.tr.t('track_added').format(matches[idx]['display_name']))
                                self.log(self.tr.t('track_added_queue_log').format(matches[idx]['display_name']))
                            else:
                                await self.play_audio(ctx, matches[idx]['path'], is_user=True)
                        else:
                            await ctx.send(self.tr.t('invalid_number'))
                except asyncio.TimeoutError:
                    await ctx.send(self.tr.t('timeout'))
        
        @self.bot.command(name='playnext', aliases=['pn', 'next', 'pnx'])
        async def play_next(ctx, *, query=None):
            if not await check_user_roles(ctx, self.config.control_role_id, self.config.admin_role_id, check_admin=False):
                await ctx.send(self.tr.t('no_permission'))
                return
            
            if not query:
                await ctx.send("❌ Specify track name!")
                return
            if not self.config.music_folder:
                await ctx.send(self.tr.t('folder_not_specified'))
                return
            guild_id = ctx.guild.id
            if guild_id not in self.queues:
                self.queues[guild_id] = PlaylistQueue()
            all_files = self.get_all_music_files()
            matches = [f for f in all_files if query.lower() in f['display_name'].lower()]
            if not matches:
                await ctx.send(self.tr.t('tracks_not_found').format(query))
                return
            if len(matches) == 1:
                voice_client = ctx.guild.voice_client
                if voice_client and voice_client.is_playing():
                    self.queues[guild_id].add_user_track_next(matches[0]['path'])
                    await ctx.send(self.tr.t('track_added_next').format(matches[0]['display_name']))
                    self.log(self.tr.t('track_added_next_log').format(matches[0]['display_name']))
                else:
                    await self.play_audio(ctx, matches[0]['path'], is_user=True)
            else:
                response = self.tr.t('search_results') + "\n"
                for i, match in enumerate(matches[:10], 1):
                    response += f"{i}. {match['display_name']}\n"
                if len(matches) > 10:
                    response += self.tr.t('and_more').format(len(matches) - 10) + "\n"
                response += "\n" + self.tr.t('enter_number')
                await ctx.send(response)
                def check(m):
                    return m.author == ctx.author and m.channel == ctx.channel
                try:
                    msg = await self.bot.wait_for('message', timeout=30.0, check=check)
                    if msg.content.lower() in ['cancel', 'отмена']:
                        await ctx.send(self.tr.t('cancelled'))
                        return
                    if msg.content.isdigit():
                        idx = int(msg.content) - 1
                        if 0 <= idx < len(matches[:10]):
                            voice_client = ctx.guild.voice_client
                            if voice_client and voice_client.is_playing():
                                self.queues[guild_id].add_user_track_next(matches[idx]['path'])
                                await ctx.send(self.tr.t('track_added_next').format(matches[idx]['display_name']))
                                self.log(self.tr.t('track_added_next_log').format(matches[idx]['display_name']))
                            else:
                                await self.play_audio(ctx, matches[idx]['path'], is_user=True)
                        else:
                            await ctx.send(self.tr.t('invalid_number'))
                except asyncio.TimeoutError:
                    await ctx.send(self.tr.t('timeout'))
        
        @self.bot.command(name='volume', aliases=['vol', 'v'])
        async def volume(ctx, volume: int = None):
            if not await check_user_roles(ctx, self.config.control_role_id, self.config.admin_role_id, check_admin=False):
                await ctx.send(self.tr.t('no_permission'))
                return
            
            if volume is None:
                current_vol = int(self.config.volume * 100)
                await ctx.send(self.tr.t('current_volume').format(current_vol))
                return
            if 0 <= volume <= 100:
                old_volume = self.config.volume
                self.config.volume = volume / 100.0
                voice_client = ctx.guild.voice_client
                if voice_client and voice_client.source and hasattr(voice_client.source, 'volume'):
                    voice_client.source.volume = self.config.volume
                    await ctx.send(self.tr.t('volume_changed_discord').format(int(old_volume * 100), volume))
                    self.log(self.tr.t('volume_changed_track').format(volume))
                    await self.update_volume_all_channels()
                else:
                    await ctx.send(self.tr.t('volume_set').format(volume))
                    self.log(self.tr.t('volume_set_next').format(volume))
            else:
                await ctx.send(self.tr.t('volume_range'))
        
        @self.bot.command(name='skip', aliases=['s', 'n'])
        async def skip(ctx):
            if not await check_user_roles(ctx, self.config.control_role_id, self.config.admin_role_id, check_admin=False):
                await ctx.send(self.tr.t('no_permission'))
                return
            await self.skip_track(ctx)
        
        @self.bot.command(name='stop', aliases=['st', 'leave', 'dc'])
        async def stop(ctx):
            if not await check_user_roles(ctx, None, self.config.admin_role_id, check_admin=True):
                await ctx.send(self.tr.t('no_permission'))
                return
            await self.stop_playback(ctx)
        
        @self.bot.command(name='pause', aliases=['pa', 'pau'])
        async def pause(ctx):
            if not await check_user_roles(ctx, self.config.control_role_id, self.config.admin_role_id, check_admin=False):
                await ctx.send(self.tr.t('no_permission'))
                return
            voice_client = ctx.guild.voice_client
            if voice_client and voice_client.is_playing():
                voice_client.pause()
                self.session_keep_paused = True
                await ctx.send(self.tr.t('paused_discord'))
                self.log(self.tr.t('paused_log'))
                # Отправляем сигнал - на паузе
                self.pause_state_signal.emit(True)
            else:
                await ctx.send(self.tr.t('nothing_playing'))
        
        @self.bot.command(name='resume', aliases=['res', 'r', 'continue'])
        async def resume(ctx):
            if not await check_user_roles(ctx, self.config.control_role_id, self.config.admin_role_id, check_admin=False):
                await ctx.send(self.tr.t('no_permission'))
                return
            voice_client = ctx.guild.voice_client
            if voice_client and voice_client.is_paused():
                voice_client.resume()
                self.session_keep_paused = False
                await ctx.send(self.tr.t('resumed_discord'))
                self.log(self.tr.t('resumed_log'))
                # Отправляем сигнал - играет
                self.pause_state_signal.emit(False)
            else:
                await ctx.send(self.tr.t('nothing_playing'))
        
        @self.bot.command(name='queue', aliases=['q', 'list', 'ls'])
        async def queue(ctx):
            if not await check_user_roles(ctx, self.config.control_role_id, self.config.admin_role_id, check_admin=False):
                await ctx.send(self.tr.t('no_permission'))
                return
            await self.show_queue(ctx)
        
        @self.bot.command(name='current', aliases=['now', 'c', 'np'])
        async def current(ctx):
            if not await check_user_roles(ctx, self.config.control_role_id, self.config.admin_role_id, check_admin=False):
                await ctx.send(self.tr.t('no_permission'))
                return
            guild_id = ctx.guild.id
            if guild_id in self.current_song:
                volume = int(self.config.volume * 100)
                track_type = "👤 User" if self.current_song[guild_id].get('is_user', False) else "♪ Auto"
                queue_info = self.queues[guild_id].get_queue_info() if guild_id in self.queues else {'user': 0, 'auto': 0}
                await ctx.send(f"▶️ Now playing: **{self.current_song[guild_id]['name']}**\n"
                              f"📋 Queue: {queue_info['user']} user + {queue_info['auto']} auto")
            else:
                await ctx.send(self.tr.t('nothing_playing'))
        
        @self.bot.command(name='clear', aliases=['cl', 'cq'])
        async def clear(ctx):
            if not await check_user_roles(ctx, self.config.control_role_id, self.config.admin_role_id, check_admin=False):
                await ctx.send(self.tr.t('no_permission'))
                return
            await self.clear_queue(ctx)
        
        @self.bot.command(name='shuffle', aliases=['sh', 'rand'])
        async def shuffle(ctx):
            if not await check_user_roles(ctx, self.config.control_role_id, self.config.admin_role_id, check_admin=False):
                await ctx.send(self.tr.t('no_permission'))
                return
            self.config.autoplay_mode = "shuffle"
            if self.config.exclude_repeats:
                self.reset_temp_playlist(ctx.guild.id)
            await ctx.send(self.tr.t('shuffle_mode'))
            self.log(self.tr.t('shuffle_mode_log'))
        
        @self.bot.command(name='sequential', aliases=['seq', 'order'])
        async def sequential(ctx):
            if not await check_user_roles(ctx, self.config.control_role_id, self.config.admin_role_id, check_admin=False):
                await ctx.send(self.tr.t('no_permission'))
                return
            self.config.autoplay_mode = "sequential"
            if self.config.exclude_repeats:
                self.reset_temp_playlist(ctx.guild.id)
            await ctx.send(self.tr.t('sequential_mode'))
            self.log(self.tr.t('sequential_mode_log'))
        
        @self.bot.command(name='autoplay', aliases=['ap', 'auto'])
        async def autoplay(ctx):
            if not await check_user_roles(ctx, self.config.control_role_id, self.config.admin_role_id, check_admin=False):
                await ctx.send(self.tr.t('no_permission'))
                return
            self.config.autoplay_enabled = not self.config.autoplay_enabled
            if self.config.autoplay_enabled:
                await ctx.send(self.tr.t('autoplay_enabled'))
                self.log(self.tr.t('autoplay_enabled_log'))
            else:
                await ctx.send(self.tr.t('autoplay_disabled'))
                self.log(self.tr.t('autoplay_disabled_log'))
            self.bot_info_signal.emit(self.bot_name, self.config.autoplay_enabled)
        
        @self.bot.command(name='delete', aliases=['del', 'remove', 'rm'])
        async def delete(ctx):
            if not await check_user_roles(ctx, None, self.config.admin_role_id, check_admin=True):
                await ctx.send(self.tr.t('no_permission'))
                return
            
            """Удаляет текущий трек с диска"""
            guild_id = ctx.guild.id
            if guild_id not in self.current_song:
                await ctx.send(self.tr.t('nothing_playing'))
                return
            
            current_track = self.current_song[guild_id]
            file_path = current_track['path']
            display_name = current_track['name']
            
            if not os.path.exists(file_path):
                await ctx.send(self.tr.t('delete_file_not_found'))
                return
            
            # Запрашиваем подтверждение с требованием ввести "atomic"
            await ctx.send(f"⚠️ **{self.tr.t('delete_confirm').format(display_name)}**\nДля подтверждения введите: `atomic`")
            
            def check(m):
                return m.author == ctx.author and m.channel == ctx.channel and m.content.lower() == 'atomic'
            
            try:
                await self.bot.wait_for('message', timeout=30.0, check=check)
                await self.delete_current_track_confirmed(ctx, file_path, display_name, guild_id)
            except asyncio.TimeoutError:
                await ctx.send(self.tr.t('delete_timeout'))
            except Exception as e:
                await ctx.send(self.tr.t('delete_error').format(str(e)))
                self.log(self.tr.t('delete_error').format(str(e)), is_error=True)
        
        @self.bot.command(name='help', aliases=['h', 'commands', '?'])
        async def help_command(ctx):
            o = self.tr.t('help_alias_or')
            help_text = f"""
{self.tr.t('help_title')}
{self.tr.t('help_intro')}

{self.tr.t('help_main')}
{self.tr.t('cmd_play_random')} ({o} !p)
{self.tr.t('cmd_play_search')} ({o} !p {self.tr.t('help_plus_query')})
{self.tr.t('cmd_playnext')} ({o} !pn, !next)
{self.tr.t('cmd_skip')} ({o} !s, !n)
{self.tr.t('cmd_stop')} ({o} !st, !leave)
{self.tr.t('cmd_pause')} ({o} !pa)
{self.tr.t('cmd_resume')} ({o} !res, !r)

{self.tr.t('help_queue')}
{self.tr.t('cmd_queue')} ({o} !q, !list)
{self.tr.t('cmd_current')} ({o} !now, !np)
{self.tr.t('cmd_clear')} ({o} !cl, !cq)

{self.tr.t('help_settings')}
{self.tr.t('cmd_volume')} ({o} !vol, !v)
{self.tr.t('cmd_shuffle')} ({o} !sh, !rand)
{self.tr.t('cmd_sequential')} ({o} !seq, !order)
{self.tr.t('cmd_autoplay')} ({o} !ap, !auto)

{self.tr.t('cmd_delete')} ({o} !del, !rm)

{self.tr.t('help_slash')}

{self.tr.t('help_shorts')}

{self.tr.t('help_footer')}
            """
            await ctx.send(help_text)
        
        @self.bot.tree.error
        async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
            if isinstance(error, app_commands.CommandInvokeError) and error.original:
                err = error.original
                self.log(self.tr.t('log_discord_error').format('slash', f'{type(err).__name__}: {err}'), is_error=True)
            try:
                msg = self.tr.t('slash_user_error')
                if interaction.response.is_done():
                    await interaction.followup.send(msg, ephemeral=True)
                else:
                    await interaction.response.send_message(msg, ephemeral=True)
            except Exception:
                pass
        
        tr = self.tr
        cfg = self.config
        
        @self.bot.tree.command(name='play', description='Воспроизвести трек (без query — случайный)')
        @app_commands.describe(query='Часть названия; пусто = случайный трек')
        @app_commands.guild_only()
        async def slash_play(interaction: discord.Interaction, query: Optional[str] = None):
            if not check_interaction_roles(interaction, cfg.control_role_id, cfg.admin_role_id, check_admin=False):
                await interaction.response.send_message(tr.t('no_permission'), ephemeral=True)
                return
            if not cfg.music_folder:
                await interaction.response.send_message(tr.t('folder_not_specified'), ephemeral=True)
                return
            guild_id = interaction.guild.id
            if guild_id not in self.queues:
                self.queues[guild_id] = PlaylistQueue()
            q = (query or '').strip()
            if not q:
                await interaction.response.defer()
                ctx = InteractionReplyContext(interaction)
                self.log(tr.t('selecting_random'))
                random_song = self.get_next_auto_song(guild_id) if cfg.exclude_repeats else self.get_random_song()
                if random_song:
                    voice_client = interaction.guild.voice_client
                    if voice_client and voice_client.is_playing():
                        self.queues[guild_id].add_user_track(random_song)
                        display_name = get_track_name_from_file(random_song)
                        await ctx.send(tr.t('track_added').format(display_name))
                        self.log(tr.t('random_added_queue').format(display_name))
                    else:
                        await self.play_audio(ctx, random_song, is_user=True)
                else:
                    await ctx.send(tr.t('no_tracks'))
                return
            all_files = self.get_all_music_files()
            matches = [f for f in all_files if q.lower() in f['display_name'].lower()]
            if not matches:
                await interaction.response.send_message(tr.t('tracks_not_found').format(q), ephemeral=True)
                return
            if len(matches) == 1:
                await interaction.response.defer()
                ctx = InteractionReplyContext(interaction)
                voice_client = interaction.guild.voice_client
                path = matches[0]['path']
                if voice_client and voice_client.is_playing():
                    self.queues[guild_id].add_user_track(path)
                    await ctx.send(tr.t('track_added').format(matches[0]['display_name']))
                    self.log(tr.t('track_added_queue_log').format(matches[0]['display_name']))
                else:
                    await self.play_audio(ctx, path, is_user=True)
                return
            view = TrackPickView(self, matches, playnext=False)
            await interaction.response.send_message(tr.t('slash_pick_track_prompt'), view=view)
        
        @self.bot.tree.command(name='playnext', description='Добавить трек следующим в очереди')
        @app_commands.describe(query='Фрагмент названия трека')
        @app_commands.guild_only()
        async def slash_playnext(interaction: discord.Interaction, query: Optional[str] = None):
            if not check_interaction_roles(interaction, cfg.control_role_id, cfg.admin_role_id, check_admin=False):
                await interaction.response.send_message(tr.t('no_permission'), ephemeral=True)
                return
            q = (query or '').strip()
            if not q:
                await interaction.response.send_message(tr.t('slash_playnext_need_query'), ephemeral=True)
                return
            if not cfg.music_folder:
                await interaction.response.send_message(tr.t('folder_not_specified'), ephemeral=True)
                return
            guild_id = interaction.guild.id
            if guild_id not in self.queues:
                self.queues[guild_id] = PlaylistQueue()
            all_files = self.get_all_music_files()
            matches = [f for f in all_files if q.lower() in f['display_name'].lower()]
            if not matches:
                await interaction.response.send_message(tr.t('tracks_not_found').format(q), ephemeral=True)
                return
            if len(matches) == 1:
                await interaction.response.defer()
                ctx = InteractionReplyContext(interaction)
                voice_client = interaction.guild.voice_client
                path = matches[0]['path']
                if voice_client and voice_client.is_playing():
                    self.queues[guild_id].add_user_track_next(path)
                    await ctx.send(tr.t('track_added_next').format(matches[0]['display_name']))
                    self.log(tr.t('track_added_next_log').format(matches[0]['display_name']))
                else:
                    await self.play_audio(ctx, path, is_user=True)
                return
            view = TrackPickView(self, matches, playnext=True)
            await interaction.response.send_message(tr.t('slash_pick_track_prompt'), view=view)
        
        @self.bot.tree.command(name='skip', description='Пропустить текущий трек')
        @app_commands.guild_only()
        async def slash_skip(interaction: discord.Interaction):
            if not check_interaction_roles(interaction, cfg.control_role_id, cfg.admin_role_id, check_admin=False):
                await interaction.response.send_message(tr.t('no_permission'), ephemeral=True)
                return
            await interaction.response.defer()
            await self.skip_track(InteractionReplyContext(interaction))
        
        @self.bot.tree.command(name='stop', description='Остановить и отключиться от голоса')
        @app_commands.guild_only()
        async def slash_stop(interaction: discord.Interaction):
            if not check_interaction_roles(interaction, None, cfg.admin_role_id, check_admin=True):
                await interaction.response.send_message(tr.t('no_permission'), ephemeral=True)
                return
            await interaction.response.defer()
            await self.stop_playback(InteractionReplyContext(interaction))
        
        @self.bot.tree.command(name='pause', description='Пауза')
        @app_commands.guild_only()
        async def slash_pause(interaction: discord.Interaction):
            if not check_interaction_roles(interaction, cfg.control_role_id, cfg.admin_role_id, check_admin=False):
                await interaction.response.send_message(tr.t('no_permission'), ephemeral=True)
                return
            voice_client = interaction.guild.voice_client
            if voice_client and voice_client.is_playing():
                voice_client.pause()
                self.session_keep_paused = True
                await interaction.response.send_message(tr.t('paused_discord'))
                self.log(tr.t('paused_log'))
                self.pause_state_signal.emit(True)
            else:
                await interaction.response.send_message(tr.t('nothing_playing'), ephemeral=True)
        
        @self.bot.tree.command(name='resume', description='Продолжить воспроизведение')
        @app_commands.guild_only()
        async def slash_resume(interaction: discord.Interaction):
            if not check_interaction_roles(interaction, cfg.control_role_id, cfg.admin_role_id, check_admin=False):
                await interaction.response.send_message(tr.t('no_permission'), ephemeral=True)
                return
            voice_client = interaction.guild.voice_client
            if voice_client and voice_client.is_paused():
                voice_client.resume()
                self.session_keep_paused = False
                await interaction.response.send_message(tr.t('resumed_discord'))
                self.log(tr.t('resumed_log'))
                self.pause_state_signal.emit(False)
            else:
                await interaction.response.send_message(tr.t('nothing_playing'), ephemeral=True)
        
        @self.bot.tree.command(name='queue', description='Показать очередь')
        @app_commands.guild_only()
        async def slash_queue(interaction: discord.Interaction):
            if not check_interaction_roles(interaction, cfg.control_role_id, cfg.admin_role_id, check_admin=False):
                await interaction.response.send_message(tr.t('no_permission'), ephemeral=True)
                return
            await interaction.response.defer()
            await self.show_queue(InteractionReplyContext(interaction))
        
        @self.bot.tree.command(name='current', description='Сейчас играет')
        @app_commands.guild_only()
        async def slash_current(interaction: discord.Interaction):
            if not check_interaction_roles(interaction, cfg.control_role_id, cfg.admin_role_id, check_admin=False):
                await interaction.response.send_message(tr.t('no_permission'), ephemeral=True)
                return
            guild_id = interaction.guild.id
            if guild_id in self.current_song:
                queue_info = self.queues[guild_id].get_queue_info() if guild_id in self.queues else {'user': 0, 'auto': 0}
                await interaction.response.send_message(
                    f"▶️ Now playing: **{self.current_song[guild_id]['name']}**\n"
                    f"📋 Queue: {queue_info['user']} user + {queue_info['auto']} auto")
            else:
                await interaction.response.send_message(tr.t('nothing_playing'), ephemeral=True)
        
        @self.bot.tree.command(name='clear', description='Очистить очередь')
        @app_commands.guild_only()
        async def slash_clear(interaction: discord.Interaction):
            if not check_interaction_roles(interaction, cfg.control_role_id, cfg.admin_role_id, check_admin=False):
                await interaction.response.send_message(tr.t('no_permission'), ephemeral=True)
                return
            await interaction.response.defer()
            await self.clear_queue(InteractionReplyContext(interaction))
        
        @self.bot.tree.command(name='volume', description='Показать или установить громкость')
        @app_commands.describe(percent='0–100; не указывайте, чтобы узнать текущую')
        @app_commands.guild_only()
        async def slash_volume(interaction: discord.Interaction, percent: Optional[int] = None):
            if not check_interaction_roles(interaction, cfg.control_role_id, cfg.admin_role_id, check_admin=False):
                await interaction.response.send_message(tr.t('no_permission'), ephemeral=True)
                return
            if percent is None:
                await interaction.response.send_message(tr.t('current_volume').format(int(cfg.volume * 100)))
                return
            if 0 <= percent <= 100:
                old_volume = cfg.volume
                cfg.volume = percent / 100.0
                voice_client = interaction.guild.voice_client
                if voice_client and voice_client.source and hasattr(voice_client.source, 'volume'):
                    voice_client.source.volume = cfg.volume
                    await interaction.response.send_message(tr.t('volume_changed_discord').format(int(old_volume * 100), percent))
                    self.log(tr.t('volume_changed_track').format(percent))
                    await self.update_volume_all_channels()
                else:
                    await interaction.response.send_message(tr.t('volume_set').format(percent))
                    self.log(tr.t('volume_set_next').format(percent))
            else:
                await interaction.response.send_message(tr.t('volume_range'), ephemeral=True)
        
        @self.bot.tree.command(name='shuffle', description='Автоплейлист: перемешивание')
        @app_commands.guild_only()
        async def slash_shuffle(interaction: discord.Interaction):
            if not check_interaction_roles(interaction, cfg.control_role_id, cfg.admin_role_id, check_admin=False):
                await interaction.response.send_message(tr.t('no_permission'), ephemeral=True)
                return
            cfg.autoplay_mode = "shuffle"
            if cfg.exclude_repeats:
                self.reset_temp_playlist(interaction.guild.id)
            await interaction.response.send_message(tr.t('shuffle_mode'))
            self.log(tr.t('shuffle_mode_log'))
        
        @self.bot.tree.command(name='sequential', description='Автоплейлист: по порядку')
        @app_commands.guild_only()
        async def slash_sequential(interaction: discord.Interaction):
            if not check_interaction_roles(interaction, cfg.control_role_id, cfg.admin_role_id, check_admin=False):
                await interaction.response.send_message(tr.t('no_permission'), ephemeral=True)
                return
            cfg.autoplay_mode = "sequential"
            if cfg.exclude_repeats:
                self.reset_temp_playlist(interaction.guild.id)
            await interaction.response.send_message(tr.t('sequential_mode'))
            self.log(tr.t('sequential_mode_log'))
        
        @self.bot.tree.command(name='autoplay', description='Включить или выключить автоплейлист')
        @app_commands.guild_only()
        async def slash_autoplay(interaction: discord.Interaction):
            if not check_interaction_roles(interaction, cfg.control_role_id, cfg.admin_role_id, check_admin=False):
                await interaction.response.send_message(tr.t('no_permission'), ephemeral=True)
                return
            cfg.autoplay_enabled = not cfg.autoplay_enabled
            if cfg.autoplay_enabled:
                await interaction.response.send_message(tr.t('autoplay_enabled'))
                self.log(tr.t('autoplay_enabled_log'))
            else:
                await interaction.response.send_message(tr.t('autoplay_disabled'))
                self.log(tr.t('autoplay_disabled_log'))
            self.bot_info_signal.emit(self.bot_name, cfg.autoplay_enabled)
        
        @self.bot.tree.command(name='delete', description='Удалить текущий трек с диска (админ)')
        @app_commands.guild_only()
        async def slash_delete(interaction: discord.Interaction):
            if not check_interaction_roles(interaction, None, cfg.admin_role_id, check_admin=True):
                await interaction.response.send_message(tr.t('no_permission'), ephemeral=True)
                return
            guild_id = interaction.guild.id
            if guild_id not in self.current_song:
                await interaction.response.send_message(tr.t('nothing_playing'), ephemeral=True)
                return
            current_track = self.current_song[guild_id]
            file_path = current_track['path']
            display_name = current_track['name']
            if not os.path.exists(file_path):
                await interaction.response.send_message(tr.t('delete_file_not_found'), ephemeral=True)
                return
            warn = tr.t('delete_confirm').format(display_name)
            view = DeleteConfirmView(self, display_name, file_path, guild_id)
            await interaction.response.send_message(f"⚠️ **{warn}**", view=view, ephemeral=True)
        
        @self.bot.tree.command(name='help', description='Список команд')
        @app_commands.guild_only()
        async def slash_help(interaction: discord.Interaction):
            o = tr.t('help_alias_or')
            help_text = f"""
{tr.t('help_title')}
{tr.t('help_intro')}

{tr.t('help_main')}
{tr.t('cmd_play_random')} ({o} !p)
{tr.t('cmd_play_search')} ({o} !p {tr.t('help_plus_query')})
{tr.t('cmd_playnext')} ({o} !pn, !next)
{tr.t('cmd_skip')} ({o} !s, !n)
{tr.t('cmd_stop')} ({o} !st, !leave)
{tr.t('cmd_pause')} ({o} !pa)
{tr.t('cmd_resume')} ({o} !res, !r)

{tr.t('help_queue')}
{tr.t('cmd_queue')} ({o} !q, !list)
{tr.t('cmd_current')} ({o} !now, !np)
{tr.t('cmd_clear')} ({o} !cl, !cq)

{tr.t('help_settings')}
{tr.t('cmd_volume')} ({o} !vol, !v)
{tr.t('cmd_shuffle')} ({o} !sh, !rand)
{tr.t('cmd_sequential')} ({o} !seq, !order)
{tr.t('cmd_autoplay')} ({o} !ap, !auto)

{tr.t('cmd_delete')} ({o} !del, !rm)

{tr.t('help_slash')}

{tr.t('help_shorts')}

{tr.t('help_footer')}
"""
            await interaction.response.send_message(help_text, ephemeral=True)
    
    def on_pause(self):
        if not self.bot or not self.loop or not self.loop.is_running() or not self.current_guild_id:
            self.log("⚠️ " + self.tr.t('bot_not_active'))
            return
        async def pause():
            try:
                guild = self.bot.get_guild(self.current_guild_id)
                if not guild:
                    self.log("⚠️ " + self.tr.t('guild_not_found'))
                    return
                voice_client = guild.voice_client
                if voice_client and voice_client.is_playing():
                    voice_client.pause()
                    self.session_keep_paused = True
                    self.pause_state_signal.emit(True)
                    self.log(self.tr.t('pause_from_gui'))
                    if self.current_guild_id in self.contexts:
                        ctx = self.contexts[self.current_guild_id]
                        await ctx.send(self.tr.t('paused_discord'))
                else:
                    self.log("⚠️ " + self.tr.t('nothing_playing_log'))
            except Exception as e:
                self.log("❌ " + self.tr.t('error_pausing').format(str(e)), is_error=True)
        asyncio.run_coroutine_threadsafe(pause(), self.loop)
    
    def on_resume(self):
        if not self.bot or not self.loop or not self.loop.is_running() or not self.current_guild_id:
            self.log("⚠️ " + self.tr.t('bot_not_active'))
            return
        async def resume():
            try:
                guild = self.bot.get_guild(self.current_guild_id)
                if not guild:
                    self.log("⚠️ " + self.tr.t('guild_not_found'))
                    return
                voice_client = guild.voice_client
                if voice_client and voice_client.is_paused():
                    voice_client.resume()
                    self.session_keep_paused = False
                    self.pause_state_signal.emit(False)
                    self.log(self.tr.t('resumed_from_gui'))
                    if self.current_guild_id in self.contexts:
                        ctx = self.contexts[self.current_guild_id]
                        await ctx.send(self.tr.t('resumed_discord'))
                else:
                    self.log("⚠️ " + self.tr.t('not_paused'))
            except Exception as e:
                self.log("❌ " + self.tr.t('error_resuming').format(str(e)), is_error=True)
        asyncio.run_coroutine_threadsafe(resume(), self.loop)
    
    def on_skip(self):
        if not self.bot or not self.loop or not self.loop.is_running() or not self.current_guild_id:
            self.log("⚠️ " + self.tr.t('bot_not_active'))
            return
        async def skip():
            try:
                guild = self.bot.get_guild(self.current_guild_id)
                if not guild:
                    self.log("⚠️ " + self.tr.t('guild_not_found'))
                    return
                if self.current_guild_id in self.contexts:
                    ctx = self.contexts[self.current_guild_id]
                    await self.skip_track(ctx)
                else:
                    self.log("⚠️ " + self.tr.t('no_context_skip'))
            except Exception as e:
                self.log("❌ " + self.tr.t('error_skipping').format(str(e)), is_error=True)
        asyncio.run_coroutine_threadsafe(skip(), self.loop)
    
    def on_clear_queue(self):
        if not self.bot or not self.loop or not self.loop.is_running() or not self.current_guild_id:
            self.log("⚠️ " + self.tr.t('bot_not_active'))
            return
        async def clear():
            try:
                guild = self.bot.get_guild(self.current_guild_id)
                if not guild:
                    self.log("⚠️ " + self.tr.t('guild_not_found'))
                    return
                if self.current_guild_id in self.contexts:
                    ctx = self.contexts[self.current_guild_id]
                    await self.clear_queue(ctx)
                else:
                    self.log("⚠️ " + self.tr.t('no_context_clear'))
            except Exception as e:
                self.log("❌ " + self.tr.t('error_clearing').format(str(e)), is_error=True)
        asyncio.run_coroutine_threadsafe(clear(), self.loop)
    
    def on_volume_update(self, new_volume):
        if not self.bot or not self.loop or not self.loop.is_running():
            self.log("⚠️ " + self.tr.t('bot_not_active_volume'))
            return
        async def update_all_volumes():
            try:
                updated_count = 0
                for guild in self.bot.guilds:
                    voice_client = guild.voice_client
                    if voice_client and voice_client.source and hasattr(voice_client.source, 'volume'):
                        voice_client.source.volume = new_volume
                        updated_count += 1
            except Exception as e:
                self.log("❌ " + self.tr.t('error_updating_volume').format(str(e)), is_error=True)
        asyncio.run_coroutine_threadsafe(update_all_volumes(), self.loop)
    
    def on_add_track_from_gui(self, file_path, display_name):
        if not self.bot or not self.loop or not self.loop.is_running():
            self.log("⚠️ " + self.tr.t('bot_not_active_track'))
            return
        async def add_track():
            try:
                for guild in self.bot.guilds:
                    voice_client = guild.voice_client
                    if voice_client:
                        guild_id = guild.id
                        self.current_guild_id = guild_id
                        if guild_id not in self.queues:
                            self.queues[guild_id] = PlaylistQueue()
                        if voice_client.is_playing():
                            self.queues[guild_id].add_user_track(file_path)
                            queue_info = self.queues[guild_id].get_queue_info()
                            self.log(self.tr.t('track_added_queue').format(queue_info['user'], display_name))
                        else:
                            self.log(self.tr.t('track_playing_gui').format(display_name, guild.name))
                            if guild_id in self.contexts:
                                ctx = self.contexts[guild_id]
                                await self.play_audio(ctx, file_path, is_user=True)
                            else:
                                self.log("⚠️ " + self.tr.t('no_context_playback').format(guild.name))
                        return
                self.log("⚠️ " + self.tr.t('no_voice_connections'))
            except Exception as e:
                self.log("❌ " + self.tr.t('error_adding_track').format(str(e)), is_error=True)
        asyncio.run_coroutine_threadsafe(add_track(), self.loop)
    
    def on_add_track_next_from_gui(self, file_path, display_name):
        if not self.bot or not self.loop or not self.loop.is_running():
            self.log("⚠️ " + self.tr.t('bot_not_active_track'))
            return
        async def add_track_next():
            try:
                for guild in self.bot.guilds:
                    voice_client = guild.voice_client
                    if voice_client:
                        guild_id = guild.id
                        self.current_guild_id = guild_id
                        if guild_id not in self.queues:
                            self.queues[guild_id] = PlaylistQueue()
                        if voice_client.is_playing():
                            self.queues[guild_id].add_user_track_next(file_path)
                            queue_info = self.queues[guild_id].get_queue_info()
                            self.log(self.tr.t('track_added_next').format(display_name))
                        else:
                            self.log(self.tr.t('track_playing_gui').format(display_name, guild.name))
                            if guild_id in self.contexts:
                                ctx = self.contexts[guild_id]
                                await self.play_audio(ctx, file_path, is_user=True)
                            else:
                                self.log("⚠️ " + self.tr.t('no_context_playback').format(guild.name))
                        return
                self.log("⚠️ " + self.tr.t('no_voice_connections'))
            except Exception as e:
                self.log("❌ " + self.tr.t('error_adding_track').format(str(e)), is_error=True)
        asyncio.run_coroutine_threadsafe(add_track_next(), self.loop)
    
    def on_play_track_now_from_gui(self, file_path, display_name):
        if not self.bot or not self.loop or not self.loop.is_running():
            self.log("⚠️ " + self.tr.t('bot_not_active_track'))
            return
        async def play_now():
            try:
                for guild in self.bot.guilds:
                    voice_client = guild.voice_client
                    if voice_client:
                        guild_id = guild.id
                        self.current_guild_id = guild_id
                        if guild_id not in self.queues:
                            self.queues[guild_id] = PlaylistQueue()
                        
                        if guild_id in self.contexts:
                            ctx = self.contexts[guild_id]
                            await self.play_audio(ctx, file_path, is_user=True, force_play=True)
                        else:
                            self.log("⚠️ " + self.tr.t('no_context_playback').format(guild.name))
                        return
                self.log("⚠️ " + self.tr.t('no_voice_connections'))
            except Exception as e:
                self.log("❌ " + self.tr.t('error_adding_track').format(str(e)), is_error=True)
        asyncio.run_coroutine_threadsafe(play_now(), self.loop)
    
    def log(self, message, is_error=False):
        timestamp = datetime.datetime.now().strftime('%H:%M:%S')
        (self.error_signal if is_error else self.log_signal).emit(f'[{timestamp}] {message}')
    
    # ─────────────────────────────────────────────────────────────
    #  Web server (aiohttp)
    # ─────────────────────────────────────────────────────────────
    async def _start_web_server(self):
        try:
            from aiohttp import web as aio_web
        except ImportError:
            self.log(self.tr.t("log_aiohttp_missing"), is_error=True)
            return

        async def _api_status(request):
            guild_id = self.current_guild_id
            current = self.current_song.get(guild_id, {})
            queue_info = self.queues.get(guild_id, PlaylistQueue()).get_queue_info() if guild_id else {'user': 0, 'auto': 0}
            vc = None
            if self.bot and guild_id:
                guild = self.bot.get_guild(guild_id)
                if guild:
                    vc = guild.voice_client
            data = {
                'running': self.is_running,
                'bot_name': self.bot_name,
                'now_playing': current.get('name', ''),
                'duration': current.get('duration', 0),
                'is_paused': bool(vc and vc.is_paused()) if vc else False,
                'is_playing': bool(vc and vc.is_playing()) if vc else False,
                'volume': int(self.config.volume * 100),
                'autoplay': self.config.autoplay_enabled,
                'autoplay_mode': self.config.autoplay_mode,
                'queue_user': queue_info['user'],
                'queue_auto': queue_info['auto'],
                'language': self.config.language if self.config.language in ('ru', 'en') else 'en',
            }
            import json as _json
            return aio_web.Response(text=_json.dumps(data, ensure_ascii=False),
                                    content_type='application/json')

        async def _api_action(request):
            import json as _json
            try:
                body = await request.json()
            except Exception:
                return aio_web.Response(status=400, text='bad json')
            action = body.get('action', '')
            if action == 'pause':
                self.on_pause()
            elif action == 'resume':
                self.on_resume()
            elif action == 'skip':
                self.on_skip()
            elif action == 'stop':
                # Полная остановка бота, как кнопка «Стоп» в GUI (не только дисконнект с голоса)
                self.web_stop_requested.emit()
            elif action == 'volume':
                v = int(body.get('value', 50))
                self.config.volume = max(0, min(100, v)) / 100.0
                self.update_volume_signal.emit(self.config.volume)
            elif action == 'play':
                query = body.get('query', '')
                all_files = self.get_all_music_files()
                matches = [f for f in all_files if query.lower() in f['display_name'].lower()]
                if matches and self.loop and self.loop.is_running():
                    self.add_track_from_gui.emit(matches[0]['path'], matches[0]['display_name'])
            return aio_web.Response(text='ok')

        async def _api_tracks(request):
            import json as _json
            q = request.rel_url.query.get('q', '').lower()
            files = self.get_all_music_files()
            result = [{'name': f['display_name'], 'path': f['path']}
                      for f in files if not q or q in f['display_name'].lower()]
            return aio_web.Response(text=_json.dumps(result, ensure_ascii=False),
                                    content_type='application/json')

        async def _index(request):
            html = _WEB_HTML
            return aio_web.Response(text=html, content_type='text/html')

        app = aio_web.Application()
        app.router.add_get('/', _index)
        app.router.add_get('/api/status', _api_status)
        app.router.add_post('/api/action', _api_action)
        app.router.add_get('/api/tracks', _api_tracks)

        from aiohttp import web as aio_web2
        runner = aio_web2.AppRunner(app)
        await runner.setup()
        site = aio_web2.TCPSite(runner, '0.0.0.0', self.config.web_port)
        try:
            await site.start()
            self._web_runner = runner
            self.log(self.tr.t("log_web_started").format(self.config.web_port))
        except Exception as e:
            self.log(self.tr.t("log_web_failed").format(e), is_error=True)

    async def _stop_web_server(self):
        if self._web_runner:
            try:
                await self._web_runner.cleanup()
            except Exception:
                pass
            self._web_runner = None

    # ─────────────────────────────────────────────────────────────
    #  Авто-действие при пустом голосовом канале
    # ─────────────────────────────────────────────────────────────
    async def _empty_channel_watch(self, guild_id, channel_name):
        """Ждёт N минут. Если канал по-прежнему пуст — делает действие."""
        try:
            timeout_sec = max(1, self.config.empty_channel_timeout) * 60
            await asyncio.sleep(timeout_sec)

            if not self.is_running:
                return

            guild = self.bot.get_guild(guild_id)
            if not guild:
                return
            vc = guild.voice_client
            if not vc or not vc.is_connected():
                return

            # Считаем людей в канале (не ботов)
            humans = [m for m in vc.channel.members if not m.bot]
            if humans:
                # Кто-то вернулся — отменяем
                return

            action = self.config.empty_channel_action
            if action == "pause":
                if vc.is_playing():
                    vc.pause()
                    self.session_keep_paused = True
                    self.pause_state_signal.emit(True)
                    self.log(self.tr.t("log_empty_pause").format(vc.channel.name, self.config.empty_channel_timeout))
                    if guild_id in self.contexts:
                        await self.contexts[guild_id].send(
                            self.tr.t("log_empty_pause_discord").format(self.config.empty_channel_timeout))
            elif action == "disconnect":
                self.log(self.tr.t("log_empty_disconnect").format(vc.channel.name, self.config.empty_channel_timeout))
                if guild_id in self.contexts:
                    await self.contexts[guild_id].send(
                        self.tr.t("log_empty_disconnect_discord").format(self.config.empty_channel_timeout))
                # Блокируем play_next и авто-реконнект
                self.stop_command_issued[guild_id] = True
                self._intentional_disconnect = True
                if guild_id in self.queues:
                    self.queues[guild_id].clear_all()
                self.session_keep_paused = False
                if guild_id in self.current_song:
                    del self.current_song[guild_id]
                vc.stop()
                await vc.disconnect()
                self.now_playing.emit("⏹️ " + self.tr.t('stopped'), "", 0)
                # Сбрасываем флаг через 3 сек — чтобы при ручном !play снова работало
                async def _reset():
                    await asyncio.sleep(3)
                    self.stop_command_issued.pop(guild_id, None)
                asyncio.ensure_future(_reset())
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.log(self.tr.t("log_empty_error").format(e), is_error=True)
        finally:
            self._empty_channel_tasks.pop(guild_id, None)

    # ─────────────────────────────────────────────────────────────
    #  Reconnect / run_bot
    # ─────────────────────────────────────────────────────────────
    def run_bot(self):
        if not self.config.token:
            self.log(self.tr.t('token_not_specified'), is_error=True)
            return

        async def start_bot():
            self._reconnect_attempt = 0
            while self.is_running:
                try:
                    intents = discord.Intents.default()
                    intents.message_content = True
                    intents.voice_states = True
                    self.bot = commands.Bot(command_prefix='!', intents=intents)
                    self.setup_commands()
                    if self._reconnect_attempt > 0:
                        self.log(self.tr.t("log_reconnect_attempt").format(self._reconnect_attempt, self.config.reconnect_max))
                        self.reconnect_signal.emit(self._reconnect_attempt, self.config.reconnect_max)
                    else:
                        self.log(self.tr.t('starting_bot'))

                    if self.config.web_enabled:
                        await self._start_web_server()

                    await self.bot.start(self.config.token)

                except discord.errors.LoginFailure as e:
                    self.log(self.tr.t("log_invalid_token").format(e), is_error=True)
                    self.status_changed.emit(False)
                    break

                except (discord.errors.ConnectionClosed,
                        discord.errors.GatewayNotFound,
                        discord.errors.HTTPException,
                        OSError) as e:
                    if not self.is_running:
                        break
                    self._reconnect_attempt += 1
                    self.log(self.tr.t("log_connection_lost").format(e), is_error=True)
                    if not self.config.reconnect_enabled or self._reconnect_attempt > self.config.reconnect_max:
                        self.log(self.tr.t("log_reconnect_exceeded"), is_error=True)
                        self.status_changed.emit(False)
                        break
                    await self._stop_web_server()
                    delay = self.config.reconnect_delay * min(self._reconnect_attempt, 4)
                    self.log(self.tr.t("log_retry").format(delay, self._reconnect_attempt, self.config.reconnect_max), is_error=True)
                    self.reconnect_signal.emit(self._reconnect_attempt, self.config.reconnect_max)
                    await asyncio.sleep(delay)
                    try:
                        await self.bot.close()
                    except Exception:
                        pass

                except Exception as e:
                    if not self.is_running:
                        break
                    self._reconnect_attempt += 1
                    self.log(self.tr.t("log_critical_bot").format(e), is_error=True)
                    if "privileged intent" in str(e).lower():
                        self.log(self.tr.t("log_privileged_intents_hint"), is_error=True)
                    if not self.config.reconnect_enabled or self._reconnect_attempt > self.config.reconnect_max:
                        self.status_changed.emit(False)
                        break
                    await self._stop_web_server()
                    delay = self.config.reconnect_delay * min(self._reconnect_attempt, 4)
                    self.log(self.tr.t("log_retry_short").format(delay), is_error=True)
                    await asyncio.sleep(delay)
                    try:
                        await self.bot.close()
                    except Exception:
                        pass
                else:
                    # bot.start вернулся без исключения — штатный выход
                    break

            await self._stop_web_server()
            self.status_changed.emit(False)

        async def shutdown_bot():
            await self._stop_web_server()
            if self.bot:
                try:
                    await self.bot.close()
                except Exception:
                    pass

        try:
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.loop.run_until_complete(start_bot())
        except Exception as e:
            self.log(self.tr.t('critical_error').format(str(e)), is_error=True)
        finally:
            try:
                if self.loop and not self.loop.is_closed():
                    self.loop.run_until_complete(shutdown_bot())
                    self.loop.close()
            except Exception:
                pass
            self.status_changed.emit(False)
    
    def run(self):
        self.is_running = True
        self.run_bot()
    
    def stop(self):
        self.log(self.tr.t('stopping_bot'))
        self.is_running = False
        self._intentional_disconnect = True  # блокируем реконнект в on_voice_state_update
        if self.loop and self.loop.is_running():
            async def shutdown():
                await self._stop_web_server()
                if self.bot:
                    try:
                        await self.bot.close()
                    except Exception:
                        pass
            asyncio.run_coroutine_threadsafe(shutdown(), self.loop)
            import time
            time.sleep(2)
            try:
                self.loop.call_soon_threadsafe(self.loop.stop)
            except Exception:
                pass
        self.status_changed.emit(False)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        # Иконка окна — icon.ico рядом с приложением (работает и в .exe)
        _icon_path = resource_path("icon.ico")
        _app_icon = QIcon(_icon_path) if os.path.isfile(_icon_path) else QIcon()
        self.setWindowIcon(_app_icon)

        # Отображать в панели задач Windows (явно, чтобы работало даже при hide())
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.Window)

        # Предзагружаем WinAPI-иконки (применим после show())
        self._win_icons = set_taskbar_icon(_icon_path)
        self._tray_icon = None
        self._tray_show_action = None
        self._tray_pause_action = None
        self._tray_skip_action = None
        self._tray_quit_action = None

        self.config = BotConfig()
        self.tr = Translator(self.config.language)
        self.bot_thread = None
        self.settings_loaded = False
        self.is_playing = False
        self.is_paused = False
        self.current_track_path = None
        self.current_album_art = None
        self.progress_timer = QTimer()
        self.progress_timer.timeout.connect(self.update_progress_display)
        self.progress_timer.setInterval(1000)
        self.current_position = 0
        self.total_duration = 0
        self.bot_name = None
        self.cached_music_files = []
        
        self.loaded_guild_id = None
        self.loaded_voice_channel_id = None
        self.loaded_text_channel_id = None
        self.loaded_auto_connect = False

        # Заглушки для виджетов, созданных в init_ui
        self.reconnect_status_label = QLabel()
        self.spectrum_widget = SpectrumWidget()
        self.empty_ch_action_combo = QComboBox()
        self.empty_ch_action_combo.addItems([
            self.tr.t("empty_ch_none"),
            self.tr.t("empty_ch_pause"),
            self.tr.t("empty_ch_disconnect"),
        ])
        self.empty_ch_timeout_input = QLineEdit("1")

        # Иконка в системном трее Windows (после self.tr)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self._tray_icon = QSystemTrayIcon(_app_icon, self)
            self._tray_icon.setToolTip("Local Music Bot")
            tray_menu = QMenu()
            tray_menu.setStyleSheet("""
                QMenu {
                    background-color: #3c3c3c;
                    color: white;
                    border: 1px solid #555;
                    padding: 4px;
                }
                QMenu::item { padding: 6px 20px; }
                QMenu::item:selected { background-color: #4a4a4a; }
                QMenu::separator { height: 1px; background: #555; margin: 4px 0; }
                QMenu::item:disabled { color: #666; }
            """)
            self._tray_show_action = QAction(self.tr.t("tray_show"), self)
            self._tray_show_action.triggered.connect(self._tray_show_window)
            tray_menu.addAction(self._tray_show_action)
            tray_menu.addSeparator()

            self._tray_pause_action = QAction(self.tr.t("tray_pause"), self)
            self._tray_pause_action.setEnabled(False)
            self._tray_pause_action.triggered.connect(self._tray_toggle_playback)
            tray_menu.addAction(self._tray_pause_action)

            self._tray_skip_action = QAction(self.tr.t("tray_skip"), self)
            self._tray_skip_action.setEnabled(False)
            self._tray_skip_action.triggered.connect(self.skip_track)
            tray_menu.addAction(self._tray_skip_action)

            tray_menu.addSeparator()
            self._tray_quit_action = QAction(self.tr.t("tray_quit"), self)
            self._tray_quit_action.triggered.connect(self._tray_quit)
            tray_menu.addAction(self._tray_quit_action)
            self._tray_icon.setContextMenu(tray_menu)
            self._tray_icon.activated.connect(self._on_tray_activated)
            self._tray_icon.show()

        self.init_ui()
        self.load_settings()
        
        sys.stdout = EmittingStream(self.python_output)
        sys.stderr = EmittingStream(self.python_output)
        
        QTimer.singleShot(100, self.check_autostart)
        # Применяем иконку в панели задач Windows после отрисовки окна
        QTimer.singleShot(200, self._apply_taskbar_icon)
    
    def _apply_taskbar_icon(self):
        """Применяет иконку к панели задач Windows через WinAPI после показа окна."""
        if sys.platform != 'win32' or not self._win_icons:
            return
        try:
            hwnd = int(self.winId())
            apply_taskbar_icon(hwnd, self._win_icons)
        except Exception:
            pass

    def check_autostart(self):
        if self.config.autostart:
            self.log_message(self.tr.t('autostart_enabled'))
            if not self.config.token:
                self.log_message(self.tr.t('autostart_failed').format(self.tr.t('enter_token')), is_error=True)
            elif not self.config.music_folder or not os.path.exists(self.config.music_folder):
                self.log_message(self.tr.t('autostart_failed').format(self.tr.t('select_folder')), is_error=True)
            else:
                self.start_bot()
    
    def update_ui_language(self):
        self.setWindowTitle(self.tr.t('window_title'))
        if not self.is_playing:
            self.now_playing_label.setText(self.tr.t('not_playing'))
        self.time_elapsed_label.setText(self.tr.t('time_elapsed'))
        self.time_total_label.setText(self.tr.t('time_total'))
        self.status_text.setText(self.tr.t('bot_running') if self.bot_thread and self.bot_thread.is_running else self.tr.t('bot_stopped_status'))
        self.bot_control_btn.setText(self.tr.t('stop') if self.bot_thread and self.bot_thread.is_running else self.tr.t('start'))
        self.playback_control_btn.setText(self.tr.t('resume') if self.is_paused else self.tr.t('pause'))
        self.skip_btn.setText(self.tr.t('skip'))
        self.clear_queue_btn.setText(self.tr.t('clear_queue'))
        self.now_playing_group.setTitle(self.tr.t('now_playing_group'))
        
        if hasattr(self, 'control_group'):
            self.control_group.setTitle(self.tr.t('playback_control'))
        if hasattr(self, 'logs_group'):
            self.logs_group.setTitle(self.tr.t('events'))
        
        for i in range(self.tabs.count()):
            self.tabs.setTabText(i, [self.tr.t('music_tab'), self.tr.t('settings_tab'), self.tr.t('info_tab'), self.tr.t('errors_tab')][i])
        self.search_label.setText(self.tr.t('search'))
        self.search_input.setPlaceholderText(self.tr.t('search_placeholder'))
        self.refresh_btn.setText(self.tr.t('refresh'))
        self.settings_group_ui.setTitle(self.tr.t('settings_cat_ui_web'))
        self.settings_group_discord.setTitle(self.tr.t('settings_cat_discord'))
        self.settings_group_library.setTitle(self.tr.t('settings_cat_library'))
        self.token_label.setText(self.tr.t('bot_token'))
        self.music_folder_label.setText(self.tr.t('music_folder'))
        self.music_folder_display.set_tooltip_hint(self.tr.t('music_folder_open_tooltip'))
        self.browse_btn.setText(self.tr.t('browse'))
        self.ffmpeg_label.setText(self.tr.t('ffmpeg'))
        if hasattr(self, 'ffmpeg_display'):
            self.ffmpeg_display.set_tooltip_hint(self.tr.t('ffmpeg_open_tooltip'))
        if hasattr(self, 'wallpaper_path_display'):
            self.wallpaper_path_display.set_tooltip_hint(self.tr.t('wallpaper_open_tooltip'))
        self.ffmpeg_browse_btn.setText(self.tr.t('browse'))
        self.volume_label_prefix.setText(self.tr.t('volume'))
        self.autoplay_check.setText(self.tr.t('enable_autoplay'))
        self.autoplay_mode_label.setText(self.tr.t('autoplay_mode'))
        self.language_label.setText(self.tr.t('language'))
        self.autostart_check.setText(self.tr.t('autostart'))
        self.show_album_art_check.setText(self.tr.t('show_album_art'))
        if hasattr(self, 'wallpaper_enable_check'):
            self.wallpaper_enable_check.setText(self.tr.t('enable_wallpaper'))
        if hasattr(self, 'wallpaper_file_label'):
            self.wallpaper_file_label.setText(self.tr.t('wallpaper_file'))
        if hasattr(self, 'wallpaper_browse_btn'):
            self.wallpaper_browse_btn.setText(self.tr.t('browse'))
        self.exclude_repeats_check.setText(self.tr.t('exclude_repeats'))
        self.exclude_repeats_check.setToolTip(self.tr.t('exclude_repeats_desc'))
        
        # Ролевая защита - обновляем текст
        if hasattr(self, 'enable_role_protection'):
            self.enable_role_protection.setText(self.tr.t('enable_role_protection'))
        if hasattr(self, 'control_role_label'):
            self.control_role_label.setText(self.tr.t('control_role'))
        if hasattr(self, 'admin_role_label'):
            self.admin_role_label.setText(self.tr.t('admin_role'))
        
        if False:  # channel_group merged into behaviour_group
            pass  # channel_group merged into behaviour_group
        self.auto_connect_check.setText(self.tr.t('enable_auto_connect'))
        self.select_server_label.setText(self.tr.t('select_server'))
        self.select_voice_channel_label.setText(self.tr.t('select_voice_channel'))
        self.select_text_channel_label.setText(self.tr.t('select_text_channel'))
        self.refresh_channels_btn.setText(self.tr.t('refresh_channels'))
        
        self.clear_errors_btn.setText(self.tr.t('clear_errors'))

        if hasattr(self, 'reconnect_check'):
            self.reconnect_check.setText(self.tr.t('reconnect_check_lbl'))
        if hasattr(self, 'reconnect_delay_label'):
            self.reconnect_delay_label.setText(self.tr.t('reconnect_delay_lbl'))
        if hasattr(self, 'reconnect_max_label'):
            self.reconnect_max_label.setText(self.tr.t('reconnect_max_lbl'))
        if hasattr(self, 'empty_ch_action_label'):
            self.empty_ch_action_label.setText(self.tr.t('empty_ch_action_lbl'))
        if hasattr(self, 'empty_ch_timeout_label'):
            self.empty_ch_timeout_label.setText(self.tr.t('empty_ch_timeout_lbl'))
        if hasattr(self, 'empty_ch_hint_label'):
            self.empty_ch_hint_label.setText(self.tr.t('empty_ch_hint'))
        if hasattr(self, 'web_enable_check'):
            self.web_enable_check.setText(self.tr.t('web_enable'))
        if hasattr(self, 'ffmpeg_auto_btn'):
            self.ffmpeg_auto_btn.setText(self.tr.t('ffmpeg_auto_btn'))
        if hasattr(self, 'web_open_btn'):
            self.web_open_btn.setText(self.tr.t('web_open_btn'))
        if hasattr(self, 'web_port_label'):
            self.web_port_label.setText(self.tr.t('web_port_lbl'))
        if hasattr(self, 'empty_ch_action_combo'):
            _cur = self.empty_ch_action_combo.currentIndex()
            self.empty_ch_action_combo.blockSignals(True)
            self.empty_ch_action_combo.clear()
            self.empty_ch_action_combo.addItems([
                self.tr.t('empty_ch_none'),
                self.tr.t('empty_ch_pause'),
                self.tr.t('empty_ch_disconnect'),
            ])
            self.empty_ch_action_combo.setCurrentIndex(_cur)
            self.empty_ch_action_combo.blockSignals(False)
        # Tray actions
        if hasattr(self, '_tray_show_action') and self._tray_show_action:
            self._tray_show_action.setText(self.tr.t('tray_show'))
        if hasattr(self, '_tray_pause_action') and self._tray_pause_action:
            self._tray_pause_action.setText(
                self.tr.t('tray_resume') if self.is_paused else self.tr.t('tray_pause'))
        if hasattr(self, '_tray_skip_action') and self._tray_skip_action:
            self._tray_skip_action.setText(self.tr.t('tray_skip'))
        if hasattr(self, '_tray_quit_action') and self._tray_quit_action:
            self._tray_quit_action.setText(self.tr.t('tray_quit'))
        self.check_music_folder()
        if hasattr(self, 'info_text'):
            self.info_text.setHtml(self.get_info_html())
    
    def _info_commands_table_rows(self):
        t = self.tr.t

        def ex(*names):
            return ', '.join(f'!{n}' for n in names)

        rows = [
            ('/play', f"!play · {ex('p', 'pl')}", f"{t('info_random_track')} / {t('info_search_track')}"),
            ('/playnext', f"!playnext · {ex('pn', 'next', 'pnx')}", t('info_add_next')),
            ('/skip', f"!skip · {ex('s', 'n')}", t('info_skip')),
            ('/stop', f"!stop · {ex('st', 'leave', 'dc')}", t('info_stop')),
            ('/pause', f"!pause · {ex('pa', 'pau')}", t('info_pause')),
            ('/resume', f"!resume · {ex('res', 'r', 'continue')}", t('info_resume')),
            ('/queue', f"!queue · {ex('q', 'list', 'ls')}", t('info_show_queue')),
            ('/current', f"!current · {ex('now', 'c', 'np')}", t('info_current_track')),
            ('/clear', f"!clear · {ex('cl', 'cq')}", t('info_clear_queue')),
            ('/volume', f"!volume · {ex('vol', 'v')}", t('info_volume')),
            ('/shuffle', f"!shuffle · {ex('sh', 'rand')}", t('info_shuffle_mode')),
            ('/sequential', f"!sequential · {ex('seq', 'order')}", t('info_sequential_mode')),
            ('/autoplay', f"!autoplay · {ex('ap', 'auto')}", t('info_toggle_autoplay')),
            ('/delete', f"!delete · {ex('del', 'remove', 'rm')}", t('info_delete_track_short')),
            ('/help', f"!help · {ex('h', 'commands', '?')}", t('info_cmd_help_desc')),
        ]
        return ''.join(
            f"<tr><td class='command'>{sl}</td><td class='command'>{pr}</td><td>{d}</td></tr>"
            for sl, pr, d in rows)

    def get_info_html(self):
        return f"""
        <style>
            h2 {{ color: #2196F3; }}
            h3 {{ color: #64B5F6; margin-top: 15px; }}
            .app-version {{ color: #888; font-size: 12px; margin: 4px 0 12px 0; }}
            .tips {{ background: #333; padding: 10px; border-radius: 5px; margin: 10px 0; }}
            .perm-col {{ margin: 12px 0 6px 0; color: #90CAF9; font-size: 13px; }}
            ul.perm-list {{ margin: 0 0 4px 0; padding-left: 22px; }}
            ul.perm-list li {{ margin: 5px 0; }}
            .command {{ background: #3c3c3c; padding: 3px 8px; border-radius: 3px; font-family: monospace; }}
            code {{ font-family: monospace; background: #444; padding: 1px 5px; border-radius: 3px; font-size: 12px; }}
            .instr-step {{ margin: 10px 0; line-height: 1.45; }}
            a {{ color: #64B5F6; text-decoration: none; }}
            a:hover {{ text-decoration: underline; }}
        </style>
        
        <h2>{self.tr.t('info_title')}</h2>
        <p class='app-version'><b>{self.tr.t('version')} {APP_VERSION}</b></p>
        
        <h3>{self.tr.t('info_commands_intro_title')}</h3>
        <div class='tips'><p>{self.tr.t('info_commands_intro_body')}</p></div>
        
        <h3>{self.tr.t('commands_title')}</h3>
        <table style='border-collapse: collapse; width: 100%;'>
        <tr><th style='background: #333; padding: 8px;'>{self.tr.t('info_cmd_table_col_slash')}</th><th style='background: #333; padding: 8px;'>{self.tr.t('info_cmd_table_col_exclam')}</th><th style='background: #333; padding: 8px;'>{self.tr.t('info_description_col')}</th></tr>
        {self._info_commands_table_rows()}
        </table>
        
        <h3>{self.tr.t('info_where_title')}</h3>
        <div class='tips'><p>{self.tr.t('info_where_body')}</p></div>
        
        <h3>{self.tr.t('info_perms_title')}</h3>
        <div class='tips'>
            <p class='instr-step'><b>1.</b> {self.tr.t('info_perms_step1')}</p>
            <p class='instr-step'><b>2.</b> {self.tr.t('info_perms_step2')}</p>
            <p class='instr-step'><b>3.</b> {self.tr.t('info_perms_step3')}</p>
            <p class='instr-step'><b>4.</b> {self.tr.t('info_perms_step4')}</p>
            <p class='perm-col'><b>{self.tr.t('info_perms_col_general')}</b></p>
            <ul class='perm-list'>
                <li><b>View Channels</b> — {self.tr.t('info_perm_view_channels')}</li>
            </ul>
            <p class='perm-col'><b>{self.tr.t('info_perms_col_text')}</b></p>
            <ul class='perm-list'>
                <li><b>Send Messages</b> — {self.tr.t('info_perm_send_messages')}</li>
                <li><b>Embed Links</b> — {self.tr.t('info_perm_embed_links')}</li>
                <li><b>Read Message History</b> — {self.tr.t('info_perm_read_history')}</li>
                <li><b>Use Slash Commands</b> — {self.tr.t('info_perm_slash')}</li>
            </ul>
            <p class='perm-col'><b>{self.tr.t('info_perms_col_voice')}</b></p>
            <ul class='perm-list'>
                <li><b>Connect</b> — {self.tr.t('info_perm_connect')}</li>
                <li><b>Speak</b> — {self.tr.t('info_perm_speak')}</li>
                <li><b>Use Voice Activity</b> — {self.tr.t('info_perm_voice_activity')}</li>
            </ul>
        </div>
        
        <h3>{self.tr.t('info_roles_title')}</h3>
        <div class='tips'><p>{self.tr.t('info_roles_body')}</p></div>
        
        <h3>{self.tr.t('how_to_use')}</h3>
        <div class='tips'>
            <p><b>1. {self.tr.t('first_step')}</b><br>
            {self.tr.t('first_step_desc')}</p>
            <p><b>2. {self.tr.t('second_step')}</b><br>
            {self.tr.t('second_step_desc')}</p>
            <p><b>3. {self.tr.t('third_step')}</b><br>
            {self.tr.t('third_step_desc')}</p>
            <p><b>4. {self.tr.t('fourth_step')}</b><br>
            {self.tr.t('fourth_step_desc')}</p>
        </div>
        
        <h3>{self.tr.t('formats_title')}</h3>
        <p><b>{self.tr.t('info_formats')}</b> MP3, FLAC, M4A, WAV, OGG, AAC, MP4</p>
        """
    
    def init_ui(self):
        self.setWindowTitle(self.tr.t('window_title'))
        self.setGeometry(300, 100, 1100, 850)
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout = QHBoxLayout(central_widget)
        main_layout.addWidget(main_splitter)
        
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_panel.setMaximumWidth(400)
        
        self.now_playing_group = QGroupBox(self.tr.t('now_playing_group'))
        self.now_playing_group.setStyleSheet("""
            QGroupBox {
            font-weight: bold;
            border: 1px solid #444;
            border-radius: 8px;
            margin-top: 1ex;
            padding-top: 10px;
            color: white;
            background: transparent;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
            }
        """)
        
        now_playing_layout = QHBoxLayout()
        self.cover_label = QLabel()
        self.cover_label.setFixedSize(100, 100)
        self.cover_label.setStyleSheet("""
            border: 2px solid #2196F3;
            border-radius: 10px;
            background-color: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 1,
                                            stop: 0 #2b2b2b, stop: 1 #3c3c3c);
        """)
        self.cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover_label.setText(self.tr.t('no_cover'))
        now_playing_layout.addWidget(self.cover_label)
        
        track_info_layout = QVBoxLayout()
        self.now_playing_label = QLabel(self.tr.t('not_playing'))
        self.now_playing_label.setStyleSheet("""
            font-weight: bold;
            font-size: 14px;
            color: #2196F3;
            padding: 5px;
            background: rgba(33, 150, 243, 0.1);
            border-radius: 5px;
        """)
        self.now_playing_label.setWordWrap(True)
        track_info_layout.addWidget(self.now_playing_label)
        
        progress_layout = QHBoxLayout()
        self.time_elapsed_label = QLabel(self.tr.t('time_elapsed'))
        self.time_elapsed_label.setStyleSheet("font-size: 10px; color: #888;")
        progress_layout.addWidget(self.time_elapsed_label)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: none;
                border-radius: 3px;
                background-color: #3c3c3c;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 0,
                                          stop: 0 #2196F3, stop: 1 #1976D2);
                border-radius: 3px;
            }
        """)
        progress_layout.addWidget(self.progress_bar)
        
        self.time_total_label = QLabel(self.tr.t('time_total'))
        self.time_total_label.setStyleSheet("font-size: 10px; color: #888;")
        progress_layout.addWidget(self.time_total_label)
        track_info_layout.addLayout(progress_layout)
        
        time_display_layout = QHBoxLayout()
        self.current_time_label = QLabel("0:00")
        self.current_time_label.setStyleSheet("""
            font-size: 12px;
            font-family: monospace;
            color: #2196F3;
            font-weight: bold;
        """)
        time_display_layout.addWidget(self.current_time_label)
        time_display_layout.addStretch()
        
        self.total_time_label = QLabel("0:00")
        self.total_time_label.setStyleSheet("""
            font-size: 12px;
            font-family: monospace;
            color: #888;
        """)
        time_display_layout.addWidget(self.total_time_label)
        track_info_layout.addLayout(time_display_layout)
        
        now_playing_layout.addLayout(track_info_layout)

        # Спектроанализатор под обложкой и треком
        np_vbox = QVBoxLayout()
        np_vbox.addLayout(now_playing_layout)
        # Переиспользуем уже созданный в __init__ виджет
        np_vbox.addWidget(self.spectrum_widget)
        self.now_playing_group.setLayout(np_vbox)
        left_layout.addWidget(self.now_playing_group)
        
        status_frame = QFrame()
        status_frame.setStyleSheet("""
            QFrame {
                background-color: #2b2b2b;
                border: 1px solid #444;
                border-radius: 5px;
                padding: 5px;
            }
        """)
        status_layout = QHBoxLayout(status_frame)
        status_layout.setContentsMargins(8, 5, 8, 5)
        status_layout.setSpacing(10)
        
        self.status_light = QLabel("●")
        self.status_light.setStyleSheet("color: #ff6b6b; font-size: 16px;")
        status_layout.addWidget(self.status_light)
        
        self.status_text = QLabel(self.tr.t('bot_stopped_status'))
        self.status_text.setStyleSheet("font-weight: bold; font-size: 12px; color: #e0e0e0;")
        status_layout.addWidget(self.status_text)
        
        self.bot_name_label = QLabel("")
        self.bot_name_label.setStyleSheet("font-size: 11px;")
        self.bot_name_label.setVisible(False)
        status_layout.addWidget(self.bot_name_label)
        
        status_layout.addStretch()
        
        self.autoplay_indicator = QLabel("")
        self.autoplay_indicator.setStyleSheet("color: #e0e0e0; font-size: 11px; font-weight: bold;")
        status_layout.addWidget(self.autoplay_indicator)
        
        left_layout.addWidget(status_frame)
        
        self.control_group = QGroupBox(self.tr.t('playback_control'))
        self.control_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 1px solid #444;
                border-radius: 8px;
                margin-top: 1ex;
                padding-top: 10px;
                color: white;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
            }
        """)
        control_layout = QVBoxLayout()
        
        first_row = QHBoxLayout()
        
        self.bot_control_btn = ModernButton(self.tr.t('start'), color="#00802b", hover_color="#00cc44")
        self.bot_control_btn.clicked.connect(self.toggle_bot)
        self.bot_control_btn.setMinimumHeight(45)
        first_row.addWidget(self.bot_control_btn)
        
        self.playback_control_btn = ModernButton(self.tr.t('pause'), color="#0961aa", hover_color="#42A5F5")
        self.playback_control_btn.clicked.connect(self.toggle_playback)
        self.playback_control_btn.setEnabled(False)
        self.playback_control_btn.setMinimumHeight(45)
        first_row.addWidget(self.playback_control_btn)
        
        control_layout.addLayout(first_row)
        
        second_row = QHBoxLayout()
        
        self.skip_btn = ModernButton(self.tr.t('skip'), color="#0961aa", hover_color="#42A5F5")
        self.skip_btn.clicked.connect(self.skip_track)
        self.skip_btn.setEnabled(False)
        self.skip_btn.setMinimumHeight(45)
        second_row.addWidget(self.skip_btn)
        
        self.clear_queue_btn = ModernButton(self.tr.t('clear_queue'), color="#0961aa", hover_color="#42A5F5")
        self.clear_queue_btn.clicked.connect(self.clear_queue)
        self.clear_queue_btn.setEnabled(False)
        self.clear_queue_btn.setMinimumHeight(45)
        second_row.addWidget(self.clear_queue_btn)
        
        control_layout.addLayout(second_row)
        
        volume_row = QHBoxLayout()
        self.volume_label_prefix = QLabel(self.tr.t('volume'))
        self.volume_label_prefix.setStyleSheet("color: #e0e0e0;")
        volume_row.addWidget(self.volume_label_prefix)
        
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(50)
        self.volume_slider.valueChanged.connect(self.update_volume)
        self.volume_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                border: 1px solid #444;
                height: 4px;
                background: #3c3c3c;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #666;
                border: 1px solid #555;
                width: 12px;
                height: 12px;
                margin: -5px 0;
                border-radius: 6px;
            }
            QSlider::handle:horizontal:hover {
                background: #777;
            }
        """)
        volume_row.addWidget(self.volume_slider, 1)
        
        self.volume_label = QLabel("50%")
        self.volume_label.setStyleSheet("color: #e0e0e0;")
        self.volume_label.setMinimumWidth(38)
        volume_row.addWidget(self.volume_label)
        control_layout.addLayout(volume_row)
        
        self.control_group.setLayout(control_layout)
        left_layout.addWidget(self.control_group)
        
        self.logs_group = QGroupBox(self.tr.t('events'))
        self.logs_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 1px solid #444;
                border-radius: 8px;
                margin-top: 1ex;
                padding-top: 10px;
                color: white;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
            }
        """)
        logs_layout = QVBoxLayout()
        self.logs_text = QTextEdit()
        self.logs_text.setReadOnly(True)
        self.logs_text.setMinimumHeight(250)
        self.logs_text.setFont(QFont("Consolas", 10))
        self.logs_text.setStyleSheet("""
            QTextEdit {
                background-color: #2b2b2b;
                color: #e0e0e0;
                border: 1px solid #444;
                border-radius: 3px;
                padding: 3px;
            }
        """)
        logs_layout.addWidget(self.logs_text)
        self.logs_group.setLayout(logs_layout)
        left_layout.addWidget(self.logs_group)
        
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #444;
                background-color: #2b2b2b;
            }
            QTabBar::tab {
                background-color: #3c3c3c;
                color: #e0e0e0;
                padding: 8px 16px;
                border: 1px solid #444;
                border-bottom: none;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                background-color: #4a4a4a;
            }
            QTabBar::tab:hover {
                background-color: #454545;
            }
        """)
        
        music_tab = QWidget()
        music_layout = QVBoxLayout(music_tab)
        music_layout.setSpacing(5)
        music_layout.setContentsMargins(5, 5, 5, 5)
        
        search_layout = QHBoxLayout()
        self.search_label = QLabel(self.tr.t('search'))
        self.search_label.setStyleSheet("color: #e0e0e0;")
        search_layout.addWidget(self.search_label)
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(self.tr.t('search_placeholder'))
        self.search_input.setStyleSheet("""
            QLineEdit {
                background-color: #3c3c3c;
                color: white;
                border: 1px solid #555;
                border-radius: 3px;
                padding: 5px;
            }
        """)
        self.search_input.textChanged.connect(self.filter_music_list)
        search_layout.addWidget(self.search_input)
        
        self.refresh_btn = ModernButton(self.tr.t('refresh'), color="#3c3c3c", hover_color="#4a4a4a")
        self.refresh_btn.clicked.connect(self.refresh_music_list)
        search_layout.addWidget(self.refresh_btn)
        music_layout.addLayout(search_layout)
        
        self.music_wallpaper_widget = MusicWallpaperWidget()
        self.music_list = QListWidget(self.music_wallpaper_widget)
        self.music_list.itemDoubleClicked.connect(self.play_selected)
        self.music_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.music_list.customContextMenuRequested.connect(self.show_context_menu)
        _mw_layout = QVBoxLayout(self.music_wallpaper_widget)
        _mw_layout.setContentsMargins(0, 0, 0, 0)
        _mw_layout.addWidget(self.music_list)
        music_layout.addWidget(self.music_wallpaper_widget)
        self.update_music_wallpaper_appearance()
        
        self.music_stats = QLabel(self.tr.t('total_files').format(0))
        self.music_stats.setStyleSheet("color: #888; padding: 3px;")
        music_layout.addWidget(self.music_stats)
        self.tabs.addTab(music_tab, self.tr.t('music_tab'))
        
        settings_tab = QWidget()
        settings_layout = QVBoxLayout(settings_tab)
        settings_layout.setContentsMargins(0, 0, 0, 0)
        
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: #2b2b2b;
            }
        """)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setSpacing(5)
        scroll_layout.setContentsMargins(14, 8, 14, 10)
        
        _group_style = """
            QGroupBox {
                font-weight: bold;
                border: 1px solid #444;
                border-radius: 5px;
                margin-top: 0.45ex;
                padding-top: 6px;
                padding-left: 10px;
                padding-right: 8px;
                color: white;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
            }
        """
        _set_lbl_w = 152
        _set_btn_w = 94
        _set_path_h = 26
        _set_la = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        _cb_set = """
            QCheckBox { color: #e0e0e0; }
            QCheckBox::indicator { width:14px;height:14px;border:1px solid #555;background:#3c3c3c; }
            QCheckBox::indicator:checked { background:#2196F3; }
        """
        
        # --- Интерфейс, оформление и веб ---
        self.settings_group_ui = QGroupBox(self.tr.t('settings_cat_ui_web'))
        self.settings_group_ui.setStyleSheet(_group_style)
        lay_ui = QVBoxLayout()
        lay_ui.setSpacing(4)
        lay_ui.setContentsMargins(4, 2, 4, 8)
        
        if_row = QHBoxLayout()
        self.language_label = QLabel(self.tr.t('language'))
        self.language_label.setStyleSheet("color: #e0e0e0;")
        self.language_label.setMinimumWidth(_set_lbl_w)
        self.language_label.setAlignment(_set_la)
        if_row.addWidget(self.language_label)
        self.language_combo = QComboBox()
        self.language_combo.addItems(["Русский", "English"])
        self.language_combo.setCurrentIndex(0 if self.config.language == 'ru' else 1)
        self.language_combo.currentIndexChanged.connect(self.on_language_changed)
        self.language_combo.setStyleSheet("""
            QComboBox {
                background-color: #3c3c3c;
                color: white;
                border: 1px solid #555;
                border-radius: 3px;
                padding: 5px;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 4px solid #888;
                margin-right: 5px;
            }
        """)
        _compact_settings_combo(self.language_combo)
        if_row.addWidget(self.language_combo)
        if_row.addSpacing(20)
        self.autostart_check = QCheckBox(self.tr.t('autostart'))
        self.autostart_check.stateChanged.connect(self.on_setting_changed)
        self.autostart_check.setStyleSheet(_cb_set)
        if_row.addWidget(self.autostart_check)
        if_row.addStretch()
        lay_ui.addLayout(if_row)
        
        ui_chk_row = QHBoxLayout()
        self.show_album_art_check = QCheckBox(self.tr.t('show_album_art'))
        self.show_album_art_check.setChecked(self.config.show_album_art)
        self.show_album_art_check.stateChanged.connect(self.on_setting_changed)
        self.show_album_art_check.setStyleSheet(_cb_set)
        ui_chk_row.addWidget(self.show_album_art_check)
        ui_chk_row.addStretch(1)
        self.wallpaper_enable_check = QCheckBox(self.tr.t('enable_wallpaper'))
        self.wallpaper_enable_check.setChecked(self.config.wallpaper_enabled)
        self.wallpaper_enable_check.stateChanged.connect(self.on_setting_changed)
        self.wallpaper_enable_check.stateChanged.connect(lambda *_: self.update_music_wallpaper_appearance())
        self.wallpaper_enable_check.setStyleSheet(_cb_set)
        ui_chk_row.addWidget(self.wallpaper_enable_check)
        lay_ui.addLayout(ui_chk_row)
        
        wall_row = QHBoxLayout()
        self.wallpaper_file_label = QLabel(self.tr.t('wallpaper_file'))
        self.wallpaper_file_label.setStyleSheet("color: #e0e0e0;")
        self.wallpaper_file_label.setMinimumWidth(_set_lbl_w)
        self.wallpaper_file_label.setAlignment(_set_la)
        wall_row.addWidget(self.wallpaper_file_label)
        self.wallpaper_path_display = ClickablePathLabel()
        self.wallpaper_path_display.setMinimumHeight(_set_path_h)
        self.wallpaper_path_display.setText(self.config.wallpaper_path or "")
        self.wallpaper_path_display.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.wallpaper_path_display.clicked.connect(self.open_wallpaper_path_from_settings)
        self.wallpaper_path_display.setStyleSheet("""
            QLabel {
                background-color: #3c3c3c;
                color: #e0e0e0;
                border: 1px solid #555;
                border-radius: 3px;
                padding: 4px 6px;
            }
        """)
        wall_row.addWidget(self.wallpaper_path_display, 1)
        self.wallpaper_browse_btn = ModernButton(self.tr.t('browse'), color="#3c3c3c", hover_color="#4a4a4a")
        self.wallpaper_browse_btn.setFixedWidth(_set_btn_w)
        self.wallpaper_browse_btn.clicked.connect(self.browse_wallpaper)
        wall_row.addWidget(self.wallpaper_browse_btn)
        lay_ui.addLayout(wall_row)
        self.wallpaper_path_display.set_tooltip_hint(self.tr.t('wallpaper_open_tooltip'))
        
        web_row = QHBoxLayout()
        self.web_enable_check = QCheckBox(self.tr.t("web_enable"))
        self.web_enable_check.setChecked(self.config.web_enabled)
        self.web_enable_check.stateChanged.connect(self.on_setting_changed)
        self.web_enable_check.setStyleSheet(_cb_set)
        web_row.addWidget(self.web_enable_check)
        web_row.addStretch(1)
        self.web_port_label = QLabel(self.tr.t("web_port_lbl"))
        self.web_port_label.setStyleSheet("color:#e0e0e0;")
        web_row.addWidget(self.web_port_label)
        self.web_port_input = QLineEdit(str(self.config.web_port))
        self.web_port_input.setFixedWidth(64)
        self.web_port_input.textChanged.connect(self.on_setting_changed)
        self.web_port_input.setStyleSheet("""
            QLineEdit{background:#3c3c3c;color:white;border:1px solid #555;border-radius:3px;padding:4px;}
        """)
        web_row.addWidget(self.web_port_input)
        self.web_open_btn = ModernButton(self.tr.t("web_open_btn"), color="#3c3c3c", hover_color="#4a4a4a")
        self.web_open_btn.setFixedWidth(_set_btn_w)
        self.web_open_btn.setFixedHeight(26)
        self.web_open_btn.clicked.connect(self.open_web_interface)
        web_row.addWidget(self.web_open_btn)
        lay_ui.addLayout(web_row)
        
        self.settings_group_ui.setLayout(lay_ui)
        scroll_layout.addWidget(self.settings_group_ui)
        self.update_music_wallpaper_appearance()
        
        # --- Плеер (папка, FFmpeg, автоплейлист) ---
        self.settings_group_library = QGroupBox(self.tr.t('settings_cat_library'))
        self.settings_group_library.setStyleSheet(_group_style)
        lay_lib = QVBoxLayout()
        lay_lib.setSpacing(4)
        lay_lib.setContentsMargins(4, 2, 4, 8)
        lib_grid = QGridLayout()
        lib_grid.setContentsMargins(0, 0, 0, 0)
        lib_grid.setHorizontalSpacing(8)
        lib_grid.setVerticalSpacing(4)
        lib_grid.setColumnStretch(1, 1)
        
        self.music_folder_label = QLabel(self.tr.t('music_folder'))
        self.music_folder_label.setStyleSheet("color: #e0e0e0;")
        self.music_folder_label.setMinimumWidth(_set_lbl_w)
        self.music_folder_label.setAlignment(_set_la)
        lib_grid.addWidget(self.music_folder_label, 0, 0)
        self.music_folder_display = ClickablePathLabel()
        self.music_folder_display.setMinimumHeight(_set_path_h)
        self.music_folder_display.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.music_folder_display.clicked.connect(self.open_music_folder_from_settings)
        self.music_folder_display.setStyleSheet("""
            QLabel {
                background-color: #3c3c3c;
                color: #e0e0e0;
                border: 1px solid #555;
                border-radius: 3px;
                padding: 4px 6px;
            }
        """)
        lib_grid.addWidget(self.music_folder_display, 0, 1)
        self.browse_btn = ModernButton(self.tr.t('browse'), color="#3c3c3c", hover_color="#4a4a4a")
        self.browse_btn.setFixedWidth(_set_btn_w)
        self.browse_btn.clicked.connect(self.browse_music_folder)
        lib_grid.addWidget(self.browse_btn, 0, 2)
        self.music_folder_display.set_tooltip_hint(self.tr.t('music_folder_open_tooltip'))
        
        self.folder_status = QLabel(self.tr.t('folder_not_selected'))
        self.folder_status.setStyleSheet("color: #888; font-size: 9px;")
        self.folder_status.setWordWrap(True)
        lib_grid.addWidget(self.folder_status, 1, 0, 1, 3)
        
        self.ffmpeg_label = QLabel(self.tr.t('ffmpeg'))
        self.ffmpeg_label.setStyleSheet("color: #e0e0e0;")
        self.ffmpeg_label.setMinimumWidth(_set_lbl_w)
        self.ffmpeg_label.setAlignment(_set_la)
        lib_grid.addWidget(self.ffmpeg_label, 2, 0)
        self.ffmpeg_display = ClickablePathLabel()
        self.ffmpeg_display.setMinimumHeight(_set_path_h)
        self.ffmpeg_display.setText(self.config.ffmpeg_path or "ffmpeg")
        self.ffmpeg_display.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.ffmpeg_display.clicked.connect(self.open_ffmpeg_path_from_settings)
        self.ffmpeg_display.setStyleSheet("""
            QLabel {
                background-color: #3c3c3c;
                color: #e0e0e0;
                border: 1px solid #555;
                border-radius: 3px;
                padding: 4px 6px;
            }
        """)
        lib_grid.addWidget(self.ffmpeg_display, 2, 1)
        _ff_btns = QWidget()
        _ff_bh = QHBoxLayout(_ff_btns)
        _ff_bh.setContentsMargins(0, 0, 0, 0)
        _ff_bh.setSpacing(6)
        self.ffmpeg_auto_btn = ModernButton(self.tr.t("ffmpeg_auto_btn"), color="#3c3c3c", hover_color="#4a4a4a")
        self.ffmpeg_auto_btn.setFixedWidth(52)
        self.ffmpeg_auto_btn.clicked.connect(self.autodetect_ffmpeg)
        _ff_bh.addWidget(self.ffmpeg_auto_btn)
        self.ffmpeg_browse_btn = ModernButton(self.tr.t('browse'), color="#3c3c3c", hover_color="#4a4a4a")
        self.ffmpeg_browse_btn.setFixedWidth(_set_btn_w)
        self.ffmpeg_browse_btn.clicked.connect(self.browse_ffmpeg)
        _ff_bh.addWidget(self.ffmpeg_browse_btn)
        lib_grid.addWidget(_ff_btns, 2, 2)
        self.ffmpeg_display.set_tooltip_hint(self.tr.t('ffmpeg_open_tooltip'))
        
        lay_lib.addLayout(lib_grid)
        self.ffmpeg_status_label = QLabel("")
        self.ffmpeg_status_label.setStyleSheet("color:#888;font-size:9px;")
        self.ffmpeg_status_label.setWordWrap(True)
        lay_lib.addWidget(self.ffmpeg_status_label)
        self._update_ffmpeg_status_label()

        _sep_pb = QFrame()
        _sep_pb.setFrameShape(QFrame.Shape.HLine)
        _sep_pb.setStyleSheet("background:#444;max-height:1px;margin-top:4px;")
        lay_lib.addWidget(_sep_pb)

        pb_chk = QHBoxLayout()
        self.autoplay_check = QCheckBox(self.tr.t('enable_autoplay'))
        self.autoplay_check.stateChanged.connect(self.on_setting_changed)
        self.autoplay_check.setStyleSheet(_cb_set)
        pb_chk.addWidget(self.autoplay_check)
        pb_chk.addStretch(1)
        self.exclude_repeats_check = QCheckBox(self.tr.t('exclude_repeats'))
        self.exclude_repeats_check.setChecked(self.config.exclude_repeats)
        self.exclude_repeats_check.stateChanged.connect(self.on_setting_changed)
        self.exclude_repeats_check.setStyleSheet(_cb_set)
        self.exclude_repeats_check.setToolTip(self.tr.t('exclude_repeats_desc'))
        pb_chk.addWidget(self.exclude_repeats_check)
        lay_lib.addLayout(pb_chk)

        mode_row = QHBoxLayout()
        self.autoplay_mode_label = QLabel(self.tr.t('autoplay_mode'))
        self.autoplay_mode_label.setStyleSheet("color: #e0e0e0;")
        self.autoplay_mode_label.setMinimumWidth(_set_lbl_w)
        self.autoplay_mode_label.setAlignment(_set_la)
        mode_row.addWidget(self.autoplay_mode_label)
        self.autoplay_mode = QComboBox()
        self.autoplay_mode.addItems([self.tr.t('shuffle'), self.tr.t('sequential')])
        self.autoplay_mode.currentTextChanged.connect(self.on_setting_changed)
        self.autoplay_mode.setStyleSheet("""
            QComboBox {
                background-color: #3c3c3c;
                color: white;
                border: 1px solid #555;
                border-radius: 3px;
                padding: 5px;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 4px solid #888;
                margin-right: 5px;
            }
        """)
        _compact_settings_combo(self.autoplay_mode)
        mode_row.addWidget(self.autoplay_mode)
        mode_row.addStretch()
        lay_lib.addLayout(mode_row)

        self.settings_group_library.setLayout(lay_lib)
        scroll_layout.addWidget(self.settings_group_library)
        
        # --- Discord: токен, роли, каналы и поведение ---
        self.settings_group_discord = QGroupBox(self.tr.t('settings_cat_discord'))
        self.settings_group_discord.setStyleSheet(_group_style)
        lay_disc = QVBoxLayout()
        lay_disc.setSpacing(4)
        lay_disc.setContentsMargins(4, 2, 4, 8)
        
        tok_row = QHBoxLayout()
        self.token_label = QLabel(self.tr.t('bot_token'))
        self.token_label.setStyleSheet("color: #e0e0e0;")
        self.token_label.setMinimumWidth(_set_lbl_w)
        self.token_label.setAlignment(_set_la)
        tok_row.addWidget(self.token_label)
        self.token_input = QLineEdit()
        self.token_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.token_input.textChanged.connect(self.on_setting_changed)
        self.token_input.setStyleSheet("""
            QLineEdit {
                background-color: #3c3c3c;
                color: white;
                border: 1px solid #555;
                border-radius: 3px;
                padding: 4px 6px;
            }
        """)
        self.token_input.setMaximumWidth(520)
        tok_row.addWidget(self.token_input, 1)
        lay_disc.addLayout(tok_row)
        
        self.enable_role_protection = QCheckBox(self.tr.t('enable_role_protection'))
        self.enable_role_protection.stateChanged.connect(self.on_setting_changed)
        self.enable_role_protection.stateChanged.connect(self.toggle_role_inputs)
        self.enable_role_protection.setStyleSheet("""
            QCheckBox {
                color: #e0e0e0;
            }
            QCheckBox::indicator {
                width: 14px;
                height: 14px;
                border: 1px solid #555;
                background-color: #3c3c3c;
            }
            QCheckBox::indicator:checked {
                background-color: #2196F3;
            }
        """)
        lay_disc.addWidget(self.enable_role_protection)
        
        _role_inp_style = """
            QLineEdit {
                background-color: #3c3c3c;
                color: white;
                border: 1px solid #555;
                border-radius: 3px;
                padding: 5px;
            }
        """
        roles_row = QHBoxLayout()
        self.control_role_label = QLabel(self.tr.t('control_role'))
        self.control_role_label.setStyleSheet("color: #e0e0e0;")
        self.control_role_label.setMinimumWidth(118)
        roles_row.addWidget(self.control_role_label)
        self.control_role_id_input = QLineEdit()
        self.control_role_id_input.setPlaceholderText("ID")
        self.control_role_id_input.setMinimumWidth(110)
        self.control_role_id_input.textChanged.connect(self.on_setting_changed)
        self.control_role_id_input.setStyleSheet(_role_inp_style)
        roles_row.addWidget(self.control_role_id_input)
        self.admin_role_label = QLabel(self.tr.t('admin_role'))
        self.admin_role_label.setStyleSheet("color: #e0e0e0;")
        self.admin_role_label.setMinimumWidth(118)
        roles_row.addWidget(self.admin_role_label)
        self.admin_role_id_input = QLineEdit()
        self.admin_role_id_input.setPlaceholderText("ID")
        self.admin_role_id_input.setMinimumWidth(110)
        self.admin_role_id_input.textChanged.connect(self.on_setting_changed)
        self.admin_role_id_input.setStyleSheet(_role_inp_style)
        roles_row.addWidget(self.admin_role_id_input)
        roles_row.addStretch()
        lay_disc.addLayout(roles_row)
        
        lay_beh = QVBoxLayout()
        lay_beh.setSpacing(4)
        lay_beh.setContentsMargins(0, 0, 0, 0)

        _cb_style = _cb_set
        _input_style = "QLineEdit{background:#3c3c3c;color:white;border:1px solid #555;border-radius:3px;padding:4px;}"

        # ── Автоподключение к каналу при старте ──────────────────────────
        ac_row = QHBoxLayout()
        self.auto_connect_check = QCheckBox(self.tr.t('enable_auto_connect'))
        self.auto_connect_check.stateChanged.connect(self.on_setting_changed)
        self.auto_connect_check.setStyleSheet(_cb_style)
        ac_row.addWidget(self.auto_connect_check)

        self.channel_status_label = QLabel("")
        self.channel_status_label.setStyleSheet("color:#888;font-size:9px;")
        self.channel_status_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        ac_row.addWidget(self.channel_status_label, 1)

        self.refresh_channels_btn = ModernButton(self.tr.t('refresh_channels'), color="#3c3c3c", hover_color="#4a4a4a")
        self.refresh_channels_btn.clicked.connect(self.refresh_channels_list)
        self.refresh_channels_btn.setEnabled(False)
        self.refresh_channels_btn.setFixedWidth(118)
        ac_row.addWidget(self.refresh_channels_btn)
        lay_beh.addLayout(ac_row)

        server_layout = QHBoxLayout()
        self.select_server_label = QLabel(self.tr.t('select_server'))
        self.select_server_label.setStyleSheet("color:#e0e0e0;")
        self.select_server_label.setMinimumWidth(_set_lbl_w)
        self.select_server_label.setAlignment(_set_la)
        server_layout.addWidget(self.select_server_label)
        self.server_combo = QComboBox()
        self.server_combo.setEnabled(False)
        self.server_combo.setStyleSheet("""
            QComboBox{background:#3c3c3c;color:white;border:1px solid #555;border-radius:3px;padding:5px;}
            QComboBox::drop-down{border:none;}
            QComboBox::down-arrow{image:none;border-left:4px solid transparent;
                border-right:4px solid transparent;border-top:4px solid #888;margin-right:5px;}
            QComboBox:disabled{background:#2b2b2b;color:#666;}
        """)
        self.server_combo.currentIndexChanged.connect(self.on_server_changed)
        _compact_settings_combo(self.server_combo, min_w=180, max_w=600)
        server_layout.addWidget(self.server_combo, 1)
        lay_beh.addLayout(server_layout)

        vc_layout = QHBoxLayout()
        self.select_voice_channel_label = QLabel(self.tr.t('select_voice_channel'))
        self.select_voice_channel_label.setStyleSheet("color:#e0e0e0;")
        self.select_voice_channel_label.setMinimumWidth(_set_lbl_w)
        self.select_voice_channel_label.setAlignment(_set_la)
        vc_layout.addWidget(self.select_voice_channel_label)
        self.voice_channel_combo = QComboBox()
        self.voice_channel_combo.setEnabled(False)
        self.voice_channel_combo.setStyleSheet("""
            QComboBox{background:#3c3c3c;color:white;border:1px solid #555;border-radius:3px;padding:5px;}
            QComboBox::drop-down{border:none;}
            QComboBox::down-arrow{image:none;border-left:4px solid transparent;
                border-right:4px solid transparent;border-top:4px solid #888;margin-right:5px;}
            QComboBox:disabled{background:#2b2b2b;color:#666;}
        """)
        self.voice_channel_combo.currentIndexChanged.connect(self.on_voice_channel_changed)
        _compact_settings_combo(self.voice_channel_combo, min_w=180, max_w=600)
        vc_layout.addWidget(self.voice_channel_combo, 1)
        lay_beh.addLayout(vc_layout)

        tc_layout = QHBoxLayout()
        self.select_text_channel_label = QLabel(self.tr.t('select_text_channel'))
        self.select_text_channel_label.setStyleSheet("color:#e0e0e0;")
        self.select_text_channel_label.setMinimumWidth(_set_lbl_w)
        self.select_text_channel_label.setAlignment(_set_la)
        tc_layout.addWidget(self.select_text_channel_label)
        self.text_channel_combo = QComboBox()
        self.text_channel_combo.setEnabled(False)
        self.text_channel_combo.setStyleSheet("""
            QComboBox{background:#3c3c3c;color:white;border:1px solid #555;border-radius:3px;padding:5px;}
            QComboBox::drop-down{border:none;}
            QComboBox::down-arrow{image:none;border-left:4px solid transparent;
                border-right:4px solid transparent;border-top:4px solid #888;margin-right:5px;}
            QComboBox:disabled{background:#2b2b2b;color:#666;}
        """)
        self.text_channel_combo.currentIndexChanged.connect(self.on_text_channel_changed)
        _compact_settings_combo(self.text_channel_combo, min_w=180, max_w=600)
        tc_layout.addWidget(self.text_channel_combo, 1)
        lay_beh.addLayout(tc_layout)

        # ── Автореконнект ────────────────────────────────────────────────
        self.reconnect_check = QCheckBox(self.tr.t("reconnect_check_lbl"))
        self.reconnect_check.setChecked(self.config.reconnect_enabled)
        self.reconnect_check.stateChanged.connect(self.on_setting_changed)
        self.reconnect_check.setStyleSheet(_cb_style)
        lay_beh.addWidget(self.reconnect_check)

        rc_row = QHBoxLayout()
        self.reconnect_delay_label = QLabel(self.tr.t("reconnect_delay_lbl"))
        self.reconnect_delay_label.setStyleSheet("color:#e0e0e0;")
        rc_row.addWidget(self.reconnect_delay_label)
        self.reconnect_delay_input = QLineEdit(str(self.config.reconnect_delay))
        self.reconnect_delay_input.setFixedWidth(45)
        self.reconnect_delay_input.textChanged.connect(self.on_setting_changed)
        self.reconnect_delay_input.setStyleSheet(_input_style)
        rc_row.addWidget(self.reconnect_delay_input)
        self.reconnect_max_label = QLabel(self.tr.t("reconnect_max_lbl"))
        self.reconnect_max_label.setStyleSheet("color:#e0e0e0;")
        rc_row.addWidget(self.reconnect_max_label)
        self.reconnect_max_input = QLineEdit(str(self.config.reconnect_max))
        self.reconnect_max_input.setFixedWidth(45)
        self.reconnect_max_input.textChanged.connect(self.on_setting_changed)
        self.reconnect_max_input.setStyleSheet(_input_style)
        rc_row.addWidget(self.reconnect_max_input)
        rc_row.addStretch()
        lay_beh.addLayout(rc_row)

        self.reconnect_status_label = QLabel("")
        self.reconnect_status_label.setStyleSheet("color:#FFA500;font-size:10px;")
        lay_beh.addWidget(self.reconnect_status_label)

        # ── Пустой канал ─────────────────────────────────────────────────
        ec_action_row = QHBoxLayout()
        self.empty_ch_action_label = QLabel(self.tr.t("empty_ch_action_lbl"))
        self.empty_ch_action_label.setStyleSheet("color:#e0e0e0;")
        ec_action_row.addWidget(self.empty_ch_action_label)
        self.empty_ch_action_combo = QComboBox()
        self.empty_ch_action_combo.addItems([self.tr.t("empty_ch_none"), self.tr.t("empty_ch_pause"), self.tr.t("empty_ch_disconnect")])
        _action_map = {"none": 0, "pause": 1, "disconnect": 2}
        self.empty_ch_action_combo.setCurrentIndex(_action_map.get(self.config.empty_channel_action, 0))
        self.empty_ch_action_combo.currentIndexChanged.connect(self.on_setting_changed)
        self.empty_ch_action_combo.setStyleSheet("""
            QComboBox{background:#3c3c3c;color:white;border:1px solid #555;border-radius:3px;padding:5px;}
            QComboBox::drop-down{border:none;}
            QComboBox::down-arrow{image:none;border-left:4px solid transparent;
                border-right:4px solid transparent;border-top:4px solid #888;margin-right:5px;}
        """)
        _compact_settings_combo(self.empty_ch_action_combo)
        ec_action_row.addWidget(self.empty_ch_action_combo)
        self.empty_ch_timeout_label = QLabel(self.tr.t("empty_ch_timeout_lbl"))
        self.empty_ch_timeout_label.setStyleSheet("color:#e0e0e0;")
        ec_action_row.addWidget(self.empty_ch_timeout_label)
        self.empty_ch_timeout_input = QLineEdit(str(self.config.empty_channel_timeout))
        self.empty_ch_timeout_input.setFixedWidth(45)
        self.empty_ch_timeout_input.textChanged.connect(self.on_setting_changed)
        self.empty_ch_timeout_input.setStyleSheet(_input_style)
        ec_action_row.addWidget(self.empty_ch_timeout_input)
        ec_action_row.addStretch()
        lay_beh.addLayout(ec_action_row)

        self.empty_ch_hint_label = QLabel(self.tr.t("empty_ch_hint"))
        self.empty_ch_hint_label.setStyleSheet("color:#666;font-size:9px;")
        self.empty_ch_hint_label.setWordWrap(True)
        lay_beh.addWidget(self.empty_ch_hint_label)

        lay_disc.addLayout(lay_beh)
        self.settings_group_discord.setLayout(lay_disc)
        scroll_layout.addWidget(self.settings_group_discord)

        scroll_layout.addStretch()
        scroll_area.setWidget(scroll_widget)
        settings_layout.addWidget(scroll_area)
        
        self.tabs.addTab(settings_tab, self.tr.t('settings_tab'))
        
        info_tab = QWidget()
        info_layout = QVBoxLayout(info_tab)
        
        self.info_text = QTextBrowser()
        self.info_text.setReadOnly(True)
        self.info_text.setOpenExternalLinks(True)
        self.info_text.setHtml(self.get_info_html())
        self.info_text.setStyleSheet("""
            QTextBrowser {
                background-color: #2b2b2b;
                color: #e0e0e0;
                border: 1px solid #444;
                border-radius: 3px;
            }
        """)
        info_layout.addWidget(self.info_text)
        self.tabs.addTab(info_tab, self.tr.t('info_tab'))
        
        errors_tab = QWidget()
        errors_layout = QVBoxLayout(errors_tab)
        
        self.errors_text = QTextEdit()
        self.errors_text.setReadOnly(True)
        self.errors_text.setFont(QFont("Consolas", 9))
        self.errors_text.setStyleSheet("""
            QTextEdit {
                background-color: #2b2b2b;
                color: #ff8a8a;
                border: 1px solid #444;
                border-radius: 3px;
            }
        """)
        errors_layout.addWidget(self.errors_text)
        
        self.clear_errors_btn = ModernButton(self.tr.t('clear_errors'), color="#3c3c3c", hover_color="#4a4a4a")
        self.clear_errors_btn.clicked.connect(self.errors_text.clear)
        errors_layout.addWidget(self.clear_errors_btn)
        self.tabs.addTab(errors_tab, self.tr.t('errors_tab'))
        
        right_layout.addWidget(self.tabs)
        main_splitter.addWidget(left_panel)
        main_splitter.addWidget(right_panel)
        main_splitter.setSizes([500, 700])
    
    def toggle_role_inputs(self):
        enabled = self.enable_role_protection.isChecked()
        self.control_role_id_input.setEnabled(enabled)
        self.admin_role_id_input.setEnabled(enabled)
    
    def show_context_menu(self, position):
        item = self.music_list.itemAt(position)
        if not item:
            return
        
        selected_display_name = item.text()
        found_path = None
        album_art = None
        
        if hasattr(self, 'cached_music_files'):
            for f in self.cached_music_files:
                if f['display_name'] == selected_display_name:
                    found_path = f['path']
                    if self.config.show_album_art:
                        album_art = get_album_art(found_path)
                    break
        
        menu = QMenu()
        menu.setStyleSheet("""
            QMenu {
                background-color: #3c3c3c;
                color: white;
                border: 1px solid #555;
                padding: 5px;
            }
            QMenu::item {
                padding: 5px 20px;
                border: none;
            }
            QMenu::item:selected {
                background-color: #4a4a4a;
            }
            QMenu::separator {
                height: 1px;
                background-color: #555;
                margin: 5px 0;
            }
        """)
        
        # Создаем отдельный виджет для первого пункта с обложкой
        if album_art and not album_art.isNull():
            cover_widget = QWidget()
            cover_layout = QHBoxLayout(cover_widget)
            cover_layout.setContentsMargins(5, 5, 5, 5)
            cover_layout.setSpacing(10)
            
            cover_label = QLabel()
            scaled_cover = album_art.scaled(100, 100, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            cover_label.setPixmap(scaled_cover)
            cover_label.setFixedSize(100, 100)
            cover_layout.addWidget(cover_label)
            
            text_label = QLabel(selected_display_name)
            text_label.setStyleSheet("color: #2196F3; font-weight: bold; font-size: 13px;")
            text_label.setWordWrap(True)
            cover_layout.addWidget(text_label)
            
            cover_layout.addStretch()
            
            cover_widget.setStyleSheet("""
                QWidget {
                    background-color: #2b2b2b;
                    border-bottom: 1px solid #555;
                }
            """)
            
            cover_action = QWidgetAction(menu)
            cover_action.setDefaultWidget(cover_widget)
            menu.addAction(cover_action)
        
        # Обычные пункты меню без обложек
        add_to_queue_action = CustomAction(self.tr.t('add_to_queue'), self)
        add_to_queue_action.triggered.connect(lambda: self.play_selected(item))
        menu.addAction(add_to_queue_action)
        
        add_next_action = CustomAction(self.tr.t('add_next'), self)
        add_next_action.triggered.connect(lambda: self.play_selected_next(item))
        menu.addAction(add_next_action)
        
        play_now_action = CustomAction(self.tr.t('play_now'), self)
        play_now_action.triggered.connect(lambda: self.play_selected_now(item))
        menu.addAction(play_now_action)
        
        menu.addSeparator()
        
        # Показать в папке
        if found_path:
            show_in_folder_action = CustomAction(self.tr.t('show_in_folder'), self)
            show_in_folder_action.triggered.connect(lambda: self.show_in_folder(found_path))
            menu.addAction(show_in_folder_action)
        
        # Удалить файл
        delete_file_action = CustomAction(self.tr.t('delete_file'), self)
        delete_file_action.triggered.connect(lambda: self.delete_file_from_disk(item, found_path))
        menu.addAction(delete_file_action)
        
        menu.exec(self.music_list.mapToGlobal(position))
    
    def show_in_folder(self, file_path):
        """Открывает папку с файлом в проводнике"""
        try:
            # Получаем директорию файла
            folder_path = os.path.dirname(file_path)
            
            # Для Windows
            if sys.platform == 'win32':
                os.startfile(folder_path)
            # Для macOS
            elif sys.platform == 'darwin':
                import subprocess
                subprocess.run(['open', folder_path])
            # Для Linux
            else:
                import subprocess
                subprocess.run(['xdg-open', folder_path])
                
        except Exception as e:
            self.log_message(f"❌ {self.tr.t('error')}: {str(e)}", is_error=True)
    
    def delete_file_from_disk(self, item, file_path):
        """Удаляет файл с диска после подтверждения"""
        if not file_path or not os.path.exists(file_path):
            QMessageBox.warning(self, self.tr.t('error'), self.tr.t('delete_file_not_found'))
            return
        
        selected_display_name = item.text()
        
        # Диалог подтверждения
        reply = QMessageBox.question(
            self,
            self.tr.t('delete_file'),
            self.tr.t('delete_confirm').format(selected_display_name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            try:
                # Если бот запущен, удаляем из его очередей
                if self.bot_thread and self.bot_thread.is_running and hasattr(self.bot_thread, 'delete_file_from_disk'):
                    # Используем асинхронный метод через сигнал
                    async def delete_async():
                        await self.bot_thread.delete_file_from_disk(file_path)
                    
                    if self.bot_thread.loop and self.bot_thread.loop.is_running():
                        asyncio.run_coroutine_threadsafe(delete_async(), self.bot_thread.loop)
                else:
                    # Просто удаляем файл
                    os.remove(file_path)
                    self.log_message(self.tr.t('delete_success').format(selected_display_name))
                
                # Обновляем список музыки
                self.refresh_music_list()
                
            except Exception as e:
                QMessageBox.critical(self, self.tr.t('error'), self.tr.t('delete_error').format(str(e)))
                self.log_message(self.tr.t('delete_error').format(str(e)), is_error=True)
    
    def play_selected_now(self, item):
        if not self.bot_thread or not self.bot_thread.is_running:
            QMessageBox.warning(self, self.tr.t('error'), self.tr.t('bot_not_running'))
            return
        
        selected_display_name = item.text()
        found_path = None
        
        if hasattr(self, 'cached_music_files'):
            for f in self.cached_music_files:
                if f['display_name'] == selected_display_name:
                    found_path = f['path']
                    break
        
        if not found_path:
            QMessageBox.warning(self, self.tr.t('error'), self.tr.t('track_not_found'))
            return
        
        self.bot_thread.play_track_now_from_gui.emit(found_path, selected_display_name)
    
    def play_selected_next(self, item):
        if not self.bot_thread or not self.bot_thread.is_running:
            QMessageBox.warning(self, self.tr.t('error'), self.tr.t('bot_not_running'))
            return
        
        selected_display_name = item.text()
        found_path = None
        
        if hasattr(self, 'cached_music_files'):
            for f in self.cached_music_files:
                if f['display_name'] == selected_display_name:
                    found_path = f['path']
                    break
        
        if not found_path:
            QMessageBox.warning(self, self.tr.t('error'), self.tr.t('track_not_found'))
            return
        
        self.bot_thread.add_track_next_from_gui.emit(found_path, selected_display_name)
    
    def update_bot_info(self, bot_name, autoplay_enabled):
        self.bot_name = bot_name
        self.bot_name_label.setText(bot_name)
        self.bot_name_label.setVisible(True)
        if autoplay_enabled:
            self.autoplay_indicator.setText(f"{self.tr.t('autoplay_status')}")
            self.autoplay_indicator.setStyleSheet("color: #e0e0e0; font-size: 11px; font-weight: bold;")
        else:
            self.autoplay_indicator.setText("")
    
    def update_guilds_list(self, guilds_data):
        self.server_combo.blockSignals(True)
        self.voice_channel_combo.blockSignals(True)
        self.text_channel_combo.blockSignals(True)
        
        self.server_combo.clear()
        self.server_combo.addItem(self.tr.t('select_server'), None)
        
        for guild in guilds_data:
            self.server_combo.addItem(f"{guild['name']}", guild['id'])
        
        self.guilds_data = guilds_data
        
        if self.loaded_guild_id:
            found_guild = False
            for i in range(self.server_combo.count()):
                if self.server_combo.itemData(i) == self.loaded_guild_id:
                    self.server_combo.setCurrentIndex(i)
                    found_guild = True
                    break
            
            if found_guild:
                self.update_channel_combos()
        
        self.server_combo.blockSignals(False)
        self.voice_channel_combo.blockSignals(False)
        self.text_channel_combo.blockSignals(False)
        self.refresh_channels_btn.setEnabled(True)

    def update_channel_combos(self):
        guild_id = self.server_combo.currentData()
        
        self.voice_channel_combo.blockSignals(True)
        self.text_channel_combo.blockSignals(True)
        
        self.voice_channel_combo.clear()
        self.text_channel_combo.clear()
        
        self.voice_channel_combo.addItem(self.tr.t('select_voice_channel'), None)
        self.text_channel_combo.addItem(self.tr.t('select_text_channel'), None)
        
        if guild_id and hasattr(self, 'guilds_data'):
            for guild in self.guilds_data:
                if guild['id'] == guild_id:
                    for channel in guild.get('voice_channels', []):
                        user_text = f" ({channel['user_count']})" if channel['user_count'] > 0 else ""
                        self.voice_channel_combo.addItem(f"{channel['name']}{user_text}", channel['id'])
                    
                    for channel in guild.get('text_channels', []):
                        suffix = f" {self.tr.t('same_as_voice')}" if channel.get('voice_channel') else ""
                        self.text_channel_combo.addItem(f"{channel['name']}{suffix}", channel['id'])
                    break
        
        self.voice_channel_combo.blockSignals(False)
        self.text_channel_combo.blockSignals(False)
        
        if self.loaded_voice_channel_id and guild_id == self.loaded_guild_id:
            for i in range(self.voice_channel_combo.count()):
                if self.voice_channel_combo.itemData(i) == self.loaded_voice_channel_id:
                    self.voice_channel_combo.setCurrentIndex(i)
                    break
        
        if self.loaded_text_channel_id and guild_id == self.loaded_guild_id:
            for i in range(self.text_channel_combo.count()):
                if self.text_channel_combo.itemData(i) == self.loaded_text_channel_id:
                    self.text_channel_combo.setCurrentIndex(i)
                    break
        
        self.update_channel_status()

    def on_server_changed(self, index):
        if not self.settings_loaded:
            return
        
        self.update_channel_combos()
        self.config.default_voice_channel_id = None
        self.config.default_text_channel_id = None
        self.loaded_voice_channel_id = None
        self.loaded_text_channel_id = None
        self.update_channel_status()

    def on_voice_channel_changed(self, index):
        if not self.settings_loaded:
            return
        
        voice_channel_id = self.voice_channel_combo.currentData()
        guild_id = self.server_combo.currentData()
        
        if voice_channel_id and guild_id:
            self.config.default_voice_channel_id = voice_channel_id
            self.config.default_guild_id = guild_id
            self.loaded_voice_channel_id = voice_channel_id
            self.loaded_guild_id = guild_id
        else:
            self.config.default_voice_channel_id = None
            self.loaded_voice_channel_id = None
        
        self.update_channel_status()
        self.on_setting_changed()
    
    def on_text_channel_changed(self, index):
        if not self.settings_loaded:
            return
        
        text_channel_id = self.text_channel_combo.currentData()
        guild_id = self.server_combo.currentData()
        
        if text_channel_id and guild_id:
            self.config.default_text_channel_id = text_channel_id
            self.config.default_guild_id = guild_id
            self.loaded_text_channel_id = text_channel_id
            self.loaded_guild_id = guild_id
        else:
            self.config.default_text_channel_id = None
            self.loaded_text_channel_id = None
        
        self.update_channel_status()
        self.on_setting_changed()
    
    def refresh_channels_list(self):
        if self.bot_thread and self.bot_thread.is_running and hasattr(self.bot_thread, 'get_guilds_and_channels'):
            guilds_data = self.bot_thread.get_guilds_and_channels()
            self.update_guilds_list(guilds_data)
    
    def update_channel_status(self):
        if (self.config.default_guild_id and 
            self.config.default_voice_channel_id and 
            self.config.default_text_channel_id and 
            hasattr(self, 'guilds_data')):
            
            for guild in self.guilds_data:
                if guild['id'] == self.config.default_guild_id:
                    voice_channel_name = None
                    text_channel_name = None
                    
                    for channel in guild.get('voice_channels', []):
                        if channel['id'] == self.config.default_voice_channel_id:
                            voice_channel_name = channel['name']
                            break
                    
                    for channel in guild.get('text_channels', []):
                        if channel['id'] == self.config.default_text_channel_id:
                            text_channel_name = channel['name']
                            suffix = f" {self.tr.t('same_as_voice')}" if channel.get('voice_channel') else ""
                            break
                    
                    if voice_channel_name and text_channel_name:
                        self.channel_status_label.setText(
                            f"{voice_channel_name} | {text_channel_name}"
                        )
                        self.channel_status_label.setStyleSheet("color: #4CAF50; font-size: 9px;")
                        return
            
            self.channel_status_label.setText(self.tr.t('selected_channel_not_found'))
            self.channel_status_label.setStyleSheet("color: #ff6b6b; font-size: 9px;")
        else:
            self.channel_status_label.setText("")
    
    def on_language_changed(self, index):
        new_language = 'ru' if index == 0 else 'en'
        if new_language != self.config.language:
            self.config.language = new_language
            self.tr.set_language(new_language)
            self.update_ui_language()
            if hasattr(self, 'info_text'):
                self.info_text.setHtml(self.get_info_html())
            self.save_settings()
            self.autoplay_mode.clear()
            self.autoplay_mode.addItems([self.tr.t('shuffle'), self.tr.t('sequential')])
            self.autoplay_mode.setCurrentIndex(0 if self.config.autoplay_mode == "shuffle" else 1)
            self.autostart_check.setText(self.tr.t('autostart'))
            self.show_album_art_check.setText(self.tr.t('show_album_art'))
            if hasattr(self, 'wallpaper_enable_check'):
                self.wallpaper_enable_check.setText(self.tr.t('enable_wallpaper'))
            if hasattr(self, 'wallpaper_file_label'):
                self.wallpaper_file_label.setText(self.tr.t('wallpaper_file'))
            if hasattr(self, 'wallpaper_browse_btn'):
                self.wallpaper_browse_btn.setText(self.tr.t('browse'))
            if hasattr(self, 'ffmpeg_display'):
                self.ffmpeg_display.set_tooltip_hint(self.tr.t('ffmpeg_open_tooltip'))
            if hasattr(self, 'wallpaper_path_display'):
                self.wallpaper_path_display.set_tooltip_hint(self.tr.t('wallpaper_open_tooltip'))
            if hasattr(self, 'music_folder_display'):
                self.music_folder_display.set_tooltip_hint(self.tr.t('music_folder_open_tooltip'))
            self.exclude_repeats_check.setText(self.tr.t('exclude_repeats'))
            self.exclude_repeats_check.setToolTip(self.tr.t('exclude_repeats_desc'))
            
            # Ролевая защита - обновляем текст
            self.enable_role_protection.setText(self.tr.t('enable_role_protection'))
            self.control_role_label.setText(self.tr.t('control_role'))
            self.admin_role_label.setText(self.tr.t('admin_role'))
            self.auto_connect_check.setText(self.tr.t('enable_auto_connect'))
            self.select_server_label.setText(self.tr.t('select_server'))
            self.select_voice_channel_label.setText(self.tr.t('select_voice_channel'))
            self.select_text_channel_label.setText(self.tr.t('select_text_channel'))
            self.refresh_channels_btn.setText(self.tr.t('refresh_channels'))
            pass  # channel_group merged into behaviour_group

            if hasattr(self, 'reconnect_check'):
                self.reconnect_check.setText(self.tr.t('reconnect_check_lbl'))
            if hasattr(self, 'reconnect_delay_label'):
                self.reconnect_delay_label.setText(self.tr.t('reconnect_delay_lbl'))
            if hasattr(self, 'reconnect_max_label'):
                self.reconnect_max_label.setText(self.tr.t('reconnect_max_lbl'))
            if hasattr(self, 'empty_ch_action_label'):
                self.empty_ch_action_label.setText(self.tr.t('empty_ch_action_lbl'))
            if hasattr(self, 'empty_ch_timeout_label'):
                self.empty_ch_timeout_label.setText(self.tr.t('empty_ch_timeout_lbl'))
            if hasattr(self, 'empty_ch_hint_label'):
                self.empty_ch_hint_label.setText(self.tr.t('empty_ch_hint'))
            if hasattr(self, 'web_enable_check'):
                self.web_enable_check.setText(self.tr.t('web_enable'))
            if hasattr(self, 'settings_group_ui'):
                self.settings_group_ui.setTitle(self.tr.t('settings_cat_ui_web'))
            if hasattr(self, 'settings_group_library'):
                self.settings_group_library.setTitle(self.tr.t('settings_cat_library'))
            if hasattr(self, 'settings_group_discord'):
                self.settings_group_discord.setTitle(self.tr.t('settings_cat_discord'))
            if hasattr(self, 'ffmpeg_auto_btn'):
                self.ffmpeg_auto_btn.setText(self.tr.t('ffmpeg_auto_btn'))
            if hasattr(self, 'web_open_btn'):
                self.web_open_btn.setText(self.tr.t('web_open_btn'))
            if hasattr(self, 'web_port_label'):
                self.web_port_label.setText(self.tr.t('web_port_lbl'))
            # Repopulate empty channel combo
            if hasattr(self, 'empty_ch_action_combo'):
                _cur = self.empty_ch_action_combo.currentIndex()
                self.empty_ch_action_combo.blockSignals(True)
                self.empty_ch_action_combo.clear()
                self.empty_ch_action_combo.addItems([
                    self.tr.t('empty_ch_none'),
                    self.tr.t('empty_ch_pause'),
                    self.tr.t('empty_ch_disconnect'),
                ])
                self.empty_ch_action_combo.setCurrentIndex(_cur)
                self.empty_ch_action_combo.blockSignals(False)
            # Tray actions
            if hasattr(self, '_tray_show_action') and self._tray_show_action:
                self._tray_show_action.setText(self.tr.t('tray_show'))
            if hasattr(self, '_tray_pause_action') and self._tray_pause_action:
                self._tray_pause_action.setText(
                    self.tr.t('tray_resume') if self.is_paused else self.tr.t('tray_pause'))
            if hasattr(self, '_tray_skip_action') and self._tray_skip_action:
                self._tray_skip_action.setText(self.tr.t('tray_skip'))
            if hasattr(self, '_tray_quit_action') and self._tray_quit_action:
                self._tray_quit_action.setText(self.tr.t('tray_quit'))

            if self.server_combo.count() > 0:
                self.server_combo.setItemText(0, self.tr.t('select_server'))

            if self.voice_channel_combo.count() > 0:
                self.voice_channel_combo.setItemText(0, self.tr.t('select_voice_channel'))
            
            if self.text_channel_combo.count() > 0:
                self.text_channel_combo.setItemText(0, self.tr.t('select_text_channel'))
            
            if self.bot_thread and self.bot_thread.is_running and self.bot_name:
                self.bot_name_label.setText(self.bot_name)
            if self.config.autoplay_enabled:
                self.autoplay_indicator.setText(f"{self.tr.t('autoplay_status')}")
                self.autoplay_indicator.setStyleSheet("color: #e0e0e0; font-size: 11px; font-weight: bold;")
    
    def update_album_art(self, file_path):
        if not self.config.show_album_art:
            self.cover_label.setText(self.tr.t('no_cover'))
            self.cover_label.setPixmap(QPixmap())
            return
        pixmap = get_album_art(file_path)
        if pixmap and not pixmap.isNull():
            scaled_pixmap = pixmap.scaled(98, 98, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.cover_label.setPixmap(scaled_pixmap)
            self.cover_label.setText("")
        else:
            self.cover_label.setText(self.tr.t('no_cover'))
            self.cover_label.setPixmap(QPixmap())
    
    def format_time(self, seconds):
        if seconds <= 0:
            return "0:00"
        minutes = seconds // 60
        seconds = seconds % 60
        return f"{minutes}:{seconds:02d}"
    
    def update_progress_display(self):
        if self.total_duration > 0 and not self.is_paused:
            self.current_position += 1
            if self.current_position > self.total_duration:
                self.current_position = self.total_duration
            progress = int((self.current_position / self.total_duration) * 100)
            self.progress_bar.setValue(progress)
            self.current_time_label.setText(self.format_time(self.current_position))
            self.total_time_label.setText(self.format_time(self.total_duration))
    
    def update_now_playing(self, name, file_path, duration):
        self.now_playing_label.setText(f"{self.tr.t('now_playing')} {name}")
        self.current_track_path = file_path
        self.total_duration = duration
        self.current_position = 0
        if file_path:
            self.update_album_art(file_path)
        else:
            self.cover_label.setText(self.tr.t('no_cover'))
            self.cover_label.setPixmap(QPixmap())
        if duration > 0:
            self.progress_bar.setValue(0)
            self.current_time_label.setText("0:00")
            self.total_time_label.setText(self.format_time(duration))
            self.progress_timer.start()
        else:
            self.progress_timer.stop()
            self.progress_bar.setValue(0)
            self.current_time_label.setText("0:00")
            self.total_time_label.setText("0:00")
        if name and not name.startswith("⏹️"):
            self.is_playing = True
            self.is_paused = False  # Сбрасываем паузу при новом треке
            self.playback_control_btn.setEnabled(True)
            self.skip_btn.setEnabled(True)
            self.clear_queue_btn.setEnabled(True)
            self.playback_control_btn.setText(self.tr.t('pause'))  # Устанавливаем "Пауза"
            self._tray_update_playback_actions()
            self.spectrum_widget.set_active(True)
        elif "⏹️" in name:
            self.is_playing = False
            self.is_paused = False
            self.playback_control_btn.setEnabled(False)
            self.skip_btn.setEnabled(False)
            self.clear_queue_btn.setEnabled(False)
            self.progress_timer.stop()
            self.progress_bar.setValue(0)
            self.current_time_label.setText("0:00")
            self.total_time_label.setText("0:00")
            self._tray_update_playback_actions()
            self.spectrum_widget.set_active(False)
    
    def update_playback_button_from_discord(self, is_paused):
        """Обновляет кнопку паузы/продолжить в зависимости от состояния из Discord"""
        self.is_paused = is_paused
        if is_paused:
            self.playback_control_btn.setText(self.tr.t('resume'))
            self.progress_timer.stop()
            self.spectrum_widget.set_active(False)
        else:
            self.playback_control_btn.setText(self.tr.t('pause'))
            if self.is_playing:
                self.progress_timer.start()
                self.spectrum_widget.set_active(True)
        self._tray_update_playback_actions()
    
    def toggle_bot(self):
        if self.bot_thread and self.bot_thread.is_running:
            self.stop_bot()
        else:
            self.start_bot()
    
    def toggle_playback(self):
        if not self.bot_thread or not self.bot_thread.is_running:
            return
        if self.is_paused:
            self.resume_playback()
        else:
            self.pause_playback()
    
    def pause_playback(self):
        if self.bot_thread and self.bot_thread.is_running:
            self.bot_thread.pause_signal.emit()
            self.is_paused = True
            self.playback_control_btn.setText(self.tr.t('resume'))
            self.progress_timer.stop()
    
    def resume_playback(self):
        if self.bot_thread and self.bot_thread.is_running:
            self.bot_thread.resume_signal.emit()
            self.is_paused = False
            self.playback_control_btn.setText(self.tr.t('pause'))
            self.progress_timer.start()
    
    def skip_track(self):
        if self.bot_thread and self.bot_thread.is_running:
            self.bot_thread.skip_signal.emit()
    
    def clear_queue(self):
        if self.bot_thread and self.bot_thread.is_running:
            self.bot_thread.clear_queue_signal.emit()
    
    def on_setting_changed(self):
        if self.settings_loaded:
            self.save_settings()
    
    def open_music_folder_from_settings(self):
        folder = self.music_folder_display.text().strip()
        if not folder or not os.path.isdir(folder):
            QMessageBox.warning(self, self.tr.t('error'), self.tr.t('folder_not_found'))
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.normpath(folder)))

    def open_ffmpeg_path_from_settings(self):
        p = self.ffmpeg_display.text().strip()
        if not p:
            QMessageBox.warning(self, self.tr.t('error'), self.tr.t('folder_not_found'))
            return
        p_norm = os.path.normpath(p.replace('/', os.sep))
        if os.path.isfile(p_norm):
            folder = os.path.dirname(p_norm)
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
            return
        if os.path.isdir(p_norm):
            QDesktopServices.openUrl(QUrl.fromLocalFile(p_norm))
            return
        name = os.path.basename(p_norm)
        resolved = shutil.which(name) if name else None
        if resolved and os.path.isfile(resolved):
            folder = os.path.dirname(os.path.normpath(resolved))
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
            return
        QMessageBox.warning(self, self.tr.t('error'), self.tr.t('ffmpeg_open_failed'))

    def open_wallpaper_path_from_settings(self):
        p = self.wallpaper_path_display.text().strip()
        if not p:
            QMessageBox.warning(self, self.tr.t('error'), self.tr.t('folder_not_found'))
            return
        p_norm = os.path.normpath(p.replace('/', os.sep))
        if os.path.isfile(p_norm):
            folder = os.path.dirname(p_norm)
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
            return
        QMessageBox.warning(self, self.tr.t('error'), self.tr.t('folder_not_found'))

    def browse_music_folder(self):
        folder = QFileDialog.getExistingDirectory(self, self.tr.t('music_folder'))
        if folder:
            folder = folder.replace('\\', '/')
            self.music_folder_display.setText(folder)
            self.config.music_folder = folder
            self.check_music_folder()
            self.refresh_music_list()
            self.save_settings()
    
    def _update_ffmpeg_status_label(self):
        if not hasattr(self, 'ffmpeg_status_label'):
            return
        path = self.ffmpeg_display.text().strip() if hasattr(self, 'ffmpeg_display') else ""
        import shutil
        if not path or path == "ffmpeg":
            found = shutil.which("ffmpeg")
            if found:
                short = _shorten_path_for_status(found)
                self.ffmpeg_status_label.setText(self.tr.t("ffmpeg_ok_in_path").format(short))
                self.ffmpeg_status_label.setToolTip(found)
                self.ffmpeg_status_label.setStyleSheet("color:#4CAF50;font-size:9px;")
            else:
                self.ffmpeg_status_label.setText(self.tr.t("ffmpeg_not_found"))
                self.ffmpeg_status_label.setToolTip("")
                self.ffmpeg_status_label.setStyleSheet("color:#ff6b6b;font-size:9px;")
        elif os.path.isfile(path):
            if "ffmpeg-static" in path or "node_modules" in path:
                short = _shorten_path_for_status(path)
                self.ffmpeg_status_label.setText(self.tr.t("ffmpeg_ok_in_path").format(short))
            else:
                short = _shorten_path_for_status(path)
                self.ffmpeg_status_label.setText(f"✔ {short}")
            self.ffmpeg_status_label.setToolTip(path)
            self.ffmpeg_status_label.setStyleSheet("color:#4CAF50;font-size:9px;")
        else:
            short = _shorten_path_for_status(path)
            self.ffmpeg_status_label.setText(self.tr.t("ffmpeg_file_not_found").format(short))
            self.ffmpeg_status_label.setToolTip(path)
            self.ffmpeg_status_label.setStyleSheet("color:#ff6b6b;font-size:9px;")

    def autodetect_ffmpeg(self):
        detected = find_ffmpeg()
        self.ffmpeg_display.setText(detected)
        self.config.ffmpeg_path = detected
        self._update_ffmpeg_status_label()
        self.save_settings()

    def browse_ffmpeg(self):
        file, _ = QFileDialog.getOpenFileName(self, self.tr.t('ffmpeg'), "", "Executable (*.exe);;All files (*.*)")
        if file:
            file = file.replace('\\', '/')
            self.ffmpeg_display.setText(file)
            self._update_ffmpeg_status_label()
            self.save_settings()
    
    def update_music_wallpaper_appearance(self):
        if not hasattr(self, 'music_wallpaper_widget') or not hasattr(self, 'music_list'):
            return
        if hasattr(self, 'wallpaper_enable_check'):
            enabled = self.wallpaper_enable_check.isChecked()
            path = self.wallpaper_path_display.text().strip()
        else:
            enabled = self.config.wallpaper_enabled
            path = (self.config.wallpaper_path or "").strip()
        active = enabled and path and os.path.isfile(path)
        if active:
            self.music_wallpaper_widget.set_wallpaper(True, path)
            self.music_list.viewport().setAutoFillBackground(False)
            self.music_list.setStyleSheet("""
                QListWidget {
                    background-color: transparent;
                    color: white;
                    border: 1px solid #555;
                    border-radius: 3px;
                    outline: none;
                }
                QListWidget::item {
                    padding: 2px 5px;
                    border: none;
                    background-color: rgba(60, 60, 60, 210);
                }
                QListWidget::item:selected {
                    background-color: rgba(74, 74, 74, 235);
                }
                QListWidget::item:hover {
                    background-color: rgba(69, 69, 69, 225);
                }
            """)
        else:
            self.music_wallpaper_widget.set_wallpaper(False, "")
            self.music_list.viewport().setAutoFillBackground(True)
            self.music_list.setStyleSheet("""
                QListWidget {
                    background-color: #3c3c3c;
                    color: white;
                    border: 1px solid #555;
                    border-radius: 3px;
                    outline: none;
                }
                QListWidget::item {
                    padding: 2px 5px;
                    border: none;
                }
                QListWidget::item:selected {
                    background-color: #4a4a4a;
                }
                QListWidget::item:hover {
                    background-color: #454545;
                }
            """)
    
    def browse_wallpaper(self):
        start_dir = ""
        p = self.wallpaper_path_display.text().strip()
        if p and os.path.isfile(p):
            start_dir = os.path.dirname(p)
        elif p and os.path.isdir(p):
            start_dir = p
        file, _ = QFileDialog.getOpenFileName(
            self, self.tr.t('wallpaper_file'),
            start_dir,
            "Images (*.png *.jpg *.jpeg *.bmp *.webp *.gif *.tif *.tiff);;All files (*.*)"
        )
        if file:
            file = file.replace('\\', '/')
            self.wallpaper_path_display.setText(file)
            self.update_music_wallpaper_appearance()
            self.save_settings()
    
    def check_music_folder(self):
        folder = self.music_folder_display.text()
        if folder and os.path.exists(folder):
            count = 0
            for root, dirs, files in os.walk(folder):
                for file in files:
                    if any(file.lower().endswith(fmt) for fmt in self.config.supported_formats):
                        count += 1
            if count > 0:
                self.folder_status.setText(self.tr.t('found_files').format(count))
                self.folder_status.setStyleSheet("color: #4CAF50; font-size: 11px;")
            else:
                self.folder_status.setText(self.tr.t('folder_not_selected'))
                self.folder_status.setStyleSheet("color: #888; font-size: 11px;")
        else:
            self.folder_status.setText(self.tr.t('folder_not_found'))
            self.folder_status.setStyleSheet("color: #ff6b6b; font-size: 11px;")
    
    def update_volume(self, value):
        self.volume_label.setText(f"{value}%")
        self.config.volume = value / 100.0
        if self.bot_thread and self.bot_thread.is_running:
            self.bot_thread.update_volume_signal.emit(self.config.volume)
        self.on_setting_changed()
    
    def save_settings(self):
        self.config.token = self.token_input.text()
        self.config.music_folder = self.music_folder_display.text()
        self.config.ffmpeg_path = self.ffmpeg_display.text()
        self.config.autoplay_enabled = self.autoplay_check.isChecked()
        self.config.autoplay_mode = "shuffle" if self.autoplay_mode.currentText() == self.tr.t('shuffle') else "sequential"
        self.config.language = 'ru' if self.language_combo.currentIndex() == 0 else 'en'
        self.config.autostart = self.autostart_check.isChecked()
        self.config.show_album_art = self.show_album_art_check.isChecked()
        self.config.exclude_repeats = self.exclude_repeats_check.isChecked()
        self.config.wallpaper_enabled = self.wallpaper_enable_check.isChecked()
        self.config.wallpaper_path = self.wallpaper_path_display.text().strip()
        self.update_music_wallpaper_appearance()
        
        # Ролевая защита
        self.config.role_control_enabled = self.enable_role_protection.isChecked()
        try:
            self.config.control_role_id = int(self.control_role_id_input.text()) if self.control_role_id_input.text() else None
        except ValueError:
            self.config.control_role_id = None
            if self.control_role_id_input.text():
                QMessageBox.warning(self, self.tr.t('error'), self.tr.t('invalid_role_id'))
        
        try:
            self.config.admin_role_id = int(self.admin_role_id_input.text()) if self.admin_role_id_input.text() else None
        except ValueError:
            self.config.admin_role_id = None
            if self.admin_role_id_input.text():
                QMessageBox.warning(self, self.tr.t('error'), self.tr.t('invalid_role_id'))
        
        self.config.auto_connect_enabled = self.auto_connect_check.isChecked()

        # Web
        self.config.web_enabled = self.web_enable_check.isChecked()
        try:
            self.config.web_port = int(self.web_port_input.text())
        except ValueError:
            self.config.web_port = 8080

        # Reconnect
        self.config.reconnect_enabled = self.reconnect_check.isChecked()
        try:
            self.config.reconnect_delay = int(self.reconnect_delay_input.text())
        except ValueError:
            self.config.reconnect_delay = 5
        try:
            self.config.reconnect_max = int(self.reconnect_max_input.text())
        except ValueError:
            self.config.reconnect_max = 3

        # Пустой канал
        _ec_map = {0: "none", 1: "pause", 2: "disconnect"}
        self.config.empty_channel_action = _ec_map.get(self.empty_ch_action_combo.currentIndex(), "none")
        try:
            self.config.empty_channel_timeout = max(1, int(self.empty_ch_timeout_input.text()))
        except ValueError:
            self.config.empty_channel_timeout = 1

        if self.loaded_guild_id and self.loaded_voice_channel_id and self.loaded_text_channel_id:
            self.config.default_guild_id = self.loaded_guild_id
            self.config.default_voice_channel_id = self.loaded_voice_channel_id
            self.config.default_text_channel_id = self.loaded_text_channel_id
        else:
            guild_id = self.server_combo.currentData()
            voice_channel_id = self.voice_channel_combo.currentData()
            text_channel_id = self.text_channel_combo.currentData()
            if guild_id and voice_channel_id and text_channel_id and self.settings_loaded:
                self.config.default_guild_id = guild_id
                self.config.default_voice_channel_id = voice_channel_id
                self.config.default_text_channel_id = text_channel_id
                self.loaded_guild_id = guild_id
                self.loaded_voice_channel_id = voice_channel_id
                self.loaded_text_channel_id = text_channel_id
        
        self.config.save_to_file()
    
    def load_settings(self):
        if self.config.load_from_file():
            self.token_input.blockSignals(True)
            self.volume_slider.blockSignals(True)
            self.autoplay_check.blockSignals(True)
            self.autoplay_mode.blockSignals(True)
            self.language_combo.blockSignals(True)
            self.autostart_check.blockSignals(True)
            self.show_album_art_check.blockSignals(True)
            self.wallpaper_enable_check.blockSignals(True)
            self.exclude_repeats_check.blockSignals(True)
            self.enable_role_protection.blockSignals(True)
            self.control_role_id_input.blockSignals(True)
            self.admin_role_id_input.blockSignals(True)
            self.auto_connect_check.blockSignals(True)
            self.server_combo.blockSignals(True)
            self.voice_channel_combo.blockSignals(True)
            self.text_channel_combo.blockSignals(True)
            self.web_enable_check.blockSignals(True)
            self.reconnect_check.blockSignals(True)
            
            self.token_input.setText(self.config.token)
            self.music_folder_display.setText(self.config.music_folder)
            _ffmpeg = self.config.ffmpeg_path or "ffmpeg"
            if _ffmpeg == "ffmpeg" or not os.path.isfile(_ffmpeg):
                _ffmpeg = find_ffmpeg()
                self.config.ffmpeg_path = _ffmpeg
            self.ffmpeg_display.setText(_ffmpeg)
            self.volume_slider.setValue(int(self.config.volume * 100))
            self.autoplay_check.setChecked(self.config.autoplay_enabled)
            self.language_combo.setCurrentIndex(0 if self.config.language == 'ru' else 1)
            self.autostart_check.setChecked(self.config.autostart)
            self.show_album_art_check.setChecked(self.config.show_album_art)
            self.wallpaper_enable_check.setChecked(self.config.wallpaper_enabled)
            self.wallpaper_path_display.setText(self.config.wallpaper_path or "")
            self.exclude_repeats_check.setChecked(self.config.exclude_repeats)
            
            # Ролевая защита - загрузка
            self.enable_role_protection.setChecked(self.config.role_control_enabled)
            self.control_role_id_input.setText(str(self.config.control_role_id) if self.config.control_role_id else "")
            self.admin_role_id_input.setText(str(self.config.admin_role_id) if self.config.admin_role_id else "")
            self.toggle_role_inputs()

            # Web
            self.web_enable_check.setChecked(self.config.web_enabled)
            self.web_port_input.setText(str(self.config.web_port))

            # Reconnect
            self.reconnect_check.setChecked(self.config.reconnect_enabled)
            self.reconnect_delay_input.setText(str(self.config.reconnect_delay))
            self.reconnect_max_input.setText(str(self.config.reconnect_max))

            # Пустой канал
            _ec_map = {"none": 0, "pause": 1, "disconnect": 2}
            self.empty_ch_action_combo.setCurrentIndex(_ec_map.get(self.config.empty_channel_action, 0))
            self.empty_ch_timeout_input.setText(str(self.config.empty_channel_timeout))
            
            self.loaded_auto_connect = self.config.auto_connect_enabled
            self.loaded_guild_id = self.config.default_guild_id
            self.loaded_voice_channel_id = self.config.default_voice_channel_id
            self.loaded_text_channel_id = self.config.default_text_channel_id
            
            self.auto_connect_check.setChecked(self.loaded_auto_connect)
            
            self.tr.set_language(self.config.language)
            self.autoplay_mode.clear()
            self.autoplay_mode.addItems([self.tr.t('shuffle'), self.tr.t('sequential')])
            mode_index = 0 if self.config.autoplay_mode == "shuffle" else 1
            self.autoplay_mode.setCurrentIndex(mode_index)
            
            self.token_input.blockSignals(False)
            self.volume_slider.blockSignals(False)
            self.autoplay_check.blockSignals(False)
            self.autoplay_mode.blockSignals(False)
            self.language_combo.blockSignals(False)
            self.autostart_check.blockSignals(False)
            self.show_album_art_check.blockSignals(False)
            self.wallpaper_enable_check.blockSignals(False)
            self.exclude_repeats_check.blockSignals(False)
            self.enable_role_protection.blockSignals(False)
            self.control_role_id_input.blockSignals(False)
            self.admin_role_id_input.blockSignals(False)
            self.auto_connect_check.blockSignals(False)
            self.server_combo.blockSignals(False)
            self.voice_channel_combo.blockSignals(False)
            self.text_channel_combo.blockSignals(False)
            self.web_enable_check.blockSignals(False)
            self.reconnect_check.blockSignals(False)
            
            self.update_volume(int(self.config.volume * 100))
            self.check_music_folder()
            self.refresh_music_list()
            self.update_ui_language()
            self.update_music_wallpaper_appearance()
            self._update_ffmpeg_status_label()
            self.settings_loaded = True
    
    def refresh_music_list(self):
        if not self.config.music_folder or not os.path.exists(self.config.music_folder):
            return
        
        self.music_list.clear()
        files = []
        
        try:
            for root, dirs, filenames in os.walk(self.config.music_folder):
                dirs.sort(key=lambda x: x.lower())
                filenames.sort(key=lambda x: x.lower())
                
                for filename in filenames:
                    if any(filename.lower().endswith(fmt) for fmt in self.config.supported_formats):
                        full_path = os.path.join(root, filename)
                        display_name = get_track_name_from_file(full_path)
                        files.append({
                            'path': full_path,
                            'name': filename,
                            'relative': os.path.relpath(full_path, self.config.music_folder),
                            'display_name': display_name
                        })
            
            files.sort(key=lambda x: x['display_name'].lower())
            self.cached_music_files = files
            
            for f in files:
                self.music_list.addItem(f['display_name'])
            
            self.music_stats.setText(self.tr.t('total_files').format(len(files)))
            
            if self.bot_thread and self.bot_thread.is_running:
                self.bot_thread.refresh_music_list()
                
        except Exception as e:
            self.python_output(f"Error refreshing list: {e}")
    
    def filter_music_list(self):
        search = self.search_input.text().lower()
        for i in range(self.music_list.count()):
            self.music_list.item(i).setHidden(search not in self.music_list.item(i).text().lower())
    
    def play_selected(self, item):
        if not self.bot_thread or not self.bot_thread.is_running:
            QMessageBox.warning(self, self.tr.t('error'), self.tr.t('bot_not_running'))
            return
        
        selected_display_name = item.text()
        found_path = None
        
        if hasattr(self, 'cached_music_files'):
            for f in self.cached_music_files:
                if f['display_name'] == selected_display_name:
                    found_path = f['path']
                    break
        
        if not found_path:
            for root, dirs, files in os.walk(self.config.music_folder):
                for file in files:
                    if any(file.lower().endswith(fmt) for fmt in self.config.supported_formats):
                        full_path = os.path.join(root, file)
                        if get_track_name_from_file(full_path) == selected_display_name:
                            found_path = full_path
                            break
                if found_path:
                    break
        
        if not found_path:
            QMessageBox.warning(self, self.tr.t('error'), self.tr.t('track_not_found'))
            return
        
        self.bot_thread.add_track_from_gui.emit(found_path, selected_display_name)
    
    def log_message(self, message, is_error=False):
        try:
            lg = logging.getLogger("LocalMusicBot")
            if is_error:
                lg.error(message)
            else:
                lg.info(message)
        except Exception:
            pass
        self.logs_text.append(message)
        cursor = self.logs_text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.logs_text.setTextCursor(cursor)
    
    def python_output(self, text):
        line = text.rstrip()
        try:
            logging.getLogger("LocalMusicBot").info(line)
        except Exception:
            pass
        self.errors_text.append(line)
        cursor = self.errors_text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.errors_text.setTextCursor(cursor)
    
    def update_bot_status(self, is_running):
        if is_running:
            self.status_light.setStyleSheet("color: #4CAF50; font-size: 16px;")
            self.status_text.setText(self.tr.t('bot_running'))
            self.bot_control_btn.setText(self.tr.t('stop'))
            self.bot_control_btn.default_color = "#c2160a"
            self.bot_control_btn.hover_color = "#f43325"
            self.bot_control_btn.update_style()
            self.server_combo.setEnabled(True)
            self.voice_channel_combo.setEnabled(True)
            self.text_channel_combo.setEnabled(True)
            self.refresh_channels_btn.setEnabled(True)
        else:
            self.status_light.setStyleSheet("color: #ff6b6b; font-size: 16px;")
            self.status_text.setText(self.tr.t('bot_stopped_status'))
            self.bot_control_btn.setText(self.tr.t('start'))
            self.bot_control_btn.default_color = "#00802b"  
            self.bot_control_btn.hover_color = "#00cc44"
            self.bot_control_btn.update_style()
            self.playback_control_btn.setEnabled(False)
            self.skip_btn.setEnabled(False)
            self.clear_queue_btn.setEnabled(False)
            self.now_playing_label.setText(self.tr.t('not_playing'))
            self.is_playing = False
            self.is_paused = False
            self.progress_timer.stop()
            self.progress_bar.setValue(0)
            self.current_time_label.setText("0:00")
            self.total_time_label.setText("0:00")
            self.cover_label.setText(self.tr.t('no_cover'))
            self.cover_label.setPixmap(QPixmap())
            self.bot_name_label.setVisible(False)
            self.bot_name_label.setText("")
            self.autoplay_indicator.setText("")
            self.server_combo.setEnabled(False)
            self.voice_channel_combo.setEnabled(False)
            self.text_channel_combo.setEnabled(False)
            self.refresh_channels_btn.setEnabled(False)
            self._tray_update_playback_actions()
            self.spectrum_widget.set_active(False)
            self.reconnect_status_label.setText("")
    
    def start_bot(self):
        if not self.token_input.text():
            QMessageBox.warning(self, self.tr.t('error'), self.tr.t('enter_token'))
            return
        if not self.music_folder_display.text() or not os.path.exists(self.music_folder_display.text()):
            QMessageBox.warning(self, self.tr.t('error'), self.tr.t('select_folder'))
            return
        self.save_settings()
        self.bot_thread = DiscordBotThread(self.config, self.tr)
        self.bot_thread.log_signal.connect(self.log_message)
        self.bot_thread.error_signal.connect(self.python_output)
        self.bot_thread.music_list_updated.connect(self.update_music_list)
        self.bot_thread.status_changed.connect(self.update_bot_status)
        self.bot_thread.now_playing.connect(self.update_now_playing)
        self.bot_thread.bot_info_signal.connect(self.update_bot_info)
        self.bot_thread.guilds_updated.connect(self.update_guilds_list)
        self.bot_thread.pause_state_signal.connect(self.update_playback_button_from_discord)
        self.bot_thread.reconnect_signal.connect(self.on_reconnect_signal)
        self.bot_thread.web_stop_requested.connect(self.stop_bot, Qt.ConnectionType.QueuedConnection)
        self.bot_thread.start()
        self.log_message(self.tr.t('initializing'))

    def on_reconnect_signal(self, attempt, max_attempts):
        msg = self.tr.t("reconnect_status").format(attempt, max_attempts)
        self.reconnect_status_label.setText(msg)
        self.log_message(msg, is_error=True)

    def open_web_interface(self):
        try:
            port = int(self.web_port_input.text())
        except ValueError:
            port = 8080
        QDesktopServices.openUrl(QUrl(f"http://localhost:{port}"))
    
    def stop_bot(self):
        if self.bot_thread:
            self.bot_thread.stop()
            self.bot_thread.quit()
            self.bot_thread.wait(3000)
            self.bot_thread = None
        self.update_bot_status(False)
        self.log_message(self.tr.t('bot_stopped'))
    
    def update_music_list(self, files):
        self.music_list.clear()
        self.cached_music_files = files
        for f in files:
            self.music_list.addItem(f['display_name'])
        self.music_stats.setText(self.tr.t('total_files').format(len(files)))
    
    def _tray_toggle_playback(self):
        if self.is_paused:
            self.resume_playback()
        else:
            self.pause_playback()

    def _tray_update_playback_actions(self):
        """Синхронизирует пункты трея с текущим состоянием воспроизведения."""
        if not self._tray_icon:
            return
        playing = self.is_playing
        self._tray_pause_action.setEnabled(playing)
        self._tray_skip_action.setEnabled(playing)
        if self.is_paused:
            self._tray_pause_action.setText(self.tr.t("tray_resume"))
        else:
            self._tray_pause_action.setText(self.tr.t("tray_pause"))

    def _tray_show_window(self):
        self.showNormal()
        self.activateWindow()
        self.raise_()
        QTimer.singleShot(100, self._apply_taskbar_icon)

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._tray_show_window()

    def _tray_quit(self):
        """Принудительный выход через трей — с тем же подтверждением, что и closeEvent."""
        self._force_quit = True
        self.close()

    def closeEvent(self, event):
        # Если выход инициирован через меню трея (_tray_quit) — действительно закрываем
        # Иначе — сворачиваем в трей
        if self._tray_icon and self._tray_icon.isVisible() and not getattr(self, '_force_quit', False):
            event.ignore()
            self.hide()
            self._tray_icon.showMessage(
                "Local Music Bot",
                self.tr.t("tray_minimized"),
                QSystemTrayIcon.MessageIcon.Information,
                2000
            )
            return

        if self.bot_thread and self.bot_thread.is_running:
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle(self.tr.t('confirm_close_title'))
            msg_box.setText(self.tr.t('confirm_close_message'))
            msg_box.setIcon(QMessageBox.Icon.Question)
            
            yes_button = msg_box.addButton(self.tr.t('yes'), QMessageBox.ButtonRole.YesRole)
            no_button = msg_box.addButton(self.tr.t('no'), QMessageBox.ButtonRole.NoRole)
            msg_box.setDefaultButton(no_button)
            
            msg_box.exec()
            
            if msg_box.clickedButton() == no_button:
                self._force_quit = False
                event.ignore()
                return
        self.save_settings()
        self.stop_bot()
        if self._tray_icon:
            self._tray_icon.hide()
        sys.stdout = sys.__stdout__
        sys.stderr = sys.__stderr__
        event.accept()

def main():
    ensure_app_file_logging()
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    # Иконка в панели задач / трее
    _icon_path = resource_path("icon.ico")
    if os.path.isfile(_icon_path):
        app.setWindowIcon(QIcon(_icon_path))
    app.setStyleSheet("""
        QMainWindow {
            background-color: #2b2b2b;
        }
        QSplitter::handle {
            background-color: #444;
        }
        QScrollBar:vertical {
            border: none;
            background: #3c3c3c;
            width: 8px;
            border-radius: 4px;
        }
        QScrollBar::handle:vertical {
            background: #666;
            border-radius: 4px;
            min-height: 20px;
        }
        QScrollBar::handle:vertical:hover {
            background: #777;
        }
        QScrollBar:horizontal {
            border: none;
            background: #3c3c3c;
            height: 8px;
            border-radius: 4px;
        }
        QScrollBar::handle:horizontal {
            background: #666;
            border-radius: 4px;
            min-width: 20px;
        }
        QScrollBar::handle:horizontal:hover {
            background: #777;
        }
        QMessageBox {
            background-color: #2b2b2b;
            color: white;
        }
        QMessageBox QLabel {
            color: white;
        }
        QMessageBox QPushButton {
            background-color: #3c3c3c;
            color: white;
            border: 1px solid #555;
            border-radius: 3px;
            padding: 5px 10px;
            min-width: 60px;
        }
        QMessageBox QPushButton:hover {
            background-color: #4a4a4a;
        }
    """)
    
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
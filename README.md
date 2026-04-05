# Local Music Bot (LMB)

**[English](#-english)** . **[Русский](#-русский)** 

## 🇬🇧 English

**Local Music Bot** is a **Windows** app with a settings window. It plays **music from your computer** in a Discord voice channel.

### Features

- Play tracks from a folder, search by filename, or pick a random track  
- Queue, skip, pause, volume, clear queue  
- Autoplay: **shuffle** or **sequential**
- Chat commands: **`!`** prefix and **`/`** slash commands 
- Optional **autostart** and **auto-connect** to a chosen voice channel  
- **Role-based** restrictions on who can use stop, delete-from-disk, etc.  
- Optional **web UI** for control over your local network  
- All bot setup in the app window: token, music folder, FFmpeg, channels  
- Album art from file tags; optional **custom wallpaper** in the app  

### How to use

1. Open **[Releases](https://github.com/LouisFahrenheit/LMB/releases)** and download the latest build.  
2. Unzip anywhere and run the **EXE**.  
3. You need **your own** Discord bot (free). The **“Info”** tab in the app walks you through creating the app, enabling permissions, and inviting the bot.  
4. **FFmpeg** is required for audio: install it system-wide, place `ffmpeg.exe` next to the EXE, or set the full path in settings.  

Then enter your **bot token** and **music folder** and start the bot from the app—commands work on your server.

### Security

**`bot_settings.json`** stores your token in plain text. Do not share that file or a zip of the app folder if it contains your settings. To share the bot with friends, send them this page or the release link

---

## 🇷🇺 Русский

**Local Music Bot** — программа для Windows с окном настроек. Она проигрывает **музыку с вашего компьютера** в голосовом канале Discord. 

### Возможности

- Играть треки из папки, искать по названию файла или включить случайный трек  
- Очередь, пауза, громкость
- Автоплейлист: **перемешивание** или **по порядку** 
- Команды в чате: префикс **`!`** и **слэш-команды** **`/`**  
- **Автозапуск** программы и **автоподключение** к выбранному голосовому каналу  
- Ограничение команд по **ролям** на сервере  
- Опциональный **веб-интерфейс** для управления по локальной сети  
- Вся настройка бота — через окно программы  
- Обложки из тегов файлов, при желании — **свои обои** в окне приложения  

### Как пользоваться

1. Откройте **[Releases](https://github.com/LouisFahrenheit/LMB/releases)** и скачайте последнюю сборку.  
2. Распакуйте в любую папку и запустите **EXE**.  
3. В Discord нужен **свой бот** (бесплатно): как создать приложение, включить нужные права и пригласить бота — пошагово во вкладке **«Инфо»** в программе.  
4. Для звука нужен **FFmpeg**: установите в систему, положите `ffmpeg.exe` рядом с EXE или укажите полный путь к нему в настройках.  

Дальше в программе укажите **токен бота** и **папку с музыкой** — после запуска бота команды доступны на сервере.

### Безопасность

Файл **`bot_settings.json`** хранит токен в открытом виде. Не отправляйте его и не выкладывайте папку с программой, если в ней ваши настройки. Чтобы поделиться ботом с друзьями, отправьте ссылку на эту страницу или на релиз.

---
Repository: [github.com/LouisFahrenheit/LMB](https://github.com/LouisFahrenheit/LMB) — **PRs welcome.**

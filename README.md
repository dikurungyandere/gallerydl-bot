# gallerydl-bot

> **⚠️ AI-GENERATED CODE DISCLAIMER**: This entire codebase has been created by AI. Review it carefully before deploying to production.

A Telegram bot that downloads media from any [gallery-dl](https://github.com/mikf/gallery-dl)-supported website and uploads the files back to you via Telegram, using [Telethon](https://github.com/LonamiWebs/Telethon) (MTProto — supports files up to 2 GB).

---

## Features

- 📥 **Downloads** via `gallery-dl` — supports hundreds of sites (Instagram, Twitter/X, Reddit, Pixiv, etc.)
- 📤 **Uploads** back to Telegram using MTProto (bypassing the 50 MB Bot API limit, up to 2 GB per file)
- ⚡ **Parallel downloads** — send multiple URLs without waiting; each becomes an independent job
- 📡 **Custom forwarding target** — append `-> @channel` or `-> -100xxx` to send files to a specific chat
- 📊 **Progress reporting** — live download and upload progress with a text progress bar
- 🔀 **Album support** — batch downloads are automatically chunked into albums of ≤ 10 files (Telegram's limit)
- ❌ **Cancellation** — `/cancel` stops all jobs; `/cancel <job_id>` stops a specific one
- 🔒 **Access control** — restrict usage to a whitelist of Telegram user IDs via `ALLOWED_USERS`
- 🧹 **Automatic cleanup** — temporary files are always deleted after upload (or on error/cancel)

---

## Requirements

- Python 3.10+
- [`gallery-dl`](https://github.com/mikf/gallery-dl) installed and available on `PATH`

---

## Setup

```bash
# 1. Clone the repository
git clone https://github.com/dikurungyandere/gallerydl-bot.git
cd gallerydl-bot

# 2. Create and activate a virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 3. Install Python dependencies
pip install -r requirements.txt

# 4. Install gallery-dl (if not already installed)
pip install gallery-dl
# or: pipx install gallery-dl

# 5. Configure environment variables
cp .env.example .env
# Edit .env with your credentials (see below)

# 6. Start the bot
python bot.py
```

---

## Configuration

Copy `.env.example` to `.env` and fill in the values:

| Variable | Required | Description |
|---|---|---|
| `API_ID` | ✅ | Telegram API ID from [my.telegram.org](https://my.telegram.org) |
| `API_HASH` | ✅ | Telegram API Hash from [my.telegram.org](https://my.telegram.org) |
| `BOT_TOKEN` | ✅ | Bot token from [@BotFather](https://t.me/BotFather) |
| `ALLOWED_USERS` | ❌ | Comma-separated Telegram user IDs. Empty = allow all (⚠️ not recommended) |
| `GALLERY_DL_CONFIG_PATH` | ❌ | Path to a `gallery-dl.conf` file |
| `GALLERY_DL_CONFIG_B64` | ❌ | gallery-dl config as a **base64-encoded** JSON string (preferred; avoids shell quoting issues). Encode with: `base64 < gallery-dl.conf` |
| `GALLERY_DL_CONFIG_JSON` | ❌ | gallery-dl config as a raw JSON string (legacy; use `GALLERY_DL_CONFIG_B64` instead) |

Priority order when multiple are set: `GALLERY_DL_CONFIG_PATH` > `GALLERY_DL_CONFIG_B64` > `GALLERY_DL_CONFIG_JSON`.

---

## Commands

| Command | Description |
|---|---|
| `/start` | Show the welcome message |
| `/help` | Show usage instructions |
| `/cancel` | Cancel **all** active downloads/uploads |
| `/cancel <job_id>` | Cancel a specific job (the job ID is shown in each status message) |

Send any supported URL as a plain message to start a download. Multiple URLs can be sent at once — each starts an independent parallel job.

To forward files to a specific channel or group instead of the current chat, append `-> @username` or `-> -100xxxxxxxxxx` after the URL:

```
https://example.com/gallery -> @myarchivechannel
https://example.com/gallery -> -100123456789
```

---

## Project Structure

```
gallerydl-bot/
├── bot.py           # Main entry point: event handlers and pipeline orchestration
├── config.py        # Configuration loading and validation
├── downloader.py    # gallery-dl subprocess wrapper
├── uploader.py      # Telegram upload logic (progress, album chunking)
├── task_manager.py  # Per-user task state and cancellation
├── utils.py         # Progress bar formatter, throttled message editing, cleanup
├── requirements.txt # Python dependencies
├── .env.example     # Template for environment variables
└── .gitignore
```

---

## Security Notes

- **Never commit your `.env` file.** It contains your Telegram credentials.
- Set `ALLOWED_USERS` to restrict the bot to trusted users only.
- `gallery-dl` executes on arbitrary user-supplied URLs. Exposing this bot publicly is a security risk.

---

## License

This project is provided as-is under the MIT License. See the AI disclaimer above.
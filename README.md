# gallerydl-bot

> **⚠️ AI-GENERATED CODE DISCLAIMER**: This entire codebase has been created by AI. Review it carefully before deploying to production.

A Telegram bot that downloads media from any [gallery-dl](https://github.com/mikf/gallery-dl)-supported website and uploads the files back to you via Telegram, using [Telethon](https://github.com/LonamiWebs/Telethon) (MTProto — supports files up to 2 GB).

---

## Features

- 📥 **Downloads** via `gallery-dl` — supports hundreds of sites (Instagram, Twitter/X, Reddit, Pixiv, etc.)
- 📤 **Uploads** back to Telegram using MTProto (bypassing the 50 MB Bot API limit, up to 2 GB per file)
- ⚡ **Parallel downloads** — send multiple URLs without waiting; each becomes an independent job
- 🔄 **Streaming pipeline** — each file is uploaded to Telegram as soon as it finishes downloading; no need to wait for an entire gallery to complete before the first file arrives
- 📡 **Custom forwarding target** — append `-> @channel` or `-> -100xxx` to send files to a specific chat
- 📊 **Progress reporting** — live download and upload progress with a text progress bar
- 🔀 **Album support** — batch downloads are automatically chunked into albums of ≤ 10 files (Telegram's limit)
- ✂️ **Automatic file splitting** — files larger than ~1950 MB are split into numbered parts (`.001`, `.002`, …) so they can be uploaded and manually reassembled: `cat file.mp4.001 file.mp4.002 > file.mp4`
- 🎬 **Streamable video** — video files are sent as Telegram videos (not documents) with `supports_streaming=True`, so they play directly in the app without downloading
- ❌ **Cancellation** — `/cancel` stops all jobs; `/cancel <job_id>` stops a specific one
- 📈 **Stats command** — `/stats` shows CPU, memory, disk usage and active job count
- 🌐 **Optional Web UI** — a lightweight HTTP status page for PaaS platforms (`WEBUI=true`)
- 🔒 **Access control** — restrict usage to a whitelist of Telegram user IDs via `ALLOWED_USERS`
- 🧹 **Automatic cleanup** — temporary files are always deleted after upload (or on error/cancel)
- 🐳 **Docker-ready** — single-command deployment with `docker compose up -d`

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Getting your credentials](#getting-your-credentials)
3. [Setup — local Python](#setup--local-python)
4. [Setup — Docker (recommended)](#setup--docker-recommended)
5. [Configuration reference](#configuration-reference)
6. [Commands](#commands)
7. [Forwarding to a channel or group](#forwarding-to-a-channel-or-group)
8. [Web UI for PaaS deployment](#web-ui-for-paas-deployment)
9. [Project structure](#project-structure)
10. [Security notes](#security-notes)

---

## Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.10+ | Only needed for local setup; Docker handles this automatically |
| A Telegram account | Required to obtain API credentials |
| A bot token | Obtained from [@BotFather](https://t.me/BotFather) |

---

## Getting your credentials

You will need **three pieces of information** before running the bot.

### 1. Telegram API ID and API Hash

These let the bot use the MTProto API (needed for large-file uploads).

1. Go to [https://my.telegram.org](https://my.telegram.org) and sign in with your phone number.
2. Click **"API development tools"**.
3. Fill in a name and short description (anything works), then click **"Create application"**.
4. Copy the **App api_id** (a number) and **App api_hash** (a long hex string).

### 2. Bot Token

1. Open Telegram and search for **@BotFather**.
2. Send `/newbot` and follow the prompts (choose a name and a `@username`).
3. BotFather will reply with a token that looks like `123456789:ABCdef…`. Copy it.

### 3. Your Telegram User ID (for ALLOWED_USERS)

To restrict the bot to yourself only (strongly recommended):

1. Search for **@userinfobot** on Telegram and start it.
2. It will reply with your numeric user ID (e.g. `123456789`).

---

## Setup — local Python

```bash
# 1. Clone the repository
git clone https://github.com/dikurungyandere/gallerydl-bot.git
cd gallerydl-bot

# 2. Create and activate a virtual environment (keeps dependencies isolated)
python -m venv .venv
source .venv/bin/activate      # macOS / Linux
# .venv\Scripts\activate       # Windows PowerShell

# 3. Install Python dependencies
pip install -r requirements.txt

# 4. Configure environment variables
cp .env.example .env
# Open .env in your editor and fill in API_ID, API_HASH, BOT_TOKEN.
# Optionally set ALLOWED_USERS to your numeric Telegram user ID.

# 5. Start the bot
python bot.py
```

The first time you run the bot, Telethon may ask you to confirm the session
interactively in the terminal. This only happens once; the session is saved
to `bot_session.session`.

---

## Setup — Docker (recommended)

Docker handles Python, gallery-dl, and all dependencies automatically.

### Requirements

- [Docker](https://docs.docker.com/get-docker/) (with the Compose plugin, included in Docker Desktop)

### Steps

```bash
# 1. Clone the repository
git clone https://github.com/dikurungyandere/gallerydl-bot.git
cd gallerydl-bot

# 2. Configure environment variables
cp .env.example .env
# Open .env in your editor and fill in API_ID, API_HASH, BOT_TOKEN.

# 3. Build and start in the background
docker compose up -d

# 4. View logs
docker compose logs -f

# 5. Stop the bot
docker compose down
```

> **Session persistence**: The named Docker volume `bot_data` keeps the
> Telegram session file across restarts so the bot does not need to
> re-authenticate.

> **Web UI with Docker**: Set `WEBUI=true` in `.env` and uncomment the
> `ports` block in `docker-compose.yml`, then `docker compose up -d` again.

---

## Configuration reference

Copy `.env.example` to `.env` and fill in the values.

### Required

| Variable | Description |
|---|---|
| `API_ID` | Telegram API ID (integer) from [my.telegram.org](https://my.telegram.org) |
| `API_HASH` | Telegram API Hash from [my.telegram.org](https://my.telegram.org) |
| `BOT_TOKEN` | Bot token from [@BotFather](https://t.me/BotFather) |

### Optional

| Variable | Default | Description |
|---|---|---|
| `ALLOWED_USERS` | *(empty = anyone)* | Comma-separated Telegram user IDs that may use the bot. Strongly recommended. |
| `GALLERY_DL_CONFIG_PATH` | — | Path to a `gallery-dl.conf` file on disk. |
| `GALLERY_DL_CONFIG_B64` | — | gallery-dl config as a **base64-encoded** JSON string. Preferred over `GALLERY_DL_CONFIG_JSON` because it avoids shell quoting issues. Encode with: `base64 < gallery-dl.conf` |
| `GALLERY_DL_CONFIG_JSON` | — | gallery-dl config as a raw JSON string (legacy). |
| `WEBUI` | `false` | Set to `true` to enable the HTTP status page. |
| `WEBUI_HOST` | `0.0.0.0` | Interface the web server binds to. |
| `WEBUI_PORT` | `8080` | Port the web server listens on. |

**Config priority**: `GALLERY_DL_CONFIG_PATH` → `GALLERY_DL_CONFIG_B64` → `GALLERY_DL_CONFIG_JSON` (first match wins).

---

## Commands

| Command | Description |
|---|---|
| `/start` | Show the welcome message |
| `/help` | Show detailed usage instructions |
| `/stats` | Show CPU, memory, disk and active job count |
| `/cancel` | Cancel **all** active downloads/uploads |
| `/cancel <job_id>` | Cancel a specific job (ID shown in each status message) |

### Downloading

Send any supported URL as a plain message to start a download. The bot will
reply with a status message that updates as the download and upload progress.

Each file is uploaded to Telegram **as soon as it finishes downloading** — you
do not have to wait for an entire gallery to complete before the first file
arrives in your chat.

Multiple URLs can be sent at once — each starts an independent parallel job.

### Large files (> ~1950 MB)

Files that exceed Telegram's per-file upload limit are automatically split into
numbered parts:

```
file.mp4.001
file.mp4.002
…
```

Reassemble them on your device:

```bash
cat file.mp4.001 file.mp4.002 > file.mp4
```

### Video streaming

Video files (`.mp4`, `.mkv`, `.webm`, …) are sent as **Telegram videos** with
`supports_streaming=True` so they play directly in the Telegram app without
downloading the full file first.  No ffmpeg is required on the server side; for
the best streaming experience the source video should have its moov atom at the
front of the file (MP4 "faststart" encoding).

---

## Forwarding to a channel or group

By default, files are sent back to the same chat where you sent the URL.
To redirect them to a **channel or group** instead, append `-> @target`
after the URL:

```
https://example.com/gallery -> @myarchivechannel
https://example.com/gallery -> -100123456789
```

### ⚠️ Before forwarding works, you must add the bot to the channel/group

The bot can only send messages to chats it is a member of with posting
permissions. Follow these steps:

1. Open your channel or group in Telegram.
2. Go to **Administrators** → **Add Administrator**.
3. Search for your bot's `@username` and add it.
4. Grant at least the **"Post Messages"** permission (for channels) or
   **"Send Messages"** permission (for groups).

Once the bot is an admin, forwarding will work.

---

## Web UI for PaaS deployment

Some PaaS platforms (Render, Railway, Fly.io, Heroku, etc.) require your
application to serve HTTP traffic on a public port; otherwise they will
think the app crashed and restart it.

Enable the built-in status page with:

```ini
WEBUI=true
WEBUI_PORT=8080   # must match what your platform expects
```

The bot will then serve:

| URL | Content |
|---|---|
| `http://your-host:8080/` | HTML status page (uptime, active jobs, CPU, memory, disk) |
| `http://your-host:8080/health` | JSON health endpoint (same data, machine-readable) |

The HTML page automatically refreshes every 30 seconds and is safe to expose
publicly — it shows no sensitive information.

### Render / Railway quick-start

1. Fork this repository.
2. Create a new Web Service pointing at your fork.
3. Set the **Start Command** to `python bot.py`.
4. Add all required environment variables (`API_ID`, `API_HASH`, `BOT_TOKEN`)
   plus `WEBUI=true` and `WEBUI_PORT=<port assigned by the platform>`.
5. Deploy. The platform's health check will hit `/health` and confirm the
   app is running.

---

## Project structure

```
gallerydl-bot/
├── bot.py            # Entry point: event handlers and pipeline orchestration
├── config.py         # Configuration loading and validation
├── downloader.py     # gallery-dl subprocess wrapper
├── uploader.py       # Telegram upload logic (progress, album chunking)
├── task_manager.py   # Per-job task state and cancellation
├── utils.py          # Progress bar formatter, throttled message editing, cleanup
├── webui.py          # Optional aiohttp status page (/  and /health)
├── tests.py          # Unit tests
├── requirements.txt  # Python dependencies
├── Dockerfile        # Container image definition
├── docker-compose.yml# Docker Compose service definition
├── .env.example      # Template for environment variables
└── .gitignore
```

---

## Security notes

- **Never commit your `.env` file.** It contains your Telegram credentials.
- Set `ALLOWED_USERS` to restrict the bot to trusted users only.
- `gallery-dl` executes on arbitrary user-supplied URLs. Exposing this bot publicly is a security risk.
- The web UI (`/` and `/health`) exposes only system metrics — no credentials or private data.

---

## License

This project is provided as-is under the MIT License. See the AI disclaimer above.

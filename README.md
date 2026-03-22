# gallerydl-bot

> **⚠️ AI-GENERATED CODE DISCLAIMER**: This entire codebase has been created by AI. Review it carefully before deploying to production.

A Telegram bot that downloads media from any [gallery-dl](https://github.com/mikf/gallery-dl)-supported website and uploads the files back to you via Telegram, using [Pyrogram](https://github.com/TelegramPlayGround/Pyrogram) (MTProto — supports files up to 2 GB).

---

## Features

- 📥 **Downloads** via `gallery-dl` — supports hundreds of sites (Instagram, Twitter/X, Reddit, Pixiv, etc.)
- 📤 **Uploads** back to Telegram using MTProto (bypassing the 50 MB Bot API limit, up to 2 GB per file)
- ⚡ **Parallel downloads** — send multiple URLs without waiting; each becomes an independent job
- 🎛️ **Configuration menu** — after sending a URL an inline-keyboard menu lets you choose destination, upload mode, custom config, and custom args before the download begins
- 📡 **Custom destination** — send files to a different channel or group by picking "Custom chat" in the menu
- 🔄 **Default mode** — all files are downloaded first, then uploaded to Telegram one-by-one
- 🚀 **Duplex mode** — each file is uploaded as soon as it finishes downloading, overlapping with the remaining downloads
- ⚙️ **Custom config** — supply a per-job gallery-dl config file (document upload) or paste config JSON/TOML directly; overrides the bot's global config for that job
- 🔧 **Custom args** — pass extra gallery-dl CLI arguments per job (e.g. `--username`, `--password`, `--filter`) without touching global settings
- 📊 **Progress reporting** — live download and upload progress with a text progress bar
- ✂️ **Automatic file splitting** — files larger than ~1950 MB are split into numbered parts (`.001`, `.002`, …) so they can be uploaded and manually reassembled: `cat file.mp4.001 file.mp4.002 > file.mp4`
- 🎬 **Streamable video** — video files are sent as Telegram videos (not documents) with `supports_streaming=True`, so they play directly in the app without downloading
- 🔍 **Status command** — `/status` shows all your currently active jobs with live progress and a Refresh button
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
7. [Configuration menu](#configuration-menu)
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

The first time you run the bot, Pyrogram creates a session file
(`bot_session.session`) that is reused on subsequent starts so the bot does
not need to re-authenticate.

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
| `/status` | Show all your currently active jobs with live progress and a Refresh button |
| `/stats` | Show CPU, memory, disk and active job count |
| `/cancel` | Cancel **all** active downloads/uploads |
| `/cancel <job_id>` | Cancel a specific job (ID shown in each status message) |

### Downloading

Send any supported URL as a plain message. The bot replies with a
**configuration menu** (inline keyboard) where you set your options before the
download starts:

| Row | Left button | Right button |
|-----|-------------|--------------|
| 1 | **Current chat** ✓ (default) | **Custom chat** |
| 2 | **Default** mode ✓ (default) | **Duplex** mode |
| 3 | **⚙️ Custom Config** | **🔧 Custom Args** |
| 4 | **▶ Run** | **✖ Cancel** |

Press **▶ Run** to start the job, or **✖ Cancel** to discard it.

Multiple URLs can be sent at once — each gets its own menu and runs as an
independent parallel job.

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

## Configuration menu

After sending a URL the bot presents an inline-keyboard menu so you can
configure the job before it starts.

### Destination (row 1)

| Button | Behaviour |
|--------|-----------|
| **Current chat** ✓ | Files are uploaded to the same chat where you sent the URL (default). |
| **Custom chat** | Prompts you to **reply** to the menu message with a `@username` or numeric ID (e.g. `-100123456789`). Your reply is deleted automatically to keep the chat clean. Press **✖ Cancel** in the prompt to go back without changing the destination. |

> **Before forwarding to a channel or group works**, the bot must be an admin
> with posting permissions:
>
> 1. Open your channel or group in Telegram.
> 2. Go to **Administrators** → **Add Administrator**.
> 3. Search for your bot's `@username` and add it.
> 4. Grant at least **"Post Messages"** (channels) or **"Send Messages"** (groups).

### Upload mode (row 2)

| Button | Behaviour |
|--------|-----------|
| **Default** ✓ | gallery-dl downloads **all** files first; once the download is complete the files are uploaded to Telegram one-by-one. |
| **Duplex** | Each file is uploaded to Telegram **as soon as it finishes downloading**, without waiting for the rest of the gallery. Downloads and uploads run simultaneously. Useful for large galleries where you want the first files quickly. |

### Custom config (row 3)

| Button | Behaviour |
|--------|-----------|
| **⚙️ Custom Config** | Opens a prompt that shows the current config status (**None** / **Applied**) for this job. **Reply** to that prompt with either a **config file** (send it as a Telegram document) or **paste** the config text (JSON or TOML) directly. The custom config takes precedence over the bot's global config for this job only. Use **🔄 Reset** to clear it, or **✖ Cancel** to go back without changing anything. |

The menu message always shows the current state:
```
Custom config: None      ← no custom config set
Custom config: Applied   ← a custom config is active for this job
```

### Custom args (row 3)

| Button | Behaviour |
|--------|-----------|
| **🔧 Custom Args** | Opens a prompt that shows the current extra arguments (**None** / the argument string) for this job. **Reply** to that prompt with any extra `gallery-dl` CLI arguments as a single line of text. Use **🔄 Reset** to clear them, or **✖ Cancel** to go back without changing anything. |

Examples of useful custom args:

```
--username myuser --password mypass
--filter "width > 1000"
--chapter-range 1-5
```

The menu message always shows the current state:
```
Custom args: None
Custom args: `--username myuser --password mypass`
```

### Run / Cancel (row 4)

| Button | Behaviour |
|--------|-----------|
| **▶ Run** | Starts the download and upload pipeline with the current settings. |
| **✖ Cancel** | Discards the pending job without downloading anything. |

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
├── uploader.py       # Telegram upload logic (progress, per-file sending)
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

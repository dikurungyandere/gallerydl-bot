"""
gallerydl-bot: A Telegram bot that downloads media via gallery-dl and uploads
it back to the user using Telethon (MTProto, up to 2 GB).

AI-GENERATED CODE DISCLAIMER: This entire codebase has been created by AI.
Treat it carefully and review before deploying to production.

Usage:
    1. Copy .env.example to .env and fill in your credentials.
    2. Install dependencies: pip install -r requirements.txt
    3. Run: python bot.py
"""

import asyncio
import logging
import os
import tempfile
import time
from typing import Optional, Union

from telethon import TelegramClient, events
from telethon.errors import FloodWaitError

from config import Config, load_config
from downloader import URL_RE, TARGET_RE, run_gallery_dl
from task_manager import UserTask, task_manager
from uploader import upload_files
from utils import cleanup_directory, safe_edit_message
from webui import collect_stats, format_uptime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level config (populated in main()).
# ---------------------------------------------------------------------------
cfg: Optional[Config] = None
client: Optional[TelegramClient] = None

# ---------------------------------------------------------------------------
# Authentication decorator
# ---------------------------------------------------------------------------

def require_allowed(func):
    """Silently ignore messages from users not in ALLOWED_USERS."""
    async def wrapper(event):
        if cfg and cfg.allowed_users:
            sender_id = event.sender_id
            if sender_id not in cfg.allowed_users:
                logger.debug("Ignoring message from unauthorized user %s.", sender_id)
                return
        return await func(event)
    return wrapper


# ---------------------------------------------------------------------------
# /start and /help handlers
# ---------------------------------------------------------------------------

START_TEXT = (
    "👋 **gallerydl-bot**\n\n"
    "Send me any URL supported by [gallery-dl](https://github.com/mikf/gallery-dl) "
    "and I will download the media and send it back to you.\n\n"
    "You can run **multiple downloads at once** — just send another URL while one is "
    "already in progress.\n\n"
    "To forward files to a specific channel or group, append `-> @username` or "
    "`-> -100xxxxxxxxxx` after the URL:\n"
    "`https://example.com/gallery -> @mychannel`\n\n"
    "Commands:\n"
    "• /start — Show this message\n"
    "• /help  — Show usage instructions\n"
    "• /stats — Show server and bot statistics\n"
    "• /cancel — Cancel **all** your active downloads/uploads\n"
    "• /cancel `<job_id>` — Cancel a specific job (ID shown in the status message)\n\n"
    "_⚠️ This bot was created by AI. Use at your own risk._"
)

HELP_TEXT = (
    "📖 **How to use gallerydl-bot**\n\n"
    "1. Send a URL (e.g. an Instagram post, a Twitter/X post, a Reddit gallery…).\n"
    "2. The bot will download the media using `gallery-dl`.\n"
    "3. All downloaded files are uploaded back to you (or a target chat) via Telegram.\n\n"
    "**Parallel downloads**\n"
    "You can send multiple URLs without waiting — each one starts a separate job. "
    "The status message for each job shows its job ID.\n\n"
    "**Custom destination**\n"
    "Append `-> @channel` or `-> -100xxxxxxxxxx` after the URL to forward files "
    "to a specific channel or group instead of this chat.\n"
    "Example: `https://example.com/post -> @myarchivechannel`\n\n"
    "⚠️ **The bot must be added as an admin to the target channel/group first,**\n"
    "otherwise the upload will fail with a permissions error.\n\n"
    "**Limits**\n"
    "• Albums are split into chunks of 10 (Telegram limit).\n"
    "• Maximum upload size is ~2 GB per file (MTProto).\n"
    "• Only URLs listed in `gallery-dl`'s supported sites work.\n\n"
    "**Commands**\n"
    "• /stats — Show CPU, memory, disk and active job count.\n"
    "• /cancel — Stop **all** active downloads/uploads.\n"
    "• /cancel `<job_id>` — Stop a specific job.\n\n"
    "_⚠️ This bot was created by AI. Review the source before trusting it._"
)


@require_allowed
async def start_handler(event) -> None:
    """Handle the /start command."""
    await event.respond(START_TEXT)


@require_allowed
async def help_handler(event) -> None:
    """Handle the /help command."""
    await event.respond(HELP_TEXT)


# ---------------------------------------------------------------------------
# /stats handler
# ---------------------------------------------------------------------------

@require_allowed
async def stats_handler(event) -> None:
    """Handle the /stats command — show server and bot statistics."""
    stats = collect_stats()
    lines = [
        "📊 **Server Stats**\n",
        f"⏱ **Uptime:** {stats['uptime_human']}",
        f"⚡ **Active jobs:** {stats['active_jobs']}",
    ]

    if "cpu_percent" in stats:
        lines += [
            "",
            "🖥 **System**",
            f"• CPU: {stats['cpu_percent']:.1f}%",
            (
                f"• RAM: {stats['memory_used_mb']} MB"
                f" / {stats['memory_total_mb']} MB"
                f" ({stats['memory_percent']:.1f}%)"
            ),
            (
                f"• Disk: {stats['disk_used_gb']} GB"
                f" / {stats['disk_total_gb']} GB"
                f" ({stats['disk_percent']:.1f}%)"
            ),
        ]
    else:
        lines.append("\n_Install psutil for system resource stats._")

    await event.respond("\n".join(lines))


# ---------------------------------------------------------------------------
# /cancel handler
# ---------------------------------------------------------------------------

@require_allowed
async def cancel_handler(event) -> None:
    """Handle the /cancel [job_id] command.

    With no argument: cancel all active jobs for this user.
    With a numeric job_id: cancel only that specific job.
    """
    user_id: int = event.sender_id
    text: str = event.raw_text or ""

    # Check for an optional numeric job_id argument.
    parts = text.strip().split(None, 1)
    job_id_arg: Optional[int] = None
    if len(parts) == 2:
        try:
            job_id_arg = int(parts[1])
        except ValueError:
            await event.respond(
                "⚠️ Invalid job ID. Use /cancel to stop all jobs, "
                "or /cancel <job_id> for a specific one."
            )
            return

    active_jobs = task_manager.get_user_tasks(user_id)

    if not active_jobs:
        await event.respond("ℹ️ You have no active downloads or uploads to cancel.")
        return

    if job_id_arg is not None:
        # Cancel a specific job.
        ut = task_manager.get(job_id_arg)
        if ut is None or ut.user_id != user_id:
            await event.respond(f"ℹ️ No active job #{job_id_arg} found.")
            return

        status_msg = ut.status_message
        cancelled = await task_manager.cancel(job_id_arg)
        if cancelled:
            if status_msg is not None:
                try:
                    await status_msg.edit(f"❌ Job #{job_id_arg} cancelled by user.")
                except Exception:
                    pass
            else:
                await event.respond(f"❌ Job #{job_id_arg} cancelled by user.")
        else:
            await event.respond(f"ℹ️ Job #{job_id_arg} could not be cancelled.")
    else:
        # Cancel all jobs for this user.
        # Edit each status message before cancelling so the user sees which
        # jobs were stopped.
        for jid, ut in active_jobs:
            if ut.status_message is not None:
                try:
                    await ut.status_message.edit(f"❌ Job #{jid} cancelled by user.")
                except Exception:
                    pass

        count = await task_manager.cancel_all(user_id)
        if count:
            await event.respond(f"❌ Cancelled {count} active job(s).")
        else:
            await event.respond("ℹ️ Nothing to cancel.")


# ---------------------------------------------------------------------------
# URL / download handler
# ---------------------------------------------------------------------------

@require_allowed
async def url_handler(event) -> None:
    """Handle incoming messages that contain a URL.

    Supports an optional forwarding target after the URL:
        https://example.com/gallery -> @mychannel
        https://example.com/gallery -> -100123456789
    """
    user_id: int = event.sender_id
    text: str = event.raw_text or ""

    # Strip the optional "-> target" suffix before URL matching.
    target_str: Optional[str] = None
    target_match = TARGET_RE.search(text)
    if target_match:
        target_str = target_match.group(1)
        text_for_url = text[: target_match.start()]
    else:
        text_for_url = text

    match = URL_RE.search(text_for_url)
    if not match:
        return
    url: str = match.group(0)

    # Resolve the target chat: numeric ID or username.
    target_chat_id: Union[int, str, None]
    if target_str is None:
        target_chat_id = event.chat_id  # type: ignore[attr-defined]
    elif target_str.lstrip("-").isdigit():
        target_chat_id = int(target_str)
    else:
        target_chat_id = target_str  # Telethon accepts "@username" strings

    # Create a new job slot — no limit on concurrent jobs.
    job_id, ut = task_manager.create(user_id)
    ut.cancel_flag = False

    # Create a unique temp directory for this request.
    temp_dir = tempfile.mkdtemp(prefix=f"gdlbot_{user_id}_{job_id}_")
    ut.temp_dir = temp_dir

    # Send initial status message (includes the job ID for reference).
    status_message = await event.respond(f"⏳ Starting download… (job #{job_id})")
    ut.status_message = status_message

    # Wrap the pipeline in a task so we can cancel it.
    loop = asyncio.get_event_loop()
    task = loop.create_task(
        _pipeline(job_id, ut, url, temp_dir, target_chat_id, status_message)
    )
    ut.task = task


async def _pipeline(
    job_id: int,
    ut: UserTask,
    url: str,
    temp_dir: str,
    target_chat_id: Union[int, str],
    status_message,
) -> None:
    """Run the full download → upload pipeline for a single job."""
    last_edit: list = [0.0]

    try:
        # ----------------------------------------------------------------
        # Step 1: Download via gallery-dl
        # ----------------------------------------------------------------
        file_count_ref: list = [0]

        async def on_download_progress(n_files: int) -> None:
            file_count_ref[0] = n_files
            await safe_edit_message(
                status_message,
                f"📥 Downloading… {n_files} file(s) so far. (job #{job_id})",
                last_edit,
            )

        config_path = cfg.gallery_dl_config_path if cfg else None
        files = await run_gallery_dl(
            ut=ut,
            url=url,
            temp_dir=temp_dir,
            config_path=config_path,
            on_progress=on_download_progress,
        )

        if ut.cancel_flag:
            return

        if not files:
            await safe_edit_message(
                status_message,
                (
                    "⚠️ No files were downloaded.\n"
                    "The URL may be invalid, private, or unsupported by gallery-dl."
                ),
                last_edit,
                force=True,
            )
            return

        # ----------------------------------------------------------------
        # Step 2: Upload to Telegram
        # ----------------------------------------------------------------
        await safe_edit_message(
            status_message,
            f"✅ Downloaded {len(files)} file(s). Starting upload… (job #{job_id})",
            last_edit,
            force=True,
        )

        await upload_files(
            client=client,
            target_chat_id=target_chat_id,
            ut=ut,
            files=files,
            status_message=status_message,
        )

    except asyncio.CancelledError:
        logger.info("Pipeline cancelled for job #%s.", job_id)
        try:
            await status_message.edit(f"❌ Job #{job_id} cancelled by user.")
        except Exception:
            pass

    except FloodWaitError as exc:
        wait = exc.seconds
        logger.warning("FloodWaitError for job #%s. Waiting %s s.", job_id, wait)
        try:
            await status_message.edit(
                f"⚠️ Telegram rate limit hit. Please wait {wait} seconds and try again."
            )
        except Exception:
            pass
        await asyncio.sleep(wait)

    except RuntimeError as exc:
        logger.error("Pipeline error for job #%s: %s", job_id, exc)
        try:
            await status_message.edit(f"❌ Error: {exc}")
        except Exception:
            pass

    except Exception as exc:
        logger.exception("Unexpected error for job #%s: %s", job_id, exc)
        try:
            await status_message.edit(f"❌ Unexpected error: {exc}")
        except Exception:
            pass

    finally:
        # ----------------------------------------------------------------
        # Step 3: Cleanup (always runs)
        # ----------------------------------------------------------------
        cleanup_directory(temp_dir)
        task_manager.remove(job_id)
        logger.info("Cleanup complete for job #%s.", job_id)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Start the bot (and the optional Web UI)."""
    global cfg, client

    cfg = load_config()
    logger.info(
        "Loaded config. allowed_users=%s gallery_dl_config=%s webui=%s",
        cfg.allowed_users or "all",
        cfg.gallery_dl_config_path,
        cfg.webui_enabled,
    )

    client = TelegramClient("bot_session", cfg.api_id, cfg.api_hash)

    # Register handlers.
    client.add_event_handler(
        start_handler, events.NewMessage(pattern=r"^/start(\s.*)?$")
    )
    client.add_event_handler(
        help_handler, events.NewMessage(pattern=r"^/help(\s.*)?$")
    )
    client.add_event_handler(
        stats_handler, events.NewMessage(pattern=r"^/stats(\s.*)?$")
    )
    client.add_event_handler(
        cancel_handler, events.NewMessage(pattern=r"^/cancel(\s.*)?$")
    )
    # URL handler: any message that is NOT a command.
    client.add_event_handler(
        url_handler,
        events.NewMessage(pattern=r"^(?!/).*https?://.*$"),
    )

    async def _run() -> None:
        await client.start(bot_token=cfg.bot_token)
        if cfg.webui_enabled:
            from webui import start_webui
            await start_webui(cfg.webui_host, cfg.webui_port)
        logger.info("Bot is running…")
        await client.run_until_disconnected()

    logger.info("Starting bot…")
    try:
        asyncio.run(_run())
    finally:
        cfg.cleanup()


if __name__ == "__main__":
    main()

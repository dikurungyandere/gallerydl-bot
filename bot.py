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
from typing import Optional

from telethon import TelegramClient, events
from telethon.errors import FloodWaitError

from config import Config, load_config
from downloader import URL_RE, run_gallery_dl
from task_manager import UserTask, task_manager
from uploader import upload_files
from utils import cleanup_directory, safe_edit_message

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
    "Commands:\n"
    "• /start — Show this message\n"
    "• /help  — Show usage instructions\n"
    "• /cancel — Cancel your current download/upload\n\n"
    "_⚠️ This bot was created by AI. Use at your own risk._"
)

HELP_TEXT = (
    "📖 **How to use gallerydl-bot**\n\n"
    "1. Send a URL (e.g. an Instagram post, a Twitter/X post, a Reddit gallery…).\n"
    "2. The bot will download the media using `gallery-dl`.\n"
    "3. All downloaded files are uploaded back to you via Telegram.\n\n"
    "**Limits**\n"
    "• Albums are split into chunks of 10 (Telegram limit).\n"
    "• Maximum upload size is ~2 GB per file (MTProto).\n"
    "• Only URLs listed in `gallery-dl`'s supported sites work.\n\n"
    "**Commands**\n"
    "• /cancel — Stop an active download or upload at any time.\n\n"
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
# /cancel handler
# ---------------------------------------------------------------------------

@require_allowed
async def cancel_handler(event) -> None:
    """Handle the /cancel command."""
    user_id: int = event.sender_id

    if not task_manager.is_active(user_id):
        await event.respond("ℹ️ You have no active download or upload to cancel.")
        return

    ut = task_manager.get(user_id)
    status_msg = ut.status_message if ut else None

    cancelled = await task_manager.cancel(user_id)
    if cancelled:
        if status_msg is not None:
            try:
                await status_msg.edit("❌ Operation Cancelled by User")
            except Exception:
                pass
        else:
            await event.respond("❌ Operation Cancelled by User")
    else:
        await event.respond("ℹ️ Nothing to cancel.")


# ---------------------------------------------------------------------------
# URL / download handler
# ---------------------------------------------------------------------------

@require_allowed
async def url_handler(event) -> None:
    """Handle incoming messages that contain a URL."""
    user_id: int = event.sender_id
    text: str = event.raw_text or ""

    match = URL_RE.search(text)
    if not match:
        return
    url: str = match.group(0)

    if task_manager.is_active(user_id):
        await event.respond(
            "⚠️ You already have an active download. Use /cancel to stop it first."
        )
        return

    # Register the task slot.
    ut: UserTask = task_manager.get_or_create(user_id)
    ut.cancel_flag = False

    # Create a unique temp directory for this request.
    temp_dir = tempfile.mkdtemp(prefix=f"gdlbot_{user_id}_")
    ut.temp_dir = temp_dir

    # Send initial status message.
    status_message = await event.respond("⏳ Starting download…")
    ut.status_message = status_message

    # Wrap the pipeline in a task so we can cancel it.
    loop = asyncio.get_event_loop()
    task = loop.create_task(
        _pipeline(user_id, url, temp_dir, status_message, event)
    )
    ut.task = task


async def _pipeline(
    user_id: int,
    url: str,
    temp_dir: str,
    status_message,
    event,
) -> None:
    """Run the full download → upload pipeline for a single user request."""
    ut = task_manager.get(user_id)
    last_edit: list = [0.0]

    try:
        # ----------------------------------------------------------------
        # Phase 3: Download via gallery-dl
        # ----------------------------------------------------------------
        file_count_ref: list = [0]

        async def on_download_progress(n_files: int) -> None:
            file_count_ref[0] = n_files
            await safe_edit_message(
                status_message,
                f"📥 Downloading… {n_files} file(s) so far.",
                last_edit,
            )

        config_path = cfg.gallery_dl_config_path if cfg else None
        files = await run_gallery_dl(
            user_id=user_id,
            url=url,
            temp_dir=temp_dir,
            config_path=config_path,
            on_progress=on_download_progress,
        )

        if ut and ut.cancel_flag:
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
        # Phase 4: Upload to Telegram
        # ----------------------------------------------------------------
        await safe_edit_message(
            status_message,
            f"✅ Downloaded {len(files)} file(s). Starting upload…",
            last_edit,
            force=True,
        )

        await upload_files(
            client=client,
            event=event,
            ut=ut,
            files=files,
            status_message=status_message,
        )

    except asyncio.CancelledError:
        logger.info("Pipeline cancelled for user %s.", user_id)
        try:
            await status_message.edit("❌ Operation Cancelled by User")
        except Exception:
            pass

    except FloodWaitError as exc:
        wait = exc.seconds
        logger.warning("FloodWaitError for user %s. Waiting %s s.", user_id, wait)
        try:
            await status_message.edit(
                f"⚠️ Telegram rate limit hit. Please wait {wait} seconds and try again."
            )
        except Exception:
            pass
        await asyncio.sleep(wait)

    except RuntimeError as exc:
        logger.error("Pipeline error for user %s: %s", user_id, exc)
        try:
            await status_message.edit(f"❌ Error: {exc}")
        except Exception:
            pass

    except Exception as exc:
        logger.exception("Unexpected error for user %s: %s", user_id, exc)
        try:
            await status_message.edit(f"❌ Unexpected error: {exc}")
        except Exception:
            pass

    finally:
        # ----------------------------------------------------------------
        # Phase 5: Cleanup
        # ----------------------------------------------------------------
        cleanup_directory(temp_dir)
        task_manager.remove(user_id)
        logger.info("Cleanup complete for user %s.", user_id)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Start the bot."""
    global cfg, client

    cfg = load_config()
    logger.info(
        "Loaded config. allowed_users=%s gallery_dl_config=%s",
        cfg.allowed_users or "all",
        cfg.gallery_dl_config_path,
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
        cancel_handler, events.NewMessage(pattern=r"^/cancel(\s.*)?$")
    )
    # URL handler: any message that is NOT a command.
    client.add_event_handler(
        url_handler,
        events.NewMessage(pattern=r"^(?!/).*https?://.*$"),
    )

    logger.info("Starting bot…")
    try:
        client.start(bot_token=cfg.bot_token)
        client.run_until_disconnected()
    finally:
        cfg.cleanup()


if __name__ == "__main__":
    main()

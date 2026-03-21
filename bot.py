"""
gallerydl-bot: A Telegram bot that downloads media via gallery-dl and uploads
it back to the user using Pyrogram (MTProto).

When a URL is detected the bot presents an inline-keyboard configuration menu
so the user can choose the destination chat and the upload mode before the
download starts.  Two upload modes are supported:

* **Default** – download all files first, then upload them one-by-one.
* **Duplex**  – start uploading each file as soon as it is downloaded, without
  waiting for the entire gallery to finish.

Files larger than ~1950 MB are automatically split into numbered parts so they
can be uploaded within Telegram's per-file limit and manually reassembled.
Video files are sent as streamable Telegram videos rather than documents.

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
from dataclasses import dataclass
from typing import Dict, Optional, Tuple, Union

from pyrogram import Client, filters, idle
from pyrogram.errors import FloodWait
from pyrogram.handlers import CallbackQueryHandler, MessageHandler
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from config import Config, load_config
from downloader import URL_RE, run_gallery_dl
from task_manager import UserTask, task_manager
from uploader import upload_files
from utils import cleanup_directory, format_size, format_status_message, safe_edit_message
from webui import collect_stats, format_uptime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)
# Reduce noisy connection/session lifecycle logs from Pyrogram internals.
logging.getLogger("pyrogram.connection.connection").setLevel(logging.WARNING)
logging.getLogger("pyrogram.session.session").setLevel(logging.WARNING)

# ---------------------------------------------------------------------------
# Module-level config (populated in main()).
# ---------------------------------------------------------------------------
cfg: Optional[Config] = None
client: Optional[Client] = None

# ---------------------------------------------------------------------------
# Authentication decorator
# ---------------------------------------------------------------------------

def require_allowed(func):
    """Silently ignore messages from users not in ALLOWED_USERS."""
    async def wrapper(client, message):
        if cfg and cfg.allowed_users:
            sender_id = message.from_user.id
            if sender_id not in cfg.allowed_users:
                logger.debug("Ignoring message from unauthorized user %s.", sender_id)
                return
        return await func(client, message)
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
    "After you send a URL, a **configuration menu** will appear where you can:\n"
    "• Choose whether to upload to the **current chat** or a **custom channel/group**.\n"
    "• Select **Default** mode (download all → upload all) or **Duplex** mode "
    "(upload each file as soon as it is downloaded).\n"
    "• Press **Run** to start, or **Cancel** to abort.\n\n"
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
    "2. A **configuration menu** appears — choose your destination and upload mode.\n"
    "3. Press **▶ Run** — the bot downloads the media and uploads it one file at a time.\n\n"
    "**Parallel downloads**\n"
    "You can send multiple URLs without waiting — each one gets its own menu and job. "
    "The status message for each job shows its job ID.\n\n"
    "**Destination options**\n"
    "• **Current chat** — files are sent back to this chat (default).\n"
    "• **Custom chat** — click the button and reply with `@username` or `-100xxxxxxxxxx`.\n"
    "⚠️ The bot must be an admin in the target channel/group.\n\n"
    "**Upload modes**\n"
    "• **Default** — download everything first, then upload files one-by-one.\n"
    "• **Duplex** — upload each file as soon as it finishes downloading, without "
    "waiting for the full gallery.\n\n"
    "**Limits**\n"
    "• Files larger than ~1950 MB are automatically split into numbered parts\n"
    "  (``.001``, ``.002``, …). Reassemble with: "
    "`cat file.mp4.001 file.mp4.002 > file.mp4`\n"
    "• Only URLs listed in `gallery-dl`'s supported sites work.\n\n"
    "**Commands**\n"
    "• /stats — Show CPU, memory, disk and active job count.\n"
    "• /cancel — Stop **all** active downloads/uploads.\n"
    "• /cancel `<job_id>` — Stop a specific job.\n\n"
    "_⚠️ This bot was created by AI. Review the source before trusting it._"
)


@require_allowed
async def start_handler(client, message) -> None:
    """Handle the /start command."""
    await message.reply(START_TEXT)


@require_allowed
async def help_handler(client, message) -> None:
    """Handle the /help command."""
    await message.reply(HELP_TEXT)


# ---------------------------------------------------------------------------
# Pending-job state (configuration menu before the download starts)
# ---------------------------------------------------------------------------

@dataclass
class PendingJob:
    """Configuration for a download job that has not been started yet."""

    url: str
    user_id: int
    # The chat where the user sent the URL.
    source_chat_id: int
    # Where files will be uploaded (defaults to source_chat_id).
    target_chat_id: Union[int, str]
    # True  → upload to source_chat_id (the "current chat" button is selected).
    # False → upload to a user-supplied custom target.
    use_current_chat: bool = True
    # "default" → download all, then upload one-by-one.
    # "duplex"  → upload each file as soon as it is downloaded.
    mode: str = "default"
    # True while we are waiting for the user to reply with a custom chat ID.
    awaiting_custom_input: bool = False
    # Message ID of the configuration menu message (used to match replies).
    menu_message_id: int = 0


# pending_id (incrementing int) → PendingJob
_pending: Dict[int, PendingJob] = {}
_pending_counter: int = 0


def _next_pending_id() -> int:
    global _pending_counter
    _pending_counter += 1
    return _pending_counter


def _build_menu(pid: int, pj: PendingJob) -> Tuple[str, InlineKeyboardMarkup]:
    """Return *(text, markup)* for the download configuration menu."""
    if pj.use_current_chat:
        dest_label = "the **current chat**"
    else:
        dest_label = f"`{pj.target_chat_id}`"

    text = (
        f"🔗 **Link:** `{pj.url}`\n\n"
        f"The downloaded files will be uploaded to {dest_label}."
    )

    c_check = " ✓" if pj.use_current_chat else ""
    cu_check = " ✓" if not pj.use_current_chat else ""
    md_check = " ✓" if pj.mode == "default" else ""
    mx_check = " ✓" if pj.mode == "duplex" else ""

    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    f"Current chat{c_check}", callback_data=f"gdl:cc:{pid}"
                ),
                InlineKeyboardButton(
                    f"Custom chat{cu_check}", callback_data=f"gdl:cu:{pid}"
                ),
            ],
            [
                InlineKeyboardButton(
                    f"Default{md_check}", callback_data=f"gdl:md:{pid}"
                ),
                InlineKeyboardButton(
                    f"Duplex{mx_check}", callback_data=f"gdl:mx:{pid}"
                ),
            ],
            [
                InlineKeyboardButton("▶ Run", callback_data=f"gdl:r:{pid}"),
                InlineKeyboardButton("✖ Cancel", callback_data=f"gdl:x:{pid}"),
            ],
        ]
    )
    return text, markup


def _build_custom_input_prompt(
    pid: int, pj: PendingJob, error: str = ""
) -> Tuple[str, InlineKeyboardMarkup]:
    """Return *(text, markup)* for the custom-chat input prompt."""
    body = (
        f"🔗 **Link:** `{pj.url}`\n\n"
        "Please **reply to this message** with the username or chat ID "
        "to forward the files to.\n"
        "Examples: `@mychannel`, `-100123456789`"
    )
    if error:
        body += f"\n\n⚠️ {error} Please try again."

    markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton("✖ Cancel", callback_data=f"gdl:xcu:{pid}")]]
    )
    return body, markup


# ---------------------------------------------------------------------------
# /stats handler
# ---------------------------------------------------------------------------

@require_allowed
async def stats_handler(client, message) -> None:
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

    await message.reply("\n".join(lines))


# ---------------------------------------------------------------------------
# /cancel handler
# ---------------------------------------------------------------------------

@require_allowed
async def cancel_handler(client, message) -> None:
    """Handle the /cancel [job_id] command.

    With no argument: cancel all active jobs for this user.
    With a numeric job_id: cancel only that specific job.
    """
    user_id: int = message.from_user.id
    text: str = message.text or ""

    # Check for an optional numeric job_id argument.
    parts = text.strip().split(None, 1)
    job_id_arg: Optional[int] = None
    if len(parts) == 2:
        try:
            job_id_arg = int(parts[1])
        except ValueError:
            await message.reply(
                "⚠️ Invalid job ID. Use /cancel to stop all jobs, "
                "or /cancel <job_id> for a specific one."
            )
            return

    active_jobs = task_manager.get_user_tasks(user_id)

    if not active_jobs:
        await message.reply("ℹ️ You have no active downloads or uploads to cancel.")
        return

    if job_id_arg is not None:
        # Cancel a specific job.
        ut = task_manager.get(job_id_arg)
        if ut is None or ut.user_id != user_id:
            await message.reply(f"ℹ️ No active job #{job_id_arg} found.")
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
                await message.reply(f"❌ Job #{job_id_arg} cancelled by user.")
        else:
            await message.reply(f"ℹ️ Job #{job_id_arg} could not be cancelled.")
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
            await message.reply(f"❌ Cancelled {count} active job(s).")
        else:
            await message.reply("ℹ️ Nothing to cancel.")


# ---------------------------------------------------------------------------
# Text message handler (URL detection + custom chat input replies)
# ---------------------------------------------------------------------------

@require_allowed
async def text_message_handler(client, message) -> None:
    """Handle plain text messages.

    * If the message is a reply to a pending configuration menu that is
      waiting for a custom chat ID, process the input.
    * Otherwise, if the message contains a URL, show the configuration menu.
    """
    user_id: int = message.from_user.id
    chat_id: int = message.chat.id
    text: str = message.text or ""

    # --- Check for custom chat input (reply to a pending menu) ---
    if message.reply_to_message:
        reply_to_id: int = message.reply_to_message.id
        for pid, pj in list(_pending.items()):
            if (
                pj.awaiting_custom_input
                and pj.user_id == user_id
                and pj.source_chat_id == chat_id
                and pj.menu_message_id == reply_to_id
            ):
                await _handle_custom_input(client, message, pid, pj)
                return  # Do not also process as a URL.

    # --- Check for a URL ---
    match = URL_RE.search(text)
    if not match:
        return
    url: str = match.group(0)

    pid = _next_pending_id()
    pj = PendingJob(
        url=url,
        user_id=user_id,
        source_chat_id=chat_id,
        target_chat_id=chat_id,
        use_current_chat=True,
        mode="default",
    )

    menu_text, markup = _build_menu(pid, pj)
    sent = await message.reply(menu_text, reply_markup=markup)
    pj.menu_message_id = sent.id
    _pending[pid] = pj


async def _handle_custom_input(
    client, message, pid: int, pj: PendingJob
) -> None:
    """Validate and apply the custom-chat reply from the user."""
    input_text: str = (message.text or message.caption or "").strip()

    # Try to delete the user's reply to keep the chat clean.
    try:
        await message.delete()
    except Exception:
        pass

    # Validate: accept @username or a numeric chat ID.
    target: Union[int, str, None] = None
    if input_text.startswith("@") and len(input_text) > 1:
        target = input_text
    elif input_text.lstrip("-").isdigit():
        target = int(input_text)

    # Fetch the menu message so we can edit it.
    try:
        menu_msg = await client.get_messages(pj.source_chat_id, pj.menu_message_id)
    except Exception:
        menu_msg = None

    if target is None:
        # Invalid input — show the prompt again with an error.
        prompt_text, markup = _build_custom_input_prompt(
            pid, pj, error="Invalid format."
        )
        if menu_msg:
            try:
                await menu_msg.edit(prompt_text, reply_markup=markup)
            except Exception:
                pass
        return

    # Valid — update pending job and show the main menu again.
    pj.target_chat_id = target
    pj.use_current_chat = False
    pj.awaiting_custom_input = False

    if menu_msg:
        try:
            menu_text, markup = _build_menu(pid, pj)
            await menu_msg.edit(menu_text, reply_markup=markup)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Callback query handler (inline keyboard buttons)
# ---------------------------------------------------------------------------

@require_allowed
async def callback_query_handler(client, callback_query: CallbackQuery) -> None:
    """Handle all ``gdl:*`` callback queries from the configuration menu."""
    data: str = callback_query.data or ""

    # Parse:  gdl:<action>:<pending_id>
    parts = data.split(":", 2)
    if len(parts) != 3 or parts[0] != "gdl":
        await callback_query.answer("Unknown callback.")
        return

    action = parts[1]
    try:
        pid = int(parts[2])
    except ValueError:
        await callback_query.answer("Invalid job ID.")
        return

    pj = _pending.get(pid)
    if pj is None:
        await callback_query.answer("This menu is no longer active.", show_alert=True)
        # Remove the inline keyboard so the menu looks clearly expired.
        try:
            await callback_query.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        return

    # Only the original user may interact with their own menu.
    if callback_query.from_user.id != pj.user_id:
        await callback_query.answer(
            "This menu belongs to another user.", show_alert=True
        )
        return

    msg = callback_query.message

    if action == "cc":
        # Select "current chat" as the upload destination.
        pj.use_current_chat = True
        pj.target_chat_id = pj.source_chat_id
        pj.awaiting_custom_input = False
        menu_text, markup = _build_menu(pid, pj)
        await msg.edit(menu_text, reply_markup=markup)
        await callback_query.answer()

    elif action == "cu":
        # Ask the user to reply with a custom chat ID.
        pj.awaiting_custom_input = True
        prompt_text, markup = _build_custom_input_prompt(pid, pj)
        await msg.edit(prompt_text, reply_markup=markup)
        await callback_query.answer()

    elif action == "xcu":
        # Cancel custom-chat input; return to the main menu.
        pj.awaiting_custom_input = False
        menu_text, markup = _build_menu(pid, pj)
        await msg.edit(menu_text, reply_markup=markup)
        await callback_query.answer()

    elif action == "md":
        # Select default mode.
        pj.mode = "default"
        menu_text, markup = _build_menu(pid, pj)
        await msg.edit(menu_text, reply_markup=markup)
        await callback_query.answer()

    elif action == "mx":
        # Select duplex mode.
        pj.mode = "duplex"
        menu_text, markup = _build_menu(pid, pj)
        await msg.edit(menu_text, reply_markup=markup)
        await callback_query.answer()

    elif action == "r":
        # --- Run: start the download+upload pipeline ---
        _pending.pop(pid, None)

        job_id, ut = task_manager.create(pj.user_id)
        ut.cancel_flag = False

        temp_dir = tempfile.mkdtemp(prefix=f"gdlbot_{pj.user_id}_{job_id}_")
        ut.temp_dir = temp_dir

        # Repurpose the menu message as the status message.
        await msg.edit(
            format_status_message(pj.url, job_id, pj.mode, "⏳ Starting download…")
        )
        ut.status_message = msg

        task = asyncio.create_task(
            _pipeline(
                job_id, ut, pj.url, temp_dir, pj.target_chat_id, msg, mode=pj.mode
            )
        )
        ut.task = task
        await callback_query.answer("Starting download…")

    elif action == "x":
        # Cancel the pending configuration.
        _pending.pop(pid, None)
        await msg.edit("❌ Cancelled.")
        await callback_query.answer("Cancelled.")

    else:
        await callback_query.answer("Unknown action.")


async def _pipeline(
    job_id: int,
    ut: UserTask,
    url: str,
    temp_dir: str,
    target_chat_id: Union[int, str],
    status_message,
    mode: str = "default",
) -> None:
    """Run the full download → upload pipeline for a single job.

    Args:
        job_id:          Unique job identifier (shown in status messages).
        ut:              The :class:`~task_manager.UserTask` for this job.
        url:             Gallery URL to download.
        temp_dir:        Temporary directory for downloaded files.
        target_chat_id:  Telegram chat to upload files to.
        status_message:  The :class:`Message` used for status updates.
        mode:            ``"default"`` — download all files first, then upload
                         one-by-one.  ``"duplex"`` — upload each file as soon
                         as it is downloaded, concurrently with remaining
                         downloads.
    """
    last_edit: list = [0.0]
    config_path = cfg.gallery_dl_config_path if cfg else None

    # upload_task is only used in duplex mode; keep a reference so we can
    # cancel it in exception handlers.
    upload_task: Optional[asyncio.Task] = None

    try:
        if mode == "duplex":
            # ----------------------------------------------------------------
            # Duplex mode: producer-consumer with asyncio.Queue.
            # The downloader puts file paths in the queue; the uploader
            # drains it one file at a time.
            # ----------------------------------------------------------------
            file_queue: asyncio.Queue = asyncio.Queue()
            # Track files queued via stdout so we can upload any extra ones
            # discovered by the directory scan at the end.
            queued_files: set = set()
            n_downloaded = 0

            # Sentinel object used to signal the upload loop to exit.
            _DONE = object()

            async def on_file_duplex(path: str) -> None:
                nonlocal n_downloaded
                n_downloaded += 1
                queued_files.add(path)
                await file_queue.put(path)
                await safe_edit_message(
                    status_message,
                    format_status_message(
                        url,
                        job_id,
                        mode,
                        f"📥 Downloading… {n_downloaded} file(s) · uploading…",
                    ),
                    last_edit,
                )

            async def _upload_loop() -> None:
                while True:
                    item = await file_queue.get()
                    if item is _DONE:
                        file_queue.task_done()
                        break
                    if ut.cancel_flag:
                        file_queue.task_done()
                        break
                    try:
                        await upload_files(
                            client=client,
                            target_chat_id=target_chat_id,
                            ut=ut,
                            files=[item],
                            status_message=status_message,
                            show_completion=False,
                            url=url,
                            job_id=job_id,
                            mode=mode,
                        )
                    finally:
                        file_queue.task_done()

            upload_task = asyncio.create_task(_upload_loop())

            files = await run_gallery_dl(
                ut=ut,
                url=url,
                temp_dir=temp_dir,
                config_path=config_path,
                on_file=on_file_duplex,
            )

            # Signal the upload loop to stop after draining the queue.
            await file_queue.put(_DONE)
            await upload_task
            upload_task = None

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

            # Upload any extra files found by the directory scan but not
            # reported via gallery-dl's stdout (rare, extractor-specific).
            extra_files = [f for f in files if f not in queued_files]
            if extra_files and not ut.cancel_flag:
                await upload_files(
                    client=client,
                    target_chat_id=target_chat_id,
                    ut=ut,
                    files=extra_files,
                    status_message=status_message,
                    show_completion=False,
                    url=url,
                    job_id=job_id,
                    mode=mode,
                )

            if not ut.cancel_flag:
                total_size = sum(
                    os.path.getsize(f) for f in files if os.path.isfile(f)
                )
                summary = (
                    f"✅ **Upload completed**\n\n"
                    f"🔗 **Link:** `{url}`\n"
                    f"**File count:** {len(files)}\n"
                    f"**Total size:** {format_size(total_size)}"
                )
                await client.send_message(status_message.chat.id, summary)

        else:
            # ----------------------------------------------------------------
            # Default mode: download all → upload all.
            # ----------------------------------------------------------------
            n_downloaded = 0

            async def on_file(path: str) -> None:
                nonlocal n_downloaded
                n_downloaded += 1
                if ut.cancel_flag:
                    return
                await safe_edit_message(
                    status_message,
                    format_status_message(
                        url,
                        job_id,
                        mode,
                        f"📥 Downloading… {n_downloaded} file(s) so far",
                    ),
                    last_edit,
                )

            files = await run_gallery_dl(
                ut=ut,
                url=url,
                temp_dir=temp_dir,
                config_path=config_path,
                on_file=on_file,
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

            await safe_edit_message(
                status_message,
                format_status_message(
                    url,
                    job_id,
                    mode,
                    f"✅ Downloaded {len(files)} file(s). Uploading…",
                ),
                last_edit,
                force=True,
            )
            await upload_files(
                client=client,
                target_chat_id=target_chat_id,
                ut=ut,
                files=files,
                status_message=status_message,
                show_completion=True,
                url=url,
                job_id=job_id,
                mode=mode,
            )

    except asyncio.CancelledError:
        logger.info("Pipeline cancelled for job #%s.", job_id)
        # Ensure the duplex upload loop is also stopped.
        if upload_task is not None and not upload_task.done():
            upload_task.cancel()
            try:
                await upload_task
            except (asyncio.CancelledError, Exception):
                pass
        try:
            await status_message.edit(f"❌ Job #{job_id} cancelled by user.")
        except Exception:
            pass

    except FloodWait as exc:
        wait = exc.value
        logger.warning("FloodWait for job #%s. Waiting %s s.", job_id, wait)
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
        # Cleanup (always runs)
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

    async def _run() -> None:
        global client
        client = Client(
            "bot_session",
            api_id=cfg.api_id,
            api_hash=cfg.api_hash,
            bot_token=cfg.bot_token,
        )

        # Register handlers (must be done after Client is created).
        client.add_handler(MessageHandler(start_handler, filters.command("start")))
        client.add_handler(MessageHandler(help_handler, filters.command("help")))
        client.add_handler(MessageHandler(stats_handler, filters.command("stats")))
        client.add_handler(MessageHandler(cancel_handler, filters.command("cancel")))
        # Text message handler: processes both custom-chat-input replies (which
        # may contain no URL) AND new URL messages.  The regex URL filter is
        # intentionally omitted here so that non-URL replies (e.g. "@mychannel")
        # to the configuration menu are also caught.
        client.add_handler(
            MessageHandler(
                text_message_handler,
                filters.text
                & ~filters.command(["start", "help", "stats", "cancel"]),
            )
        )
        # Inline keyboard button handler.
        client.add_handler(
            CallbackQueryHandler(
                callback_query_handler, filters.regex(r"^gdl:")
            )
        )

        await client.start()
        if cfg.webui_enabled:
            from webui import start_webui
            await start_webui(cfg.webui_host, cfg.webui_port)
        logger.info("Bot is running…")
        await idle()
        await client.stop()

    logger.info("Starting bot…")
    try:
        asyncio.run(_run())
    finally:
        cfg.cleanup()


if __name__ == "__main__":
    main()

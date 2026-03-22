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
    "• Set a **custom gallery-dl config** (file or text) for this job only.\n"
    "• Add **custom gallery-dl arguments** (e.g. credentials, filters) for this job only.\n"
    "• Press **Run** to start, or **Cancel** to abort.\n\n"
    "Commands:\n"
    "• /start — Show this message\n"
    "• /help  — Show usage instructions\n"
    "• /stats — Show server and bot statistics\n"
    "• /status — Show your currently running jobs\n"
    "• /cancelall — Cancel **all** your active downloads/uploads\n"
    "• /cancel `<job_id>` — Cancel a specific job (ID shown in the status message)\n\n"
    "_⚠️ This bot was created by AI. Use at your own risk._"
)

HELP_TEXT = (
    "📖 **How to use gallerydl-bot**\n\n"
    "1. Send a URL (e.g. an Instagram post, a Twitter/X post, a Reddit gallery…).\n"
    "2. A **configuration menu** appears — choose your destination, upload mode, "
    "and any custom config or arguments.\n"
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
    "**Custom config (⚙️)**\n"
    "Click **⚙️ Custom Config** and reply with a gallery-dl config file (send as a "
    "document) or paste the config text. The custom config overrides the bot's global "
    "config for this job only. Shows **Applied** in the menu when active. "
    "Use **🔄 Reset** to clear it.\n\n"
    "**Custom args (🔧)**\n"
    "Click **🔧 Custom Args** and reply with extra gallery-dl CLI arguments, e.g.:\n"
    "`--username myuser --password mypass`\n"
    "`--filter \"width > 1000\"`\n"
    "The arguments apply to this job only. Shows the argument string in the menu "
    "when active. Use **🔄 Reset** to clear them.\n\n"
    "**Limits**\n"
    "• Files larger than ~1950 MB are automatically split into numbered parts\n"
    "  (``.001``, ``.002``, …). Reassemble with: "
    "`cat file.mp4.001 file.mp4.002 > file.mp4`\n"
    "• Only URLs listed in `gallery-dl`'s supported sites work.\n\n"
    "**Commands**\n"
    "• /stats — Show CPU, memory, disk and active job count.\n"
    "• /status — Show your currently running jobs with live progress.\n"
    "• /cancelall — Stop **all** active downloads/uploads.\n"
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
    # Path to a user-provided gallery-dl config file (temp file); None = use bot default.
    custom_config_path: Optional[str] = None
    # Extra gallery-dl arguments supplied by the user (raw string); None = none.
    custom_args: Optional[str] = None
    # True while waiting for the user to reply with a custom config.
    awaiting_custom_config: bool = False
    # True while waiting for the user to reply with custom arguments.
    awaiting_custom_args: bool = False


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

    config_status = "Applied" if pj.custom_config_path else "None"
    args_status = f"`{pj.custom_args}`" if pj.custom_args else "None"

    text = (
        f"🔗 **Link:** `{pj.url}`\n\n"
        f"The downloaded files will be uploaded to {dest_label}.\n"
        f"**Custom config:** {config_status}\n"
        f"**Custom args:** {args_status}"
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
                InlineKeyboardButton(
                    "⚙️ Custom Config", callback_data=f"gdl:cfg:{pid}"
                ),
                InlineKeyboardButton(
                    "🔧 Custom Args", callback_data=f"gdl:arg:{pid}"
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


def _build_custom_config_prompt(
    pid: int, pj: PendingJob, error: str = ""
) -> Tuple[str, InlineKeyboardMarkup]:
    """Return *(text, markup)* for the custom-config input prompt."""
    current = "Applied" if pj.custom_config_path else "None (using bot default)"
    body = (
        f"🔗 **Link:** `{pj.url}`\n\n"
        f"**Current custom config:** {current}\n\n"
        "Please **reply to this message** with your gallery-dl config.\n"
        "You can send a config file (as a document) or paste the config text directly."
    )
    if error:
        body += f"\n\n⚠️ {error}"

    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🔄 Reset", callback_data=f"gdl:cfgrst:{pid}"),
                InlineKeyboardButton("✖ Cancel", callback_data=f"gdl:xcfg:{pid}"),
            ]
        ]
    )
    return body, markup


def _build_custom_args_prompt(
    pid: int, pj: PendingJob, error: str = ""
) -> Tuple[str, InlineKeyboardMarkup]:
    """Return *(text, markup)* for the custom-arguments input prompt."""
    current = f"`{pj.custom_args}`" if pj.custom_args else "None"
    body = (
        f"🔗 **Link:** `{pj.url}`\n\n"
        f"**Current custom args:** {current}\n\n"
        "Please **reply to this message** with the extra gallery-dl arguments.\n"
        "Examples: `--username foo --password bar`, `--filter \"width > 1000\"`"
    )
    if error:
        body += f"\n\n⚠️ {error}"

    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🔄 Reset", callback_data=f"gdl:argrst:{pid}"),
                InlineKeyboardButton("✖ Cancel", callback_data=f"gdl:xarg:{pid}"),
            ]
        ]
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
# /status handler
# ---------------------------------------------------------------------------

def _build_status_text(user_id: int) -> str:
    """Build the status overview for all active jobs of *user_id*."""
    active = task_manager.get_user_tasks(user_id)
    if not active:
        return "ℹ️ You have no active jobs."
    parts = [
        format_status_message(ut.url, jid, ut.mode, ut.progress_text)
        for jid, ut in active
    ]
    return "\n\n—\n\n".join(parts)


@require_allowed
async def status_handler(client, message) -> None:
    """Handle the /status command — show running jobs with a Refresh button."""
    user_id: int = message.from_user.id
    active = task_manager.get_user_tasks(user_id)
    text = _build_status_text(user_id)
    if not active:
        await message.reply(text)
        return
    markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔄 Refresh", callback_data="gdl:ref:0")]]
    )
    await message.reply(text, reply_markup=markup)


# ---------------------------------------------------------------------------
# /cancel and /cancelall handlers
# ---------------------------------------------------------------------------

@require_allowed
async def cancel_handler(client, message) -> None:
    """Handle the /cancel <job_id> command.

    Requires a numeric job_id argument to cancel a specific job.
    Use /cancelall to stop all active jobs at once.
    """
    user_id: int = message.from_user.id
    text: str = message.text or ""

    # Require a numeric job_id argument.
    parts = text.strip().split(None, 1)
    if len(parts) < 2:
        await message.reply(
            "⚠️ Please provide a job ID. Use `/cancel <job_id>` to stop a specific job, "
            "or `/cancelall` to stop all active jobs."
        )
        return

    try:
        job_id_arg = int(parts[1])
    except ValueError:
        await message.reply(
            "⚠️ Invalid job ID. Use `/cancel <job_id>` for a specific job, "
            "or `/cancelall` to stop all active jobs."
        )
        return

    # Cancel a specific job.
    ut = task_manager.get(job_id_arg)
    if ut is None or ut.user_id != user_id:
        await message.reply(f"ℹ️ No active job #{job_id_arg} found.")
        return

    cancelled = await task_manager.cancel(job_id_arg)
    if cancelled:
        await message.reply(f"⏳ Cancellation requested for job #{job_id_arg}.")
    else:
        await message.reply(f"ℹ️ Job #{job_id_arg} could not be cancelled.")


@require_allowed
async def cancel_all_handler(client, message) -> None:
    """Handle the /cancelall command.

    Cancels all active jobs for this user.
    """
    user_id: int = message.from_user.id

    active_jobs = task_manager.get_user_tasks(user_id)

    if not active_jobs:
        await message.reply("ℹ️ You have no active downloads or uploads to cancel.")
        return

    count = await task_manager.cancel_all(user_id)
    if count:
        await message.reply(f"⏳ Cancellation requested for {count} active job(s).")
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
                pj.user_id != user_id
                or pj.source_chat_id != chat_id
                or pj.menu_message_id != reply_to_id
            ):
                continue
            if pj.awaiting_custom_input:
                await _handle_custom_input(client, message, pid, pj)
                return  # Do not also process as a URL.
            if pj.awaiting_custom_config:
                await _handle_custom_config_input(client, message, pid, pj)
                return
            if pj.awaiting_custom_args:
                await _handle_custom_args_input(client, message, pid, pj)
                return

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

    # Verify the bot has access to the requested chat before accepting it.
    try:
        await client.get_chat(target)
    except Exception:
        prompt_text, markup = _build_custom_input_prompt(
            pid,
            pj,
            error=(
                f"Unable to access `{target}`. "
                "The chat may not exist, or the bot may not be a member/admin."
            ),
        )
        if menu_msg:
            try:
                await menu_msg.edit(prompt_text, reply_markup=markup)
            except Exception:
                pass
        return

    # Valid and accessible — update pending job and show the main menu again.
    pj.target_chat_id = target
    pj.use_current_chat = False
    pj.awaiting_custom_input = False

    if menu_msg:
        try:
            menu_text, markup = _build_menu(pid, pj)
            await menu_msg.edit(menu_text, reply_markup=markup)
        except Exception:
            pass


async def _handle_custom_config_input(
    client, message, pid: int, pj: PendingJob
) -> None:
    """Apply the custom-config reply (text or document) from the user."""
    # Try to delete the user's reply to keep the chat clean.
    try:
        await message.delete()
    except Exception:
        pass

    # Fetch the menu message so we can edit it.
    try:
        menu_msg = await client.get_messages(pj.source_chat_id, pj.menu_message_id)
    except Exception:
        menu_msg = None

    new_config_path: Optional[str] = None

    if message.document:
        # Download the document to a temporary file.
        try:
            tmp = tempfile.NamedTemporaryFile(
                mode="wb", suffix=".conf", delete=False, prefix="gdlbot_cfg_"
            )
            tmp.close()
            await message.download(file_name=tmp.name)
            new_config_path = tmp.name
        except Exception as exc:
            prompt_text, markup = _build_custom_config_prompt(
                pid, pj, error=f"Failed to download the config file: {exc}"
            )
            if menu_msg:
                try:
                    await menu_msg.edit(prompt_text, reply_markup=markup)
                except Exception:
                    pass
            return
    else:
        config_text = (message.text or message.caption or "").strip()
        if not config_text:
            prompt_text, markup = _build_custom_config_prompt(
                pid, pj, error="Empty config received. Please send a file or paste config text."
            )
            if menu_msg:
                try:
                    await menu_msg.edit(prompt_text, reply_markup=markup)
                except Exception:
                    pass
            return
        # Write the text to a temp file.
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".conf", delete=False,
                prefix="gdlbot_cfg_", encoding="utf-8"
            ) as tmp:
                tmp.write(config_text)
            new_config_path = tmp.name
        except Exception as exc:
            prompt_text, markup = _build_custom_config_prompt(
                pid, pj, error=f"Failed to save config: {exc}"
            )
            if menu_msg:
                try:
                    await menu_msg.edit(prompt_text, reply_markup=markup)
                except Exception:
                    pass
            return

    # Clean up any previously set temp config.
    if pj.custom_config_path and os.path.isfile(pj.custom_config_path):
        try:
            os.unlink(pj.custom_config_path)
        except Exception:
            pass

    pj.custom_config_path = new_config_path
    pj.awaiting_custom_config = False

    if menu_msg:
        try:
            menu_text, markup = _build_menu(pid, pj)
            await menu_msg.edit(menu_text, reply_markup=markup)
        except Exception:
            pass


async def _handle_custom_args_input(
    client, message, pid: int, pj: PendingJob
) -> None:
    """Apply the custom-args reply from the user."""
    input_text = (message.text or message.caption or "").strip()

    # Try to delete the user's reply to keep the chat clean.
    try:
        await message.delete()
    except Exception:
        pass

    # Fetch the menu message so we can edit it.
    try:
        menu_msg = await client.get_messages(pj.source_chat_id, pj.menu_message_id)
    except Exception:
        menu_msg = None

    if not input_text:
        prompt_text, markup = _build_custom_args_prompt(
            pid, pj, error="Empty arguments received. Please reply with the gallery-dl arguments."
        )
        if menu_msg:
            try:
                await menu_msg.edit(prompt_text, reply_markup=markup)
            except Exception:
                pass
        return

    pj.custom_args = input_text
    pj.awaiting_custom_args = False

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

    # ---- Status refresh (no pending job needed) ----
    if action == "ref":
        user_id = callback_query.from_user.id
        if cfg and cfg.allowed_users and user_id not in cfg.allowed_users:
            await callback_query.answer("Unauthorized.", show_alert=True)
            return
        msg = callback_query.message
        active = task_manager.get_user_tasks(user_id)
        if not active:
            try:
                await msg.edit("ℹ️ You have no active jobs.", reply_markup=None)
            except Exception:
                pass
            await callback_query.answer("No active jobs.")
        else:
            text = _build_status_text(user_id)
            markup = InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔄 Refresh", callback_data="gdl:ref:0")]]
            )
            try:
                await msg.edit(text, reply_markup=markup)
            except Exception:
                pass
            await callback_query.answer("Refreshed.")
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

    elif action == "cfg":
        # Open the custom config prompt.
        pj.awaiting_custom_config = True
        prompt_text, markup = _build_custom_config_prompt(pid, pj)
        await msg.edit(prompt_text, reply_markup=markup)
        await callback_query.answer()

    elif action == "xcfg":
        # Cancel custom-config input; return to the main menu.
        pj.awaiting_custom_config = False
        menu_text, markup = _build_menu(pid, pj)
        await msg.edit(menu_text, reply_markup=markup)
        await callback_query.answer()

    elif action == "cfgrst":
        # Reset custom config to None; return to the main menu.
        if pj.custom_config_path and os.path.isfile(pj.custom_config_path):
            try:
                os.unlink(pj.custom_config_path)
            except Exception:
                pass
        pj.custom_config_path = None
        pj.awaiting_custom_config = False
        menu_text, markup = _build_menu(pid, pj)
        await msg.edit(menu_text, reply_markup=markup)
        await callback_query.answer("Custom config reset.")

    elif action == "arg":
        # Open the custom args prompt.
        pj.awaiting_custom_args = True
        prompt_text, markup = _build_custom_args_prompt(pid, pj)
        await msg.edit(prompt_text, reply_markup=markup)
        await callback_query.answer()

    elif action == "xarg":
        # Cancel custom-args input; return to the main menu.
        pj.awaiting_custom_args = False
        menu_text, markup = _build_menu(pid, pj)
        await msg.edit(menu_text, reply_markup=markup)
        await callback_query.answer()

    elif action == "argrst":
        # Reset custom args to None; return to the main menu.
        pj.custom_args = None
        pj.awaiting_custom_args = False
        menu_text, markup = _build_menu(pid, pj)
        await msg.edit(menu_text, reply_markup=markup)
        await callback_query.answer("Custom args reset.")

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
                job_id, ut, pj.url, temp_dir, pj.target_chat_id, msg,
                mode=pj.mode,
                custom_config_path=pj.custom_config_path,
                custom_args=pj.custom_args,
            )
        )
        ut.task = task
        await callback_query.answer("Starting download…")

    elif action == "x":
        # Cancel the pending configuration; clean up any temp config file.
        if pj.custom_config_path and os.path.isfile(pj.custom_config_path):
            try:
                os.unlink(pj.custom_config_path)
            except Exception:
                pass
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
    custom_config_path: Optional[str] = None,
    custom_args: Optional[str] = None,
) -> None:
    """Run the full download → upload pipeline for a single job.

    Args:
        job_id:             Unique job identifier (shown in status messages).
        ut:                 The :class:`~task_manager.UserTask` for this job.
        url:                Gallery URL to download.
        temp_dir:           Temporary directory for downloaded files.
        target_chat_id:     Telegram chat to upload files to.
        status_message:     The :class:`Message` used for status updates.
        mode:               ``"default"`` — download all files first, then
                            upload one-by-one.  ``"duplex"`` — upload each
                            file as soon as it is downloaded, concurrently
                            with remaining downloads.
        custom_config_path: Optional path to a user-supplied gallery-dl config
                            file.  Takes precedence over the bot's global
                            config.  The file is deleted when the pipeline
                            finishes.
        custom_args:        Optional string of extra gallery-dl arguments
                            (e.g. ``"--username foo --password bar"``).
    """
    last_edit: list = [0.0]
    # User-supplied config takes precedence over the bot's global config.
    config_path = custom_config_path or (cfg.gallery_dl_config_path if cfg else None)

    # Populate UserTask fields so /status can show live information.
    ut.url = url
    ut.mode = mode
    ut.progress_text = "⏳ Starting download…"

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
                progress = f"📥 Downloading… {n_downloaded} file(s) · uploading…"
                ut.progress_text = progress
                await safe_edit_message(
                    status_message,
                    format_status_message(url, job_id, mode, progress),
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
                extra_args=custom_args,
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
                try:
                    await status_message.delete()
                except Exception:
                    pass

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
                progress = f"📥 Downloading… {n_downloaded} file(s) so far"
                ut.progress_text = progress
                await safe_edit_message(
                    status_message,
                    format_status_message(url, job_id, mode, progress),
                    last_edit,
                )

            files = await run_gallery_dl(
                ut=ut,
                url=url,
                temp_dir=temp_dir,
                config_path=config_path,
                on_file=on_file,
                extra_args=custom_args,
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
            await client.send_message(
                status_message.chat.id,
                f"❌ Job #{job_id} cancelled by user.",
            )
            await status_message.delete()
        except Exception:
            pass

    except FloodWait as exc:
        wait = exc.value
        logger.warning("FloodWait for job #%s. Waiting %s s.", job_id, wait)
        try:
            await client.send_message(
                status_message.chat.id,
                f"⚠️ Telegram rate limit hit for job #{job_id}. "
                f"Please wait {wait} seconds and try again.",
            )
            await status_message.delete()
        except Exception:
            pass
        await asyncio.sleep(wait)

    except RuntimeError as exc:
        logger.error("Pipeline error for job #%s: %s", job_id, exc)
        try:
            await client.send_message(
                status_message.chat.id,
                f"❌ Error in job #{job_id}: {exc}",
            )
            await status_message.delete()
        except Exception:
            pass

    except Exception as exc:
        logger.exception("Unexpected error for job #%s: %s", job_id, exc)
        try:
            await client.send_message(
                status_message.chat.id,
                f"❌ Unexpected error in job #{job_id}: {exc}",
            )
            await status_message.delete()
        except Exception:
            pass

    finally:
        # ----------------------------------------------------------------
        # Cleanup (always runs)
        # ----------------------------------------------------------------
        cleanup_directory(temp_dir)
        task_manager.remove(job_id)
        # Remove the user-provided config temp file if one was used.
        if custom_config_path and os.path.isfile(custom_config_path):
            try:
                os.unlink(custom_config_path)
            except Exception:
                pass
        logger.info("Cleanup complete for job #%s.", job_id)


# ---------------------------------------------------------------------------
# Document message handler (custom config file upload)
# ---------------------------------------------------------------------------

@require_allowed
async def document_message_handler(client, message) -> None:
    """Handle document messages sent as replies to a pending config prompt."""
    user_id: int = message.from_user.id
    chat_id: int = message.chat.id

    if not message.reply_to_message:
        return

    reply_to_id: int = message.reply_to_message.id
    for pid, pj in list(_pending.items()):
        if (
            pj.awaiting_custom_config
            and pj.user_id == user_id
            and pj.source_chat_id == chat_id
            and pj.menu_message_id == reply_to_id
        ):
            await _handle_custom_config_input(client, message, pid, pj)
            return


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
        client.add_handler(MessageHandler(status_handler, filters.command("status")))
        client.add_handler(MessageHandler(cancel_handler, filters.command("cancel")))
        client.add_handler(MessageHandler(cancel_all_handler, filters.command("cancelall")))
        # Text message handler: processes both custom-chat-input replies (which
        # may contain no URL) AND new URL messages.  The regex URL filter is
        # intentionally omitted here so that non-URL replies (e.g. "@mychannel")
        # to the configuration menu are also caught.
        client.add_handler(
            MessageHandler(
                text_message_handler,
                filters.text
                & ~filters.command(["start", "help", "stats", "status", "cancel", "cancelall"]),
            )
        )
        # Document handler: catches config files sent as replies to the config prompt.
        client.add_handler(
            MessageHandler(document_message_handler, filters.document)
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

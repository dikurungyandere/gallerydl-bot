"""
Utility helpers: progress-bar formatting, cleanup, and throttled message editing.

AI-GENERATED CODE DISCLAIMER: This entire codebase has been created by AI.
Review it carefully before deploying to production.
"""

import asyncio
import logging
import shutil
import time
from typing import Optional

logger = logging.getLogger(__name__)

# Minimum seconds between message edits to avoid FloodWaitError.
EDIT_THROTTLE_SECONDS = 3


def format_progress_bar(current: int, total: int, width: int = 10) -> str:
    """Return a text progress bar string.

    Example output: ``[██████░░░░] 60%``

    Args:
        current: Bytes (or units) completed so far.
        total:   Total bytes (or units).
        width:   Number of block characters in the bar.
    """
    if total <= 0:
        return "[░░░░░░░░░░] 0%"
    pct = min(current / total, 1.0)
    filled = int(pct * width)
    bar = "█" * filled + "░" * (width - filled)
    return f"[{bar}] {int(pct * 100)}%"


def format_size(num_bytes: int) -> str:
    """Human-readable byte size string (e.g. ``3.14 MB``)."""
    for unit in ("B", "KB", "MB", "GB"):
        if abs(num_bytes) < 1024.0:
            return f"{num_bytes:.2f} {unit}"
        num_bytes /= 1024.0  # type: ignore[assignment]
    return f"{num_bytes:.2f} TB"


def format_speed(bytes_per_sec: float) -> str:
    """Human-readable transfer speed string (e.g. ``1.23 MB/s``).

    Args:
        bytes_per_sec: Transfer rate in bytes per second.  Values ≤ 0 are
                       treated as unknown and return ``"? B/s"``.
    """
    if bytes_per_sec <= 0:
        return "? B/s"
    for unit in ("B/s", "KB/s", "MB/s", "GB/s"):
        if bytes_per_sec < 1024.0:
            return f"{bytes_per_sec:.2f} {unit}"
        bytes_per_sec /= 1024.0
    return f"{bytes_per_sec:.2f} TB/s"


async def safe_edit_message(
    message: object,
    text: str,
    last_edit_time: list,
    force: bool = False,
) -> None:
    """Edit a Telegram message, throttled to avoid FloodWait.

    Args:
        message:        A Pyrogram ``Message`` object with an ``.edit()`` method.
        text:           New message text.
        last_edit_time: A single-element list holding the Unix timestamp of the last
                        edit. Pass ``[0.0]`` initially; this list is mutated in place.
        force:          If ``True``, skip the throttle check (e.g. for final status).
    """
    now = time.monotonic()
    if not force and (now - last_edit_time[0]) < EDIT_THROTTLE_SECONDS:
        return
    try:
        await message.edit(text)  # type: ignore[attr-defined]
        last_edit_time[0] = time.monotonic()
    except Exception as exc:
        # Check for FloodWait (Pyrogram) by class name to keep this module
        # library-agnostic. Pyrogram exposes the wait time via `.value`.
        exc_name = type(exc).__name__
        if "FloodWait" in exc_name:
            seconds: int = getattr(exc, "value", getattr(exc, "seconds", 5))
            logger.warning("FloodWait: sleeping %s seconds.", seconds)
            await asyncio.sleep(seconds)
        else:
            logger.warning("Failed to edit message: %s", exc)


def format_status_message(
    url: str, job_id: int, mode: str, progress_content: str
) -> str:
    """Build the standard status message shown during download/upload.

    Args:
        url:              The source URL being processed.
        job_id:           Unique job identifier.
        mode:             ``"default"`` or ``"duplex"``.
        progress_content: The current progress text to embed.

    Returns:
        A formatted Telegram-markdown string with link, job ID, mode, progress,
        and a cancel hint.
    """
    mode_label = "Duplex" if mode == "duplex" else "Default"
    return (
        f"🔗 **Link:** `{url}`\n"
        f"**Job ID:** `{job_id}`\n"
        f"**Mode:** {mode_label}\n\n"
        f"**Progress:**\n{progress_content}\n\n"
        f"Cancel: `/cancel {job_id}`"
    )


def cleanup_directory(path: Optional[str]) -> None:
    """Remove *path* and all its contents, ignoring errors.

    Safe to call even if *path* is ``None`` or has already been removed.
    """
    if path:
        shutil.rmtree(path, ignore_errors=True)
        logger.debug("Cleaned up temp directory: %s", path)

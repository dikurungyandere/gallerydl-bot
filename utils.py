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


async def safe_edit_message(
    message: object,
    text: str,
    last_edit_time: list,
    force: bool = False,
) -> None:
    """Edit a Telegram message, throttled to avoid FloodWaitError.

    Args:
        message:        A Telethon ``Message`` object with an ``.edit()`` method.
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
        # Check for FloodWait from Telethon.
        exc_name = type(exc).__name__
        if "FloodWait" in exc_name:
            seconds: int = getattr(exc, "seconds", 5)
            logger.warning("FloodWaitError: sleeping %s seconds.", seconds)
            await asyncio.sleep(seconds)
        else:
            logger.warning("Failed to edit message: %s", exc)


def cleanup_directory(path: Optional[str]) -> None:
    """Remove *path* and all its contents, ignoring errors.

    Safe to call even if *path* is ``None`` or has already been removed.
    """
    if path:
        shutil.rmtree(path, ignore_errors=True)
        logger.debug("Cleaned up temp directory: %s", path)

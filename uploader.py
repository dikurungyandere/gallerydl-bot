"""
Telegram upload logic: single files, album batches, and progress callbacks.

AI-GENERATED CODE DISCLAIMER: This entire codebase has been created by AI.
Review it carefully before deploying to production.
"""

import asyncio
import logging
import time
from typing import List, Optional

from task_manager import UserTask
from utils import format_progress_bar, format_size, safe_edit_message, EDIT_THROTTLE_SECONDS

logger = logging.getLogger(__name__)

# Telegram album limit (hard limit imposed by Telegram).
ALBUM_CHUNK_SIZE = 10


class CancelUploadException(Exception):
    """Raised inside a Telethon progress callback to abort an upload."""


def chunk_files(files: List[str], size: int = ALBUM_CHUNK_SIZE) -> List[List[str]]:
    """Split *files* into sub-lists of at most *size* elements.

    Args:
        files: Sorted list of file paths to upload.
        size:  Maximum number of files per chunk (default: 10).

    Returns:
        A list of lists, each with at most *size* file paths.
    """
    return [files[i : i + size] for i in range(0, len(files), size)]


async def upload_files(
    client: object,
    target_chat_id: object,
    ut: UserTask,
    files: List[str],
    status_message: object,
) -> None:
    """Upload all *files* to *target_chat_id*, respecting Telegram's album limit.

    Args:
        client:         Telethon ``TelegramClient`` instance.
        target_chat_id: The Telegram chat/channel/group to send files to.
                        Can be an integer ID, a ``@username`` string, or any
                        entity accepted by Telethon's ``send_file``.
        ut:             The :class:`~task_manager.UserTask` for this job.
        files:          List of local file paths to upload.
        status_message: The status :class:`Message` to update with progress.

    Raises:
        CancelUploadException: If the user requested cancellation mid-upload.
        asyncio.CancelledError: If the asyncio task is cancelled.
    """
    chunks = chunk_files(files)
    total_chunks = len(chunks)

    for chunk_idx, chunk in enumerate(chunks, start=1):
        if ut.cancel_flag:
            raise asyncio.CancelledError("Upload cancelled by user.")

        chunk_label = f"Batch {chunk_idx}/{total_chunks}" if total_chunks > 1 else ""

        # Build a progress callback bound to this chunk.
        last_edit: list = [0.0]

        single_file = len(chunk) == 1

        async def _progress_callback(current: int, total: int) -> None:
            """Telethon-compatible upload progress callback."""
            if ut.cancel_flag:
                raise CancelUploadException("Upload cancelled mid-transfer.")

            bar = format_progress_bar(current, total)
            size_info = f"{format_size(current)} / {format_size(total)}"
            prefix = f"📤 Uploading {chunk_label}\n" if chunk_label else "📤 Uploading\n"
            text = f"{prefix}{bar}\n{size_info}"

            await safe_edit_message(status_message, text, last_edit)

        try:
            if single_file:
                await client.send_file(  # type: ignore[attr-defined]
                    target_chat_id,
                    chunk[0],
                    progress_callback=_progress_callback,
                )
            else:
                # For albums: Telethon accepts a list; progress is per-file.
                await client.send_file(  # type: ignore[attr-defined]
                    target_chat_id,
                    chunk,
                    progress_callback=_progress_callback,
                )
        except CancelUploadException:
            raise asyncio.CancelledError("Upload cancelled by user.")

    # Final status update.
    await safe_edit_message(
        status_message,
        "✅ Upload Complete!",
        [0.0],
        force=True,
    )

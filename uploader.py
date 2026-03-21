"""
Telegram upload logic: single files, album batches, and progress callbacks.

AI-GENERATED CODE DISCLAIMER: This entire codebase has been created by AI.
Review it carefully before deploying to production.
"""

import asyncio
import logging
import mimetypes
import os
import time
from typing import List, Optional

from task_manager import UserTask
from utils import format_progress_bar, format_size, safe_edit_message, EDIT_THROTTLE_SECONDS

logger = logging.getLogger(__name__)

# Telegram album limit (hard limit imposed by Telegram).
ALBUM_CHUNK_SIZE = 10

# Safe upload size limit: stay below Telegram's 2 GB MTProto ceiling.
TELEGRAM_MAX_FILE_SIZE = 1950 * 1024 * 1024  # 1950 MB in bytes


class CancelUploadException(Exception):
    """Raised inside a Telethon progress callback to abort an upload."""


def split_large_file(path: str, max_size: int = TELEGRAM_MAX_FILE_SIZE) -> List[str]:
    """Split *path* into numbered parts if it exceeds *max_size* bytes.

    Parts are written alongside the original file with suffixes ``.001``,
    ``.002``, … so that users can reassemble them with::

        cat file.mp4.001 file.mp4.002 > file.mp4

    Args:
        path:     Absolute path to the source file.
        max_size: Maximum bytes per part (default: ``TELEGRAM_MAX_FILE_SIZE``).

    Returns:
        A list containing just *path* when no splitting is needed, or a list
        of the part paths in order when the file was split.
    """
    if not os.path.isfile(path):
        return [path]
    file_size = os.path.getsize(path)
    if file_size <= max_size:
        return [path]

    parts: List[str] = []
    part_num = 1
    with open(path, "rb") as src:
        while True:
            chunk = src.read(max_size)
            if not chunk:
                break
            part_path = f"{path}.{part_num:03d}"
            with open(part_path, "wb") as dst:
                dst.write(chunk)
            parts.append(part_path)
            part_num += 1

    logger.info("Split %s (%d bytes) into %d part(s).", path, file_size, len(parts))
    return parts


def _is_video(path: str) -> bool:
    """Return ``True`` when *path* appears to be a video file.

    Detection is based on the file extension via :mod:`mimetypes`; no file I/O
    is performed so the file does not need to exist on disk.
    """
    mime, _ = mimetypes.guess_type(path)
    return mime is not None and mime.startswith("video/")


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
    show_completion: bool = True,
) -> None:
    """Upload all *files* to *target_chat_id*, respecting Telegram's album limit.

    Files larger than :data:`TELEGRAM_MAX_FILE_SIZE` are automatically split
    into numbered parts (``.001``, ``.002``, …) so the recipient can
    reassemble them manually.  Video files are sent with
    ``supports_streaming=True`` so they are playable directly in the Telegram
    app without downloading.

    Args:
        client:          Telethon ``TelegramClient`` instance.
        target_chat_id:  The Telegram chat/channel/group to send files to.
                         Can be an integer ID, a ``@username`` string, or any
                         entity accepted by Telethon's ``send_file``.
        ut:              The :class:`~task_manager.UserTask` for this job.
        files:           List of local file paths to upload.
        status_message:  The status :class:`Message` to update with progress.
        show_completion: When ``True`` (default), edit the status message to
                         "✅ Upload Complete!" after all files are sent.  Set
                         to ``False`` when calling this function repeatedly
                         (e.g. once per file in streaming mode) so the final
                         message is only shown once.

    Raises:
        CancelUploadException: If the user requested cancellation mid-upload.
        asyncio.CancelledError: If the asyncio task is cancelled.
    """
    # Expand the file list: split any file that exceeds the Telegram limit.
    expanded_files: List[str] = []
    for f in files:
        parts = split_large_file(f)
        expanded_files.extend(parts)

    chunks = chunk_files(expanded_files)
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
                file_path = chunk[0]
                # For video files set supports_streaming so they play inline.
                extra_kwargs: dict = {}
                if _is_video(file_path):
                    from telethon.tl.types import DocumentAttributeVideo  # type: ignore[import]
                    extra_kwargs["attributes"] = [
                        DocumentAttributeVideo(
                            duration=0,
                            w=0,
                            h=0,
                            supports_streaming=True,
                        )
                    ]
                await client.send_file(  # type: ignore[attr-defined]
                    target_chat_id,
                    file_path,
                    progress_callback=_progress_callback,
                    **extra_kwargs,
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

    if show_completion:
        await safe_edit_message(
            status_message,
            "✅ Upload Complete!",
            [0.0],
            force=True,
        )

"""
Telegram upload logic: per-file sends and progress callbacks.

AI-GENERATED CODE DISCLAIMER: This entire codebase has been created by AI.
Review it carefully before deploying to production.
"""

import asyncio
import logging
import mimetypes
import os
import time
from typing import List, Optional

from pyrogram.errors import PhotoInvalidDimensions, PhotoSaveFileInvalid

from task_manager import UserTask
from utils import (
    format_progress_bar,
    format_size,
    format_speed,
    format_status_message,
    safe_edit_message,
)

logger = logging.getLogger(__name__)

# Safe upload size limit: stay below Telegram's 2 GB MTProto ceiling.
TELEGRAM_MAX_FILE_SIZE = 1950 * 1024 * 1024  # 1950 MB in bytes


class CancelUploadException(Exception):
    """Raised inside a Pyrogram progress callback to abort an upload."""


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


def _is_image(path: str) -> bool:
    """Return ``True`` when *path* appears to be an image file.

    Detection is based on the file extension via :mod:`mimetypes`; no file I/O
    is performed so the file does not need to exist on disk.
    """
    mime, _ = mimetypes.guess_type(path)
    return mime is not None and mime.startswith("image/")


def _file_caption(path: str) -> Optional[str]:
    """Return the filename as a caption for images and videos; ``None`` otherwise.

    Images and videos are sent as native Telegram media (rendered inline) and
    benefit from having the original filename in the caption.  Generic files
    (documents) already show their filename in the file header, so no separate
    caption is needed.

    Args:
        path: Absolute (or relative) path to the file.

    Returns:
        ``os.path.basename(path)`` when the file is an image or video;
        ``None`` for all other file types.
    """
    if _is_image(path) or _is_video(path):
        return os.path.basename(path)
    return None


async def upload_files(
    client: object,
    target_chat_id: object,
    ut: UserTask,
    files: List[str],
    status_message: object,
    show_completion: bool = True,
    url: str = "",
    job_id: int = 0,
    mode: str = "default",
    delete_after_upload: bool = False,
) -> None:
    """Upload all *files* to *target_chat_id* one-by-one.

    Files larger than :data:`TELEGRAM_MAX_FILE_SIZE` are automatically split
    into numbered parts (``.001``, ``.002``, …) so the recipient can
    reassemble them manually.  Video files are sent with
    ``supports_streaming=True`` so they are playable directly in the Telegram
    app without downloading.

    Args:
        client:               Pyrogram ``Client`` instance.
        target_chat_id:       The Telegram chat/channel/group to send files to.
                              Can be an integer ID or a ``@username`` string.
        ut:                   The :class:`~task_manager.UserTask` for this job.
        files:                List of local file paths to upload.
        status_message:       The status :class:`Message` to update with progress.
        show_completion:      When ``True`` (default), send a new summary message
                              after all files are sent.  Set to ``False`` when
                              calling this function repeatedly (e.g. once per file
                              in streaming mode) so the final message is only shown
                              once.
        url:                  Source URL, embedded in the progress and summary messages.
        job_id:               Unique job identifier, embedded in the progress messages.
        mode:                 ``"default"``, ``"zip"``, or ``"duplex"``, shown in
                              progress messages.
        delete_after_upload:  When ``True``, each local file is deleted immediately
                              after it has been successfully uploaded (duplex mode).

    Raises:
        CancelUploadException: If the user requested cancellation mid-upload.
        asyncio.CancelledError: If the asyncio task is cancelled.
    """
    # Expand the file list: split any file that exceeds the Telegram limit.
    expanded_files: List[str] = []
    for f in files:
        parts = split_large_file(f)
        expanded_files.extend(parts)

    total_files = len(expanded_files)
    # Compute total size before any deletions so the completion summary is
    # accurate even when delete_after_upload=True removes files mid-loop.
    total_size = sum(os.path.getsize(f) for f in expanded_files if os.path.isfile(f))

    for file_idx, file_path in enumerate(expanded_files, start=1):
        if ut.cancel_flag:
            raise asyncio.CancelledError("Upload cancelled by user.")

        file_label = f"File {file_idx}/{total_files}" if total_files > 1 else ""

        # Build a progress callback bound to this file.
        last_edit: list = [0.0]
        # Speed tracking: [prev_bytes, prev_monotonic_time]
        speed_state: list = [0, time.monotonic()]

        async def _progress_callback(current: int, total: int) -> None:
            """Pyrogram-compatible upload progress callback."""
            if ut.cancel_flag:
                raise CancelUploadException("Upload cancelled mid-transfer.")

            now = time.monotonic()
            elapsed = now - speed_state[1]
            if elapsed > 0:
                speed = (current - speed_state[0]) / elapsed
            else:
                speed = 0.0
            speed_state[0] = current
            speed_state[1] = now

            bar = format_progress_bar(current, total)
            size_info = f"{format_size(current)} / {format_size(total)}"
            speed_info = format_speed(speed)
            prefix = f"📤 Uploading {file_label}\n" if file_label else "📤 Uploading\n"
            progress_content = f"{prefix}{bar}\n{size_info} • {speed_info}"

            if url and job_id:
                text = format_status_message(url, job_id, mode, progress_content)
            else:
                text = progress_content

            ut.progress_text = progress_content
            await safe_edit_message(status_message, text, last_edit)

        try:
            caption = _file_caption(file_path) or ""
            if _is_video(file_path):
                await client.send_video(  # type: ignore[attr-defined]
                    target_chat_id,
                    file_path,
                    caption=caption,
                    supports_streaming=True,
                    progress=_progress_callback,
                )
            elif _is_image(file_path):
                try:
                    await client.send_photo(  # type: ignore[attr-defined]
                        target_chat_id,
                        file_path,
                        caption=caption,
                        progress=_progress_callback,
                    )
                except (PhotoInvalidDimensions, PhotoSaveFileInvalid):
                    # Image rejected by Telegram (e.g. very tall manga pages,
                    # or a format the Telegram server can't process as a photo);
                    # fall back to sending as a document.
                    await client.send_document(  # type: ignore[attr-defined]
                        target_chat_id,
                        file_path,
                        caption=caption,
                        progress=_progress_callback,
                    )
            else:
                await client.send_document(  # type: ignore[attr-defined]
                    target_chat_id,
                    file_path,
                    progress=_progress_callback,
                )
        except CancelUploadException:
            raise asyncio.CancelledError("Upload cancelled by user.")

        if delete_after_upload:
            try:
                if os.path.isfile(file_path):
                    os.unlink(file_path)
                    logger.debug("Duplex: deleted %s after upload.", file_path)
            except Exception as exc:
                logger.warning("Duplex: failed to delete %s: %s", file_path, exc)

    if delete_after_upload:
        # Remove original files that were split into parts (parts are already
        # deleted in the per-file loop above; expanded_files contains the part
        # paths, not the original, when splitting occurred).
        expanded_set = set(expanded_files)
        for f in files:
            if f in expanded_set:
                # Not split — already deleted in the per-file loop; skip.
                continue
            try:
                if os.path.isfile(f):
                    os.unlink(f)
                    logger.debug("Duplex: deleted split original %s after upload.", f)
            except Exception as exc:
                logger.warning("Duplex: failed to delete split original %s: %s", f, exc)

    if show_completion:
        summary = (
            f"✅ **Upload completed**\n\n"
            f"🔗 **Link:** `{url}`\n"
            f"**File count:** {total_files}\n"
            f"**Total size:** {format_size(total_size)}"
        )
        await client.send_message(  # type: ignore[attr-defined]
            status_message.chat.id,  # type: ignore[attr-defined]
            summary,
        )
        try:
            await status_message.delete()  # type: ignore[attr-defined]
        except Exception:
            pass

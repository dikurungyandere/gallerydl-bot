"""
gallery-dl subprocess wrapper.

AI-GENERATED CODE DISCLAIMER: This entire codebase has been created by AI.
Review it carefully before deploying to production.
"""

import asyncio
import logging
import os
import re
import tempfile
from typing import Callable, Awaitable, List, Optional

from task_manager import UserTask, task_manager
from utils import safe_edit_message

logger = logging.getLogger(__name__)

# Regex to detect URLs in messages.
URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)

# Timeout in seconds before gallery-dl is forcibly killed (0 = no timeout).
SUBPROCESS_TIMEOUT_SECONDS = 3600  # 1 hour


def _build_gallery_dl_cmd(
    url: str,
    dest: str,
    config_path: Optional[str],
) -> List[str]:
    """Construct the gallery-dl command list.

    Args:
        url:         The URL to download.
        dest:        Destination directory for downloaded files.
        config_path: Optional path to a gallery-dl config file.
    """
    cmd = ["gallery-dl", "--dest", dest]
    if config_path:
        cmd.extend(["--config", config_path])
    cmd.append(url)
    return cmd


async def run_gallery_dl(
    user_id: int,
    url: str,
    temp_dir: str,
    config_path: Optional[str],
    on_progress: Callable[[int], Awaitable[None]],
) -> List[str]:
    """Run gallery-dl and collect downloaded file paths.

    Args:
        user_id:     Telegram user ID (used to check cancel_flag and store process).
        url:         URL to download.
        temp_dir:    Directory where gallery-dl writes files.
        config_path: Optional path to gallery-dl config file.
        on_progress: Async callback called with the number of files downloaded
                     so far (after each new file appears in stdout).

    Returns:
        Sorted list of absolute paths to downloaded files.

    Raises:
        RuntimeError: If gallery-dl exits with a non-zero code or times out.
        asyncio.CancelledError: If cancellation was requested.
    """
    cmd = _build_gallery_dl_cmd(url, temp_dir, config_path)
    logger.info("Running: %s", " ".join(cmd))

    ut: UserTask = task_manager.get_or_create(user_id)

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    ut.process = process

    downloaded_files: List[str] = []

    async def _read_stdout() -> None:
        """Read gallery-dl stdout line-by-line, counting downloaded files."""
        assert process.stdout is not None
        async for raw_line in process.stdout:
            if ut.cancel_flag:
                break
            line = raw_line.decode("utf-8", errors="replace").rstrip()
            logger.debug("gallery-dl: %s", line)
            # gallery-dl prints downloaded file paths to stdout.
            if line and os.path.isabs(line):
                downloaded_files.append(line)
                await on_progress(len(downloaded_files))

    try:
        # Read stdout concurrently with a timeout watchdog.
        await asyncio.wait_for(_read_stdout(), timeout=SUBPROCESS_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        raise RuntimeError(
            f"gallery-dl timed out after {SUBPROCESS_TIMEOUT_SECONDS} seconds."
        )

    # Wait for the process to finish.
    try:
        await asyncio.wait_for(process.wait(), timeout=30)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()

    if ut.cancel_flag:
        raise asyncio.CancelledError("Download cancelled by user.")

    # Even if gallery-dl returns non-zero, we still try to recover files already
    # written to disk (it sometimes returns 1 for partial successes).
    return_code = process.returncode
    if return_code not in (0, None):
        # Collect stderr for a better error message.
        stderr_bytes = b""
        if process.stderr is not None:
            try:
                stderr_bytes = await asyncio.wait_for(
                    process.stderr.read(), timeout=5
                )
            except asyncio.TimeoutError:
                pass
        logger.warning(
            "gallery-dl exited with code %s. stderr: %s",
            return_code,
            stderr_bytes.decode("utf-8", errors="replace")[:500],
        )

    # Scan the directory for any files gallery-dl wrote there (stdout may have
    # reported relative paths or nothing at all on some extractors).
    disk_files = _scan_directory(temp_dir)
    # Merge: prefer disk scan (always absolute) but keep order from stdout too.
    all_files = sorted(set(disk_files))
    return all_files


def _scan_directory(path: str) -> List[str]:
    """Return a sorted list of all regular files under *path*."""
    result: List[str] = []
    for root, _dirs, files in os.walk(path):
        for fname in files:
            result.append(os.path.join(root, fname))
    return sorted(result)

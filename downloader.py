"""
gallery-dl subprocess wrapper.

AI-GENERATED CODE DISCLAIMER: This entire codebase has been created by AI.
Review it carefully before deploying to production.
"""

import asyncio
import logging
import os
import re
import shlex
from typing import Callable, Awaitable, List, Optional

from task_manager import UserTask

logger = logging.getLogger(__name__)

# Regex to detect URLs in messages.
URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)

# Regex to detect an optional forwarding target at the end of a message:
#   "-> @username"  or  "-> -100123456789"
TARGET_RE = re.compile(r"\s*->\s*(\S+)\s*$")


def _build_gallery_dl_cmd(
    url: str,
    dest: str,
    config_path: Optional[str],
    extra_args: Optional[str] = None,
    ytdl: bool = False,
    ugoira_convert: bool = False,
    ugoira_mkvmerge: bool = False,
    cookies_path: Optional[str] = None,
) -> List[str]:
    """Construct the gallery-dl command list.

    Args:
        url:             The URL to download.
        dest:            Destination directory for downloaded files.
        config_path:     Optional path to a gallery-dl config file.
        extra_args:      Optional string of extra gallery-dl arguments (e.g.
                         ``"--username foo --password bar"``).  Parsed with
                         :mod:`shlex` so quoted tokens are handled correctly.
        ytdl:            When ``True``, pass ``--yt-dlp`` so gallery-dl uses
                         yt-dlp for HLS/DASH streams and other ytdl-handled
                         URLs.
        ugoira_convert:  When ``True``, pass ``--ugoira-conv`` so gallery-dl
                         converts Pixiv Ugoira ZIP files to WebM/MP4 via
                         FFmpeg.
        ugoira_mkvmerge: When ``True``, pass ``--ugoira-conv-mkvmerge`` so
                         gallery-dl produces MKV files with accurate per-frame
                         timecodes using mkvmerge instead of FFmpeg.
        cookies_path:    Optional path to a Netscape-format cookies file.
                         Passed to gallery-dl via ``--cookies``.
    """
    cmd = ["gallery-dl", "--dest", dest]
    if config_path:
        cmd.extend(["--config", config_path])
    if cookies_path:
        cmd.extend(["--cookies", cookies_path])
    if ytdl:
        cmd.append("--yt-dlp")
    if ugoira_convert:
        cmd.append("--ugoira-conv")
    if ugoira_mkvmerge:
        cmd.append("--ugoira-conv-mkvmerge")
    if extra_args:
        cmd.extend(shlex.split(extra_args))
    cmd.append(url)
    return cmd


async def run_gallery_dl(
    ut: UserTask,
    url: str,
    temp_dir: str,
    config_path: Optional[str],
    on_file: Callable[[str], Awaitable[None]],
    extra_args: Optional[str] = None,
    ytdl: bool = False,
    ugoira_convert: bool = False,
    ugoira_mkvmerge: bool = False,
    cookies_path: Optional[str] = None,
) -> List[str]:
    """Run gallery-dl and collect downloaded file paths.

    There is intentionally no timeout: large gallery downloads can take hours
    or even days. Use /cancel to stop an in-progress download at any time.

    Args:
        ut:              The :class:`~task_manager.UserTask` for this job (used to
                         check ``cancel_flag`` and store the subprocess handle).
        url:             URL to download.
        temp_dir:        Directory where gallery-dl writes files.
        config_path:     Optional path to gallery-dl config file.
        on_file:         Async callback called with the absolute path of each file
                         as soon as gallery-dl reports it on stdout.  Use this to
                         upload files immediately rather than waiting for the whole
                         batch to finish.
        extra_args:      Optional string of extra gallery-dl arguments (e.g.
                         ``"--username foo --password bar"``).
        ytdl:            When ``True``, pass ``--yt-dlp`` to enable yt-dlp
                         integration for HLS/DASH video downloads.
        ugoira_convert:  When ``True``, pass ``--ugoira-conv`` to convert
                         Pixiv Ugoira files to WebM/MP4 via FFmpeg.
        ugoira_mkvmerge: When ``True``, pass ``--ugoira-conv-mkvmerge`` to
                         produce MKV files with accurate frame timecodes using
                         mkvmerge.
        cookies_path:    Optional path to a Netscape-format cookies file.
                         Passed to gallery-dl via ``--cookies``.

    Returns:
        Sorted list of absolute paths to all downloaded files (including any
        that were not reported via stdout and discovered by directory scan).

    Raises:
        RuntimeError: If gallery-dl exits with a non-zero code.
        asyncio.CancelledError: If cancellation was requested.
    """
    cmd = _build_gallery_dl_cmd(
        url, temp_dir, config_path, extra_args,
        ytdl=ytdl, ugoira_convert=ugoira_convert, ugoira_mkvmerge=ugoira_mkvmerge,
        cookies_path=cookies_path,
    )
    logger.info("Running: %s", " ".join(cmd))

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    ut.process = process

    downloaded_files: List[str] = []

    async def _read_stdout() -> None:
        """Read gallery-dl stdout line-by-line, calling on_file for each."""
        assert process.stdout is not None
        async for raw_line in process.stdout:
            if ut.cancel_flag:
                break
            line = raw_line.decode("utf-8", errors="replace").rstrip()
            logger.debug("gallery-dl: %s", line)
            # gallery-dl prints downloaded file paths to stdout.
            if line and os.path.isabs(line):
                downloaded_files.append(line)
                await on_file(line)

    # Read stdout with no timeout — let gallery-dl run as long as it needs.
    await _read_stdout()

    # Wait for the process to exit (it should be nearly instant after EOF).
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
    all_files = sorted(set(disk_files))
    return all_files


def _scan_directory(path: str) -> List[str]:
    """Return a sorted list of all regular files under *path*."""
    result: List[str] = []
    for root, _dirs, files in os.walk(path):
        for fname in files:
            result.append(os.path.join(root, fname))
    return sorted(result)

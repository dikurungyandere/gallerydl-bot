"""
Configuration module for gallerydl-bot.

AI-GENERATED CODE DISCLAIMER: This entire codebase has been created by AI.
Review it carefully before deploying to production.
"""

import base64
import json
import os
import tempfile
from dataclasses import dataclass, field
from typing import Optional, Set

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    """Holds all validated configuration values for the bot."""

    api_id: int
    api_hash: str
    bot_token: str
    allowed_users: Set[int]
    gallery_dl_config_path: Optional[str]

    # Web UI settings.
    webui_enabled: bool = False
    webui_host: str = "0.0.0.0"
    webui_port: int = 8080

    # yt-dlp / youtube-dl integration: pass --yt-dlp to gallery-dl so that
    # HLS/DASH streams (and other ytdl-handled URLs) are downloaded correctly.
    ytdl_enabled: bool = False

    # FFmpeg Pixiv Ugoira conversion: pass --ugoira-conv to gallery-dl so
    # that Ugoira ZIP files are automatically converted to WebM/MP4.
    ugoira_convert: bool = False

    # mkvmerge Ugoira timecodes: pass --ugoira-conv-mkvmerge to gallery-dl so
    # that Ugoira files are converted to MKV with accurate per-frame timecodes.
    ugoira_mkvmerge: bool = False

    # Proxy settings (optional).  When set, the proxy is passed to Pyrogram
    # so all MTProto connections (including file uploads) go through it.
    # Supported schemes: "socks5", "socks4", "http".
    proxy: Optional[dict] = None

    # Path to a cookies file (Netscape format) passed to gallery-dl via
    # --cookies.  When set, gallery-dl uses these cookies for authenticated
    # requests.  Loaded from GALLERY_DL_COOKIES_PATH, GALLERY_DL_COOKIES_B64,
    # or GALLERY_DL_COOKIES env vars.
    gallery_dl_cookies_path: Optional[str] = None

    # Path to a temporary file written from GALLERY_DL_CONFIG_B64 or
    # GALLERY_DL_CONFIG_JSON, if used.
    _temp_config_file: Optional[str] = field(default=None, repr=False)

    # Path to a temporary cookies file written from GALLERY_DL_COOKIES_B64 or
    # GALLERY_DL_COOKIES, if used.
    _temp_cookies_file: Optional[str] = field(default=None, repr=False)

    def cleanup(self) -> None:
        """Remove any temporary config/cookies files created at startup."""
        if self._temp_config_file and os.path.exists(self._temp_config_file):
            os.remove(self._temp_config_file)
            self._temp_config_file = None
        if self._temp_cookies_file and os.path.exists(self._temp_cookies_file):
            os.remove(self._temp_cookies_file)
            self._temp_cookies_file = None


def _write_temp_config(parsed: object) -> str:
    """Serialise *parsed* as JSON into a temporary file and return its path."""
    fd, temp_path = tempfile.mkstemp(suffix=".conf", prefix="gallerydl_")
    with os.fdopen(fd, "w") as f:
        json.dump(parsed, f)
    return temp_path


def load_config() -> Config:
    """Load and validate configuration from environment variables.

    gallery-dl config resolution order (first match wins):
    1. ``GALLERY_DL_CONFIG_PATH`` – path to an existing config file.
    2. ``GALLERY_DL_CONFIG_B64``  – base64-encoded JSON config string.
    3. ``GALLERY_DL_CONFIG_JSON`` – raw JSON config string (legacy).

    gallery-dl cookies resolution order (first match wins):
    1. ``GALLERY_DL_COOKIES_PATH`` – path to an existing Netscape cookies file.
    2. ``GALLERY_DL_COOKIES_B64``  – base64-encoded cookies file content.
    3. ``GALLERY_DL_COOKIES``      – raw cookies file content.

    Returns a populated :class:`Config` instance.

    Raises:
        ValueError: When a required environment variable is missing or invalid.
    """
    raw_api_id = os.getenv("API_ID", "").strip()
    if not raw_api_id:
        raise ValueError("API_ID environment variable is required but not set.")
    try:
        api_id = int(raw_api_id)
    except ValueError:
        raise ValueError(f"API_ID must be an integer, got: {raw_api_id!r}")

    api_hash = os.getenv("API_HASH", "").strip()
    if not api_hash:
        raise ValueError("API_HASH environment variable is required but not set.")

    bot_token = os.getenv("BOT_TOKEN", "").strip()
    if not bot_token:
        raise ValueError("BOT_TOKEN environment variable is required but not set.")

    # Optional: comma-separated list of allowed Telegram user IDs.
    allowed_users: Set[int] = set()
    raw_allowed = os.getenv("ALLOWED_USERS", "").strip()
    if raw_allowed:
        for part in raw_allowed.split(","):
            part = part.strip()
            if part:
                try:
                    allowed_users.add(int(part))
                except ValueError:
                    raise ValueError(
                        f"ALLOWED_USERS contains a non-integer value: {part!r}"
                    )

    # gallery-dl config: prefer an explicit file path, then base64, then JSON.
    gallery_dl_config_path = os.getenv("GALLERY_DL_CONFIG_PATH", "").strip() or None
    temp_config_file: Optional[str] = None

    if not gallery_dl_config_path:
        # Try GALLERY_DL_CONFIG_B64 (preferred: base64-encoded JSON).
        raw_b64 = os.getenv("GALLERY_DL_CONFIG_B64", "").strip()
        if raw_b64:
            try:
                decoded = base64.b64decode(raw_b64).decode("utf-8")
            except Exception as exc:
                raise ValueError(
                    f"GALLERY_DL_CONFIG_B64 is not valid base64: {exc}"
                ) from exc
            try:
                parsed = json.loads(decoded)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"GALLERY_DL_CONFIG_B64 decoded to invalid JSON: {exc}"
                ) from exc
            temp_config_file = _write_temp_config(parsed)
            gallery_dl_config_path = temp_config_file

    if not gallery_dl_config_path:
        # Fall back to GALLERY_DL_CONFIG_JSON (legacy raw JSON).
        gallery_dl_config_json = os.getenv("GALLERY_DL_CONFIG_JSON", "").strip()
        if gallery_dl_config_json:
            try:
                parsed = json.loads(gallery_dl_config_json)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"GALLERY_DL_CONFIG_JSON is not valid JSON: {exc}"
                ) from exc
            temp_config_file = _write_temp_config(parsed)
            gallery_dl_config_path = temp_config_file

    # Web UI settings.
    webui_enabled = os.getenv("WEBUI", "false").strip().lower() in ("true", "1", "yes")
    webui_host = os.getenv("WEBUI_HOST", "0.0.0.0").strip()
    raw_webui_port = os.getenv("WEBUI_PORT", "8080").strip()
    try:
        webui_port = int(raw_webui_port)
    except ValueError:
        raise ValueError(
            f"WEBUI_PORT must be an integer, got: {raw_webui_port!r}"
        )

    # Optional media-processing flags passed to gallery-dl.
    ytdl_enabled = os.getenv("YTDL_ENABLED", "false").strip().lower() in ("true", "1", "yes")
    ugoira_convert = os.getenv("UGOIRA_CONVERT", "false").strip().lower() in ("true", "1", "yes")
    ugoira_mkvmerge = os.getenv("UGOIRA_MKVMERGE", "false").strip().lower() in ("true", "1", "yes")

    # Optional proxy for Pyrogram MTProto connections.
    proxy: Optional[dict] = None
    proxy_scheme = os.getenv("PROXY_SCHEME", "").strip().lower()
    proxy_hostname = os.getenv("PROXY_HOSTNAME", "").strip()
    raw_proxy_port = os.getenv("PROXY_PORT", "").strip()
    if proxy_scheme and proxy_hostname and raw_proxy_port:
        try:
            proxy_port = int(raw_proxy_port)
        except ValueError:
            raise ValueError(
                f"PROXY_PORT must be an integer, got: {raw_proxy_port!r}"
            )
        proxy = {"scheme": proxy_scheme, "hostname": proxy_hostname, "port": proxy_port}
        proxy_username = os.getenv("PROXY_USERNAME", "").strip()
        proxy_password = os.getenv("PROXY_PASSWORD", "").strip()
        if proxy_username:
            proxy["username"] = proxy_username
        if proxy_password:
            proxy["password"] = proxy_password

    # gallery-dl cookies: prefer an explicit file path, then base64, then raw.
    gallery_dl_cookies_path = os.getenv("GALLERY_DL_COOKIES_PATH", "").strip() or None
    temp_cookies_file: Optional[str] = None

    if not gallery_dl_cookies_path:
        # Try GALLERY_DL_COOKIES_B64 (base64-encoded cookies file content).
        raw_cookies_b64 = os.getenv("GALLERY_DL_COOKIES_B64", "").strip()
        if raw_cookies_b64:
            try:
                cookies_content = base64.b64decode(raw_cookies_b64).decode("utf-8")
            except Exception as exc:
                raise ValueError(
                    f"GALLERY_DL_COOKIES_B64 is not valid base64: {exc}"
                ) from exc
            fd, temp_cookies_path = tempfile.mkstemp(
                suffix=".txt", prefix="gallerydl_cookies_"
            )
            with os.fdopen(fd, "w") as f:
                f.write(cookies_content)
            temp_cookies_file = temp_cookies_path
            gallery_dl_cookies_path = temp_cookies_file

    if not gallery_dl_cookies_path:
        # Fall back to GALLERY_DL_COOKIES (raw cookies file content).
        raw_cookies = os.getenv("GALLERY_DL_COOKIES", "").strip()
        if raw_cookies:
            fd, temp_cookies_path = tempfile.mkstemp(
                suffix=".txt", prefix="gallerydl_cookies_"
            )
            with os.fdopen(fd, "w") as f:
                f.write(raw_cookies)
            temp_cookies_file = temp_cookies_path
            gallery_dl_cookies_path = temp_cookies_file

    cfg = Config(
        api_id=api_id,
        api_hash=api_hash,
        bot_token=bot_token,
        allowed_users=allowed_users,
        gallery_dl_config_path=gallery_dl_config_path,
        webui_enabled=webui_enabled,
        webui_host=webui_host,
        webui_port=webui_port,
        ytdl_enabled=ytdl_enabled,
        ugoira_convert=ugoira_convert,
        ugoira_mkvmerge=ugoira_mkvmerge,
        proxy=proxy,
        gallery_dl_cookies_path=gallery_dl_cookies_path,
    )
    cfg._temp_config_file = temp_config_file
    cfg._temp_cookies_file = temp_cookies_file
    return cfg

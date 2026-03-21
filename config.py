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

    # Path to a temporary file written from GALLERY_DL_CONFIG_B64 or
    # GALLERY_DL_CONFIG_JSON, if used.
    _temp_config_file: Optional[str] = field(default=None, repr=False)

    def cleanup(self) -> None:
        """Remove any temporary config file created at startup."""
        if self._temp_config_file and os.path.exists(self._temp_config_file):
            os.remove(self._temp_config_file)
            self._temp_config_file = None


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

    cfg = Config(
        api_id=api_id,
        api_hash=api_hash,
        bot_token=bot_token,
        allowed_users=allowed_users,
        gallery_dl_config_path=gallery_dl_config_path,
    )
    cfg._temp_config_file = temp_config_file
    return cfg

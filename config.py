"""
Configuration module for gallerydl-bot.

AI-GENERATED CODE DISCLAIMER: This entire codebase has been created by AI.
Review it carefully before deploying to production.
"""

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

    # Path to a temporary file written from GALLERY_DL_CONFIG_JSON, if used.
    _temp_config_file: Optional[str] = field(default=None, repr=False)

    def cleanup(self) -> None:
        """Remove any temporary config file created at startup."""
        if self._temp_config_file and os.path.exists(self._temp_config_file):
            os.remove(self._temp_config_file)
            self._temp_config_file = None


def load_config() -> Config:
    """Load and validate configuration from environment variables.

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

    # gallery-dl config: prefer an explicit file path, fall back to JSON env var.
    gallery_dl_config_path = os.getenv("GALLERY_DL_CONFIG_PATH", "").strip() or None
    temp_config_file: Optional[str] = None

    gallery_dl_config_json = os.getenv("GALLERY_DL_CONFIG_JSON", "").strip()
    if gallery_dl_config_json and not gallery_dl_config_path:
        try:
            parsed = json.loads(gallery_dl_config_json)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"GALLERY_DL_CONFIG_JSON is not valid JSON: {exc}"
            ) from exc

        fd, temp_path = tempfile.mkstemp(suffix=".conf", prefix="gallerydl_")
        with os.fdopen(fd, "w") as f:
            json.dump(parsed, f)
        gallery_dl_config_path = temp_path
        temp_config_file = temp_path

    cfg = Config(
        api_id=api_id,
        api_hash=api_hash,
        bot_token=bot_token,
        allowed_users=allowed_users,
        gallery_dl_config_path=gallery_dl_config_path,
    )
    cfg._temp_config_file = temp_config_file
    return cfg

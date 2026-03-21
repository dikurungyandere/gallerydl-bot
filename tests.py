"""
Unit tests for gallerydl-bot.

Tests cover the modules that do NOT require live Telegram credentials:
config.py, task_manager.py, utils.py, downloader.py, and uploader.py.
"""

import asyncio
import os
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# config.py tests
# ---------------------------------------------------------------------------

class TestConfig(unittest.TestCase):
    """Tests for configuration loading."""

    def _load(self, env: dict):
        """Helper: load config with a given set of env vars."""
        with patch.dict(os.environ, env, clear=True):
            from config import load_config
            return load_config()

    def test_valid_config(self):
        from config import load_config
        env = {
            "API_ID": "12345",
            "API_HASH": "abc",
            "BOT_TOKEN": "tok",
            "ALLOWED_USERS": "111,222",
        }
        with patch.dict(os.environ, env, clear=True):
            cfg = load_config()
        self.assertEqual(cfg.api_id, 12345)
        self.assertEqual(cfg.api_hash, "abc")
        self.assertEqual(cfg.bot_token, "tok")
        self.assertIn(111, cfg.allowed_users)
        self.assertIn(222, cfg.allowed_users)

    def test_missing_api_id_raises(self):
        env = {"API_HASH": "abc", "BOT_TOKEN": "tok"}
        with patch.dict(os.environ, env, clear=True):
            from config import load_config
            with self.assertRaises(ValueError):
                load_config()

    def test_non_integer_api_id_raises(self):
        env = {"API_ID": "notanint", "API_HASH": "abc", "BOT_TOKEN": "tok"}
        with patch.dict(os.environ, env, clear=True):
            from config import load_config
            with self.assertRaises(ValueError):
                load_config()

    def test_non_integer_allowed_user_raises(self):
        env = {"API_ID": "1", "API_HASH": "h", "BOT_TOKEN": "t", "ALLOWED_USERS": "bad"}
        with patch.dict(os.environ, env, clear=True):
            from config import load_config
            with self.assertRaises(ValueError):
                load_config()

    def test_gallery_dl_config_json_writes_temp_file(self):
        env = {
            "API_ID": "1",
            "API_HASH": "h",
            "BOT_TOKEN": "t",
            "GALLERY_DL_CONFIG_JSON": '{"key": "value"}',
        }
        with patch.dict(os.environ, env, clear=True):
            from config import load_config
            cfg = load_config()
        try:
            self.assertIsNotNone(cfg.gallery_dl_config_path)
            self.assertTrue(os.path.exists(cfg.gallery_dl_config_path))
        finally:
            cfg.cleanup()
        # File should be gone after cleanup.
        self.assertFalse(os.path.exists(cfg._temp_config_file or "/nonexistent"))

    def test_invalid_gallery_dl_config_json_raises(self):
        env = {
            "API_ID": "1",
            "API_HASH": "h",
            "BOT_TOKEN": "t",
            "GALLERY_DL_CONFIG_JSON": "not-json",
        }
        with patch.dict(os.environ, env, clear=True):
            from config import load_config
            with self.assertRaises(ValueError):
                load_config()

    def test_empty_allowed_users(self):
        env = {"API_ID": "1", "API_HASH": "h", "BOT_TOKEN": "t", "ALLOWED_USERS": ""}
        with patch.dict(os.environ, env, clear=True):
            from config import load_config
            cfg = load_config()
        self.assertEqual(cfg.allowed_users, set())


# ---------------------------------------------------------------------------
# task_manager.py tests
# ---------------------------------------------------------------------------

class TestTaskManager(unittest.TestCase):
    """Tests for TaskManager."""

    def setUp(self):
        # Import fresh to avoid cross-test state pollution via the module singleton.
        from task_manager import TaskManager
        self.tm = TaskManager()

    def test_get_or_create_and_remove(self):
        ut = self.tm.get_or_create(1)
        self.assertIsNotNone(ut)
        self.assertFalse(ut.cancel_flag)
        self.tm.remove(1)
        self.assertIsNone(self.tm.get(1))

    def test_is_active_no_task(self):
        self.tm.get_or_create(2)
        self.assertFalse(self.tm.is_active(2))

    def test_is_active_with_running_task(self):
        ut = self.tm.get_or_create(3)

        async def _run():
            task = asyncio.create_task(asyncio.sleep(100))
            ut.task = task
            is_active = self.tm.is_active(3)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            return is_active

        result = asyncio.run(_run())
        self.assertTrue(result)

    def test_cancel_sets_flag(self):
        ut = self.tm.get_or_create(4)

        async def _test():
            return await self.tm.cancel(4)

        result = asyncio.run(_test())
        self.assertTrue(result)
        self.assertTrue(ut.cancel_flag)

    def test_cancel_nonexistent_returns_false(self):
        async def _test():
            return await self.tm.cancel(9999)

        result = asyncio.run(_test())
        self.assertFalse(result)


# ---------------------------------------------------------------------------
# utils.py tests
# ---------------------------------------------------------------------------

class TestUtils(unittest.TestCase):
    """Tests for utility functions."""

    def test_format_progress_bar_zero(self):
        from utils import format_progress_bar
        bar = format_progress_bar(0, 0)
        self.assertIn("0%", bar)

    def test_format_progress_bar_half(self):
        from utils import format_progress_bar
        bar = format_progress_bar(5, 10)
        self.assertIn("50%", bar)

    def test_format_progress_bar_full(self):
        from utils import format_progress_bar
        bar = format_progress_bar(10, 10)
        self.assertIn("100%", bar)
        self.assertNotIn("░", bar)

    def test_format_size_bytes(self):
        from utils import format_size
        self.assertIn("B", format_size(500))

    def test_format_size_mb(self):
        from utils import format_size
        result = format_size(5 * 1024 * 1024)
        self.assertIn("MB", result)

    def test_cleanup_directory_removes_dir(self):
        from utils import cleanup_directory
        d = tempfile.mkdtemp()
        open(os.path.join(d, "file.txt"), "w").close()
        cleanup_directory(d)
        self.assertFalse(os.path.exists(d))

    def test_cleanup_directory_none_is_safe(self):
        from utils import cleanup_directory
        # Should not raise.
        cleanup_directory(None)

    def test_cleanup_directory_missing_path_is_safe(self):
        from utils import cleanup_directory
        cleanup_directory("/nonexistent/path/xyz")

    def test_safe_edit_message_throttled(self):
        """Message should NOT be edited if called too soon."""
        from utils import safe_edit_message

        mock_msg = AsyncMock()
        last_edit = [time.monotonic()]  # Pretend we just edited.

        asyncio.run(
            safe_edit_message(mock_msg, "new text", last_edit, force=False)
        )
        mock_msg.edit.assert_not_called()

    def test_safe_edit_message_forced(self):
        """Message SHOULD be edited when force=True regardless of throttle."""
        from utils import safe_edit_message

        mock_msg = AsyncMock()
        last_edit = [time.monotonic()]  # Pretend we just edited.

        asyncio.run(
            safe_edit_message(mock_msg, "forced", last_edit, force=True)
        )
        mock_msg.edit.assert_called_once_with("forced")


# ---------------------------------------------------------------------------
# uploader.py tests
# ---------------------------------------------------------------------------

class TestUploader(unittest.TestCase):
    """Tests for upload helpers."""

    def test_chunk_files_exact_multiple(self):
        from uploader import chunk_files
        files = [str(i) for i in range(20)]
        chunks = chunk_files(files, size=10)
        self.assertEqual(len(chunks), 2)
        self.assertEqual(len(chunks[0]), 10)
        self.assertEqual(len(chunks[1]), 10)

    def test_chunk_files_remainder(self):
        from uploader import chunk_files
        files = [str(i) for i in range(15)]
        chunks = chunk_files(files, size=10)
        self.assertEqual(len(chunks), 2)
        self.assertEqual(len(chunks[1]), 5)

    def test_chunk_files_empty(self):
        from uploader import chunk_files
        self.assertEqual(chunk_files([]), [])

    def test_chunk_files_single(self):
        from uploader import chunk_files
        chunks = chunk_files(["a.jpg"])
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0], ["a.jpg"])


# ---------------------------------------------------------------------------
# downloader.py tests
# ---------------------------------------------------------------------------

class TestDownloader(unittest.TestCase):
    """Tests for downloader helpers."""

    def test_url_regex_matches_http(self):
        from downloader import URL_RE
        m = URL_RE.search("check this out https://example.com/page?q=1")
        self.assertIsNotNone(m)
        self.assertTrue(m.group(0).startswith("https://"))

    def test_url_regex_no_match(self):
        from downloader import URL_RE
        m = URL_RE.search("no url here")
        self.assertIsNone(m)

    def test_build_gallery_dl_cmd_basic(self):
        from downloader import _build_gallery_dl_cmd
        cmd = _build_gallery_dl_cmd("https://example.com", "/tmp/dest", None)
        self.assertIn("gallery-dl", cmd)
        self.assertIn("--dest", cmd)
        self.assertIn("/tmp/dest", cmd)
        self.assertIn("https://example.com", cmd)

    def test_build_gallery_dl_cmd_with_config(self):
        from downloader import _build_gallery_dl_cmd
        cmd = _build_gallery_dl_cmd("https://x.com", "/tmp/d", "/etc/gdl.conf")
        self.assertIn("--config", cmd)
        self.assertIn("/etc/gdl.conf", cmd)

    def test_scan_directory(self):
        from downloader import _scan_directory
        with tempfile.TemporaryDirectory() as d:
            path1 = os.path.join(d, "a.jpg")
            path2 = os.path.join(d, "b.jpg")
            open(path1, "w").close()
            open(path2, "w").close()
            result = _scan_directory(d)
        self.assertEqual(len(result), 2)
        self.assertTrue(all(os.path.isabs(p) for p in result))


if __name__ == "__main__":
    unittest.main(verbosity=2)

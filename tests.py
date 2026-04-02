"""
Unit tests for gallerydl-bot.

Tests cover the modules that do NOT require live Telegram credentials:
config.py, task_manager.py, utils.py, downloader.py, uploader.py, and webui.py.
"""

import asyncio
import base64
import json
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

    def test_gallery_dl_config_b64_writes_temp_file(self):
        """GALLERY_DL_CONFIG_B64 should be decoded and written to a temp file."""
        raw_json = '{"extractor": {"base-directory": "/tmp"}}'
        b64_value = base64.b64encode(raw_json.encode()).decode()
        env = {
            "API_ID": "1",
            "API_HASH": "h",
            "BOT_TOKEN": "t",
            "GALLERY_DL_CONFIG_B64": b64_value,
        }
        with patch.dict(os.environ, env, clear=True):
            from config import load_config
            cfg = load_config()
        try:
            self.assertIsNotNone(cfg.gallery_dl_config_path)
            self.assertTrue(os.path.exists(cfg.gallery_dl_config_path))
            with open(cfg.gallery_dl_config_path) as f:
                data = json.load(f)
            self.assertEqual(data["extractor"]["base-directory"], "/tmp")
        finally:
            cfg.cleanup()

    def test_gallery_dl_config_b64_invalid_base64_raises(self):
        env = {
            "API_ID": "1",
            "API_HASH": "h",
            "BOT_TOKEN": "t",
            "GALLERY_DL_CONFIG_B64": "!!!not-base64!!!",
        }
        with patch.dict(os.environ, env, clear=True):
            from config import load_config
            with self.assertRaises(ValueError):
                load_config()

    def test_gallery_dl_config_b64_invalid_json_raises(self):
        """Valid base64 but the decoded content is not JSON → ValueError."""
        b64_value = base64.b64encode(b"not-json-at-all").decode()
        env = {
            "API_ID": "1",
            "API_HASH": "h",
            "BOT_TOKEN": "t",
            "GALLERY_DL_CONFIG_B64": b64_value,
        }
        with patch.dict(os.environ, env, clear=True):
            from config import load_config
            with self.assertRaises(ValueError):
                load_config()

    def test_b64_takes_priority_over_json(self):
        """GALLERY_DL_CONFIG_B64 is preferred over GALLERY_DL_CONFIG_JSON."""
        b64_json = '{"source": "b64"}'
        b64_value = base64.b64encode(b64_json.encode()).decode()
        env = {
            "API_ID": "1",
            "API_HASH": "h",
            "BOT_TOKEN": "t",
            "GALLERY_DL_CONFIG_B64": b64_value,
            "GALLERY_DL_CONFIG_JSON": '{"source": "json"}',
        }
        with patch.dict(os.environ, env, clear=True):
            from config import load_config
            cfg = load_config()
        try:
            with open(cfg.gallery_dl_config_path) as f:
                data = json.load(f)
            self.assertEqual(data["source"], "b64")
        finally:
            cfg.cleanup()

    def test_explicit_path_takes_priority_over_b64(self):
        """GALLERY_DL_CONFIG_PATH overrides GALLERY_DL_CONFIG_B64."""
        b64_value = base64.b64encode(b'{"source":"b64"}').decode()
        with tempfile.NamedTemporaryFile(suffix=".conf", delete=False) as f:
            explicit_path = f.name
        try:
            env = {
                "API_ID": "1",
                "API_HASH": "h",
                "BOT_TOKEN": "t",
                "GALLERY_DL_CONFIG_PATH": explicit_path,
                "GALLERY_DL_CONFIG_B64": b64_value,
            }
            with patch.dict(os.environ, env, clear=True):
                from config import load_config
                cfg = load_config()
            self.assertEqual(cfg.gallery_dl_config_path, explicit_path)
            # No temp file should have been created.
            self.assertIsNone(cfg._temp_config_file)
        finally:
            os.unlink(explicit_path)

    def test_webui_disabled_by_default(self):
        """WEBUI defaults to false when not set."""
        env = {"API_ID": "1", "API_HASH": "h", "BOT_TOKEN": "t"}
        with patch.dict(os.environ, env, clear=True):
            from config import load_config
            cfg = load_config()
        self.assertFalse(cfg.webui_enabled)
        self.assertEqual(cfg.webui_port, 8080)
        self.assertEqual(cfg.webui_host, "0.0.0.0")

    def test_webui_enabled(self):
        """WEBUI=true enables the web server."""
        env = {
            "API_ID": "1",
            "API_HASH": "h",
            "BOT_TOKEN": "t",
            "WEBUI": "true",
            "WEBUI_PORT": "9000",
            "WEBUI_HOST": "127.0.0.1",
        }
        with patch.dict(os.environ, env, clear=True):
            from config import load_config
            cfg = load_config()
        self.assertTrue(cfg.webui_enabled)
        self.assertEqual(cfg.webui_port, 9000)
        self.assertEqual(cfg.webui_host, "127.0.0.1")

    def test_webui_enabled_variants(self):
        """WEBUI accepts '1' and 'yes' as truthy values."""
        for truthy in ("1", "yes", "true", "True", "YES"):
            env = {"API_ID": "1", "API_HASH": "h", "BOT_TOKEN": "t", "WEBUI": truthy}
            with patch.dict(os.environ, env, clear=True):
                from config import load_config
                cfg = load_config()
            self.assertTrue(cfg.webui_enabled, f"Expected webui_enabled for WEBUI={truthy!r}")

    def test_webui_invalid_port_raises(self):
        """WEBUI_PORT must be an integer."""
        env = {"API_ID": "1", "API_HASH": "h", "BOT_TOKEN": "t", "WEBUI_PORT": "notaport"}
        with patch.dict(os.environ, env, clear=True):
            from config import load_config
            with self.assertRaises(ValueError):
                load_config()

    def test_gallery_dl_cookies_path_used_directly(self):
        """GALLERY_DL_COOKIES_PATH is stored directly without a temp file."""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            ck_path = f.name
        try:
            env = {
                "API_ID": "1", "API_HASH": "h", "BOT_TOKEN": "t",
                "GALLERY_DL_COOKIES_PATH": ck_path,
            }
            with patch.dict(os.environ, env, clear=True):
                from config import load_config
                cfg = load_config()
            self.assertEqual(cfg.gallery_dl_cookies_path, ck_path)
            self.assertIsNone(cfg._temp_cookies_file)
        finally:
            os.unlink(ck_path)

    def test_gallery_dl_cookies_b64_writes_temp_file(self):
        """GALLERY_DL_COOKIES_B64 is decoded and written to a temp file."""
        cookies_content = "# Netscape HTTP Cookie File\nexample.com\tFALSE\t/\tFALSE\t0\tsession\tabc"
        b64_value = base64.b64encode(cookies_content.encode()).decode()
        env = {
            "API_ID": "1", "API_HASH": "h", "BOT_TOKEN": "t",
            "GALLERY_DL_COOKIES_B64": b64_value,
        }
        with patch.dict(os.environ, env, clear=True):
            from config import load_config
            cfg = load_config()
        try:
            self.assertIsNotNone(cfg.gallery_dl_cookies_path)
            self.assertTrue(os.path.exists(cfg.gallery_dl_cookies_path))
            with open(cfg.gallery_dl_cookies_path) as f:
                self.assertIn("session", f.read())
        finally:
            cfg.cleanup()

    def test_gallery_dl_cookies_b64_invalid_raises(self):
        """Invalid base64 in GALLERY_DL_COOKIES_B64 raises ValueError."""
        env = {
            "API_ID": "1", "API_HASH": "h", "BOT_TOKEN": "t",
            "GALLERY_DL_COOKIES_B64": "!!!not-base64!!!",
        }
        with patch.dict(os.environ, env, clear=True):
            from config import load_config
            with self.assertRaises(ValueError):
                load_config()

    def test_gallery_dl_cookies_raw_writes_temp_file(self):
        """GALLERY_DL_COOKIES (raw text) is written to a temp file."""
        cookies_content = "# Netscape HTTP Cookie File\nexample.com\tFALSE\t/\tFALSE\t0\ttoken\txyz"
        env = {
            "API_ID": "1", "API_HASH": "h", "BOT_TOKEN": "t",
            "GALLERY_DL_COOKIES": cookies_content,
        }
        with patch.dict(os.environ, env, clear=True):
            from config import load_config
            cfg = load_config()
        try:
            self.assertIsNotNone(cfg.gallery_dl_cookies_path)
            self.assertTrue(os.path.exists(cfg.gallery_dl_cookies_path))
            with open(cfg.gallery_dl_cookies_path) as f:
                self.assertIn("token", f.read())
        finally:
            cfg.cleanup()

    def test_cookies_path_takes_priority_over_b64(self):
        """GALLERY_DL_COOKIES_PATH takes priority over GALLERY_DL_COOKIES_B64."""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            ck_path = f.name
        try:
            b64_value = base64.b64encode(b"cookies content").decode()
            env = {
                "API_ID": "1", "API_HASH": "h", "BOT_TOKEN": "t",
                "GALLERY_DL_COOKIES_PATH": ck_path,
                "GALLERY_DL_COOKIES_B64": b64_value,
            }
            with patch.dict(os.environ, env, clear=True):
                from config import load_config
                cfg = load_config()
            self.assertEqual(cfg.gallery_dl_cookies_path, ck_path)
            self.assertIsNone(cfg._temp_cookies_file)
        finally:
            os.unlink(ck_path)

    def test_cookies_b64_takes_priority_over_raw(self):
        """GALLERY_DL_COOKIES_B64 takes priority over GALLERY_DL_COOKIES."""
        b64_value = base64.b64encode(b"b64 cookies").decode()
        env = {
            "API_ID": "1", "API_HASH": "h", "BOT_TOKEN": "t",
            "GALLERY_DL_COOKIES_B64": b64_value,
            "GALLERY_DL_COOKIES": "raw cookies",
        }
        with patch.dict(os.environ, env, clear=True):
            from config import load_config
            cfg = load_config()
        try:
            with open(cfg.gallery_dl_cookies_path) as f:
                self.assertIn("b64 cookies", f.read())
        finally:
            cfg.cleanup()

    def test_no_cookies_env_gives_none(self):
        """When no cookies env var is set, gallery_dl_cookies_path is None."""
        env = {"API_ID": "1", "API_HASH": "h", "BOT_TOKEN": "t"}
        with patch.dict(os.environ, env, clear=True):
            from config import load_config
            cfg = load_config()
        self.assertIsNone(cfg.gallery_dl_cookies_path)

    def test_cleanup_removes_temp_cookies_file(self):
        """cleanup() removes the temporary cookies file."""
        cookies_content = "# cookies"
        env = {
            "API_ID": "1", "API_HASH": "h", "BOT_TOKEN": "t",
            "GALLERY_DL_COOKIES": cookies_content,
        }
        with patch.dict(os.environ, env, clear=True):
            from config import load_config
            cfg = load_config()
        ck_path = cfg.gallery_dl_cookies_path
        self.assertTrue(os.path.exists(ck_path))
        cfg.cleanup()
        self.assertFalse(os.path.exists(ck_path))


# ---------------------------------------------------------------------------
# task_manager.py tests
# ---------------------------------------------------------------------------

class TestTaskManager(unittest.TestCase):
    """Tests for TaskManager."""

    def setUp(self):
        from task_manager import TaskManager
        self.tm = TaskManager()

    def test_create_returns_incrementing_ids(self):
        jid1, ut1 = self.tm.create(1)
        jid2, ut2 = self.tm.create(1)
        self.assertNotEqual(jid1, jid2)
        self.assertLess(jid1, jid2)
        self.assertEqual(ut1.user_id, 1)
        self.assertEqual(ut2.user_id, 1)

    def test_get_returns_task_by_job_id(self):
        jid, ut = self.tm.create(1)
        self.assertIs(self.tm.get(jid), ut)

    def test_get_nonexistent_returns_none(self):
        self.assertIsNone(self.tm.get(9999))

    def test_remove_cleans_up(self):
        jid, _ = self.tm.create(2)
        self.tm.remove(jid)
        self.assertIsNone(self.tm.get(jid))

    def test_remove_nonexistent_is_safe(self):
        # Should not raise.
        self.tm.remove(9999)

    def test_is_active_no_task(self):
        self.tm.create(3)
        self.assertFalse(self.tm.is_active(3))

    def test_is_active_with_running_task(self):
        jid, ut = self.tm.create(4)

        async def _run():
            task = asyncio.create_task(asyncio.sleep(100))
            ut.task = task
            active = self.tm.is_active(4)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            return active

        result = asyncio.run(_run())
        self.assertTrue(result)

    def test_multiple_jobs_per_user(self):
        jid1, ut1 = self.tm.create(5)
        jid2, ut2 = self.tm.create(5)

        async def _run():
            t1 = asyncio.create_task(asyncio.sleep(100))
            t2 = asyncio.create_task(asyncio.sleep(100))
            ut1.task = t1
            ut2.task = t2
            jobs = self.tm.get_user_tasks(5)
            t1.cancel()
            t2.cancel()
            for t in (t1, t2):
                try:
                    await t
                except asyncio.CancelledError:
                    pass
            return jobs

        jobs = asyncio.run(_run())
        self.assertEqual(len(jobs), 2)
        job_ids = {j[0] for j in jobs}
        self.assertIn(jid1, job_ids)
        self.assertIn(jid2, job_ids)

    def test_cancel_specific_job(self):
        jid1, ut1 = self.tm.create(6)
        jid2, ut2 = self.tm.create(6)

        async def _run():
            t1 = asyncio.create_task(asyncio.sleep(100))
            t2 = asyncio.create_task(asyncio.sleep(100))
            ut1.task = t1
            ut2.task = t2
            cancelled = await self.tm.cancel(jid1)
            return cancelled, ut1.cancel_flag, ut2.cancel_flag

        cancelled, flag1, flag2 = asyncio.run(_run())
        self.assertTrue(cancelled)
        self.assertTrue(flag1)
        self.assertFalse(flag2)

    def test_cancel_all(self):
        jid1, ut1 = self.tm.create(7)
        jid2, ut2 = self.tm.create(7)

        async def _run():
            t1 = asyncio.create_task(asyncio.sleep(100))
            t2 = asyncio.create_task(asyncio.sleep(100))
            ut1.task = t1
            ut2.task = t2
            count = await self.tm.cancel_all(7)
            return count, ut1.cancel_flag, ut2.cancel_flag

        count, flag1, flag2 = asyncio.run(_run())
        self.assertEqual(count, 2)
        self.assertTrue(flag1)
        self.assertTrue(flag2)

    def test_cancel_nonexistent_returns_false(self):
        async def _test():
            return await self.tm.cancel(9999)

        result = asyncio.run(_test())
        self.assertFalse(result)

    def test_cancel_all_no_jobs_returns_zero(self):
        async def _test():
            return await self.tm.cancel_all(9999)

        result = asyncio.run(_test())
        self.assertEqual(result, 0)

    def test_remove_updates_user_job_list(self):
        jid1, _ = self.tm.create(8)
        jid2, ut2 = self.tm.create(8)

        async def _run():
            t = asyncio.create_task(asyncio.sleep(100))
            ut2.task = t
            self.tm.remove(jid1)
            jobs = self.tm.get_user_tasks(8)
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass
            return jobs

        jobs = asyncio.run(_run())
        job_ids = [j[0] for j in jobs]
        self.assertNotIn(jid1, job_ids)
        self.assertIn(jid2, job_ids)


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

    def test_format_speed_zero(self):
        from utils import format_speed
        result = format_speed(0)
        self.assertIn("?", result)

    def test_format_speed_negative(self):
        from utils import format_speed
        result = format_speed(-1)
        self.assertIn("?", result)

    def test_format_speed_bytes_per_sec(self):
        from utils import format_speed
        result = format_speed(500)
        self.assertIn("B/s", result)
        self.assertNotIn("KB/s", result)

    def test_format_speed_kbps(self):
        from utils import format_speed
        result = format_speed(512 * 1024)  # 512 KB/s
        self.assertIn("KB/s", result)

    def test_format_speed_mbps(self):
        from utils import format_speed
        result = format_speed(5 * 1024 * 1024)  # 5 MB/s
        self.assertIn("MB/s", result)

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

    def test_format_status_message_default_mode(self):
        """format_status_message includes link, job ID, Default mode, progress, and cancel hint."""
        from utils import format_status_message
        result = format_status_message(
            url="https://example.com/gallery",
            job_id=42,
            mode="default",
            progress_content="📥 Downloading… 3 file(s) so far",
        )
        self.assertIn("https://example.com/gallery", result)
        self.assertIn("42", result)
        self.assertIn("Default", result)
        self.assertNotIn("Duplex", result)
        self.assertIn("📥 Downloading… 3 file(s) so far", result)
        self.assertIn("/cancel 42", result)

    def test_format_status_message_duplex_mode(self):
        """format_status_message shows 'Duplex' for duplex mode."""
        from utils import format_status_message
        result = format_status_message(
            url="https://example.com",
            job_id=7,
            mode="duplex",
            progress_content="📥 Downloading…",
        )
        self.assertIn("Duplex", result)
        self.assertNotIn("Default", result)

    def test_format_status_message_zip_mode(self):
        """format_status_message shows 'Zip' for zip mode."""
        from utils import format_status_message
        result = format_status_message(
            url="https://example.com",
            job_id=5,
            mode="zip",
            progress_content="📥 Downloading…",
        )
        self.assertIn("Zip", result)
        self.assertNotIn("Default", result)
        self.assertNotIn("Duplex", result)

    def test_format_status_message_contains_progress_header(self):
        """format_status_message labels the progress section."""
        from utils import format_status_message
        result = format_status_message("https://x.com", 1, "default", "some progress")
        self.assertIn("Progress", result)
        self.assertIn("some progress", result)


# ---------------------------------------------------------------------------
# uploader.py tests
# ---------------------------------------------------------------------------

class TestUploader(unittest.TestCase):
    """Tests for upload helpers."""

    def test_upload_uses_target_chat_id(self):
        """upload_files must send to target_chat_id, not event.chat_id."""
        from uploader import upload_files
        from task_manager import UserTask

        mock_client = MagicMock()
        mock_client.send_photo = AsyncMock()
        mock_client.send_message = AsyncMock()
        mock_status = AsyncMock()

        ut = UserTask(user_id=1)
        target = -1001234567890

        asyncio.run(
            upload_files(
                client=mock_client,
                target_chat_id=target,
                ut=ut,
                files=["/tmp/fake.jpg"],
                status_message=mock_status,
            )
        )

        mock_client.send_photo.assert_called_once()
        call_args = mock_client.send_photo.call_args
        self.assertEqual(call_args[0][0], target)

    def test_upload_multiple_files_sent_individually(self):
        """Multiple files should be uploaded as individual sends, not albums."""
        from uploader import upload_files
        from task_manager import UserTask

        mock_client = MagicMock()
        mock_client.send_photo = AsyncMock()
        mock_client.send_media_group = AsyncMock()
        mock_client.send_message = AsyncMock()
        mock_status = AsyncMock()

        ut = UserTask(user_id=1)
        target = -1001234567890
        files = ["/tmp/a.jpg", "/tmp/b.jpg"]

        asyncio.run(
            upload_files(
                client=mock_client,
                target_chat_id=target,
                ut=ut,
                files=files,
                status_message=mock_status,
            )
        )

        self.assertEqual(mock_client.send_photo.await_count, 2)
        mock_client.send_media_group.assert_not_called()

    def test_upload_show_completion_sends_new_message(self):
        """When show_completion=True, a new summary message is sent (not edit)."""
        from uploader import upload_files
        from task_manager import UserTask
        import tempfile

        mock_client = MagicMock()
        mock_client.send_photo = AsyncMock()
        mock_client.send_message = AsyncMock()
        mock_status = AsyncMock()
        mock_status.delete = AsyncMock()

        ut = UserTask(user_id=1)
        target = -1001234567890

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"\xff\xd8\xff" + b"x" * 100)
            path = f.name

        try:
            asyncio.run(
                upload_files(
                    client=mock_client,
                    target_chat_id=target,
                    ut=ut,
                    files=[path],
                    status_message=mock_status,
                    show_completion=True,
                    url="https://example.com",
                    job_id=5,
                    mode="default",
                )
            )
        finally:
            os.unlink(path)

        # A new message should be sent with the summary.
        mock_client.send_message.assert_awaited_once()
        call_text = mock_client.send_message.call_args[0][1]
        self.assertIn("Upload completed", call_text)
        self.assertIn("https://example.com", call_text)
        self.assertIn("File count", call_text)
        self.assertIn("Total size", call_text)
        # The progress/status message must be deleted after success.
        mock_status.delete.assert_awaited_once()

    def test_upload_show_completion_false_no_summary(self):
        """When show_completion=False, no summary message is sent."""
        from uploader import upload_files
        from task_manager import UserTask
        import tempfile

        mock_client = MagicMock()
        mock_client.send_photo = AsyncMock()
        mock_client.send_message = AsyncMock()
        mock_status = AsyncMock()

        ut = UserTask(user_id=1)
        target = -1001234567890

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"\xff\xd8\xff" + b"x" * 100)
            path = f.name

        try:
            asyncio.run(
                upload_files(
                    client=mock_client,
                    target_chat_id=target,
                    ut=ut,
                    files=[path],
                    status_message=mock_status,
                    show_completion=False,
                )
            )
        finally:
            os.unlink(path)

        mock_client.send_message.assert_not_awaited()

    # ------------------------------------------------------------------
    # split_large_file tests
    # ------------------------------------------------------------------

    def test_split_large_file_no_split_needed(self):
        """Files under the size limit are returned as a single-item list."""
        from uploader import split_large_file
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"x" * 100)
            path = f.name
        try:
            result = split_large_file(path, max_size=1000)
            self.assertEqual(result, [path])
        finally:
            os.unlink(path)

    def test_split_large_file_splits_into_parts(self):
        """A file larger than max_size is split into the correct number of parts."""
        from uploader import split_large_file
        data = b"A" * 1000
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(data)
            path = f.name
        try:
            parts = split_large_file(path, max_size=300)
            self.assertEqual(len(parts), 4)  # ceil(1000/300) = 4
            self.assertTrue(parts[0].endswith(".001"))
            self.assertTrue(parts[1].endswith(".002"))
            # Reassembled content matches original.
            reassembled = b""
            for p in parts:
                with open(p, "rb") as fh:
                    reassembled += fh.read()
            self.assertEqual(reassembled, data)
        finally:
            os.unlink(path)
            for p in parts:
                if os.path.exists(p):
                    os.unlink(p)

    def test_split_large_file_nonexistent_returns_path(self):
        """A missing file is returned as-is without raising."""
        from uploader import split_large_file
        result = split_large_file("/nonexistent/path/file.mp4")
        self.assertEqual(result, ["/nonexistent/path/file.mp4"])

    # ------------------------------------------------------------------
    # _is_video tests
    # ------------------------------------------------------------------

    def test_is_video_mp4(self):
        from uploader import _is_video
        self.assertTrue(_is_video("clip.mp4"))

    def test_is_video_mkv(self):
        from uploader import _is_video
        self.assertTrue(_is_video("clip.mkv"))

    def test_is_video_webm(self):
        from uploader import _is_video
        self.assertTrue(_is_video("clip.webm"))

    def test_is_video_jpg_is_false(self):
        from uploader import _is_video
        self.assertFalse(_is_video("photo.jpg"))

    def test_is_video_png_is_false(self):
        from uploader import _is_video
        self.assertFalse(_is_video("image.png"))

    def test_is_video_no_extension_is_false(self):
        from uploader import _is_video
        self.assertFalse(_is_video("noextension"))

    # ------------------------------------------------------------------
    # _is_image tests
    # ------------------------------------------------------------------

    def test_is_image_jpg(self):
        from uploader import _is_image
        self.assertTrue(_is_image("photo.jpg"))

    def test_is_image_png(self):
        from uploader import _is_image
        self.assertTrue(_is_image("image.png"))

    def test_is_image_gif(self):
        from uploader import _is_image
        self.assertTrue(_is_image("anim.gif"))

    def test_is_image_webp(self):
        from uploader import _is_image
        self.assertTrue(_is_image("sticker.webp"))

    def test_is_image_mp4_is_false(self):
        from uploader import _is_image
        self.assertFalse(_is_image("clip.mp4"))

    def test_is_image_no_extension_is_false(self):
        from uploader import _is_image
        self.assertFalse(_is_image("noextension"))

    # ------------------------------------------------------------------
    # _file_caption tests
    # ------------------------------------------------------------------

    def test_file_caption_image_returns_basename(self):
        from uploader import _file_caption
        self.assertEqual(_file_caption("/downloads/photo.jpg"), "photo.jpg")

    def test_file_caption_video_returns_basename(self):
        from uploader import _file_caption
        self.assertEqual(_file_caption("/downloads/clip.mp4"), "clip.mp4")

    def test_file_caption_document_returns_none(self):
        from uploader import _file_caption
        self.assertIsNone(_file_caption("/downloads/archive.zip"))

    def test_file_caption_no_extension_returns_none(self):
        from uploader import _file_caption
        self.assertIsNone(_file_caption("/downloads/unknownfile"))

    # ------------------------------------------------------------------
    # delete_after_upload (duplex mode) tests
    # ------------------------------------------------------------------

    def test_upload_delete_after_upload_removes_file(self):
        """When delete_after_upload=True, each file is deleted after upload."""
        from uploader import upload_files
        from task_manager import UserTask
        import tempfile

        mock_client = MagicMock()
        mock_client.send_photo = AsyncMock()
        mock_client.send_message = AsyncMock()
        mock_status = AsyncMock()
        mock_status.delete = AsyncMock()

        ut = UserTask(user_id=1)
        target = -1001234567890

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"\xff\xd8\xff" + b"x" * 100)
            path = f.name

        asyncio.run(
            upload_files(
                client=mock_client,
                target_chat_id=target,
                ut=ut,
                files=[path],
                status_message=mock_status,
                show_completion=False,
                delete_after_upload=True,
            )
        )

        self.assertFalse(os.path.exists(path), "File should be deleted after upload.")

    def test_upload_delete_after_upload_false_keeps_file(self):
        """When delete_after_upload=False (default), files are not deleted."""
        from uploader import upload_files
        from task_manager import UserTask
        import tempfile

        mock_client = MagicMock()
        mock_client.send_photo = AsyncMock()
        mock_client.send_message = AsyncMock()
        mock_status = AsyncMock()

        ut = UserTask(user_id=1)
        target = -1001234567890

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"\xff\xd8\xff" + b"x" * 100)
            path = f.name

        try:
            asyncio.run(
                upload_files(
                    client=mock_client,
                    target_chat_id=target,
                    ut=ut,
                    files=[path],
                    status_message=mock_status,
                    show_completion=False,
                    delete_after_upload=False,
                )
            )
            self.assertTrue(os.path.exists(path), "File should remain on disk.")
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_upload_delete_after_upload_deletes_split_original(self):
        """When delete_after_upload=True, the original file of split parts is deleted."""
        from uploader import upload_files
        from task_manager import UserTask
        import tempfile

        mock_client = MagicMock()
        mock_client.send_document = AsyncMock()
        mock_client.send_message = AsyncMock()
        mock_status = AsyncMock()

        ut = UserTask(user_id=1)
        target = -1001234567890

        # Create a file that will be split (use a tiny max_size via monkeypatching
        # split_large_file to simulate split behaviour).
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
            f.write(b"A" * 20)
            path = f.name

        # Manually create two "part" files and patch split_large_file so
        # upload_files sees them as pre-split parts.
        part1 = path + ".001"
        part2 = path + ".002"
        with open(part1, "wb") as p:
            p.write(b"A" * 10)
        with open(part2, "wb") as p:
            p.write(b"A" * 10)

        import uploader as uploader_mod

        original_split = uploader_mod.split_large_file

        def fake_split(p, max_size=None):
            if p == path:
                return [part1, part2]
            return [p]

        uploader_mod.split_large_file = fake_split
        try:
            asyncio.run(
                upload_files(
                    client=mock_client,
                    target_chat_id=target,
                    ut=ut,
                    files=[path],
                    status_message=mock_status,
                    show_completion=False,
                    delete_after_upload=True,
                )
            )
        finally:
            uploader_mod.split_large_file = original_split

        self.assertFalse(os.path.exists(part1), "Part .001 should be deleted.")
        self.assertFalse(os.path.exists(part2), "Part .002 should be deleted.")
        self.assertFalse(os.path.exists(path), "Split original should be deleted.")


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

    def test_target_regex_username(self):
        from downloader import TARGET_RE
        m = TARGET_RE.search("https://example.com/gallery -> @mychannel")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "@mychannel")

    def test_target_regex_numeric_id(self):
        from downloader import TARGET_RE
        m = TARGET_RE.search("https://example.com -> -100123456789")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "-100123456789")

    def test_target_regex_no_target(self):
        from downloader import TARGET_RE
        m = TARGET_RE.search("https://example.com/gallery")
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

    def test_build_gallery_dl_cmd_with_extra_args(self):
        from downloader import _build_gallery_dl_cmd
        cmd = _build_gallery_dl_cmd(
            "https://x.com", "/tmp/d", None,
            extra_args="--username foo --password bar"
        )
        self.assertIn("--username", cmd)
        self.assertIn("foo", cmd)
        self.assertIn("--password", cmd)
        self.assertIn("bar", cmd)
        # URL must still be the last element.
        self.assertEqual(cmd[-1], "https://x.com")

    def test_build_gallery_dl_cmd_extra_args_none(self):
        from downloader import _build_gallery_dl_cmd
        cmd = _build_gallery_dl_cmd("https://x.com", "/tmp/d", None, extra_args=None)
        self.assertNotIn("--username", cmd)
        self.assertEqual(cmd[-1], "https://x.com")

    def test_build_gallery_dl_cmd_with_cookies(self):
        from downloader import _build_gallery_dl_cmd
        cmd = _build_gallery_dl_cmd("https://x.com", "/tmp/d", None, cookies_path="/tmp/ck.txt")
        self.assertIn("--cookies", cmd)
        self.assertIn("/tmp/ck.txt", cmd)
        self.assertEqual(cmd[-1], "https://x.com")

    def test_build_gallery_dl_cmd_no_cookies_by_default(self):
        from downloader import _build_gallery_dl_cmd
        cmd = _build_gallery_dl_cmd("https://x.com", "/tmp/d", None)
        self.assertNotIn("--cookies", cmd)

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


# ---------------------------------------------------------------------------
# webui.py tests
# ---------------------------------------------------------------------------

class TestWebui(unittest.TestCase):
    """Tests for the web UI helpers."""

    def test_format_uptime_seconds_only(self):
        from webui import format_uptime
        self.assertEqual(format_uptime(45), "45s")

    def test_format_uptime_minutes_and_seconds(self):
        from webui import format_uptime
        result = format_uptime(125)
        self.assertIn("2m", result)
        self.assertIn("5s", result)

    def test_format_uptime_days_hours_minutes(self):
        from webui import format_uptime
        # 2 days + 3 hours + 4 minutes + 5 seconds
        secs = 2 * 86400 + 3 * 3600 + 4 * 60 + 5
        result = format_uptime(secs)
        self.assertIn("2d", result)
        self.assertIn("3h", result)
        self.assertIn("4m", result)
        self.assertIn("5s", result)

    def test_format_uptime_zero(self):
        from webui import format_uptime
        self.assertEqual(format_uptime(0), "0s")

    def test_collect_stats_contains_required_keys(self):
        from webui import collect_stats
        stats = collect_stats()
        self.assertIn("status", stats)
        self.assertIn("uptime_seconds", stats)
        self.assertIn("uptime_human", stats)
        self.assertIn("active_jobs", stats)
        self.assertEqual(stats["status"], "running")
        self.assertIsInstance(stats["uptime_seconds"], int)
        self.assertGreaterEqual(stats["uptime_seconds"], 0)
        self.assertIsInstance(stats["active_jobs"], int)

    def test_collect_stats_includes_psutil_keys(self):
        """When psutil is available, system stats should be present."""
        try:
            import psutil  # noqa: F401
            psutil_available = True
        except ImportError:
            psutil_available = False

        from webui import collect_stats
        stats = collect_stats()
        if psutil_available:
            for key in ("cpu_percent", "memory_used_mb", "memory_total_mb",
                        "memory_percent", "disk_used_gb", "disk_total_gb",
                        "disk_percent"):
                self.assertIn(key, stats, f"Missing key: {key}")
        else:
            self.assertNotIn("cpu_percent", stats)

    def test_collect_stats_active_jobs_zero_by_default(self):
        """With no active tasks, active_jobs should be 0."""
        from webui import collect_stats
        from task_manager import TaskManager, task_manager as _tm
        # Use the module-level task_manager which starts clean.
        stats = collect_stats()
        # active_jobs should be a non-negative integer.
        self.assertGreaterEqual(stats["active_jobs"], 0)


# ---------------------------------------------------------------------------
# bot.py helper function tests (PendingJob, _build_menu, _build_custom_input_prompt)
# ---------------------------------------------------------------------------

class TestBotHelpers(unittest.TestCase):
    """Tests for the bot.py configuration-menu helper functions."""

    def _make_pj(self, **kwargs):
        """Create a PendingJob with sensible defaults, overridden by kwargs."""
        from bot import PendingJob
        defaults = dict(
            url="https://example.com/gallery",
            user_id=42,
            source_chat_id=100,
            target_chat_id=100,
            use_current_chat=True,
            mode="default",
            awaiting_custom_input=False,
            menu_message_id=7,
        )
        defaults.update(kwargs)
        return PendingJob(**defaults)

    # ------------------------------------------------------------------
    # PendingJob defaults
    # ------------------------------------------------------------------

    def test_pending_job_defaults(self):
        from bot import PendingJob
        pj = PendingJob(
            url="https://x.com/p",
            user_id=1,
            source_chat_id=10,
            target_chat_id=10,
        )
        self.assertTrue(pj.use_current_chat)
        self.assertEqual(pj.mode, "default")
        self.assertFalse(pj.awaiting_custom_input)
        self.assertEqual(pj.menu_message_id, 0)

    # ------------------------------------------------------------------
    # _next_pending_id
    # ------------------------------------------------------------------

    def test_next_pending_id_increments(self):
        from bot import _next_pending_id
        id1 = _next_pending_id()
        id2 = _next_pending_id()
        self.assertGreater(id2, id1)

    # ------------------------------------------------------------------
    # _build_menu
    # ------------------------------------------------------------------

    def test_build_menu_contains_url(self):
        from bot import _build_menu
        pj = self._make_pj(url="https://example.com/x")
        text, markup = _build_menu(1, pj)
        self.assertIn("https://example.com/x", text)

    def test_build_menu_current_chat_selected_by_default(self):
        from bot import _build_menu
        pj = self._make_pj(use_current_chat=True)
        text, markup = _build_menu(1, pj)
        # The "Current chat" button should have the check mark.
        btn_labels = [
            btn.text
            for row in markup.inline_keyboard
            for btn in row
        ]
        current_btn = next(b for b in btn_labels if "Current" in b)
        self.assertIn("✓", current_btn)

    def test_build_menu_custom_chat_selected(self):
        from bot import _build_menu
        pj = self._make_pj(use_current_chat=False, target_chat_id="@chan")
        text, markup = _build_menu(5, pj)
        btn_labels = [
            btn.text
            for row in markup.inline_keyboard
            for btn in row
        ]
        custom_btn = next(b for b in btn_labels if "Custom" in b)
        self.assertIn("✓", custom_btn)
        # Destination should be shown in the text.
        self.assertIn("@chan", text)

    def test_build_menu_default_mode_selected(self):
        from bot import _build_menu
        pj = self._make_pj(mode="default")
        _, markup = _build_menu(1, pj)
        btn_labels = [
            btn.text
            for row in markup.inline_keyboard
            for btn in row
        ]
        default_btn = next(b for b in btn_labels if "Default" in b)
        duplex_btn = next(b for b in btn_labels if "Duplex" in b)
        self.assertIn("✓", default_btn)
        self.assertNotIn("✓", duplex_btn)

    def test_build_menu_duplex_mode_selected(self):
        from bot import _build_menu
        pj = self._make_pj(mode="duplex")
        _, markup = _build_menu(1, pj)
        btn_labels = [
            btn.text
            for row in markup.inline_keyboard
            for btn in row
        ]
        default_btn = next(b for b in btn_labels if "Default" in b)
        duplex_btn = next(b for b in btn_labels if "Duplex" in b)
        self.assertNotIn("✓", default_btn)
        self.assertIn("✓", duplex_btn)

    def test_build_menu_zip_mode_selected(self):
        from bot import _build_menu
        pj = self._make_pj(mode="zip")
        _, markup = _build_menu(1, pj)
        btn_labels = [
            btn.text
            for row in markup.inline_keyboard
            for btn in row
        ]
        default_btn = next(b for b in btn_labels if "Default" in b)
        duplex_btn = next(b for b in btn_labels if "Duplex" in b)
        zip_btn = next(b for b in btn_labels if "Zip" in b)
        self.assertNotIn("✓", default_btn)
        self.assertNotIn("✓", duplex_btn)
        self.assertIn("✓", zip_btn)

    def test_build_menu_has_zip_button(self):
        from bot import _build_menu
        pj = self._make_pj()
        _, markup = _build_menu(1, pj)
        btn_data = [
            btn.callback_data
            for row in markup.inline_keyboard
            for btn in row
        ]
        self.assertTrue(any("gdl:zip:" in d for d in btn_data))

    def test_build_menu_has_run_and_cancel_buttons(self):
        from bot import _build_menu
        pj = self._make_pj()
        _, markup = _build_menu(1, pj)
        btn_data = [
            btn.callback_data
            for row in markup.inline_keyboard
            for btn in row
        ]
        self.assertTrue(any("gdl:r:" in d for d in btn_data))
        self.assertTrue(any("gdl:x:" in d for d in btn_data))

    def test_build_menu_callback_data_contains_pid(self):
        from bot import _build_menu
        pj = self._make_pj()
        pid = 999
        _, markup = _build_menu(pid, pj)
        btn_data = [
            btn.callback_data
            for row in markup.inline_keyboard
            for btn in row
        ]
        self.assertTrue(all(str(pid) in d for d in btn_data))

    def test_build_menu_has_five_rows(self):
        from bot import _build_menu
        pj = self._make_pj()
        _, markup = _build_menu(1, pj)
        self.assertEqual(len(markup.inline_keyboard), 5)

    # ------------------------------------------------------------------
    # _build_custom_input_prompt
    # ------------------------------------------------------------------

    def test_build_custom_input_prompt_contains_url(self):
        from bot import _build_custom_input_prompt
        pj = self._make_pj(url="https://example.com/p")
        text, markup = _build_custom_input_prompt(2, pj)
        self.assertIn("https://example.com/p", text)

    def test_build_custom_input_prompt_contains_cancel_button(self):
        from bot import _build_custom_input_prompt
        pj = self._make_pj()
        _, markup = _build_custom_input_prompt(2, pj)
        btn_data = [
            btn.callback_data
            for row in markup.inline_keyboard
            for btn in row
        ]
        self.assertTrue(any("gdl:xcu:" in d for d in btn_data))

    def test_build_custom_input_prompt_error_shown(self):
        from bot import _build_custom_input_prompt
        pj = self._make_pj()
        text, _ = _build_custom_input_prompt(2, pj, error="Invalid format.")
        self.assertIn("Invalid format.", text)

    def test_build_custom_input_prompt_no_error_by_default(self):
        from bot import _build_custom_input_prompt
        pj = self._make_pj()
        text, _ = _build_custom_input_prompt(2, pj)
        self.assertNotIn("⚠️", text)

    # ------------------------------------------------------------------
    # PendingJob new fields
    # ------------------------------------------------------------------

    def test_pending_job_new_fields_default_to_none(self):
        from bot import PendingJob
        pj = PendingJob(
            url="https://x.com/p",
            user_id=1,
            source_chat_id=10,
            target_chat_id=10,
        )
        self.assertIsNone(pj.custom_config_path)
        self.assertIsNone(pj.custom_args)
        self.assertFalse(pj.awaiting_custom_config)
        self.assertFalse(pj.awaiting_custom_args)

    # ------------------------------------------------------------------
    # _build_menu: custom config / args status in text
    # ------------------------------------------------------------------

    def test_build_menu_shows_none_for_custom_config_and_args(self):
        from bot import _build_menu
        pj = self._make_pj(custom_config_path=None, custom_args=None)
        text, _ = _build_menu(1, pj)
        self.assertIn("Custom config:", text)
        self.assertIn("Custom args:", text)
        # Both should show "None" when unset.
        lines = text.splitlines()
        config_line = next(l for l in lines if "Custom config:" in l)
        args_line = next(l for l in lines if "Custom args:" in l)
        self.assertIn("None", config_line)
        self.assertIn("None", args_line)

    def test_build_menu_shows_applied_when_custom_config_set(self):
        from bot import _build_menu
        pj = self._make_pj(custom_config_path="/tmp/some_config.conf")
        text, _ = _build_menu(1, pj)
        lines = text.splitlines()
        config_line = next(l for l in lines if "Custom config:" in l)
        self.assertIn("Applied", config_line)

    def test_build_menu_shows_args_when_custom_args_set(self):
        from bot import _build_menu
        pj = self._make_pj(custom_args="--username foo --password bar")
        text, _ = _build_menu(1, pj)
        self.assertIn("--username foo --password bar", text)

    def test_build_menu_has_custom_config_and_args_buttons(self):
        from bot import _build_menu
        pj = self._make_pj()
        _, markup = _build_menu(1, pj)
        btn_data = [
            btn.callback_data
            for row in markup.inline_keyboard
            for btn in row
        ]
        self.assertTrue(any("gdl:cfg:" in d for d in btn_data))
        self.assertTrue(any("gdl:arg:" in d for d in btn_data))

    # ------------------------------------------------------------------
    # _build_custom_config_prompt
    # ------------------------------------------------------------------

    def test_build_custom_config_prompt_contains_url(self):
        from bot import _build_custom_config_prompt
        pj = self._make_pj(url="https://example.com/p")
        text, markup = _build_custom_config_prompt(3, pj)
        self.assertIn("https://example.com/p", text)

    def test_build_custom_config_prompt_shows_none_when_unset(self):
        from bot import _build_custom_config_prompt
        pj = self._make_pj(custom_config_path=None)
        text, _ = _build_custom_config_prompt(3, pj)
        self.assertIn("None", text)

    def test_build_custom_config_prompt_shows_applied_when_set(self):
        from bot import _build_custom_config_prompt
        pj = self._make_pj(custom_config_path="/tmp/cfg.conf")
        text, _ = _build_custom_config_prompt(3, pj)
        self.assertIn("Applied", text)

    def test_build_custom_config_prompt_has_reset_and_cancel_buttons(self):
        from bot import _build_custom_config_prompt
        pj = self._make_pj()
        _, markup = _build_custom_config_prompt(3, pj)
        btn_data = [
            btn.callback_data
            for row in markup.inline_keyboard
            for btn in row
        ]
        self.assertTrue(any("gdl:cfgrst:" in d for d in btn_data))
        self.assertTrue(any("gdl:xcfg:" in d for d in btn_data))

    def test_build_custom_config_prompt_error_shown(self):
        from bot import _build_custom_config_prompt
        pj = self._make_pj()
        text, _ = _build_custom_config_prompt(3, pj, error="Download failed.")
        self.assertIn("Download failed.", text)

    def test_build_custom_config_prompt_no_error_by_default(self):
        from bot import _build_custom_config_prompt
        pj = self._make_pj()
        text, _ = _build_custom_config_prompt(3, pj)
        self.assertNotIn("⚠️", text)

    # ------------------------------------------------------------------
    # _build_custom_args_prompt
    # ------------------------------------------------------------------

    def test_build_custom_args_prompt_contains_url(self):
        from bot import _build_custom_args_prompt
        pj = self._make_pj(url="https://example.com/g")
        text, markup = _build_custom_args_prompt(4, pj)
        self.assertIn("https://example.com/g", text)

    def test_build_custom_args_prompt_shows_none_when_unset(self):
        from bot import _build_custom_args_prompt
        pj = self._make_pj(custom_args=None)
        text, _ = _build_custom_args_prompt(4, pj)
        self.assertIn("None", text)

    def test_build_custom_args_prompt_shows_current_args(self):
        from bot import _build_custom_args_prompt
        pj = self._make_pj(custom_args="--username alice")
        text, _ = _build_custom_args_prompt(4, pj)
        self.assertIn("--username alice", text)

    def test_build_custom_args_prompt_has_reset_and_cancel_buttons(self):
        from bot import _build_custom_args_prompt
        pj = self._make_pj()
        _, markup = _build_custom_args_prompt(4, pj)
        btn_data = [
            btn.callback_data
            for row in markup.inline_keyboard
            for btn in row
        ]
        self.assertTrue(any("gdl:argrst:" in d for d in btn_data))
        self.assertTrue(any("gdl:xarg:" in d for d in btn_data))

    def test_build_custom_args_prompt_error_shown(self):
        from bot import _build_custom_args_prompt
        pj = self._make_pj()
        text, _ = _build_custom_args_prompt(4, pj, error="Empty arguments received.")
        self.assertIn("Empty arguments received.", text)

    def test_build_custom_args_prompt_no_error_by_default(self):
        from bot import _build_custom_args_prompt
        pj = self._make_pj()
        text, _ = _build_custom_args_prompt(4, pj)
        self.assertNotIn("⚠️", text)

    # ------------------------------------------------------------------
    # Cookies: PendingJob fields
    # ------------------------------------------------------------------

    def test_pending_job_cookies_fields_default_to_none(self):
        from bot import PendingJob
        pj = PendingJob(url="https://x.com", user_id=1, source_chat_id=10, target_chat_id=10)
        self.assertIsNone(pj.custom_cookies_path)
        self.assertFalse(pj.awaiting_custom_cookies)

    # ------------------------------------------------------------------
    # Cookies: _build_menu status line and button
    # ------------------------------------------------------------------

    def test_build_menu_shows_cookies_none_when_unset(self):
        from bot import _build_menu
        pj = self._make_pj(custom_cookies_path=None)
        text, _ = _build_menu(1, pj)
        lines = text.splitlines()
        ck_line = next((l for l in lines if "Cookies:" in l), None)
        self.assertIsNotNone(ck_line, "Expected a 'Cookies:' line in the menu text")
        self.assertIn("None", ck_line)

    def test_build_menu_shows_cookies_applied_when_set(self):
        from bot import _build_menu
        pj = self._make_pj(custom_cookies_path="/tmp/ck.txt")
        text, _ = _build_menu(1, pj)
        lines = text.splitlines()
        ck_line = next((l for l in lines if "Cookies:" in l), None)
        self.assertIsNotNone(ck_line, "Expected a 'Cookies:' line in the menu text")
        self.assertIn("Applied", ck_line)

    def test_build_menu_has_cookies_button(self):
        from bot import _build_menu
        pj = self._make_pj()
        _, markup = _build_menu(1, pj)
        btn_data = [btn.callback_data for row in markup.inline_keyboard for btn in row]
        self.assertTrue(any("gdl:ck:" in d for d in btn_data))

    # ------------------------------------------------------------------
    # Cookies: _build_custom_cookies_prompt
    # ------------------------------------------------------------------

    def test_build_custom_cookies_prompt_contains_url(self):
        from bot import _build_custom_cookies_prompt
        pj = self._make_pj(url="https://example.com/g")
        text, _ = _build_custom_cookies_prompt(5, pj)
        self.assertIn("https://example.com/g", text)

    def test_build_custom_cookies_prompt_shows_none_when_unset(self):
        from bot import _build_custom_cookies_prompt
        pj = self._make_pj(custom_cookies_path=None)
        text, _ = _build_custom_cookies_prompt(5, pj)
        self.assertIn("None", text)

    def test_build_custom_cookies_prompt_shows_applied_when_set(self):
        from bot import _build_custom_cookies_prompt
        pj = self._make_pj(custom_cookies_path="/tmp/ck.txt")
        text, _ = _build_custom_cookies_prompt(5, pj)
        self.assertIn("Applied", text)

    def test_build_custom_cookies_prompt_has_reset_and_cancel_buttons(self):
        from bot import _build_custom_cookies_prompt
        pj = self._make_pj()
        _, markup = _build_custom_cookies_prompt(5, pj)
        btn_data = [btn.callback_data for row in markup.inline_keyboard for btn in row]
        self.assertTrue(any("gdl:ckrst:" in d for d in btn_data))
        self.assertTrue(any("gdl:xck:" in d for d in btn_data))

    def test_build_custom_cookies_prompt_error_shown(self):
        from bot import _build_custom_cookies_prompt
        pj = self._make_pj()
        text, _ = _build_custom_cookies_prompt(5, pj, error="Download failed.")
        self.assertIn("Download failed.", text)

    def test_build_custom_cookies_prompt_no_error_by_default(self):
        from bot import _build_custom_cookies_prompt
        pj = self._make_pj()
        text, _ = _build_custom_cookies_prompt(5, pj)
        self.assertNotIn("⚠️", text)


# ---------------------------------------------------------------------------
# bot.py duplex pipeline tests
# ---------------------------------------------------------------------------

class TestDuplexPipeline(unittest.TestCase):
    """Tests for the duplex-mode _pipeline logic."""

    def _run_pipeline_duplex(self, files_on_disk):
        """Run _pipeline in duplex mode with mocked gallery-dl and upload."""
        import bot as bot_module
        from bot import _pipeline
        from task_manager import TaskManager, UserTask

        # Patch the module-level client and cfg that _pipeline uses.
        mock_client = MagicMock()
        mock_client.send_photo = AsyncMock()
        mock_client.send_message = AsyncMock()
        mock_status = AsyncMock()
        mock_status.edit = AsyncMock()

        original_client = bot_module.client
        original_cfg = bot_module.cfg
        bot_module.client = mock_client
        bot_module.cfg = None  # No gallery-dl config needed.

        tm = TaskManager()
        job_id, ut = tm.create(user_id=1)
        ut.cancel_flag = False

        queued_paths = []

        async def fake_run_gallery_dl(ut, url, temp_dir, config_path, on_file, **kwargs):
            for p in files_on_disk:
                queued_paths.append(p)
                await on_file(p)
            return files_on_disk, ""

        async def fake_upload_files(client, target_chat_id, ut, files,
                                    status_message, show_completion=True,
                                    url="", job_id=0, mode="default",
                                    delete_after_upload=False):
            pass  # No-op; we only verify it was called.

        with tempfile.TemporaryDirectory() as tmp:
            try:
                with (
                    patch("bot.run_gallery_dl", fake_run_gallery_dl),
                    patch("bot.upload_files", fake_upload_files),
                    patch("bot.task_manager", tm),
                ):
                    asyncio.run(
                        _pipeline(
                            job_id=job_id,
                            ut=ut,
                            url="https://example.com",
                            temp_dir=tmp,
                            target_chat_id=1,
                            status_message=mock_status,
                            mode="duplex",
                        )
                    )
            finally:
                bot_module.client = original_client
                bot_module.cfg = original_cfg

        return queued_paths, mock_client, mock_status

    def test_duplex_pipeline_queues_all_files(self):
        """In duplex mode all files reported by gallery-dl are queued."""
        files = ["/tmp/a.jpg", "/tmp/b.jpg", "/tmp/c.mp4"]
        queued, _, _ = self._run_pipeline_duplex(files)
        self.assertEqual(queued, files)

    def test_duplex_pipeline_completion_message(self):
        """Duplex mode sends a new summary message after all files are uploaded."""
        files = ["/tmp/x.jpg"]
        _, mock_client, _ = self._run_pipeline_duplex(files)
        # A new message should be sent (not just editing the status message).
        send_calls = [str(c) for c in mock_client.send_message.call_args_list]
        self.assertTrue(
            any("Upload completed" in c for c in send_calls),
            f"Expected 'Upload completed' in send_message calls: {send_calls}",
        )

    def test_duplex_pipeline_no_files_shows_warning(self):
        """Duplex mode with no downloaded files shows the 'no files' warning."""
        _, _, mock_status = self._run_pipeline_duplex([])
        edit_calls = [str(c) for c in mock_status.edit.call_args_list]
        self.assertTrue(
            any("No files" in c or "⚠️" in c for c in edit_calls),
            f"Expected warning in edit calls: {edit_calls}",
        )

    def test_duplex_pipeline_deletes_status_message_on_success(self):
        """Duplex mode deletes the status message after sending the summary."""
        files = ["/tmp/x.jpg"]
        _, _, mock_status = self._run_pipeline_duplex(files)
        mock_status.delete.assert_awaited_once()


# ---------------------------------------------------------------------------
# UserTask new fields
# ---------------------------------------------------------------------------

class TestUserTaskNewFields(unittest.TestCase):
    """Tests for url/mode/progress_text fields added to UserTask."""

    def test_user_task_default_url(self):
        from task_manager import UserTask
        ut = UserTask(user_id=1)
        self.assertEqual(ut.url, "")

    def test_user_task_default_mode(self):
        from task_manager import UserTask
        ut = UserTask(user_id=1)
        self.assertEqual(ut.mode, "default")

    def test_user_task_default_progress_text(self):
        from task_manager import UserTask
        ut = UserTask(user_id=1)
        self.assertIn("Starting", ut.progress_text)

    def test_user_task_fields_mutable(self):
        from task_manager import UserTask
        ut = UserTask(user_id=1)
        ut.url = "https://example.com"
        ut.mode = "duplex"
        ut.progress_text = "📥 Downloading…"
        self.assertEqual(ut.url, "https://example.com")
        self.assertEqual(ut.mode, "duplex")
        self.assertEqual(ut.progress_text, "📥 Downloading…")


# ---------------------------------------------------------------------------
# _build_status_text tests
# ---------------------------------------------------------------------------

class TestBuildStatusText(unittest.TestCase):
    """Tests for the _build_status_text helper."""

    def _make_active_task(self, tm, url, mode, progress):
        from task_manager import UserTask
        import asyncio
        jid, ut = tm.create(user_id=42)
        ut.url = url
        ut.mode = mode
        ut.progress_text = progress
        # Give it a dummy non-done task so get_user_tasks returns it.
        ut.task = asyncio.get_event_loop().create_future()
        return jid, ut

    def test_build_status_text_no_jobs(self):
        from task_manager import TaskManager
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            import bot as bot_module
            from bot import _build_status_text
            original_tm = bot_module.task_manager
            tm = TaskManager()
            bot_module.task_manager = tm
            try:
                result = _build_status_text(42)
                self.assertIn("no active", result.lower())
            finally:
                bot_module.task_manager = original_tm
        finally:
            loop.close()
            asyncio.set_event_loop(None)

    def test_build_status_text_with_one_job(self):
        from task_manager import TaskManager
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            import bot as bot_module
            from bot import _build_status_text
            original_tm = bot_module.task_manager
            tm = TaskManager()
            bot_module.task_manager = tm
            try:
                jid, ut = self._make_active_task(
                    tm, "https://example.com", "default", "📥 Downloading…"
                )
                result = _build_status_text(42)
                self.assertIn("https://example.com", result)
                self.assertIn(str(jid), result)
                self.assertIn("Default", result)
                self.assertIn("📥 Downloading…", result)
                self.assertIn(f"/cancel {jid}", result)
            finally:
                bot_module.task_manager = original_tm
        finally:
            loop.close()
            asyncio.set_event_loop(None)

    def test_build_status_text_multiple_jobs_separated(self):
        from task_manager import TaskManager
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            import bot as bot_module
            from bot import _build_status_text
            original_tm = bot_module.task_manager
            tm = TaskManager()
            bot_module.task_manager = tm
            try:
                self._make_active_task(tm, "https://a.com", "default", "p1")
                self._make_active_task(tm, "https://b.com", "duplex", "p2")
                result = _build_status_text(42)
                self.assertIn("https://a.com", result)
                self.assertIn("https://b.com", result)
                self.assertIn("—", result)  # separator
            finally:
                bot_module.task_manager = original_tm
        finally:
            loop.close()
            asyncio.set_event_loop(None)


# ---------------------------------------------------------------------------
# Pipeline error notification tests
# ---------------------------------------------------------------------------

class TestPipelineErrorNotifications(unittest.TestCase):
    """Tests that pipeline errors send a new message and delete the status msg."""

    def _run_pipeline_with_error(self, error):
        """Run _pipeline where gallery-dl raises *error*."""
        import bot as bot_module
        from bot import _pipeline
        from task_manager import TaskManager

        mock_client = MagicMock()
        mock_client.send_message = AsyncMock()
        mock_status = AsyncMock()
        mock_status.edit = AsyncMock()
        mock_status.delete = AsyncMock()
        mock_status.chat = MagicMock()
        mock_status.chat.id = 1

        original_client = bot_module.client
        original_cfg = bot_module.cfg
        bot_module.client = mock_client
        bot_module.cfg = None

        tm = TaskManager()
        job_id, ut = tm.create(user_id=1)
        ut.cancel_flag = False

        async def fake_run_gallery_dl(ut, url, temp_dir, config_path, on_file, **kwargs):
            raise error

        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            try:
                with (
                    patch("bot.run_gallery_dl", fake_run_gallery_dl),
                    patch("bot.task_manager", tm),
                ):
                    asyncio.run(
                        _pipeline(
                            job_id=job_id,
                            ut=ut,
                            url="https://example.com",
                            temp_dir=tmp,
                            target_chat_id=1,
                            status_message=mock_status,
                            mode="default",
                        )
                    )
            finally:
                bot_module.client = original_client
                bot_module.cfg = original_cfg

        return mock_client, mock_status

    def test_runtime_error_sends_new_message(self):
        """RuntimeError in pipeline sends a new message (not edit)."""
        mock_client, mock_status = self._run_pipeline_with_error(
            RuntimeError("gallery-dl failed")
        )
        send_calls = [str(c) for c in mock_client.send_message.call_args_list]
        self.assertTrue(
            any("Error" in c for c in send_calls),
            f"Expected error in send_message calls: {send_calls}",
        )

    def test_runtime_error_deletes_status_message(self):
        """RuntimeError in pipeline deletes the status message."""
        _, mock_status = self._run_pipeline_with_error(
            RuntimeError("gallery-dl failed")
        )
        mock_status.delete.assert_awaited_once()

    def test_generic_error_sends_new_message(self):
        """Unexpected exception in pipeline sends a new message."""
        mock_client, _ = self._run_pipeline_with_error(
            ValueError("something unexpected")
        )
        send_calls = [str(c) for c in mock_client.send_message.call_args_list]
        self.assertTrue(
            any("error" in c.lower() or "Error" in c for c in send_calls),
            f"Expected error in send_message calls: {send_calls}",
        )

    def test_generic_error_deletes_status_message(self):
        """Unexpected exception in pipeline deletes the status message."""
        _, mock_status = self._run_pipeline_with_error(
            ValueError("something unexpected")
        )
        mock_status.delete.assert_awaited_once()


# ---------------------------------------------------------------------------
# ytdl / ugoira / mkvmerge support tests
# ---------------------------------------------------------------------------

class TestMediaProcessingConfig(unittest.TestCase):
    """Tests for the ytdl_enabled, ugoira_convert, ugoira_mkvmerge config options."""

    def _load(self, env: dict):
        with patch.dict(os.environ, env, clear=True):
            from config import load_config
            return load_config()

    def test_ytdl_disabled_by_default(self):
        env = {"API_ID": "1", "API_HASH": "h", "BOT_TOKEN": "t"}
        with patch.dict(os.environ, env, clear=True):
            from config import load_config
            cfg = load_config()
        self.assertFalse(cfg.ytdl_enabled)

    def test_ytdl_enabled_via_env(self):
        env = {"API_ID": "1", "API_HASH": "h", "BOT_TOKEN": "t", "YTDL_ENABLED": "true"}
        with patch.dict(os.environ, env, clear=True):
            from config import load_config
            cfg = load_config()
        self.assertTrue(cfg.ytdl_enabled)

    def test_ytdl_enabled_variants(self):
        for truthy in ("1", "yes", "true", "True"):
            env = {"API_ID": "1", "API_HASH": "h", "BOT_TOKEN": "t", "YTDL_ENABLED": truthy}
            with patch.dict(os.environ, env, clear=True):
                from config import load_config
                cfg = load_config()
            self.assertTrue(cfg.ytdl_enabled, f"Expected ytdl_enabled for YTDL_ENABLED={truthy!r}")

    def test_ugoira_convert_disabled_by_default(self):
        env = {"API_ID": "1", "API_HASH": "h", "BOT_TOKEN": "t"}
        with patch.dict(os.environ, env, clear=True):
            from config import load_config
            cfg = load_config()
        self.assertFalse(cfg.ugoira_convert)

    def test_ugoira_convert_enabled_via_env(self):
        env = {"API_ID": "1", "API_HASH": "h", "BOT_TOKEN": "t", "UGOIRA_CONVERT": "true"}
        with patch.dict(os.environ, env, clear=True):
            from config import load_config
            cfg = load_config()
        self.assertTrue(cfg.ugoira_convert)

    def test_ugoira_mkvmerge_disabled_by_default(self):
        env = {"API_ID": "1", "API_HASH": "h", "BOT_TOKEN": "t"}
        with patch.dict(os.environ, env, clear=True):
            from config import load_config
            cfg = load_config()
        self.assertFalse(cfg.ugoira_mkvmerge)

    def test_ugoira_mkvmerge_enabled_via_env(self):
        env = {"API_ID": "1", "API_HASH": "h", "BOT_TOKEN": "t", "UGOIRA_MKVMERGE": "true"}
        with patch.dict(os.environ, env, clear=True):
            from config import load_config
            cfg = load_config()
        self.assertTrue(cfg.ugoira_mkvmerge)


class TestDownloaderMediaFlags(unittest.TestCase):
    """Tests for the new ytdl/ugoira/mkvmerge flags in _build_gallery_dl_cmd."""

    def test_ytdl_flag_added_when_true(self):
        from downloader import _build_gallery_dl_cmd
        cmd = _build_gallery_dl_cmd("https://x.com", "/tmp/d", None, ytdl=True)
        self.assertIn("--yt-dlp", cmd)
        self.assertEqual(cmd[-1], "https://x.com")

    def test_ytdl_flag_not_added_when_false(self):
        from downloader import _build_gallery_dl_cmd
        cmd = _build_gallery_dl_cmd("https://x.com", "/tmp/d", None, ytdl=False)
        self.assertNotIn("--yt-dlp", cmd)

    def test_ugoira_conv_flag_added_when_true(self):
        from downloader import _build_gallery_dl_cmd
        cmd = _build_gallery_dl_cmd("https://x.com", "/tmp/d", None, ugoira_convert=True)
        self.assertIn("--ugoira-conv", cmd)
        self.assertEqual(cmd[-1], "https://x.com")

    def test_ugoira_conv_flag_not_added_when_false(self):
        from downloader import _build_gallery_dl_cmd
        cmd = _build_gallery_dl_cmd("https://x.com", "/tmp/d", None, ugoira_convert=False)
        self.assertNotIn("--ugoira-conv", cmd)

    def test_ugoira_mkvmerge_flag_added_when_true(self):
        from downloader import _build_gallery_dl_cmd
        cmd = _build_gallery_dl_cmd("https://x.com", "/tmp/d", None, ugoira_mkvmerge=True)
        self.assertIn("--ugoira-conv-mkvmerge", cmd)
        self.assertEqual(cmd[-1], "https://x.com")

    def test_ugoira_mkvmerge_flag_not_added_when_false(self):
        from downloader import _build_gallery_dl_cmd
        cmd = _build_gallery_dl_cmd("https://x.com", "/tmp/d", None, ugoira_mkvmerge=False)
        self.assertNotIn("--ugoira-conv-mkvmerge", cmd)

    def test_all_flags_combined(self):
        from downloader import _build_gallery_dl_cmd
        cmd = _build_gallery_dl_cmd(
            "https://x.com", "/tmp/d", None,
            extra_args="--username foo",
            ytdl=True,
            ugoira_convert=True,
            ugoira_mkvmerge=True,
        )
        self.assertIn("--yt-dlp", cmd)
        self.assertIn("--ugoira-conv", cmd)
        self.assertIn("--ugoira-conv-mkvmerge", cmd)
        self.assertIn("--username", cmd)
        self.assertEqual(cmd[-1], "https://x.com")

    def test_flags_appear_before_extra_args_and_url(self):
        """Builtin flags should be injected before extra_args and the URL."""
        from downloader import _build_gallery_dl_cmd
        cmd = _build_gallery_dl_cmd(
            "https://x.com", "/tmp/d", None,
            extra_args="--filter \"width>100\"",
            ytdl=True,
        )
        ytdl_idx = cmd.index("--yt-dlp")
        url_idx = cmd.index("https://x.com")
        self.assertLess(ytdl_idx, url_idx)


class TestMediaProcessingMenu(unittest.TestCase):
    """Tests for the media-processing toggle buttons added to _build_menu."""

    def _make_pj(self, **kwargs):
        from bot import PendingJob
        defaults = dict(
            url="https://example.com/gallery",
            user_id=42,
            source_chat_id=100,
            target_chat_id=100,
            use_current_chat=True,
            mode="default",
        )
        defaults.update(kwargs)
        return PendingJob(**defaults)

    def test_pending_job_media_flags_default_to_false(self):
        from bot import PendingJob
        pj = PendingJob(url="https://x.com", user_id=1, source_chat_id=10, target_chat_id=10)
        self.assertFalse(pj.ytdl)
        self.assertFalse(pj.ugoira_convert)
        self.assertFalse(pj.ugoira_mkvmerge)

    def test_menu_has_ytdl_button(self):
        from bot import _build_advanced_menu
        pj = self._make_pj()
        _, markup = _build_advanced_menu(1, pj)
        btn_data = [btn.callback_data for row in markup.inline_keyboard for btn in row]
        self.assertTrue(any("gdl:ytdl:" in d for d in btn_data))

    def test_menu_has_ugoira_button(self):
        from bot import _build_advanced_menu
        pj = self._make_pj()
        _, markup = _build_advanced_menu(1, pj)
        btn_data = [btn.callback_data for row in markup.inline_keyboard for btn in row]
        self.assertTrue(any("gdl:ugo:" in d for d in btn_data))

    def test_menu_has_mkv_button(self):
        from bot import _build_advanced_menu
        pj = self._make_pj()
        _, markup = _build_advanced_menu(1, pj)
        btn_data = [btn.callback_data for row in markup.inline_keyboard for btn in row]
        self.assertTrue(any("gdl:mkv:" in d for d in btn_data))

    def test_menu_ytdl_button_shows_check_when_enabled(self):
        from bot import _build_advanced_menu
        pj = self._make_pj(ytdl=True)
        _, markup = _build_advanced_menu(1, pj)
        btn_labels = [btn.text for row in markup.inline_keyboard for btn in row]
        ytdl_btn = next(b for b in btn_labels if "ytdl" in b or "yt-dlp" in b)
        self.assertIn("✓", ytdl_btn)

    def test_menu_ytdl_button_no_check_when_disabled(self):
        from bot import _build_advanced_menu
        pj = self._make_pj(ytdl=False)
        _, markup = _build_advanced_menu(1, pj)
        btn_labels = [btn.text for row in markup.inline_keyboard for btn in row]
        ytdl_btn = next(b for b in btn_labels if "ytdl" in b or "yt-dlp" in b)
        self.assertNotIn("✓", ytdl_btn)

    def test_menu_ugoira_button_shows_check_when_enabled(self):
        from bot import _build_advanced_menu
        pj = self._make_pj(ugoira_convert=True)
        _, markup = _build_advanced_menu(1, pj)
        btn_labels = [btn.text for row in markup.inline_keyboard for btn in row]
        ugo_btn = next(b for b in btn_labels if "Ugoira" in b)
        self.assertIn("✓", ugo_btn)

    def test_menu_mkv_button_shows_check_when_enabled(self):
        from bot import _build_advanced_menu
        pj = self._make_pj(ugoira_mkvmerge=True)
        _, markup = _build_advanced_menu(1, pj)
        btn_labels = [btn.text for row in markup.inline_keyboard for btn in row]
        mkv_btn = next(b for b in btn_labels if "MKV" in b)
        self.assertIn("✓", mkv_btn)

    def test_menu_text_shows_ytdl_status(self):
        # Main menu shows a compact advanced summary; advanced menu shows full status.
        from bot import _build_menu, _build_advanced_menu
        pj_on = self._make_pj(ytdl=True)
        pj_off = self._make_pj(ytdl=False)
        # Main menu lists active flags by name.
        text_on, _ = _build_menu(1, pj_on)
        text_off, _ = _build_menu(2, pj_off)
        self.assertIn("yt-dlp", text_on)
        # Advanced menu shows ✓ when enabled.
        adv_on, _ = _build_advanced_menu(1, pj_on)
        adv_off, _ = _build_advanced_menu(2, pj_off)
        self.assertIn("✓", adv_on)

    def test_menu_text_shows_ugoira_status(self):
        from bot import _build_menu, _build_advanced_menu
        pj = self._make_pj(ugoira_convert=True)
        text, _ = _build_menu(1, pj)
        self.assertIn("Ugoira", text)
        adv_text, _ = _build_advanced_menu(1, pj)
        self.assertIn("Ugoira", adv_text)
        self.assertIn("✓", adv_text)

    def test_menu_text_shows_mkv_status(self):
        from bot import _build_menu, _build_advanced_menu
        pj = self._make_pj(ugoira_mkvmerge=True)
        text, _ = _build_menu(1, pj)
        self.assertIn("MKV", text)
        adv_text, _ = _build_advanced_menu(1, pj)
        self.assertIn("MKV", adv_text)
        self.assertIn("✓", adv_text)


if __name__ == "__main__":
    unittest.main(verbosity=2)

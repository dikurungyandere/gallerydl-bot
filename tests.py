"""
Unit tests for gallerydl-bot.

Tests cover the modules that do NOT require live Telegram credentials:
config.py, task_manager.py, utils.py, downloader.py, and uploader.py.
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

    def test_upload_uses_target_chat_id(self):
        """upload_files must send to target_chat_id, not event.chat_id."""
        from uploader import upload_files
        from task_manager import UserTask

        mock_client = MagicMock()
        mock_client.send_file = AsyncMock()
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

        mock_client.send_file.assert_called_once()
        call_args = mock_client.send_file.call_args
        self.assertEqual(call_args[0][0], target)


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

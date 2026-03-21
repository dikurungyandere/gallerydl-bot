"""
Task manager for tracking active download/upload operations.

AI-GENERATED CODE DISCLAIMER: This entire codebase has been created by AI.
Review it carefully before deploying to production.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class UserTask:
    """Holds state for a single user's active download/upload task."""

    # The asyncio.Task wrapping the whole download+upload pipeline.
    task: Optional[asyncio.Task] = None
    # The asyncio subprocess running gallery-dl.
    process: Optional[asyncio.subprocess.Process] = None
    # Temporary directory holding downloaded files for this request.
    temp_dir: Optional[str] = None
    # Set to True to signal all running coroutines to abort.
    cancel_flag: bool = False
    # The Telegram Message object used to display status updates.
    status_message: object = None


class TaskManager:
    """Thread-safe (asyncio-safe) registry of per-user active tasks."""

    def __init__(self) -> None:
        self._tasks: Dict[int, UserTask] = {}

    # ------------------------------------------------------------------
    # Registration helpers
    # ------------------------------------------------------------------

    def get_or_create(self, user_id: int) -> UserTask:
        """Return the existing :class:`UserTask` for *user_id*, or create one."""
        if user_id not in self._tasks:
            self._tasks[user_id] = UserTask()
        return self._tasks[user_id]

    def get(self, user_id: int) -> Optional[UserTask]:
        """Return the :class:`UserTask` for *user_id*, or ``None``."""
        return self._tasks.get(user_id)

    def remove(self, user_id: int) -> None:
        """Remove the task entry for *user_id* (called from ``finally`` blocks)."""
        self._tasks.pop(user_id, None)

    def is_active(self, user_id: int) -> bool:
        """Return ``True`` if *user_id* has an active, non-cancelled task."""
        ut = self._tasks.get(user_id)
        if ut is None:
            return False
        if ut.cancel_flag:
            return False
        return ut.task is not None and not ut.task.done()

    # ------------------------------------------------------------------
    # Cancellation
    # ------------------------------------------------------------------

    async def cancel(self, user_id: int) -> bool:
        """Cancel the active task for *user_id*.

        Steps:
        1. Set the ``cancel_flag`` so all coroutines know to abort.
        2. Terminate the gallery-dl subprocess (if still running).
        3. Cancel the asyncio Task.

        Returns ``True`` if there was an active task to cancel, ``False``
        if there was nothing to cancel.
        """
        ut = self._tasks.get(user_id)
        if ut is None:
            return False

        ut.cancel_flag = True

        # Kill the gallery-dl subprocess.
        if ut.process is not None:
            try:
                ut.process.terminate()
                # Give it a moment; escalate to SIGKILL if needed.
                try:
                    await asyncio.wait_for(ut.process.wait(), timeout=5)
                except asyncio.TimeoutError:
                    ut.process.kill()
                    await ut.process.wait()
            except ProcessLookupError:
                pass  # Already exited.
            except Exception as exc:
                logger.warning("Error terminating gallery-dl process: %s", exc)

        # Cancel the asyncio Task.
        if ut.task is not None and not ut.task.done():
            ut.task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(ut.task), timeout=5)
            except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                pass

        return True


# Module-level singleton used by all handlers.
task_manager = TaskManager()

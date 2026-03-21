"""
Task manager for tracking active download/upload operations.

AI-GENERATED CODE DISCLAIMER: This entire codebase has been created by AI.
Review it carefully before deploying to production.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class UserTask:
    """Holds state for a single active download/upload job."""

    # The Telegram user that owns this job.
    user_id: int = 0
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
    # Source URL being processed (used by /status).
    url: str = ""
    # Upload mode: "default" or "duplex" (used by /status).
    mode: str = "default"
    # Latest progress content text (used by /status to show live state).
    progress_text: str = "⏳ Starting…"


class TaskManager:
    """Asyncio-safe registry of concurrent per-job tasks.

    Each download request is assigned a unique integer *job_id*.  A single
    user may have multiple jobs running concurrently.
    """

    def __init__(self) -> None:
        # job_id -> UserTask
        self._tasks: Dict[int, UserTask] = {}
        # user_id -> list of job_ids
        self._user_jobs: Dict[int, List[int]] = {}
        self._next_id: int = 1

    # ------------------------------------------------------------------
    # Registration helpers
    # ------------------------------------------------------------------

    def create(self, user_id: int) -> Tuple[int, UserTask]:
        """Create a new job for *user_id* and return *(job_id, UserTask)*."""
        job_id = self._next_id
        self._next_id += 1
        ut = UserTask(user_id=user_id)
        self._tasks[job_id] = ut
        self._user_jobs.setdefault(user_id, []).append(job_id)
        return job_id, ut

    def get(self, job_id: int) -> Optional[UserTask]:
        """Return the :class:`UserTask` for *job_id*, or ``None``."""
        return self._tasks.get(job_id)

    def get_user_tasks(self, user_id: int) -> List[Tuple[int, UserTask]]:
        """Return *(job_id, UserTask)* pairs for all active jobs of *user_id*."""
        result = []
        for jid in list(self._user_jobs.get(user_id, [])):
            ut = self._tasks.get(jid)
            if ut is None:
                continue
            if ut.cancel_flag:
                continue
            if ut.task is not None and not ut.task.done():
                result.append((jid, ut))
        return result

    def remove(self, job_id: int) -> None:
        """Remove the task entry for *job_id* (called from ``finally`` blocks)."""
        ut = self._tasks.pop(job_id, None)
        if ut is not None:
            job_list = self._user_jobs.get(ut.user_id, [])
            if job_id in job_list:
                job_list.remove(job_id)
            if not job_list:
                self._user_jobs.pop(ut.user_id, None)

    def count_active_jobs(self) -> int:
        """Return the total number of currently running jobs across all users."""
        count = 0
        for jid_list in list(self._user_jobs.values()):
            for jid in jid_list:
                ut = self._tasks.get(jid)
                if (
                    ut is not None
                    and not ut.cancel_flag
                    and ut.task is not None
                    and not ut.task.done()
                ):
                    count += 1
        return count

    def is_active(self, user_id: int) -> bool:
        """Return ``True`` if *user_id* has at least one active job."""
        return len(self.get_user_tasks(user_id)) > 0

    # ------------------------------------------------------------------
    # Cancellation
    # ------------------------------------------------------------------

    async def cancel(self, job_id: int) -> bool:
        """Cancel the job identified by *job_id*.

        Steps:
        1. Set the ``cancel_flag`` so all coroutines know to abort.
        2. Terminate the gallery-dl subprocess (if still running).
        3. Cancel the asyncio Task.

        Returns ``True`` if there was a job to cancel, ``False`` otherwise.
        """
        ut = self._tasks.get(job_id)
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

    async def cancel_all(self, user_id: int) -> int:
        """Cancel every active job for *user_id*.

        Returns the number of jobs that were cancelled.
        """
        job_ids = [jid for jid, _ in self.get_user_tasks(user_id)]
        count = 0
        for job_id in job_ids:
            if await self.cancel(job_id):
                count += 1
        return count


# Module-level singleton used by all handlers.
task_manager = TaskManager()

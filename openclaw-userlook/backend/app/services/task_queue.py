from __future__ import annotations

import asyncio
import contextlib
from collections import defaultdict


class TaskQueueRegistry:
    def __init__(self) -> None:
        self._agent_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._running_tasks: dict[int, asyncio.Task[None]] = {}

    def get_agent_lock(self, agent_id: int) -> asyncio.Lock:
        return self._agent_locks[agent_id]

    def register_task(self, run_id: int, task: asyncio.Task[None]) -> None:
        self._running_tasks[run_id] = task

    def unregister_task(self, run_id: int) -> None:
        self._running_tasks.pop(run_id, None)

    def cancel_task(self, run_id: int) -> bool:
        task = self._running_tasks.get(run_id)
        if task is None or task.done():
            return False
        task.cancel()
        return True

    async def shutdown(self) -> None:
        tasks = list(self._running_tasks.values())
        for task in tasks:
            if not task.done():
                task.cancel()
        for task in tasks:
            with contextlib.suppress(BaseException):
                await task
        self._running_tasks.clear()


task_queue = TaskQueueRegistry()

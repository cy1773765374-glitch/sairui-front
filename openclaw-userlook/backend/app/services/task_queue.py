from __future__ import annotations

import asyncio
import contextlib
import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

from app.core.config import get_settings

QueueStatus = Literal["queued", "immediate"]
AbortCallable = Callable[[], object]
TaskFunc = Callable[[asyncio.Event], Awaitable[None]]


@dataclass
class ActiveDispatcher:
    run_id: int
    conversation_id: int
    task: asyncio.Task[None]
    cancel_event: asyncio.Event
    abort: AbortCallable | None = None


class TaskQueueRegistry:
    def __init__(self) -> None:
        self._active_dispatchers: dict[int, dict[int, ActiveDispatcher]] = {}
        self._run_dispatchers: dict[int, ActiveDispatcher] = {}
        self._global_chat_semaphore: asyncio.Semaphore | None = None
        self._global_chat_limit: int | None = None
        self._agent_chat_semaphores: dict[int, tuple[int, asyncio.Semaphore]] = {}
        self._user_chat_semaphores: dict[int, tuple[int, asyncio.Semaphore]] = {}
        self._conversation_chat_semaphores: dict[int, tuple[int, asyncio.Semaphore]] = {}
        self._lock = asyncio.Lock()

    def build_queue_key(self, conversation_id: int) -> str:
        return str(conversation_id)

    def get_chat_semaphore(self, max_concurrency: int | None = None) -> asyncio.Semaphore:
        settings = get_settings()
        limit = max(1, max_concurrency or settings.task_global_chat_concurrency)
        if self._global_chat_semaphore is None or self._global_chat_limit != limit:
            self._global_chat_semaphore = asyncio.Semaphore(limit)
            self._global_chat_limit = limit
        return self._global_chat_semaphore

    def get_agent_semaphore(self, agent_id: int, max_concurrency: int | None = None) -> asyncio.Semaphore:
        settings = get_settings()
        limit = max(1, max_concurrency or settings.task_agent_max_concurrency)
        cached = self._agent_chat_semaphores.get(agent_id)
        if cached is None or cached[0] != limit:
            cached = (limit, asyncio.Semaphore(limit))
            self._agent_chat_semaphores[agent_id] = cached
        return cached[1]

    def get_user_semaphore(self, user_id: int, max_concurrency: int | None = None) -> asyncio.Semaphore:
        settings = get_settings()
        limit = max(1, max_concurrency or settings.task_user_max_concurrency)
        cached = self._user_chat_semaphores.get(user_id)
        if cached is None or cached[0] != limit:
            cached = (limit, asyncio.Semaphore(limit))
            self._user_chat_semaphores[user_id] = cached
        return cached[1]

    def get_conversation_semaphore(self, conversation_id: int, max_concurrency: int | None = None) -> asyncio.Semaphore:
        settings = get_settings()
        limit = max(1, max_concurrency or settings.task_conversation_max_concurrency)
        cached = self._conversation_chat_semaphores.get(conversation_id)
        if cached is None or cached[0] != limit:
            cached = (limit, asyncio.Semaphore(limit))
            self._conversation_chat_semaphores[conversation_id] = cached
        return cached[1]

    def has_active_task(self, conversation_id: int) -> int:
        return sum(
            1
            for dispatcher in self._active_dispatchers.get(conversation_id, {}).values()
            if not dispatcher.task.done()
        )

    def register_active_dispatcher(
        self,
        conversation_id: int,
        dispatcher: ActiveDispatcher,
    ) -> None:
        self._active_dispatchers.setdefault(conversation_id, {})[dispatcher.run_id] = dispatcher
        self._run_dispatchers[dispatcher.run_id] = dispatcher

    def unregister_active_dispatcher(self, conversation_id: int, run_id: int) -> None:
        dispatchers = self._active_dispatchers.get(conversation_id)
        if dispatchers is not None:
            dispatchers.pop(run_id, None)
            if not dispatchers:
                self._active_dispatchers.pop(conversation_id, None)
        self._run_dispatchers.pop(run_id, None)

    def get_active_dispatcher(self, conversation_id: int) -> ActiveDispatcher | None:
        for dispatcher in self._active_dispatchers.get(conversation_id, {}).values():
            if not dispatcher.task.done():
                return dispatcher
        return None

    def get_active_dispatchers(self, conversation_id: int) -> list[ActiveDispatcher]:
        return [
            dispatcher
            for dispatcher in self._active_dispatchers.get(conversation_id, {}).values()
            if not dispatcher.task.done()
        ]

    def get_dispatcher_for_run(self, run_id: int) -> ActiveDispatcher | None:
        dispatcher = self._run_dispatchers.get(run_id)
        if dispatcher is None or dispatcher.task.done():
            return None
        return dispatcher

    def set_abort(self, run_id: int, abort: AbortCallable | None) -> None:
        dispatcher = self._run_dispatchers.get(run_id)
        if dispatcher is not None:
            dispatcher.abort = abort

    def cancel_conversation_task(self, conversation_id: int) -> bool:
        dispatchers = self.get_active_dispatchers(conversation_id)
        if not dispatchers:
            return False
        cancelled = False
        for dispatcher in dispatchers:
            cancelled = self._cancel_dispatcher(dispatcher) or cancelled
        return cancelled

    def cancel_task(self, run_id: int) -> bool:
        dispatcher = self.get_dispatcher_for_run(run_id)
        if dispatcher is None:
            return False
        return self._cancel_dispatcher(dispatcher)

    def _cancel_dispatcher(self, dispatcher: ActiveDispatcher) -> bool:
        dispatcher.cancel_event.set()
        if dispatcher.abort is not None:
            try:
                result = dispatcher.abort()
                if inspect.isawaitable(result):
                    asyncio.create_task(result)
            except Exception:
                pass
        if not dispatcher.task.done():
            dispatcher.task.cancel()
            return True
        return False

    async def enqueue_task(
        self,
        *,
        conversation_id: int,
        run_id: int,
        user_id: int,
        agent_id: int,
        task_func: TaskFunc,
    ) -> QueueStatus:
        cancel_event = asyncio.Event()

        async def runner() -> None:
            if cancel_event.is_set():
                return
            global_semaphore = self.get_chat_semaphore()
            agent_semaphore = self.get_agent_semaphore(agent_id)
            user_semaphore = self.get_user_semaphore(user_id)
            conversation_semaphore = self.get_conversation_semaphore(conversation_id)
            async with global_semaphore, agent_semaphore, user_semaphore, conversation_semaphore:
                if cancel_event.is_set():
                    return
                await task_func(cancel_event)

        task = asyncio.create_task(runner())
        dispatcher = ActiveDispatcher(
            run_id=run_id,
            conversation_id=conversation_id,
            task=task,
            cancel_event=cancel_event,
        )
        async with self._lock:
            self.register_active_dispatcher(conversation_id, dispatcher)
        task.add_done_callback(
            lambda done_task, cid=conversation_id, rid=run_id: self._cleanup_done_task(
                cid,
                rid,
                done_task,
            )
        )
        return "immediate"

    async def enqueue_conversation_task(
        self,
        conversation_id: int,
        run_id: int,
        task_func: TaskFunc,
    ) -> QueueStatus:
        return await self.enqueue_task(
            conversation_id=conversation_id,
            run_id=run_id,
            user_id=0,
            agent_id=0,
            task_func=task_func,
        )

    def _cleanup_done_task(
        self,
        conversation_id: int,
        run_id: int,
        done_task: asyncio.Task[None],
    ) -> None:
        self.unregister_active_dispatcher(conversation_id, run_id)

    async def shutdown(self) -> None:
        tasks = list({dispatcher.task for dispatcher in self._run_dispatchers.values()})
        for dispatcher in list(self._run_dispatchers.values()):
            dispatcher.cancel_event.set()
            if dispatcher.abort is not None:
                with contextlib.suppress(Exception):
                    result = dispatcher.abort()
                    if inspect.isawaitable(result):
                        await result
        for task in tasks:
            if not task.done():
                task.cancel()
        for task in tasks:
            with contextlib.suppress(BaseException):
                await task
        self._active_dispatchers.clear()
        self._run_dispatchers.clear()
        self._agent_chat_semaphores.clear()
        self._user_chat_semaphores.clear()
        self._conversation_chat_semaphores.clear()


task_queue = TaskQueueRegistry()

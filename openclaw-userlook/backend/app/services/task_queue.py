from __future__ import annotations

import asyncio
import contextlib
import inspect
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
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
        self._per_conversation_semaphores: dict[int, asyncio.Semaphore] = {}
        self._per_conversation_limit: int | None = None
        self._per_agent_semaphores: dict[int, asyncio.Semaphore] = {}
        self._per_agent_limit: int | None = None
        self._per_user_semaphores: dict[int, asyncio.Semaphore] = {}
        self._per_user_limit: int | None = None
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

    def _get_per_conversation_semaphore(self, conversation_id: int) -> asyncio.Semaphore:
        settings = get_settings()
        limit = max(1, settings.task_per_conversation_concurrency)
        if self._per_conversation_limit != limit:
            self._per_conversation_semaphores.clear()
            self._per_conversation_limit = limit
        if conversation_id not in self._per_conversation_semaphores:
            self._per_conversation_semaphores[conversation_id] = asyncio.Semaphore(limit)
        return self._per_conversation_semaphores[conversation_id]

    def _get_per_agent_semaphore(self, agent_id: int) -> asyncio.Semaphore:
        settings = get_settings()
        limit = max(1, settings.task_per_agent_concurrency)
        if self._per_agent_limit != limit:
            self._per_agent_semaphores.clear()
            self._per_agent_limit = limit
        if agent_id not in self._per_agent_semaphores:
            self._per_agent_semaphores[agent_id] = asyncio.Semaphore(limit)
        return self._per_agent_semaphores[agent_id]

    def _get_per_user_semaphore(self, user_id: int) -> asyncio.Semaphore:
        settings = get_settings()
        limit = max(1, settings.task_per_user_concurrency)
        if self._per_user_limit != limit:
            self._per_user_semaphores.clear()
            self._per_user_limit = limit
        if user_id not in self._per_user_semaphores:
            self._per_user_semaphores[user_id] = asyncio.Semaphore(limit)
        return self._per_user_semaphores[user_id]

    @asynccontextmanager
    async def _chat_concurrency_slots(
        self,
        *,
        conversation_id: int,
        agent_id: int | None,
        user_id: int | None,
    ) -> AsyncIterator[None]:
        semaphores = [self._get_per_conversation_semaphore(conversation_id)]
        if agent_id is not None:
            semaphores.append(self._get_per_agent_semaphore(agent_id))
        if user_id is not None:
            semaphores.append(self._get_per_user_semaphore(user_id))
        semaphores.append(self.get_chat_semaphore())

        acquired: list[asyncio.Semaphore] = []
        try:
            for semaphore in semaphores:
                await semaphore.acquire()
                acquired.append(semaphore)
            yield
        finally:
            for semaphore in reversed(acquired):
                semaphore.release()

    def active_task_count(self, conversation_id: int) -> int:
        return sum(
            1
            for dispatcher in self._active_dispatchers.get(conversation_id, {}).values()
            if not dispatcher.task.done()
        )

    def has_active_task(self, conversation_id: int) -> bool:
        return self.active_task_count(conversation_id) > 0

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

    async def enqueue_conversation_task(
        self,
        conversation_id: int,
        run_id: int,
        task_func: TaskFunc,
        *,
        agent_id: int | None = None,
        user_id: int | None = None,
    ) -> QueueStatus:
        async with self._lock:
            cancel_event = asyncio.Event()

            async def runner() -> None:
                if cancel_event.is_set():
                    return
                async with self._chat_concurrency_slots(
                    conversation_id=conversation_id,
                    agent_id=agent_id,
                    user_id=user_id,
                ):
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
            self.register_active_dispatcher(conversation_id, dispatcher)
            task.add_done_callback(
                lambda done_task, cid=conversation_id, rid=run_id: self._cleanup_done_task(
                    cid,
                    rid,
                    done_task,
                )
            )
            return "immediate"

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
        self._per_conversation_semaphores.clear()
        self._per_agent_semaphores.clear()
        self._per_user_semaphores.clear()


task_queue = TaskQueueRegistry()

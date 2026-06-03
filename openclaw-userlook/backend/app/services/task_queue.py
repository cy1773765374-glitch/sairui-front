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
        self._conversation_queues: dict[int, asyncio.Task[None]] = {}
        self._active_dispatchers: dict[int, ActiveDispatcher] = {}
        self._run_dispatchers: dict[int, ActiveDispatcher] = {}
        self._global_chat_semaphore: asyncio.Semaphore | None = None
        self._global_chat_limit: int | None = None
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

    def has_active_task(self, conversation_id: int) -> bool:
        dispatcher = self._active_dispatchers.get(conversation_id)
        return dispatcher is not None and not dispatcher.task.done()

    def register_active_dispatcher(
        self,
        conversation_id: int,
        dispatcher: ActiveDispatcher,
    ) -> None:
        self._active_dispatchers[conversation_id] = dispatcher
        self._run_dispatchers[dispatcher.run_id] = dispatcher

    def unregister_active_dispatcher(self, conversation_id: int, run_id: int) -> None:
        dispatcher = self._active_dispatchers.get(conversation_id)
        if dispatcher is not None and dispatcher.run_id == run_id:
            self._active_dispatchers.pop(conversation_id, None)
        self._run_dispatchers.pop(run_id, None)

    def get_active_dispatcher(self, conversation_id: int) -> ActiveDispatcher | None:
        dispatcher = self._active_dispatchers.get(conversation_id)
        if dispatcher is None or dispatcher.task.done():
            return None
        return dispatcher

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
        dispatcher = self.get_active_dispatcher(conversation_id)
        if dispatcher is None:
            return False
        return self._cancel_dispatcher(dispatcher)

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
    ) -> QueueStatus:
        async with self._lock:
            previous_task = self._conversation_queues.get(conversation_id)
            queue_status: QueueStatus = (
                "queued" if previous_task is not None and not previous_task.done() else "immediate"
            )
            cancel_event = asyncio.Event()

            async def runner() -> None:
                if previous_task is not None and not previous_task.done():
                    with contextlib.suppress(BaseException):
                        await previous_task
                if cancel_event.is_set():
                    return
                semaphore = self.get_chat_semaphore()
                async with semaphore:
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
            self._conversation_queues[conversation_id] = task
            task.add_done_callback(
                lambda done_task, cid=conversation_id, rid=run_id: self._cleanup_done_task(
                    cid,
                    rid,
                    done_task,
                )
            )
            return queue_status

    def _cleanup_done_task(
        self,
        conversation_id: int,
        run_id: int,
        done_task: asyncio.Task[None],
    ) -> None:
        if self._conversation_queues.get(conversation_id) is done_task:
            self._conversation_queues.pop(conversation_id, None)
        self.unregister_active_dispatcher(conversation_id, run_id)

    async def shutdown(self) -> None:
        tasks = list({*self._conversation_queues.values(), *(d.task for d in self._run_dispatchers.values())})
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
        self._conversation_queues.clear()
        self._active_dispatchers.clear()
        self._run_dispatchers.clear()


task_queue = TaskQueueRegistry()

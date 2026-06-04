import asyncio
import os
import unittest
from unittest.mock import patch

from app.core.config import get_settings
from app.services.task_queue import TaskQueueRegistry
from app.services.ws_connection_manager import WebSocketConnectionManager


class TaskQueueConcurrencyTest(unittest.IsolatedAsyncioTestCase):
    async def test_same_agent_multiple_conversations_start_without_serial_wait(self) -> None:
        queue = TaskQueueRegistry()
        started: list[tuple[int, float]] = []
        release_event = asyncio.Event()

        def make_job(conversation_id: int):
            async def job(cancel_event: asyncio.Event) -> None:
                started.append((conversation_id, asyncio.get_running_loop().time()))
                await release_event.wait()

            return job

        await asyncio.gather(
            queue.enqueue_conversation_task(11, 101, make_job(11)),
            queue.enqueue_conversation_task(12, 102, make_job(12)),
        )

        for _ in range(20):
            if len(started) == 2:
                break
            await asyncio.sleep(0.01)

        self.assertEqual({item[0] for item in started}, {11, 12})
        self.assertTrue(queue.has_active_task(11))
        self.assertTrue(queue.has_active_task(12))
        self.assertLess(max(item[1] for item in started) - min(item[1] for item in started), 0.05)

        release_event.set()
        await queue.shutdown()

    async def test_per_conversation_limit_queues_extra_runs(self) -> None:
        with patch.dict(
            os.environ,
            {
                "TASK_PER_CONVERSATION_CONCURRENCY": "2",
                "TASK_PER_AGENT_CONCURRENCY": "10",
                "TASK_PER_USER_CONCURRENCY": "10",
                "TASK_GLOBAL_CHAT_CONCURRENCY": "10",
            },
        ):
            get_settings.cache_clear()
            queue = TaskQueueRegistry()
            started: list[int] = []
            release_events = {101: asyncio.Event(), 102: asyncio.Event(), 103: asyncio.Event()}

            def make_job(run_id: int):
                async def job(cancel_event: asyncio.Event) -> None:
                    started.append(run_id)
                    await release_events[run_id].wait()

                return job

            try:
                await queue.enqueue_conversation_task(11, 101, make_job(101), agent_id=3, user_id=7)
                await queue.enqueue_conversation_task(11, 102, make_job(102), agent_id=3, user_id=7)
                await queue.enqueue_conversation_task(11, 103, make_job(103), agent_id=3, user_id=7)

                for _ in range(20):
                    if len(started) == 2:
                        break
                    await asyncio.sleep(0.01)

                self.assertEqual(set(started), {101, 102})

                release_events[101].set()
                for _ in range(20):
                    if 103 in started:
                        break
                    await asyncio.sleep(0.01)

                self.assertIn(103, started)
            finally:
                for event in release_events.values():
                    event.set()
                await queue.shutdown()
                get_settings.cache_clear()

    async def test_cancel_task_only_cancels_the_target_run_id(self) -> None:
        queue = TaskQueueRegistry()
        started: list[int] = []
        cancelled: list[int] = []
        release_event = asyncio.Event()

        def make_job(run_id: int):
            async def job(cancel_event: asyncio.Event) -> None:
                started.append(run_id)
                try:
                    await release_event.wait()
                except asyncio.CancelledError:
                    cancelled.append(run_id)
                    raise

            return job

        await queue.enqueue_conversation_task(11, 101, make_job(101))
        await queue.enqueue_conversation_task(11, 102, make_job(102))

        for _ in range(20):
            if queue.active_task_count(11) == 2 and set(started) == {101, 102}:
                break
            await asyncio.sleep(0.01)

        self.assertEqual(set(started), {101, 102})

        self.assertTrue(queue.cancel_task(101))
        await asyncio.sleep(0.05)

        self.assertIn(101, cancelled)
        self.assertNotIn(102, cancelled)
        self.assertIsNone(queue.get_dispatcher_for_run(101))
        self.assertIsNotNone(queue.get_dispatcher_for_run(102))

        release_event.set()
        await queue.shutdown()


class WebSocketConnectionManagerTest(unittest.IsolatedAsyncioTestCase):
    async def test_same_conversation_multiple_browser_connections_receive_broadcasts(self) -> None:
        manager = WebSocketConnectionManager()
        first = FakeWebSocket()
        second = FakeWebSocket()

        await manager.connect(11, first)
        await manager.connect(11, second)
        await manager.broadcast_json(11, {"type": "assistant_delta", "run_id": 101, "content": "hi"})

        self.assertEqual(len(first.sent), 1)
        self.assertEqual(len(second.sent), 1)
        self.assertEqual(first.sent[0]["run_id"], 101)
        self.assertEqual(second.sent[0]["run_id"], 101)

        manager.disconnect(11, first)
        await manager.broadcast_json(11, {"type": "run_status", "run_id": 102, "status": "success"})

        self.assertEqual(len(first.sent), 1)
        self.assertEqual(len(second.sent), 2)
        self.assertEqual(second.sent[1]["run_id"], 102)


class FakeWebSocket:
    def __init__(self) -> None:
        self.accepted = False
        self.sent: list[dict] = []

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)


if __name__ == "__main__":
    unittest.main()

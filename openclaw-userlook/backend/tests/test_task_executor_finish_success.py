import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.agent import Agent, AgentRiskLevel
from app.models.conversation import Conversation
from app.models.message import Message, MessageRole
from app.models.task_run import TaskRun, TaskRunStatus
from app.models.user import User, UserRole, UserStatus
from app.services.openclaw_adapter import OpenClawAdapterEvent
from app.services.run_service import list_task_runs
from app.services.task_executor import _finish_success, execute_chat_run


class TaskExecutorFinishSuccessTest(unittest.IsolatedAsyncioTestCase):
    async def test_finish_success_persists_run_output_and_assistant_message(self) -> None:
        engine = create_engine("sqlite:///:memory:", future=True)
        Base.metadata.create_all(engine)
        session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

        with session_factory() as db:
            user = User(
                id=7,
                username="alice",
                password_hash="x",
                display_name="Alice",
                status=UserStatus.active,
                role=UserRole.user,
            )
            agent = Agent(
                id=3,
                code="mysql",
                name="MySQL Agent",
                openclaw_agent_id="mysql-analysis",
                risk_level=AgentRiskLevel.low,
            )
            conversation = Conversation(
                id=11,
                user_id=user.id,
                agent_id=agent.id,
                title="MySQL",
                session_key="web:7:mysql:11",
            )
            run = TaskRun(
                id=59,
                user_id=user.id,
                agent_id=agent.id,
                conversation_id=conversation.id,
                input_text="who are you",
                run_type="chat",
                priority=100,
                status=TaskRunStatus.running,
                output_dir="/tmp/openclaw-userlook/outputs/7/20260603/run_59",
                client_message_id="client-1",
                gateway_session_key="agent:mysql-analysis:web:7:mysql:11",
                idempotency_key="openclaw-userlook:59:client-1",
                raw_payload={
                    "agent_code": agent.code,
                    "openclaw_agent_id": agent.openclaw_agent_id,
                    "client_message_id": "client-1",
                    "gateway_session_key": "agent:mysql-analysis:web:7:mysql:11",
                },
            )
            assistant_message = Message(
                id=100,
                conversation_id=conversation.id,
                run_id=run.id,
                role=MessageRole.assistant,
                content="streaming...",
                raw_payload={"streaming": True, "status": "running"},
            )
            db.add_all([user, agent, conversation, run, assistant_message])
            db.commit()

            with (
                patch("app.services.task_executor.register_output_files", return_value=[]),
                patch("app.services.task_executor.connection_manager.broadcast_json", new=AsyncMock()) as broadcast,
            ):
                await _finish_success(
                    db=db,
                    run=run,
                    user=user,
                    agent=agent,
                    conversation=conversation,
                    conversation_id=conversation.id,
                    assistant_content="I am MySQL Agent.",
                    raw_payload={
                        "gateway_event": {"type": "res", "id": "chat-59"},
                        "terminal_event_received": True,
                        "gateway_terminal_status": "success",
                    },
                )

            saved_run = db.get(TaskRun, run.id)
            self.assertIsNotNone(saved_run)
            self.assertEqual(saved_run.status, TaskRunStatus.success)
            self.assertEqual(saved_run.output_text, "I am MySQL Agent.")
            self.assertEqual(saved_run.output_files_json, [])
            self.assertEqual(saved_run.raw_payload["status"], "success")
            self.assertEqual(saved_run.raw_payload["client_message_id"], "client-1")
            self.assertEqual(saved_run.raw_payload["gateway_session_key"], "agent:mysql-analysis:web:7:mysql:11")
            self.assertEqual(saved_run.raw_payload["gateway_terminal_status"], "success")

            assistant_messages = db.scalars(
                select(Message)
                .where(Message.run_id == run.id)
                .where(Message.role == MessageRole.assistant)
            ).all()
            self.assertEqual(len(assistant_messages), 1)
            self.assertEqual(assistant_messages[0].id, 100)
            self.assertEqual(assistant_messages[0].conversation_id, conversation.id)
            self.assertEqual(assistant_messages[0].content, "I am MySQL Agent.")
            self.assertEqual(assistant_messages[0].raw_payload["status"], "success")
            self.assertEqual(saved_run.raw_payload["assistant_message_id"], assistant_messages[0].id)

            self.assertEqual(broadcast.await_count, 2)

    async def test_list_task_runs_uses_lightweight_payload(self) -> None:
        engine = create_engine("sqlite:///:memory:", future=True)
        Base.metadata.create_all(engine)
        session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

        with session_factory() as db:
            user = User(
                id=7,
                username="alice",
                password_hash="x",
                display_name="Alice",
                status=UserStatus.active,
                role=UserRole.user,
            )
            agent = Agent(
                id=3,
                code="mysql",
                name="MySQL Agent",
                openclaw_agent_id="mysql-analysis",
                risk_level=AgentRiskLevel.low,
            )
            conversation = Conversation(
                id=11,
                user_id=user.id,
                agent_id=agent.id,
                title="MySQL",
                session_key="web:7:mysql:11",
            )
            run = TaskRun(
                id=59,
                user_id=user.id,
                agent_id=agent.id,
                conversation_id=conversation.id,
                input_text="who are you",
                run_type="chat",
                priority=100,
                status=TaskRunStatus.timeout,
                output_dir="/tmp/openclaw-userlook/outputs/7/20260603/run_59",
                raw_payload={"status": "timeout", "gateway_debug_events": [{"classification": "outbound_request"}]},
            )
            db.add_all([user, agent, conversation, run])
            db.commit()

            with patch("app.services.run_service.list_output_files_for_dir") as list_files:
                rows = list_task_runs(db, user)

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].raw_payload["status"], "timeout")
            self.assertIsNone(rows[0].raw_payload_summary)
            self.assertEqual(rows[0].output_files, [])
            list_files.assert_not_called()

    async def test_execute_chat_run_persists_timeout_debug_payload_without_output(self) -> None:
        engine = create_engine("sqlite:///:memory:", future=True)
        Base.metadata.create_all(engine)
        session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

        with session_factory() as db:
            user = User(
                id=7,
                username="alice",
                password_hash="x",
                display_name="Alice",
                status=UserStatus.active,
                role=UserRole.user,
            )
            agent = Agent(
                id=3,
                code="mysql",
                name="MySQL Agent",
                openclaw_agent_id="mysql-analysis",
                risk_level=AgentRiskLevel.low,
            )
            conversation = Conversation(
                id=11,
                user_id=user.id,
                agent_id=agent.id,
                title="MySQL",
                session_key="web:7:mysql:11",
            )
            run = TaskRun(
                id=59,
                user_id=user.id,
                agent_id=agent.id,
                conversation_id=conversation.id,
                input_text="who are you",
                run_type="chat",
                priority=100,
                status=TaskRunStatus.queued,
                output_dir="/tmp/openclaw-userlook/outputs/7/20260603/run_59",
                client_message_id="client-1",
                gateway_session_key="agent:mysql-analysis:web:7:mysql:11",
                idempotency_key="openclaw-userlook:59:client-1",
                raw_payload={"status": "queued"},
            )
            assistant_message = Message(
                id=100,
                conversation_id=conversation.id,
                run_id=run.id,
                role=MessageRole.assistant,
                content="",
                raw_payload={},
            )
            db.add_all([user, agent, conversation, run, assistant_message])
            db.commit()

        class FakeTimeoutAdapter:
            settings = type("Settings", (), {"mock_openclaw": False})()

            async def stream_chat(self, **kwargs):
                yield OpenClawAdapterEvent(
                    type="error",
                    status="timeout",
                    content="OpenClaw Gateway response timed out",
                    gateway_request={"method": "chat.send", "params": {"sessionKey": "agent:mysql-analysis:web:7:mysql:11"}},
                    gateway_debug_events=[{"classification": "outbound_request"}],
                )

        with (
            patch("app.services.task_executor.SessionLocal", session_factory),
            patch("app.services.task_executor.OpenClawAdapter", return_value=FakeTimeoutAdapter()),
            patch("app.services.task_executor.connection_manager.broadcast_json", new=AsyncMock()),
        ):
            await execute_chat_run(
                run_id=59,
                user_id=7,
                agent_id=3,
                conversation_id=11,
                content="who are you",
                file_ids=[],
                gateway_files=[],
                cancel_event=asyncio.Event(),
            )

        with session_factory() as db:
            saved_run = db.get(TaskRun, 59)
            self.assertIsNotNone(saved_run)
            self.assertEqual(saved_run.status, TaskRunStatus.timeout)
            self.assertEqual(saved_run.raw_payload["status"], "timeout")
            self.assertTrue(saved_run.raw_payload["timeout"])
            self.assertEqual(saved_run.raw_payload["gateway_request"]["method"], "chat.send")
            self.assertEqual(saved_run.raw_payload["gateway_debug_events"][0]["classification"], "outbound_request")
            assistant_messages = db.scalars(
                select(Message)
                .where(Message.run_id == 59)
                .where(Message.role == MessageRole.assistant)
            ).all()
            self.assertEqual(len(assistant_messages), 1)
            self.assertEqual(assistant_messages[0].id, 100)
            self.assertEqual(assistant_messages[0].content, "OpenClaw Gateway response timed out")
            self.assertEqual(assistant_messages[0].raw_payload["status"], "timeout")


if __name__ == "__main__":
    unittest.main()

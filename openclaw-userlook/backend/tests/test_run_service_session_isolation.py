import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.agent import Agent, AgentRiskLevel
from app.models.conversation import Conversation
from app.models.message import Message, MessageRole
from app.models.task_run import TaskRun, TaskRunStatus
from app.models.user import User, UserRole, UserStatus
from app.services.conversation_service import get_conversation_detail
from app.services.run_service import (
    get_task_run_by_client_message,
    mark_task_run_cancelled,
    mark_task_run_failed,
    mark_task_run_success,
    mark_task_run_timeout,
)


class RunServiceSessionIsolationTest(unittest.TestCase):
    def test_client_message_id_lookup_is_scoped_to_conversation(self) -> None:
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
            conversation_a = Conversation(
                id=11,
                user_id=user.id,
                agent_id=agent.id,
                title="A",
                session_key="web:7:mysql:11",
            )
            conversation_b = Conversation(
                id=12,
                user_id=user.id,
                agent_id=agent.id,
                title="B",
                session_key="web:7:mysql:12",
            )
            run_a = TaskRun(
                id=59,
                user_id=user.id,
                agent_id=agent.id,
                conversation_id=conversation_a.id,
                input_text="same client id in A",
                run_type="chat",
                priority=100,
                status=TaskRunStatus.queued,
                client_message_id="client-1",
                gateway_session_key="agent:mysql-analysis:web:7:mysql:11",
                idempotency_key="openclaw-userlook:59:client-1",
            )
            run_b = TaskRun(
                id=60,
                user_id=user.id,
                agent_id=agent.id,
                conversation_id=conversation_b.id,
                input_text="same client id in B",
                run_type="chat",
                priority=100,
                status=TaskRunStatus.queued,
                client_message_id="client-1",
                gateway_session_key="agent:mysql-analysis:web:7:mysql:12",
                idempotency_key="openclaw-userlook:60:client-1",
            )
            db.add_all([user, agent, conversation_a, conversation_b, run_a, run_b])
            db.commit()

            self.assertEqual(
                get_task_run_by_client_message(
                    db,
                    conversation_id=conversation_a.id,
                    client_message_id="client-1",
                ).id,
                run_a.id,
            )
            self.assertEqual(
                get_task_run_by_client_message(
                    db,
                    conversation_id=conversation_b.id,
                    client_message_id="client-1",
                ).id,
                run_b.id,
            )
            self.assertIsNone(
                get_task_run_by_client_message(
                    db,
                    conversation_id=conversation_a.id,
                    client_message_id="missing",
                )
            )

    def test_terminal_status_transitions_leave_running_state(self) -> None:
        engine = create_engine("sqlite:///:memory:", future=True)
        Base.metadata.create_all(engine)
        session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

        with session_factory() as db:
            user, agent, conversation = self._seed_user_agent_conversation(db)
            runs = [
                TaskRun(
                    id=run_id,
                    user_id=user.id,
                    agent_id=agent.id,
                    conversation_id=conversation.id,
                    input_text=f"run {run_id}",
                    run_type="chat",
                    priority=100,
                    status=TaskRunStatus.running,
                )
                for run_id in (101, 102, 103, 104)
            ]
            db.add_all(runs)
            db.commit()

            self.assertEqual(mark_task_run_success(db, runs[0], output_text="ok").status, TaskRunStatus.success)
            self.assertEqual(mark_task_run_failed(db, runs[1], "failed").status, TaskRunStatus.failed)
            self.assertEqual(mark_task_run_timeout(db, runs[2], "timeout").status, TaskRunStatus.timeout)
            self.assertEqual(mark_task_run_cancelled(db, runs[3], "cancelled").status, TaskRunStatus.cancelled)

            saved_statuses = {db.get(TaskRun, run.id).status for run in runs}
            self.assertEqual(
                saved_statuses,
                {
                    TaskRunStatus.success,
                    TaskRunStatus.failed,
                    TaskRunStatus.timeout,
                    TaskRunStatus.cancelled,
                },
            )

    def test_conversation_detail_restores_history_and_latest_active_run_after_ws_disconnect(self) -> None:
        engine = create_engine("sqlite:///:memory:", future=True)
        Base.metadata.create_all(engine)
        session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

        with session_factory() as db:
            user, agent, conversation = self._seed_user_agent_conversation(db)
            active_run = TaskRun(
                id=101,
                user_id=user.id,
                agent_id=agent.id,
                conversation_id=conversation.id,
                input_text="still running",
                run_type="chat",
                priority=100,
                status=TaskRunStatus.running,
                client_message_id="client-101",
                gateway_session_key="agent:mysql-analysis:web:7:mysql:11",
                idempotency_key="openclaw-userlook:101:client-101",
            )
            completed_run = TaskRun(
                id=100,
                user_id=user.id,
                agent_id=agent.id,
                conversation_id=conversation.id,
                input_text="done",
                run_type="chat",
                priority=100,
                status=TaskRunStatus.success,
                output_text="done reply",
            )
            db.add_all(
                [
                    active_run,
                    completed_run,
                    Message(
                        id=201,
                        conversation_id=conversation.id,
                        run_id=completed_run.id,
                        role=MessageRole.user,
                        content="done",
                    ),
                    Message(
                        id=202,
                        conversation_id=conversation.id,
                        run_id=completed_run.id,
                        role=MessageRole.assistant,
                        content="done reply",
                    ),
                ]
            )
            db.commit()

            detail = get_conversation_detail(db, user, conversation.id)

            self.assertEqual(detail.active_run.id, active_run.id)
            self.assertEqual(detail.active_run.status, TaskRunStatus.running)
            self.assertEqual([message.id for message in detail.messages], [201, 202])
            self.assertEqual(detail.active_run.client_message_id, "client-101")

    def _seed_user_agent_conversation(self, db):
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
            title="A",
            session_key="web:7:mysql:11",
        )
        db.add_all([user, agent, conversation])
        db.commit()
        return user, agent, conversation


if __name__ == "__main__":
    unittest.main()

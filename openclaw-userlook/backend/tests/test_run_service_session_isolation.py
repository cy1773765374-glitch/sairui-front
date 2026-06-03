import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.agent import Agent, AgentRiskLevel
from app.models.conversation import Conversation
from app.models.task_run import TaskRun, TaskRunStatus
from app.models.user import User, UserRole, UserStatus
from app.services.run_service import get_task_run_by_client_message


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


if __name__ == "__main__":
    unittest.main()

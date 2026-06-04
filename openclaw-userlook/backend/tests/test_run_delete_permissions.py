import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.agent import Agent, AgentRiskLevel
from app.models.task_run import TaskRun, TaskRunStatus
from app.models.user import User, UserRole, UserStatus
from app.services.run_service import batch_delete_task_runs, delete_task_run


class RunDeletePermissionsTest(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:", future=True)
        Base.metadata.create_all(engine)
        self.session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def test_regular_user_cannot_delete_single_or_batch_task_runs(self) -> None:
        with self.session_factory() as db:
            user, _, _ = self._seed(db)

            with self.assertRaises(HTTPException) as single_context:
                delete_task_run(db, user, 59)
            self.assertEqual(single_context.exception.status_code, 403)

            with self.assertRaises(HTTPException) as batch_context:
                batch_delete_task_runs(db, user, [59])
            self.assertEqual(batch_context.exception.status_code, 403)

            run = db.get(TaskRun, 59)
            self.assertIsNotNone(run)
            self.assertIsNone(run.deleted_at)

    def test_admin_can_delete_terminal_run_but_not_active_run(self) -> None:
        with self.session_factory() as db:
            _, admin, _ = self._seed(db)

            delete_task_run(db, admin, 59)
            terminal_run = db.get(TaskRun, 59)
            self.assertIsNotNone(terminal_run)
            self.assertIsNotNone(terminal_run.deleted_at)

            with self.assertRaises(HTTPException) as context:
                delete_task_run(db, admin, 60)
            self.assertEqual(context.exception.status_code, 409)

            active_run = db.get(TaskRun, 60)
            self.assertIsNotNone(active_run)
            self.assertIsNone(active_run.deleted_at)

    def test_admin_batch_delete_skips_active_runs(self) -> None:
        with self.session_factory() as db:
            _, admin, _ = self._seed(db)

            result = batch_delete_task_runs(db, admin, [59, 60, 999])

            self.assertEqual(result["deleted_ids"], [59])
            self.assertEqual(
                result["skipped"],
                [{"id": 60, "reason": "active"}, {"id": 999, "reason": "not_found"}],
            )

    def _seed(self, db):
        user = User(
            id=7,
            username="alice",
            password_hash="x",
            display_name="Alice",
            status=UserStatus.active,
            role=UserRole.user,
        )
        admin = User(
            id=1,
            username="admin",
            password_hash="x",
            display_name="Admin",
            status=UserStatus.active,
            role=UserRole.admin,
        )
        agent = Agent(
            id=3,
            code="knife",
            name="刀版合成 Agent",
            openclaw_agent_id="knife-agent",
            risk_level=AgentRiskLevel.low,
        )
        terminal_run = TaskRun(
            id=59,
            user_id=user.id,
            agent_id=agent.id,
            conversation_id=None,
            input_text="done",
            run_type="chat",
            priority=100,
            status=TaskRunStatus.success,
        )
        active_run = TaskRun(
            id=60,
            user_id=user.id,
            agent_id=agent.id,
            conversation_id=None,
            input_text="running",
            run_type="chat",
            priority=100,
            status=TaskRunStatus.running,
        )
        db.add_all([user, admin, agent, terminal_run, active_run])
        db.commit()
        return user, admin, agent


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.agent import Agent, AgentRiskLevel
from app.models.conversation import Conversation
from app.models.file import File, FilePurpose
from app.models.user import User, UserRole, UserStatus
from app.services.pending_task_service import consume_pending_task, save_pending_files, save_pending_text
from app.services.runners.daoban_job_runner import build_daoban_command, inspect_daoban_outputs
from app.services.runners.router import AgentRunnerRouter
from app.services.task_classifier import DAOBAN_TASK_TYPE, TaskKind, classify_task
from app.services.workspace_service import resolve_agent_workspace


class WorkspaceJobRunnerTest(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:", future=True)
        Base.metadata.create_all(engine)
        self.session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def test_workspace_resolve_known_agent_aliases(self) -> None:
        cases = [
            ("main", "main", "/home/cy/.openclaw/workspace"),
            ("spider_1688", "spider", "/home/cy/.openclaw/workspace-spider"),
            ("xingzheng", "xingzheng_a", "/home/cy/.openclaw/workspace-xingzheng_a"),
            ("image_daoban", "image-daoban", "/home/cy/.openclaw/workspace-image-daoban"),
            ("mysql_analysis", "huizong-ceshi", "/home/cy/.openclaw/workspace-huizong-ceshi"),
        ]
        for code, openclaw_agent_id, expected in cases:
            agent = Agent(
                id=1,
                code=code,
                name=code,
                openclaw_agent_id=openclaw_agent_id,
                risk_level=AgentRiskLevel.low,
            )
            self.assertEqual(str(resolve_agent_workspace(agent)).replace("\\", "/"), expected)

    def test_task_classifier_daoban_pdf_and_text(self) -> None:
        with self.session_factory() as db:
            user, agent, conversation = self._seed_user_agent_conversation(db)
            pdf = self._file(user.id, 10, "source.pdf")
            result = classify_task(
                db,
                user=user,
                agent=agent,
                conversation_id=conversation.id,
                content="山水插画",
                files=[pdf],
            )
            self.assertEqual(result.task_kind, TaskKind.long_job)
            self.assertEqual(result.runner, "daoban_job")
            self.assertEqual(result.effective_file_ids, [10])

    def test_task_classifier_daoban_pdf_only(self) -> None:
        with self.session_factory() as db:
            user, agent, conversation = self._seed_user_agent_conversation(db)
            pdf = self._file(user.id, 10, "source.pdf")
            result = classify_task(db, user=user, agent=agent, conversation_id=conversation.id, content="", files=[pdf])
            self.assertEqual(result.task_kind, TaskKind.pending_input)
            self.assertEqual(result.response_message, "已收到刀版 PDF，请继续输入创意描述。")

    def test_task_classifier_daoban_text_only_without_pdf(self) -> None:
        with self.session_factory() as db:
            user, agent, conversation = self._seed_user_agent_conversation(db)
            result = classify_task(db, user=user, agent=agent, conversation_id=conversation.id, content="山水插画", files=[])
            self.assertEqual(result.task_kind, TaskKind.pending_input)
            self.assertEqual(result.response_message, "已记录创意描述，请上传 PDF 刀版文件。")

    def test_task_classifier_daoban_text_after_pdf(self) -> None:
        with self.session_factory() as db:
            user, agent, conversation = self._seed_user_agent_conversation(db)
            save_pending_files(
                db,
                user=user,
                conversation_id=conversation.id,
                agent=agent,
                task_type=DAOBAN_TASK_TYPE,
                file_ids=[10],
            )
            result = classify_task(db, user=user, agent=agent, conversation_id=conversation.id, content="山水插画", files=[])
            self.assertEqual(result.task_kind, TaskKind.long_job)
            self.assertEqual(result.effective_file_ids, [10])
            self.assertEqual(result.selected_pending_file_id, 10)

    def test_task_classifier_daoban_pdf_after_text(self) -> None:
        with self.session_factory() as db:
            user, agent, conversation = self._seed_user_agent_conversation(db)
            save_pending_text(
                db,
                user=user,
                conversation_id=conversation.id,
                agent=agent,
                task_type=DAOBAN_TASK_TYPE,
                text_value="山水插画",
            )
            pdf = self._file(user.id, 10, "source.pdf")
            result = classify_task(db, user=user, agent=agent, conversation_id=conversation.id, content="", files=[pdf])
            self.assertEqual(result.task_kind, TaskKind.long_job)
            self.assertEqual(result.effective_content, "山水插画")
            self.assertEqual(result.effective_file_ids, [10])

    def test_pending_task_consume_marks_context_used(self) -> None:
        with self.session_factory() as db:
            user, agent, conversation = self._seed_user_agent_conversation(db)
            pending = save_pending_text(
                db,
                user=user,
                conversation_id=conversation.id,
                agent=agent,
                task_type=DAOBAN_TASK_TYPE,
                text_value="山水插画",
            )
            consume_pending_task(db, pending, run_id=99)
            db.refresh(pending)
            self.assertEqual(pending.status, "consumed")
            self.assertEqual(pending.consumed_by_run_id, 99)

    def test_daoban_runner_builds_command(self) -> None:
        command = build_daoban_command(
            workspace=Path("/home/cy/.openclaw/workspace-image-daoban"),
            pdf_path="/tmp/input.pdf",
            prompt="山水插画",
            output_dir="/data/share/yaq/test/2026-06-05-run-104",
        )
        self.assertIn("scripts/run_daoban_job.py", command)
        self.assertIn("--pdf", command)
        self.assertIn("/tmp/input.pdf", command)
        self.assertIn("--prompt", command)
        self.assertIn("山水插画", command)
        self.assertIn("--run-dir", command)
        self.assertIn("/data/share/yaq/test/2026-06-05-run-104", command)

    def test_daoban_runner_detects_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as output_dir:
            root = Path(output_dir)
            (root / "out.pdf").write_bytes(b"%PDF")
            (root / "out.png").write_bytes(b"png")
            (root / "qc_report.json").write_text("{}", encoding="utf-8")
            found, missing, minimum_ok = inspect_daoban_outputs(output_dir)
            self.assertTrue(minimum_ok)
            self.assertIn("out.pdf", found)
            self.assertIn("layout_plan.json", missing)

    def test_router_selects_daoban_runner_without_gateway(self) -> None:
        from app.models.task_run import TaskRun, TaskRunStatus

        agent = Agent(
            id=3,
            code="image_daoban",
            name="Daoban",
            openclaw_agent_id="image-daoban",
            risk_level=AgentRiskLevel.medium,
        )
        run = TaskRun(
            id=7,
            user_id=1,
            agent_id=agent.id,
            conversation_id=1,
            status=TaskRunStatus.queued,
            input_text="山水插画",
            run_type="job",
            priority=100,
            runner_name="daoban_job",
        )
        self.assertEqual(AgentRunnerRouter().select_runner(run=run, agent=agent).name, "daoban_job")

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
            code="image_daoban",
            name="Daoban",
            openclaw_agent_id="image-daoban",
            risk_level=AgentRiskLevel.medium,
            workspace_path="/home/cy/.openclaw/workspace-image-daoban",
            execution_mode="job",
        )
        conversation = Conversation(
            id=19,
            user_id=user.id,
            agent_id=agent.id,
            title="Daoban",
            session_key="web:7:image_daoban:19",
        )
        db.add_all([user, agent, conversation])
        db.commit()
        return user, agent, conversation

    def _file(self, user_id: int, file_id: int, name: str) -> File:
        return File(
            id=file_id,
            user_id=user_id,
            original_name=name,
            stored_path=f"/tmp/{name}",
            file_type="pdf",
            mime_type="application/pdf",
            file_size=4,
            purpose=FilePurpose.upload,
            status="ready",
        )


if __name__ == "__main__":
    unittest.main()

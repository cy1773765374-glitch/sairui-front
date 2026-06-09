import os
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
from app.services.file_service import _allowed_output_roots
from app.services.mysql_analysis_service import (
    MYSQL_ANALYSIS_TASK_TYPE,
    build_mysql_analysis_command,
    build_mysql_success_text,
    parse_mysql_analysis_request,
    sanitize_mysql_analysis_text,
)
from app.services.pending_task_service import consume_pending_task, save_pending_files, save_pending_text
from app.services.runners.ppt_generation_job_runner import (
    build_ppt_generation_env,
    build_ppt_generation_command,
    extract_json_object,
    ppt_failure_text,
    ppt_success_text,
)
from app.services.runners.daoban_job_runner import build_daoban_command, inspect_daoban_outputs
from app.services.runners.router import AgentRunnerRouter
from app.services.task_classifier import DAOBAN_TASK_TYPE, PPT_TASK_TYPE, MemoryAction, TaskKind, classify_task
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
            ("mysql-analysis", "mysql-analysis", "/home/cy/.openclaw/workspace-huizong-ceshi"),
            ("mysql", "mysql", "/home/cy/.openclaw/workspace-huizong-ceshi"),
            ("ppt_generation", "ppt-generation", "/home/cy/.openclaw/workspace-PPT-Generation"),
            ("pptmaster", "ppt-master", "/home/cy/.openclaw/workspace-PPT-Generation"),
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

    def test_task_classifier_ppt_text_intent_runs_local_job(self) -> None:
        with self.session_factory() as db:
            user, agent, conversation = self._seed_ppt_user_agent_conversation(db)
            result = classify_task(
                db,
                user=user,
                agent=agent,
                conversation_id=conversation.id,
                content="生成一个厨房餐具相关的3页的商品目录册PPT",
                files=[],
            )
            self.assertEqual(result.task_kind, TaskKind.long_job)
            self.assertEqual(result.runner, "ppt_generation_job")
            self.assertEqual(result.task_type, PPT_TASK_TYPE)
            self.assertEqual(result.effective_file_ids, [])

    def test_task_classifier_ppt_plain_chat_stays_gateway(self) -> None:
        with self.session_factory() as db:
            user, agent, conversation = self._seed_ppt_user_agent_conversation(db)
            result = classify_task(
                db,
                user=user,
                agent=agent,
                conversation_id=conversation.id,
                content="你好，介绍一下自己",
                files=[],
            )
            self.assertEqual(result.task_kind, TaskKind.short_chat)
            self.assertEqual(result.runner, "gateway_chat")

    def test_task_classifier_ppt_file_only_saves_pending(self) -> None:
        with self.session_factory() as db:
            user, agent, conversation = self._seed_ppt_user_agent_conversation(db)
            source = self._file(user.id, 22, "catalog.xlsx", file_type="xlsx", mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            result = classify_task(db, user=user, agent=agent, conversation_id=conversation.id, content="", files=[source])
            self.assertEqual(result.task_kind, TaskKind.pending_input)
            self.assertEqual(result.memory_action, MemoryAction.save_files)
            self.assertEqual(result.effective_file_ids, [22])
            self.assertIn("已收到资料", result.response_message or "")

    def test_task_classifier_ppt_text_after_pending_file_merges_file_ids(self) -> None:
        with self.session_factory() as db:
            user, agent, conversation = self._seed_ppt_user_agent_conversation(db)
            pending = save_pending_files(
                db,
                user=user,
                conversation_id=conversation.id,
                agent=agent,
                task_type=PPT_TASK_TYPE,
                file_ids=[22],
            )
            result = classify_task(
                db,
                user=user,
                agent=agent,
                conversation_id=conversation.id,
                content="根据刚才资料，生成一个5页英文商品目录册PPT，风格简洁商务",
                files=[],
            )
            self.assertEqual(result.task_kind, TaskKind.long_job)
            self.assertEqual(result.runner, "ppt_generation_job")
            self.assertEqual(result.memory_action, MemoryAction.consume_pending)
            self.assertEqual(result.pending_task.id, pending.id)
            self.assertEqual(result.effective_file_ids, [22])

    def test_task_classifier_ppt_incomplete_text_saves_pending(self) -> None:
        with self.session_factory() as db:
            user, agent, conversation = self._seed_ppt_user_agent_conversation(db)
            result = classify_task(
                db,
                user=user,
                agent=agent,
                conversation_id=conversation.id,
                content="等下按这个做 PPT",
                files=[],
            )
            self.assertEqual(result.task_kind, TaskKind.pending_input)
            self.assertEqual(result.memory_action, MemoryAction.save_text)

    def test_ppt_runner_builds_command_and_parses_json(self) -> None:
        command = build_ppt_generation_command(
            workspace=Path("/home/cy/.openclaw/workspace-PPT-Generation"),
            prompt="生成3页PPT",
            sender_name="Alice",
            sender_open_id="7",
        )
        self.assertIn("scripts/generate_catalog_ppt.py", command)
        self.assertIn("--prompt", command)
        self.assertIn("生成3页PPT", command)
        self.assertNotIn(" ".join(command), command)

        data = extract_json_object('log line\n{"ok": true, "reply_text": "Z:\\\\yaq\\\\ppt\\\\catalog\\\\demo.pptx", "validation": {"ok": true}}')
        self.assertTrue(data["ok"])
        self.assertEqual(ppt_success_text(data), "Z:\\yaq\\ppt\\catalog\\demo.pptx")
        self.assertEqual(
            ppt_failure_text({"ok": False, "error": "图片生成失败"}),
            "PPT 生成失败：图片生成失败",
        )

    def test_ppt_runner_env_prefers_workspace_venv_for_nested_python(self) -> None:
        with tempfile.TemporaryDirectory() as workspace_dir:
            workspace = Path(workspace_dir)
            venv_bin = workspace / ".venv" / ("Scripts" if os.name == "nt" else "bin")
            venv_bin.mkdir(parents=True)

            env = build_ppt_generation_env(
                workspace,
                base_env={
                    "PATH": "/usr/bin",
                    "PYTHONHOME": "/unexpected/python",
                },
            )

            self.assertEqual(env["PATH"].split(os.pathsep)[0], str(venv_bin))
            self.assertEqual(env["VIRTUAL_ENV"], str(workspace / ".venv"))
            self.assertEqual(env["PYTHONUNBUFFERED"], "1")
            self.assertNotIn("PYTHONHOME", env)

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

    def test_router_selects_ppt_runner_without_gateway(self) -> None:
        from app.models.task_run import TaskRun, TaskRunStatus

        agent = Agent(
            id=3,
            code="ppt_generation",
            name="PPT 生成 Agent",
            openclaw_agent_id="ppt-generation",
            risk_level=AgentRiskLevel.medium,
        )
        run = TaskRun(
            id=8,
            user_id=1,
            agent_id=agent.id,
            conversation_id=1,
            status=TaskRunStatus.queued,
            input_text="生成3页PPT",
            run_type="job",
            priority=100,
            runner_name="ppt_generation_job",
        )
        self.assertEqual(AgentRunnerRouter().select_runner(run=run, agent=agent).name, "ppt_generation_job")

    def test_task_classifier_mysql_help_stays_gateway(self) -> None:
        with self.session_factory() as db:
            user, agent, conversation = self._seed_mysql_user_agent_conversation(db)
            result = classify_task(
                db,
                user=user,
                agent=agent,
                conversation_id=conversation.id,
                content="你是谁",
                files=[],
            )
            self.assertEqual(result.task_kind, TaskKind.short_chat)
            self.assertEqual(result.runner, "gateway_chat")

    def test_task_classifier_mysql_report_missing_date_is_pending_input(self) -> None:
        with self.session_factory() as db:
            user, agent, conversation = self._seed_mysql_user_agent_conversation(db)
            result = classify_task(
                db,
                user=user,
                agent=agent,
                conversation_id=conversation.id,
                content="帮我统计供应商出货采购金额",
                files=[],
            )
            self.assertEqual(result.task_kind, TaskKind.pending_input)
            self.assertEqual(result.runner, "pending_input")
            self.assertEqual(result.task_type, MYSQL_ANALYSIS_TASK_TYPE)
            self.assertIn("需要开始日期和结束日期", result.response_message or "")

    def test_task_classifier_mysql_report_runs_local_job(self) -> None:
        with self.session_factory() as db:
            user, agent, conversation = self._seed_mysql_user_agent_conversation(db)
            result = classify_task(
                db,
                user=user,
                agent=agent,
                conversation_id=conversation.id,
                content="统计 2026-05-01 到 2026-05-31 的供应商出货采购金额，并生成 Excel 和图表",
                files=[],
            )
            self.assertEqual(result.task_kind, TaskKind.long_job)
            self.assertEqual(result.runner, "mysql_analysis_job")
            self.assertEqual(result.task_type, MYSQL_ANALYSIS_TASK_TYPE)
            self.assertEqual(result.metadata["mysql_analysis"]["start_date"], "2026-05-01")
            self.assertEqual(result.metadata["mysql_analysis"]["end_date"], "2026-05-31")

    def test_mysql_date_and_union_parsing(self) -> None:
        from datetime import datetime

        explicit = parse_mysql_analysis_request("统计 2026-05-01 到 2026-05-31 的供应商出货采购金额")
        self.assertEqual(explicit.start_date, "2026-05-01")
        self.assertEqual(explicit.end_date, "2026-05-31")

        chinese_month = parse_mysql_analysis_request("查一下 2026年5月供应商出货采购金额Top10")
        self.assertEqual(chinese_month.start_date, "2026-05-01")
        self.assertEqual(chinese_month.end_date, "2026-05-31")

        current_year = parse_mysql_analysis_request("今年5月供应商出货采购金额Top10", now=datetime(2026, 6, 8))
        self.assertEqual(current_year.start_date, "2026-05-01")
        self.assertEqual(current_year.default_year, 2026)

        month_only = parse_mysql_analysis_request("5月供应商出货采购金额Top10", now=datetime(2026, 6, 8))
        self.assertEqual(month_only.start_date, "2026-05-01")
        self.assertEqual(month_only.end_date, "2026-05-31")
        self.assertEqual(month_only.default_year, 2026)

        with_union = parse_mysql_analysis_request("统计 unionId=1001 在 2026-05-01 到 2026-05-31 的供应商 Top10")
        self.assertEqual(with_union.union_id, "1001")

    def test_mysql_runner_builds_safe_command(self) -> None:
        command = build_mysql_analysis_command(
            workspace=Path("/home/cy/.openclaw/workspace-huizong-ceshi"),
            start_date="2026-05-01",
            end_date="2026-05-31",
            union_id="1001",
            asker="Alice",
            question="统计 unionId=1001 在 2026-05-01 到 2026-05-31 的供应商 Top10",
        )
        self.assertIn("scripts/run_supplier_shipment_report.py", command)
        self.assertIn("--start-date", command)
        self.assertIn("2026-05-01", command)
        self.assertIn("--end-date", command)
        self.assertIn("--union-id", command)
        self.assertIn("1001", command)
        self.assertNotIn(" ".join(command), command)

    def test_router_selects_mysql_runner_without_gateway(self) -> None:
        from app.models.task_run import TaskRun, TaskRunStatus

        agent = Agent(
            id=5,
            code="mysql_analysis",
            name="MySQL 分析 Agent",
            openclaw_agent_id="huizong-ceshi",
            risk_level=AgentRiskLevel.high,
        )
        run = TaskRun(
            id=9,
            user_id=1,
            agent_id=agent.id,
            conversation_id=1,
            status=TaskRunStatus.queued,
            input_text="统计 2026-05-01 到 2026-05-31 的供应商出货采购金额",
            run_type="job",
            priority=100,
            runner_name="mysql_analysis_job",
        )
        self.assertEqual(AgentRunnerRouter().select_runner(run=run, agent=agent).name, "mysql_analysis_job")

    def test_mysql_success_text_and_sanitizer(self) -> None:
        from datetime import datetime

        parsed = parse_mysql_analysis_request("统计 5月供应商出货采购金额", now=datetime(2026, 6, 8))
        with tempfile.TemporaryDirectory() as output_dir:
            root = Path(output_dir)
            (root / "report_summary.md").write_text("摘要", encoding="utf-8")
            (root / "run_meta.json").write_text("{}", encoding="utf-8")
            text = build_mysql_success_text(parsed_request=parsed, output_dir=root, report_summary="摘要")
            self.assertIn("供应商出货统计完成", text)
            self.assertIn("已按 2026 年 5 月处理", text)
            self.assertIn("report_summary.md", text)

        sanitized = sanitize_mysql_analysis_text("MYSQL_PASSWORD=abc token:secret mysql+pymysql://u:p@host/db")
        self.assertNotIn("abc", sanitized)
        self.assertNotIn("secret", sanitized)
        self.assertNotIn(":p@", sanitized)

    def test_mysql_output_root_is_allowed_when_env_configured(self) -> None:
        old_value = os.environ.get("MYSQL_ANALYSIS_OUTPUT_ROOT")
        try:
            with tempfile.TemporaryDirectory() as output_root:
                os.environ["MYSQL_ANALYSIS_OUTPUT_ROOT"] = output_root
                roots = _allowed_output_roots(7)
                self.assertIn(Path(output_root).resolve(), roots)
        finally:
            if old_value is None:
                os.environ.pop("MYSQL_ANALYSIS_OUTPUT_ROOT", None)
            else:
                os.environ["MYSQL_ANALYSIS_OUTPUT_ROOT"] = old_value


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

    def _seed_ppt_user_agent_conversation(self, db):
        user = User(
            id=7,
            username="alice",
            password_hash="x",
            display_name="Alice",
            status=UserStatus.active,
            role=UserRole.user,
        )
        agent = Agent(
            id=4,
            code="ppt_generation",
            name="PPT 生成 Agent",
            openclaw_agent_id="ppt-generation",
            risk_level=AgentRiskLevel.medium,
            workspace_path="/home/cy/.openclaw/workspace-PPT-Generation",
            execution_mode="job",
        )
        conversation = Conversation(
            id=20,
            user_id=user.id,
            agent_id=agent.id,
            title="PPT",
            session_key="web:7:ppt_generation:20",
        )
        db.add_all([user, agent, conversation])
        db.commit()
        return user, agent, conversation

    def _seed_mysql_user_agent_conversation(self, db):
        user = User(
            id=7,
            username="alice",
            password_hash="x",
            display_name="Alice",
            status=UserStatus.active,
            role=UserRole.user,
        )
        agent = Agent(
            id=5,
            code="mysql_analysis",
            name="MySQL 分析 Agent",
            openclaw_agent_id="huizong-ceshi",
            risk_level=AgentRiskLevel.high,
            workspace_path="/home/cy/.openclaw/workspace-huizong-ceshi",
            execution_mode="auto",
        )
        conversation = Conversation(
            id=21,
            user_id=user.id,
            agent_id=agent.id,
            title="MySQL",
            session_key="web:7:mysql_analysis:21",
        )
        db.add_all([user, agent, conversation])
        db.commit()
        return user, agent, conversation

    def _file(
        self,
        user_id: int,
        file_id: int,
        name: str,
        *,
        file_type: str = "pdf",
        mime_type: str = "application/pdf",
    ) -> File:
        return File(
            id=file_id,
            user_id=user_id,
            original_name=name,
            stored_path=f"/tmp/{name}",
            file_type=file_type,
            mime_type=mime_type,
            file_size=4,
            purpose=FilePurpose.upload,
            status="ready",
        )


if __name__ == "__main__":
    unittest.main()

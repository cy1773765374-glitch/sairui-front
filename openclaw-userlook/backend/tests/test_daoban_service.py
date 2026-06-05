import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.core.database import Base
from app.models.agent import Agent, AgentRiskLevel
from app.models.file import File, FilePurpose
from app.models.task_run import TaskRun, TaskRunStatus
from app.models.user import User, UserRole, UserStatus
from app.services.daoban_service import is_daoban_agent, require_daoban_pdf, sync_daoban_files_to_workspace


class DaobanServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:", future=True)
        Base.metadata.create_all(engine)
        self.session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def test_is_daoban_agent_matches_known_aliases(self) -> None:
        for code, name, openclaw_agent_id in [
            ("image_daoban", "刀版合成 Agent", "image-daoban"),
            ("image-daoban", "Image Daoban", "main"),
            ("daoban", "Daoban", "main"),
            ("workspace-image-daoban", "Workspace", "main"),
            ("main", "刀版合成", "main"),
        ]:
            self.assertTrue(
                is_daoban_agent(
                    Agent(
                        id=3,
                        code=code,
                        name=name,
                        openclaw_agent_id=openclaw_agent_id,
                        risk_level=AgentRiskLevel.medium,
                    )
                )
            )

    def test_require_daoban_pdf_rejects_non_pdf_files(self) -> None:
        with self.assertRaises(HTTPException) as context:
            require_daoban_pdf(
                [
                    File(
                        id=10,
                        user_id=7,
                        original_name="ref.png",
                        stored_path="/tmp/ref.png",
                        file_type="png",
                        mime_type="image/png",
                        file_size=3,
                        purpose=FilePurpose.upload,
                    )
                ]
            )

        self.assertEqual(context.exception.status_code, 400)
        self.assertEqual(context.exception.detail["code"], "DAOBAN_PDF_REQUIRED")

    def test_sync_daoban_files_to_workspace_copies_files_and_builds_payload(self) -> None:
        with tempfile.TemporaryDirectory() as upload_root, tempfile.TemporaryDirectory() as workspace_root:
            with patch.dict(os.environ, {"OPENCLAW_DAOBAN_WORKSPACE": workspace_root}):
                get_settings.cache_clear()
                try:
                    source_pdf = Path(upload_root) / "圣诞树挂卡.pdf"
                    source_pdf.write_bytes(b"%PDF")
                    source_png = Path(upload_root) / "ref.png"
                    source_png.write_bytes(b"png")

                    with self.session_factory() as db:
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
                            name="刀版合成 Agent",
                            openclaw_agent_id="image-daoban",
                            risk_level=AgentRiskLevel.medium,
                        )
                        pdf = File(
                            id=10,
                            user_id=user.id,
                            original_name="圣诞树挂卡.pdf",
                            stored_path=str(source_pdf),
                            file_type="pdf",
                            mime_type="application/pdf",
                            file_size=4,
                            purpose=FilePurpose.upload,
                            status="ready",
                        )
                        image = File(
                            id=11,
                            user_id=user.id,
                            original_name="ref.png",
                            stored_path=str(source_png),
                            file_type="png",
                            mime_type="image/png",
                            file_size=3,
                            purpose=FilePurpose.upload,
                            status="ready",
                        )
                        db.add_all([user, agent, pdf, image])
                        db.commit()
                        run = TaskRun(
                            id=63,
                            user_id=user.id,
                            agent_id=agent.id,
                            conversation_id=19,
                            status=TaskRunStatus.queued,
                            input_text="山水插画",
                            run_type="chat",
                            priority=100,
                        )

                        gateway_files, payload = sync_daoban_files_to_workspace(
                            db,
                            run=run,
                            agent=agent,
                            content="山水插画",
                            files=[pdf, image],
                        )

                        self.assertTrue(Path(pdf.workspace_path).is_file())
                        self.assertTrue(Path(image.workspace_path).is_file())
                        self.assertIn("run-63", pdf.workspace_path)
                        self.assertEqual(payload["daoban"]["pdf_path"], pdf.workspace_path)
                        self.assertEqual(payload["daoban"]["prompt"], "山水插画")
                        self.assertEqual(gateway_files[0]["path"], pdf.workspace_path)
                        self.assertEqual(gateway_files[0]["storage_path"], str(source_pdf.resolve()))
                finally:
                    get_settings.cache_clear()


if __name__ == "__main__":
    unittest.main()

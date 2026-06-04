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
from app.models.file import File, FilePurpose
from app.models.user import User, UserRole, UserStatus
from app.services.file_service import list_gateway_upload_files, validate_user_upload_file_ids


class FileServiceUploadValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:", future=True)
        Base.metadata.create_all(engine)
        self.session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def test_validate_user_upload_file_ids_skips_empty_and_reports_invalid_ids(self) -> None:
        with self.session_factory() as db:
            user, other_user = self._seed_users(db)
            owned_file = File(
                id=10,
                user_id=user.id,
                original_name="report.pdf",
                stored_path="/tmp/report.pdf",
                file_type="pdf",
                mime_type="application/pdf",
                file_size=100,
                purpose=FilePurpose.upload,
            )
            other_file = File(
                id=11,
                user_id=other_user.id,
                original_name="other.pdf",
                stored_path="/tmp/other.pdf",
                file_type="pdf",
                mime_type="application/pdf",
                file_size=100,
                purpose=FilePurpose.upload,
            )
            db.add_all([owned_file, other_file])
            db.commit()

            validate_user_upload_file_ids(db, user, [])
            validate_user_upload_file_ids(db, user, [owned_file.id])

            with self.assertRaises(HTTPException) as context:
                validate_user_upload_file_ids(db, user, [owned_file.id, other_file.id, 99])

            self.assertEqual(context.exception.status_code, 400)
            self.assertEqual(context.exception.detail["code"], "INVALID_UPLOAD_FILES")
            self.assertEqual(context.exception.detail["invalid_file_ids"], [other_file.id, 99])

    def test_list_gateway_upload_files_uses_real_stored_path_and_mime_type(self) -> None:
        with tempfile.TemporaryDirectory() as upload_root:
            with patch.dict(os.environ, {"USER_UPLOAD_ROOT": upload_root}):
                get_settings.cache_clear()
                try:
                    stored_path = Path(upload_root) / "7" / "20260604" / "source.pdf"
                    stored_path.parent.mkdir(parents=True)
                    stored_path.write_bytes(b"pdf")

                    with self.session_factory() as db:
                        user, _ = self._seed_users(db)
                        file = File(
                            id=10,
                            user_id=user.id,
                            original_name="source.pdf",
                            stored_path=str(stored_path),
                            file_type="pdf",
                            mime_type="application/pdf",
                            file_size=3,
                            purpose=FilePurpose.upload,
                        )
                        db.add(file)
                        db.commit()

                        file_id = file.id
                        gateway_files = list_gateway_upload_files(db, user, [file.id])

                    self.assertEqual(gateway_files[0]["id"], file_id)
                    self.assertEqual(gateway_files[0]["path"], str(stored_path.resolve()))
                    self.assertEqual(gateway_files[0]["file_type"], "pdf")
                    self.assertEqual(gateway_files[0]["file_size"], 3)
                finally:
                    get_settings.cache_clear()

    def _seed_users(self, db):
        user = User(
            id=7,
            username="alice",
            password_hash="x",
            display_name="Alice",
            status=UserStatus.active,
            role=UserRole.user,
        )
        other_user = User(
            id=8,
            username="bob",
            password_hash="x",
            display_name="Bob",
            status=UserStatus.active,
            role=UserRole.user,
        )
        db.add_all([user, other_user])
        db.commit()
        return user, other_user


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.file import File, FilePurpose
from app.models.user import User, UserRole
from app.schemas.file import FileRead

ALLOWED_EXTENSIONS = {
    "txt",
    "md",
    "doc",
    "docx",
    "xls",
    "xlsx",
    "ppt",
    "pptx",
    "pdf",
    "png",
    "jpg",
    "jpeg",
}

SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._ -]+")
CHUNK_SIZE = 1024 * 1024


def _resolve_root(root: str) -> Path:
    return Path(root).expanduser().resolve()


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _safe_filename(filename: str) -> str:
    name = Path(filename or "upload").name
    safe = SAFE_FILENAME_RE.sub("_", name).strip(" .")
    return safe or "upload"


def _extension(filename: str) -> str:
    return Path(filename).suffix.lower().lstrip(".")


def _ensure_allowed_file(filename: str) -> str:
    ext = _extension(filename)
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="unsupported file type",
        )
    return ext


def file_to_read(file: File) -> FileRead:
    return FileRead(
        id=file.id,
        user_id=file.user_id,
        original_name=file.original_name,
        file_type=file.file_type,
        file_size=file.file_size,
        purpose=file.purpose,
        created_at=file.created_at,
        download_url=f"/api/files/{file.id}/download",
    )


def list_files(db: Session, current_user: User) -> list[FileRead]:
    statement = select(File).order_by(File.created_at.desc(), File.id.desc())
    if current_user.role != UserRole.admin:
        statement = statement.where(File.user_id == current_user.id)
    return [file_to_read(file) for file in db.scalars(statement)]


def validate_user_upload_file_ids(db: Session, current_user: User, file_ids: list[int]) -> None:
    if not file_ids:
        return

    unique_file_ids = set(file_ids)
    owned_file_ids = set(
        db.scalars(
            select(File.id).where(
                File.id.in_(unique_file_ids),
                File.user_id == current_user.id,
                File.purpose == FilePurpose.upload,
            )
        )
    )
    if owned_file_ids != unique_file_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid file_ids",
        )


async def save_upload_file(db: Session, current_user: User, upload: UploadFile) -> FileRead:
    settings = get_settings()
    original_name = Path(upload.filename or "upload").name
    safe_name = _safe_filename(original_name)
    ext = _ensure_allowed_file(safe_name)
    max_bytes = settings.max_upload_mb * 1024 * 1024

    root = _resolve_root(settings.user_upload_root)
    date_part = datetime.now().strftime("%Y%m%d")
    user_dir = (root / str(current_user.id) / date_part).resolve()
    if not _is_relative_to(user_dir, root):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid upload path")

    user_dir.mkdir(parents=True, exist_ok=True)
    target_path = (user_dir / f"{uuid4().hex}_{safe_name}").resolve()
    if not _is_relative_to(target_path, root):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid upload path")

    size = 0
    try:
        with target_path.open("wb") as target:
            while chunk := await upload.read(CHUNK_SIZE):
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail="file too large",
                    )
                target.write(chunk)
    except Exception:
        if target_path.exists():
            target_path.unlink()
        raise
    finally:
        await upload.close()

    file = File(
        user_id=current_user.id,
        original_name=original_name,
        stored_path=str(target_path),
        file_type=ext,
        file_size=size,
        purpose=FilePurpose.upload,
    )
    db.add(file)
    db.commit()
    db.refresh(file)
    return file_to_read(file)


def get_downloadable_file(db: Session, current_user: User, file_id: int) -> tuple[File, Path]:
    file = db.get(File, file_id)
    if file is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="file not found")

    if current_user.role != UserRole.admin and file.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="file not found")

    settings = get_settings()
    if file.purpose == FilePurpose.upload:
        root = _resolve_root(settings.user_upload_root)
    elif file.purpose == FilePurpose.output:
        root = _resolve_root(settings.user_output_root)
    else:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="file not found")

    stored_path = Path(file.stored_path).expanduser().resolve()
    if not _is_relative_to(stored_path, root) or not stored_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="file not found")

    return file, stored_path


def build_run_output_dir(user_id: int, run_id: int) -> str:
    settings = get_settings()
    root = _resolve_root(settings.user_output_root)
    date_part = datetime.now().strftime("%Y%m%d")
    output_dir = (root / str(user_id) / date_part / f"run_{run_id}").resolve()
    if not _is_relative_to(output_dir, root):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid output path")
    output_dir.mkdir(parents=True, exist_ok=True)
    return str(output_dir)


def register_output_files(db: Session, user_id: int, output_dir: str | None) -> list[FileRead]:
    if not output_dir:
        return []

    settings = get_settings()
    root = _resolve_root(settings.user_output_root)
    user_root = (root / str(user_id)).resolve()
    directory = Path(output_dir).expanduser().resolve()
    if not _is_relative_to(directory, user_root) or not directory.is_dir():
        return []

    existing_paths = set(
        db.scalars(
            select(File.stored_path).where(
                File.user_id == user_id,
                File.purpose == FilePurpose.output,
            )
        )
    )
    created: list[File] = []
    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue
        resolved = path.resolve()
        if not _is_relative_to(resolved, user_root) or str(resolved) in existing_paths:
            continue
        ext = _extension(resolved.name)
        if ext not in ALLOWED_EXTENSIONS:
            continue
        file = File(
            user_id=user_id,
            original_name=resolved.name,
            stored_path=str(resolved),
            file_type=ext,
            file_size=resolved.stat().st_size,
            purpose=FilePurpose.output,
        )
        db.add(file)
        created.append(file)

    if created:
        db.commit()
        for file in created:
            db.refresh(file)

    return [file_to_read(file) for file in created]


def list_output_files_for_dir(db: Session, user_id: int, output_dir: str | None) -> list[FileRead]:
    if not output_dir:
        return []

    settings = get_settings()
    root = _resolve_root(settings.user_output_root)
    user_root = (root / str(user_id)).resolve()
    directory = Path(output_dir).expanduser().resolve()
    if not _is_relative_to(directory, user_root):
        return []

    files = db.scalars(
        select(File)
        .where(
            File.user_id == user_id,
            File.purpose == FilePurpose.output,
        )
        .order_by(File.created_at.desc(), File.id.desc())
    )
    return [
        file_to_read(file)
        for file in files
        if _is_relative_to(Path(file.stored_path).expanduser().resolve(), directory)
    ]

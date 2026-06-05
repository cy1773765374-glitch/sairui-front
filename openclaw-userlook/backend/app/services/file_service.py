from __future__ import annotations

import re
import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.file import File, FilePurpose, FileStatus
from app.models.user import User, UserRole
from app.schemas.file import FileRead

ALLOWED_EXTENSIONS = {
    "txt",
    "text",
    "md",
    "markdown",
    "csv",
    "tsv",
    "json",
    "jsonl",
    "yaml",
    "yml",
    "xml",
    "html",
    "htm",
    "log",
    "rtf",
    "doc",
    "docx",
    "odt",
    "xls",
    "xlsx",
    "ods",
    "ppt",
    "pptx",
    "odp",
    "pdf",
    "zip",
    "rar",
    "7z",
    "tar",
    "gz",
    "png",
    "jpg",
    "jpeg",
    "gif",
    "webp",
    "bmp",
    "tif",
    "tiff",
    "svg",
    "heic",
    "heif",
}

SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._ -]+")
CHUNK_SIZE = 1024 * 1024
INVALID_FILE_IDS_DETAIL = "上传文件记录无效，请重新上传后再发送"
INVALID_FILE_IDS_CODE = "INVALID_FILE_RECORD"
MISSING_UPLOAD_FILE_DETAIL = "上传文件内容不存在，请重新上传"
READY_FILE_STATUSES = {
    FileStatus.ready.value,
    FileStatus.uploaded.value,
    FileStatus.available.value,
}

logger = logging.getLogger(__name__)


def _resolve_root(root: str) -> Path:
    return Path(root).expanduser().resolve()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _allowed_output_roots(user_id: int) -> list[Path]:
    settings = get_settings()
    roots = [(_resolve_root(settings.user_output_root) / str(user_id)).resolve()]
    daoban_root = _resolve_root(settings.openclaw_daoban_output_root)
    if daoban_root not in roots:
        roots.append(daoban_root)
    return roots


def _is_under_any(path: Path, roots: list[Path]) -> bool:
    return any(_is_relative_to(path, root) for root in roots)


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


def _invalid_upload_files_exception(invalid_file_ids: list[int]) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={
            "code": INVALID_FILE_IDS_CODE,
            "message": INVALID_FILE_IDS_DETAIL,
            "detail": INVALID_FILE_IDS_DETAIL,
            "invalid_file_ids": invalid_file_ids,
        },
    )


def file_to_read(file: File) -> FileRead:
    return FileRead(
        id=file.id,
        user_id=file.user_id,
        conversation_id=file.conversation_id,
        agent_code=file.agent_code,
        original_name=file.original_name,
        stored_name=file.stored_name or Path(file.stored_path).name,
        file_type=file.file_type,
        mime_type=file.mime_type,
        file_size=file.file_size,
        sha256=file.sha256,
        status=file.status or FileStatus.ready.value,
        workspace_path=file.workspace_path,
        purpose=file.purpose,
        created_at=file.created_at,
        updated_at=getattr(file, "updated_at", None),
        download_url=f"/api/files/{file.id}/download",
    )


def list_files(db: Session, current_user: User) -> list[FileRead]:
    statement = select(File).where(File.deleted_at.is_(None)).order_by(File.created_at.desc(), File.id.desc())
    if current_user.role != UserRole.admin:
        statement = statement.where(File.user_id == current_user.id)
    return [file_to_read(file) for file in db.scalars(statement)]


def _missing_upload_content_exception(file_id: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_410_GONE,
        detail={
            "code": "FILE_CONTENT_MISSING",
            "message": MISSING_UPLOAD_FILE_DETAIL,
            "detail": MISSING_UPLOAD_FILE_DETAIL,
            "file_id": file_id,
        },
    )


def _file_not_ready_exception(file: File) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "FILE_NOT_READY",
            "message": "文件仍在上传或处理，请稍后再发送",
            "detail": "文件仍在上传或处理，请稍后再发送",
            "file_id": file.id,
        },
    )


def _file_conversation_mismatch_exception(file: File) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "FILE_CONVERSATION_MISMATCH",
            "message": "该文件不属于当前会话，请重新上传",
            "detail": "该文件不属于当前会话，请重新上传",
            "file_id": file.id,
        },
    )


def _ordered_files_by_ids(files: list[File], file_ids: list[int]) -> list[File]:
    files_by_id = {file.id: file for file in files}
    return [files_by_id[file_id] for file_id in file_ids if file_id in files_by_id]


def _resolve_upload_path(file: File, root: Path) -> Path:
    stored_path = Path(file.stored_path).expanduser().resolve()
    if not _is_relative_to(stored_path, root) or not stored_path.is_file():
        raise _missing_upload_content_exception(file.id)
    return stored_path


def validate_and_bind_upload_files(
    db: Session,
    current_user: User,
    conversation_id: int,
    file_ids: list[int],
) -> list[File]:
    if not file_ids:
        return []

    unique_file_ids = list(dict.fromkeys(file_ids))
    files = list(
        db.scalars(
            select(File).where(
                File.id.in_(unique_file_ids),
                File.user_id == current_user.id,
                File.purpose == FilePurpose.upload,
                File.deleted_at.is_(None),
            )
        )
    )
    files_by_id = {file.id: file for file in files}
    invalid_file_ids = [file_id for file_id in unique_file_ids if file_id not in files_by_id]
    if invalid_file_ids:
        logger.warning("[file-validate] missing file_ids=%s user_id=%s", invalid_file_ids, current_user.id)
        raise _invalid_upload_files_exception(invalid_file_ids)

    settings = get_settings()
    root = _resolve_root(settings.user_upload_root)
    for file_id in unique_file_ids:
        file = files_by_id[file_id]
        if (file.status or FileStatus.ready.value) not in READY_FILE_STATUSES:
            raise _file_not_ready_exception(file)
        _resolve_upload_path(file, root)
        if file.conversation_id is None:
            file.conversation_id = conversation_id
            logger.info("[file-bind] file_id=%s conversation_id=%s", file.id, conversation_id)
        elif file.conversation_id != conversation_id:
            raise _file_conversation_mismatch_exception(file)

    db.flush()
    return _ordered_files_by_ids(files, unique_file_ids)


def validate_user_upload_file_ids(db: Session, current_user: User, file_ids: list[int]) -> None:
    if not file_ids:
        return

    unique_file_ids = list(dict.fromkeys(file_ids))
    owned_file_ids = set(
        db.scalars(
            select(File.id).where(
                File.id.in_(unique_file_ids),
                File.user_id == current_user.id,
                File.purpose == FilePurpose.upload,
                File.deleted_at.is_(None),
            )
        )
    )
    invalid_file_ids = [file_id for file_id in unique_file_ids if file_id not in owned_file_ids]
    if invalid_file_ids:
        raise _invalid_upload_files_exception(invalid_file_ids)


def files_to_gateway_payload(files: list[File], *, prefer_workspace_path: bool = False) -> list[dict[str, object]]:
    gateway_files: list[dict[str, object]] = []
    for file in files:
        stored_path = str(Path(file.stored_path).expanduser().resolve())
        workspace_path = file.workspace_path
        effective_path = workspace_path if prefer_workspace_path and workspace_path else stored_path
        gateway_files.append(
            {
                "id": file.id,
                "name": file.original_name,
                "original_name": file.original_name,
                "stored_name": file.stored_name or Path(file.stored_path).name,
                "file_type": file.file_type,
                "mime_type": file.mime_type,
                "file_size": file.file_size,
                "size": file.file_size,
                "path": effective_path,
                "stored_path": stored_path,
                "storage_path": stored_path,
                "workspace_path": workspace_path,
                "purpose": file.purpose.value,
                "status": file.status or FileStatus.ready.value,
            }
        )
    return gateway_files


def list_gateway_upload_files(
    db: Session,
    current_user: User,
    file_ids: list[int],
    *,
    prefer_workspace_path: bool = False,
) -> list[dict[str, object]]:
    if not file_ids:
        return []

    settings = get_settings()
    root = _resolve_root(settings.user_upload_root)
    unique_file_ids = list(dict.fromkeys(file_ids))
    files = list(
        db.scalars(
            select(File).where(
                File.id.in_(unique_file_ids),
                File.user_id == current_user.id,
                File.purpose == FilePurpose.upload,
                File.deleted_at.is_(None),
            )
        )
    )
    files_by_id = {file.id: file for file in files}
    if set(files_by_id) != set(unique_file_ids):
        invalid_file_ids = [file_id for file_id in unique_file_ids if file_id not in files_by_id]
        raise _invalid_upload_files_exception(invalid_file_ids)

    ordered_files: list[File] = []
    for file_id in unique_file_ids:
        file = files_by_id[file_id]
        if (file.status or FileStatus.ready.value) not in READY_FILE_STATUSES:
            raise _file_not_ready_exception(file)
        _resolve_upload_path(file, root)
        if prefer_workspace_path and file.workspace_path:
            workspace_path = Path(file.workspace_path).expanduser()
            if not workspace_path.is_file():
                raise HTTPException(
                    status_code=status.HTTP_410_GONE,
                    detail={
                        "code": "DAOBAN_WORKSPACE_FILE_MISSING",
                        "message": "刀版文件未同步到 OpenClaw 工作区，请重新上传",
                        "detail": "刀版文件未同步到 OpenClaw 工作区，请重新上传",
                        "file_id": file.id,
                    },
                )
        ordered_files.append(file)
    return files_to_gateway_payload(ordered_files, prefer_workspace_path=prefer_workspace_path)


async def save_upload_file(
    db: Session,
    current_user: User,
    upload: UploadFile,
    *,
    agent_code: str | None = None,
) -> FileRead:
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
    digest = hashlib.sha256()
    try:
        with target_path.open("wb") as target:
            while chunk := await upload.read(CHUNK_SIZE):
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail="file too large",
                    )
                digest.update(chunk)
                target.write(chunk)
    except Exception:
        if target_path.exists():
            target_path.unlink()
        raise
    finally:
        await upload.close()

    file = File(
        user_id=current_user.id,
        agent_code=agent_code or None,
        original_name=original_name,
        stored_name=target_path.name,
        stored_path=str(target_path),
        file_type=ext,
        mime_type=upload.content_type,
        file_size=size,
        sha256=digest.hexdigest(),
        status=FileStatus.ready.value,
        purpose=FilePurpose.upload,
    )
    db.add(file)
    db.commit()
    db.refresh(file)
    logger.info(
        "[file-upload] user_id=%s file_id=%s agent=%s name=%s storage_path=%s",
        current_user.id,
        file.id,
        agent_code or "",
        file.original_name,
        file.stored_path,
    )
    return file_to_read(file)


def get_downloadable_file(db: Session, current_user: User, file_id: int) -> tuple[File, Path]:
    file = db.get(File, file_id)
    if file is None or file.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="file not found")

    if current_user.role != UserRole.admin and file.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="file not found")

    settings = get_settings()
    if file.purpose == FilePurpose.upload:
        root = _resolve_root(settings.user_upload_root)
        stored_path = Path(file.stored_path).expanduser().resolve()
        if not _is_relative_to(stored_path, root) or not stored_path.is_file():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="file not found")
    elif file.purpose == FilePurpose.output:
        stored_path = Path(file.stored_path).expanduser().resolve()
        if not _is_under_any(stored_path, _allowed_output_roots(file.user_id)) or not stored_path.is_file():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="file not found")
    else:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="file not found")

    return file, stored_path


def delete_file(db: Session, current_user: User, file_id: int) -> None:
    file = db.get(File, file_id)
    if file is None or file.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="file not found")
    if current_user.role != UserRole.admin and file.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="file not found")
    if file.purpose not in {FilePurpose.upload, FilePurpose.output}:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="file not found")
    file.deleted_at = _utc_now()
    db.commit()


def batch_delete_files(db: Session, current_user: User, file_ids: list[int]) -> dict[str, list[object]]:
    deleted_ids: list[int] = []
    skipped: list[dict[str, object]] = []
    for file_id in list(dict.fromkeys(file_ids)):
        file = db.get(File, file_id)
        if file is None or file.deleted_at is not None:
            skipped.append({"id": file_id, "reason": "not_found"})
            continue
        if current_user.role != UserRole.admin and file.user_id != current_user.id:
            skipped.append({"id": file_id, "reason": "not_found"})
            continue
        if file.purpose not in {FilePurpose.upload, FilePurpose.output}:
            skipped.append({"id": file_id, "reason": "unsupported_purpose"})
            continue
        file.deleted_at = _utc_now()
        deleted_ids.append(file.id)
    if deleted_ids:
        db.commit()
    return {"deleted_ids": deleted_ids, "skipped": skipped}


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
    directory = Path(output_dir).expanduser().resolve()
    allowed_roots = _allowed_output_roots(user_id)
    if not _is_under_any(directory, allowed_roots) or not directory.is_dir():
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
        if not _is_under_any(resolved, allowed_roots) or str(resolved) in existing_paths:
            continue
        ext = _extension(resolved.name)
        if ext not in ALLOWED_EXTENSIONS:
            continue
        file = File(
            user_id=user_id,
            original_name=resolved.name,
            stored_path=str(resolved),
            file_type=ext,
            mime_type=None,
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
    directory = Path(output_dir).expanduser().resolve()
    allowed_roots = _allowed_output_roots(user_id)
    if not _is_under_any(directory, allowed_roots):
        return []

    files = db.scalars(
        select(File)
        .where(
            File.user_id == user_id,
            File.purpose == FilePurpose.output,
            File.deleted_at.is_(None),
        )
        .order_by(File.created_at.desc(), File.id.desc())
    )
    return [
        file_to_read(file)
        for file in files
        if _is_relative_to(Path(file.stored_path).expanduser().resolve(), directory)
    ]

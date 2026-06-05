from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.user import User
from app.schemas.file import BatchDeleteFilesRequest, BatchDeleteFilesResponse, FileRead, FileUploadResponse
from app.services.auth_service import get_current_user
from app.services.file_service import batch_delete_files, delete_file, get_downloadable_file, list_files, save_upload_file

router = APIRouter(prefix="/files", tags=["files"])


@router.get("", response_model=list[FileRead])
def get_files(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[FileRead]:
    return list_files(db, current_user)


@router.post("/upload", response_model=FileUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_file(
    upload: UploadFile = File(...),
    agent_code: str | None = Form(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FileUploadResponse:
    file = await save_upload_file(db, current_user, upload, agent_code=agent_code)
    return FileUploadResponse(
        id=file.id,
        file_id=file.id,
        name=file.original_name,
        original_name=file.original_name,
        size=file.file_size,
        mime_type=file.mime_type,
        status=file.status,
        workspace_path=file.workspace_path,
        file=file,
    )


@router.get("/{file_id}/download")
def download_file(
    file_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FileResponse:
    file, path = get_downloadable_file(db, current_user, file_id)
    return FileResponse(path=path, filename=file.original_name, media_type="application/octet-stream")


@router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_existing_file(
    file_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    delete_file(db, current_user, file_id)


@router.post("/batch-delete", response_model=BatchDeleteFilesResponse)
def batch_delete_existing_files(
    payload: BatchDeleteFilesRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BatchDeleteFilesResponse:
    return BatchDeleteFilesResponse(**batch_delete_files(db, current_user, payload.file_ids))

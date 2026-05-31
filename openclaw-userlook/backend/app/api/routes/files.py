from fastapi import APIRouter, Depends, File, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.user import User
from app.schemas.file import FileRead, FileUploadResponse
from app.services.auth_service import get_current_user
from app.services.file_service import get_downloadable_file, list_files, save_upload_file

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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FileUploadResponse:
    file = await save_upload_file(db, current_user, upload)
    return FileUploadResponse(file_id=file.id, file=file)


@router.get("/{file_id}/download")
def download_file(
    file_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FileResponse:
    file, path = get_downloadable_file(db, current_user, file_id)
    return FileResponse(path=path, filename=file.original_name, media_type="application/octet-stream")

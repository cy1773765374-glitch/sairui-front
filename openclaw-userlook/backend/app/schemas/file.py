from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.file import FilePurpose


class FileRead(BaseModel):
    id: int
    user_id: int
    original_name: str
    file_type: str
    file_size: int
    purpose: FilePurpose
    created_at: datetime
    download_url: str

    model_config = ConfigDict(from_attributes=True)


class FileUploadResponse(BaseModel):
    file_id: int
    file: FileRead

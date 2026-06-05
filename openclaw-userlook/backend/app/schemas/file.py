from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.file import FilePurpose


class FileRead(BaseModel):
    id: int
    user_id: int
    conversation_id: int | None = None
    agent_code: str | None = None
    original_name: str
    stored_name: str | None = None
    file_type: str
    mime_type: str | None = None
    file_size: int
    sha256: str | None = None
    status: str = "ready"
    workspace_path: str | None = None
    purpose: FilePurpose
    created_at: datetime
    updated_at: datetime | None = None
    download_url: str

    model_config = ConfigDict(from_attributes=True)


class FileUploadResponse(BaseModel):
    id: int
    file_id: int
    name: str
    original_name: str
    size: int
    mime_type: str | None = None
    status: str
    workspace_path: str | None = None
    file: FileRead


class BatchDeleteFilesRequest(BaseModel):
    file_ids: list[int]


class DeleteSkippedItem(BaseModel):
    id: int
    reason: str


class BatchDeleteFilesResponse(BaseModel):
    deleted_ids: list[int]
    skipped: list[DeleteSkippedItem]

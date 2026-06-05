from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.models.task_run import TaskRunStatus
from app.schemas.file import FileRead


class TaskRunRead(BaseModel):
    id: int
    user_id: int
    agent_id: int
    agent_code: str | None = None
    agent_name: str | None = None
    openclaw_agent_id: str | None = None
    conversation_id: int | None
    status: TaskRunStatus
    input_text: str
    run_type: str
    priority: int
    output_text: str | None
    output_dir: str | None
    output_files_json: Any | None = None
    raw_payload: Any | None = None
    raw_payload_summary: Any | None = None
    task_kind: str | None = None
    runner_name: str | None = None
    workspace_path: str | None = None
    phase: str | None = None
    progress_message: str | None = None
    duration_seconds: int | None = None
    client_message_id: str | None = None
    gateway_session_key: str | None = None
    idempotency_key: str | None = None
    error_message: str | None
    queued_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    heartbeat_at: datetime | None
    cancel_requested: bool
    timeout_seconds: int | None
    created_at: datetime
    updated_at: datetime
    output_files: list[FileRead] = []


class BatchDeleteRunsRequest(BaseModel):
    run_ids: list[int]


class DeleteSkippedItem(BaseModel):
    id: int
    reason: str


class BatchDeleteRunsResponse(BaseModel):
    deleted_ids: list[int]
    skipped: list[DeleteSkippedItem]

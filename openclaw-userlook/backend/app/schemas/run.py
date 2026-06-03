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

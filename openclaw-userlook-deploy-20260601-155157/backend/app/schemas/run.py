from datetime import datetime

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
    output_text: str | None
    output_dir: str | None
    error_message: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime
    output_files: list[FileRead] = []

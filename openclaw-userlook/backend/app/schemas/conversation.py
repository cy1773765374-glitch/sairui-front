from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.run import TaskRunRead
from app.schemas.message import MessageRead


class ConversationCreate(BaseModel):
    agent_id: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=255)


class ConversationUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=255)


class ConversationRead(BaseModel):
    id: int
    user_id: int
    agent_id: int
    agent_code: str
    agent_name: str
    title: str
    is_title_manual: bool
    session_key: str
    created_at: datetime
    updated_at: datetime


class ConversationDetail(ConversationRead):
    messages: list[MessageRead]
    active_run: TaskRunRead | None = None

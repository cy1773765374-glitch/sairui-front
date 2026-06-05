from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.message import MessageRole


class MessageRead(BaseModel):
    id: int
    conversation_id: int
    run_id: int | None = None
    role: MessageRole
    content: str
    raw_payload: dict[str, Any] | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WebSocketUserMessage(BaseModel):
    type: Literal["user_message"]
    content: str = Field(default="", max_length=20000)
    file_ids: list[int] = Field(default_factory=list)
    client_message_id: str | None = Field(default=None, max_length=80)


class WebSocketCancelRunMessage(BaseModel):
    type: Literal["cancel_run"]
    run_id: int

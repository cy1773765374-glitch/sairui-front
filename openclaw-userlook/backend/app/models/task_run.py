from datetime import datetime, timezone
from enum import Enum
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.mysql import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.user import enum_values


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TaskRunStatus(str, Enum):
    pending = "pending"
    queued = "queued"
    running = "running"
    success = "success"
    failed = "failed"
    cancelled = "cancelled"
    timeout = "timeout"
    stale = "stale"


ACTIVE_RUN_STATUSES = {
    TaskRunStatus.pending,
    TaskRunStatus.queued,
    TaskRunStatus.running,
}

TERMINAL_RUN_STATUSES = {
    TaskRunStatus.success,
    TaskRunStatus.failed,
    TaskRunStatus.cancelled,
    TaskRunStatus.timeout,
    TaskRunStatus.stale,
}


class TaskRun(Base):
    __tablename__ = "task_runs"
    __table_args__ = {"mysql_charset": "utf8mb4"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), index=True, nullable=False)
    conversation_id: Mapped[int | None] = mapped_column(ForeignKey("conversations.id"), index=True, nullable=True)
    status: Mapped[TaskRunStatus] = mapped_column(
        SQLEnum(
            TaskRunStatus,
            values_callable=enum_values,
            name="task_run_status",
        ),
        default=TaskRunStatus.queued,
        nullable=False,
    )
    input_text: Mapped[str] = mapped_column(Text, nullable=False)
    run_type: Mapped[str] = mapped_column(String(50), default="chat", nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    output_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_dir: Mapped[str | None] = mapped_column(String(500), nullable=True)
    output_files_json: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    timeout_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

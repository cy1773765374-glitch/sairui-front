from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import BigInteger, DateTime, ForeignKey, String
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.user import enum_values


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class FilePurpose(str, Enum):
    upload = "upload"
    output = "output"
    temp = "temp"


class FileStatus(str, Enum):
    ready = "ready"
    uploaded = "uploaded"
    available = "available"
    processing = "processing"
    failed = "failed"


class File(Base):
    __tablename__ = "files"
    __table_args__ = {"mysql_charset": "utf8mb4"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    conversation_id: Mapped[int | None] = mapped_column(ForeignKey("conversations.id"), index=True, nullable=True)
    agent_code: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stored_path: Mapped[str] = mapped_column(String(500), nullable=False)
    workspace_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    file_type: Mapped[str] = mapped_column(String(100), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default=FileStatus.ready.value, nullable=False)
    purpose: Mapped[FilePurpose] = mapped_column(
        SQLEnum(
            FilePurpose,
            values_callable=enum_values,
            name="file_purpose",
        ),
        nullable=False,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

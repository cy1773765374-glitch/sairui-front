from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey
from sqlalchemy import Enum as SQLEnum
from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.user import UserRole, enum_values


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AgentRiskLevel(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class Agent(Base):
    __tablename__ = "agents"
    __table_args__ = {"mysql_charset": "utf8mb4"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    openclaw_agent_id: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    risk_level: Mapped[AgentRiskLevel] = mapped_column(
        SQLEnum(
            AgentRiskLevel,
            values_callable=enum_values,
            name="agent_risk_level",
        ),
        default=AgentRiskLevel.low,
        nullable=False,
    )
    support_files: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    support_images: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    workspace_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    execution_mode: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )


class AgentPermission(Base):
    __tablename__ = "agent_permissions"
    __table_args__ = {"mysql_charset": "utf8mb4"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), index=True, nullable=False)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    role: Mapped[UserRole | None] = mapped_column(
        SQLEnum(
            UserRole,
            values_callable=enum_values,
            name="agent_permission_role",
        ),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

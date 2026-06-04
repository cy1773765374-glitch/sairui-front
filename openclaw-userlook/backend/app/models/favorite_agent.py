from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class UserFavoriteAgent(Base):
    __tablename__ = "user_favorite_agents"
    __table_args__ = (
        UniqueConstraint("user_id", "agent_code", name="uq_user_favorite_agents_user_agent"),
        Index("ix_user_favorite_agents_user_sort", "user_id", "sort_order"),
        {"mysql_charset": "utf8mb4"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    agent_code: Mapped[str] = mapped_column(ForeignKey("agents.code"), index=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

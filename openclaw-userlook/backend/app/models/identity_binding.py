from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import BigInteger, DateTime, ForeignKey, String
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.user import enum_values


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class IdentityProvider(str, Enum):
    wecom = "wecom"
    feishu = "feishu"


class IdentityBinding(Base):
    __tablename__ = "identity_bindings"
    __table_args__ = {"mysql_charset": "utf8mb4"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    provider: Mapped[IdentityProvider] = mapped_column(
        SQLEnum(
            IdentityProvider,
            values_callable=enum_values,
            name="identity_provider",
        ),
        nullable=False,
    )
    external_user_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    external_open_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    external_union_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

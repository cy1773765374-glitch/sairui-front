from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import BigInteger, DateTime
from sqlalchemy import Enum as SQLEnum
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def enum_values(enum_class: type[Enum]) -> list[str]:
    return [item.value for item in enum_class]


class UserStatus(str, Enum):
    pending = "pending"
    active = "active"
    disabled = "disabled"


class UserRole(str, Enum):
    admin = "admin"
    user = "user"


class User(Base):
    __tablename__ = "users"
    __table_args__ = {"mysql_charset": "utf8mb4"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[UserStatus] = mapped_column(
        SQLEnum(
            UserStatus,
            values_callable=enum_values,
            name="user_status",
        ),
        default=UserStatus.pending,
        nullable=False,
    )
    role: Mapped[UserRole] = mapped_column(
        SQLEnum(
            UserRole,
            values_callable=enum_values,
            name="user_role",
        ),
        default=UserRole.user,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

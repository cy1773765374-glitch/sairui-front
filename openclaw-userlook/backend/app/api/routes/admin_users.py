from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.user import User, UserStatus
from app.schemas.user import UserRead
from app.services.auth_service import require_admin

router = APIRouter(prefix="/admin/users", tags=["admin-users"])


@router.get("", response_model=list[UserRead])
def list_users(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> list[User]:
    return list(db.scalars(select(User).order_by(User.created_at.desc())))


@router.post("/{user_id}/approve", response_model=UserRead)
def approve_user(
    user_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")

    user.status = UserStatus.active
    db.commit()
    db.refresh(user)
    return user


@router.post("/{user_id}/disable", response_model=UserRead)
def disable_user(
    user_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")

    user.status = UserStatus.disabled
    db.commit()
    db.refresh(user)
    return user

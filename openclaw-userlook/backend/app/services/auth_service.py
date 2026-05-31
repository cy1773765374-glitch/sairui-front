from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import create_access_token, decode_access_token, hash_password, verify_password
from app.models.user import User, UserRole, UserStatus
from app.schemas.auth import RegisterRequest

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def get_user_by_username(db: Session, username: str) -> User | None:
    return db.scalar(select(User).where(User.username == username))


def get_user_by_id(db: Session, user_id: int) -> User | None:
    return db.get(User, user_id)


def register_user(db: Session, payload: RegisterRequest) -> User:
    if get_user_by_username(db, payload.username):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="username already exists",
        )

    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name,
        status=UserStatus.pending,
        role=UserRole.user,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, username: str, password: str) -> tuple[str, User]:
    user = get_user_by_username(db, username)
    if user is None or not verify_password(password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid username or password",
        )

    if user.status != UserStatus.active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="user is not active",
        )

    return create_access_token(str(user.id)), user


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="invalid authentication credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = decode_access_token(token)
        subject = payload.get("sub")
        if subject is None:
            raise credentials_exception
        user_id = int(subject)
    except (JWTError, ValueError) as exc:
        raise credentials_exception from exc

    user = get_user_by_id(db, user_id)
    if user is None:
        raise credentials_exception

    if user.status != UserStatus.active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="user is not active",
        )

    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != UserRole.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="admin permission required",
        )
    return current_user


def seed_default_admin(db: Session) -> User:
    settings = get_settings()
    user = get_user_by_username(db, settings.default_admin_username)
    if user is not None:
        return user

    admin = User(
        username=settings.default_admin_username,
        password_hash=hash_password(settings.default_admin_password),
        display_name=settings.default_admin_username,
        status=UserStatus.active,
        role=UserRole.admin,
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
    return admin

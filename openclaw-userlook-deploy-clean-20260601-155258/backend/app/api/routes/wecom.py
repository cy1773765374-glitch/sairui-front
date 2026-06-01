import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.models.audit_log import AuditLog
from app.models.identity_binding import IdentityBinding, IdentityProvider
from app.models.user import User, UserStatus
from app.schemas.wecom import WeComCallbackResponse, WeComLoginUrlResponse, WeComMeResponse
from app.services.auth_service import get_current_user
from app.services.wecom_auth_service import WeComAuthService

router = APIRouter(prefix="/wecom", tags=["wecom"])


def _request_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _record_wecom_audit(
    db: Session,
    request: Request,
    *,
    action: str,
    user_id: int | None = None,
    detail: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            user_id=user_id,
            action=action,
            target_type="wecom",
            target_id=None,
            detail=json.dumps(detail or {}, ensure_ascii=False),
            ip=_request_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
    )
    db.commit()


@router.get("/login-url", response_model=WeComLoginUrlResponse)
def login_url(
    request: Request,
    state: str = Query(default=""),
    db: Session = Depends(get_db),
) -> WeComLoginUrlResponse:
    settings = get_settings()
    service = WeComAuthService(settings)
    url = service.build_login_url(state or None)
    _record_wecom_audit(
        db,
        request,
        action="wecom.login_url",
        detail={"mock": settings.wecom_mock_login, "state": state},
    )
    return WeComLoginUrlResponse(
        login_url=url,
        mock=settings.wecom_mock_login,
        message="WeCom mock login is enabled" if settings.wecom_mock_login else None,
    )


@router.get("/callback", response_model=WeComCallbackResponse)
def callback(
    request: Request,
    code: str = Query(min_length=1),
    state: str = Query(default=""),
    db: Session = Depends(get_db),
) -> WeComCallbackResponse:
    service = WeComAuthService()
    _record_wecom_audit(
        db,
        request,
        action="wecom.callback",
        detail={"state": state, "code_present": bool(code)},
    )
    identity = service.get_user_identity_by_code(code)

    user, binding, created = service.get_or_create_binding(db, identity)
    if created:
        _record_wecom_audit(
            db,
            request,
            action="wecom.binding_created",
            user_id=user.id,
            detail={"external_user_id": identity.user_id},
        )

    if user.status != UserStatus.active:
        _record_wecom_audit(
            db,
            request,
            action="wecom.login_pending",
            user_id=user.id,
            detail={"status": user.status.value, "external_user_id": identity.user_id},
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="WeCom user is bound but the local account is not active",
        )

    access_token = service.issue_token_for_user(user)
    _record_wecom_audit(
        db,
        request,
        action="wecom.login_success",
        user_id=user.id,
        detail={"external_user_id": identity.user_id},
    )
    return WeComCallbackResponse(access_token=access_token, user=user, binding=binding)


@router.get("/me", response_model=WeComMeResponse)
def me(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WeComMeResponse:
    binding = db.scalar(
        select(IdentityBinding).where(
            IdentityBinding.user_id == current_user.id,
            IdentityBinding.provider == IdentityProvider.wecom,
        )
    )
    return WeComMeResponse(bound=binding is not None, binding=binding)

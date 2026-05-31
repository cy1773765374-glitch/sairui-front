import json
import secrets
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.security import create_access_token, hash_password
from app.models.identity_binding import IdentityBinding, IdentityProvider
from app.models.user import User, UserRole, UserStatus


@dataclass(frozen=True)
class WeComUserIdentity:
    user_id: str
    open_id: str | None = None
    union_id: str | None = None
    display_name: str | None = None


class WeComAuthService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def build_login_url(self, state: str | None = None) -> str:
        state_value = state or secrets.token_urlsafe(16)
        redirect_uri = self.settings.wecom_redirect_uri or "/wecom/callback"

        if self.settings.wecom_mock_login:
            query = urlencode({"code": "mock-code", "state": state_value})
            return f"{redirect_uri}?{query}"

        if not self.settings.wecom_corp_id or not self.settings.wecom_redirect_uri:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="WeCom corp id or redirect uri is not configured",
            )

        query = {
            "appid": self.settings.wecom_corp_id,
            "redirect_uri": self.settings.wecom_redirect_uri,
            "response_type": "code",
            "scope": "snsapi_base",
            "state": state_value,
        }
        if self.settings.wecom_agent_id:
            query["agentid"] = self.settings.wecom_agent_id

        return f"https://open.weixin.qq.com/connect/oauth2/authorize?{urlencode(query)}#wechat_redirect"

    def get_access_token(self) -> str:
        if self.settings.wecom_mock_login:
            return "mock-access-token"

        if not self.settings.wecom_corp_id or not self.settings.wecom_secret:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="WeCom corp id or secret is not configured",
            )

        payload = self._get_json(
            "https://qyapi.weixin.qq.com/cgi-bin/gettoken?"
            + urlencode(
                {
                    "corpid": self.settings.wecom_corp_id,
                    "corpsecret": self.settings.wecom_secret,
                }
            )
        )
        self._raise_for_wecom_error(payload)
        access_token = payload.get("access_token")
        if not access_token:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="WeCom access token response missing access_token",
            )
        return str(access_token)

    def get_user_identity_by_code(self, code: str) -> WeComUserIdentity:
        if self.settings.wecom_mock_login:
            mock_user_id = "mock_user" if code == "mock-code" else f"mock_{code[:48]}"
            return WeComUserIdentity(
                user_id=mock_user_id,
                open_id=f"open_{mock_user_id}",
                union_id=f"union_{mock_user_id}",
                display_name="WeCom Mock User",
            )

        access_token = self.get_access_token()
        payload = self._get_json(
            "https://qyapi.weixin.qq.com/cgi-bin/auth/getuserinfo?"
            + urlencode({"access_token": access_token, "code": code})
        )
        self._raise_for_wecom_error(payload)

        user_id = payload.get("UserId") or payload.get("userid")
        open_id = payload.get("OpenId") or payload.get("openid")
        if not user_id and not open_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="WeCom user identity not found for code",
            )

        return WeComUserIdentity(
            user_id=str(user_id or open_id),
            open_id=str(open_id) if open_id else None,
            union_id=str(payload["unionid"]) if payload.get("unionid") else None,
            display_name=str(user_id or open_id),
        )

    def issue_token_for_user(self, user: User) -> str:
        return create_access_token(str(user.id), extra_claims={"login_source": "wecom"})

    def get_or_create_binding(
        self,
        db: Session,
        identity: WeComUserIdentity,
    ) -> tuple[User, IdentityBinding, bool]:
        binding = db.scalar(
            select(IdentityBinding).where(
                IdentityBinding.provider == IdentityProvider.wecom,
                IdentityBinding.external_user_id == identity.user_id,
            )
        )
        if binding is not None:
            user = db.get(User, binding.user_id)
            if user is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="WeCom binding points to a missing user",
                )
            return user, binding, False

        user = self._find_or_create_local_user(db, identity)
        binding = IdentityBinding(
            user_id=user.id,
            provider=IdentityProvider.wecom,
            external_user_id=identity.user_id,
            external_open_id=identity.open_id,
            external_union_id=identity.union_id,
            display_name=identity.display_name,
        )
        db.add(binding)
        db.commit()
        db.refresh(binding)
        return user, binding, True

    def _find_or_create_local_user(self, db: Session, identity: WeComUserIdentity) -> User:
        username = self._make_username(identity.user_id)
        user = db.scalar(select(User).where(User.username == username))
        if user is not None:
            return user

        user = User(
            username=username,
            password_hash=hash_password(secrets.token_urlsafe(32)),
            display_name=identity.display_name or identity.user_id,
            status=self._default_user_status(),
            role=UserRole.user,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    def _default_user_status(self) -> UserStatus:
        try:
            return UserStatus(self.settings.wecom_default_user_status)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="WECOM_DEFAULT_USER_STATUS must be pending, active, or disabled",
            ) from exc

    @staticmethod
    def _make_username(external_user_id: str) -> str:
        safe = "".join(char if char.isalnum() or char in {"_", "-"} else "_" for char in external_user_id)
        username = f"wecom_{safe}"
        if len(username) <= 64:
            return username
        return f"{username[:54]}_{secrets.token_hex(4)}"

    @staticmethod
    def _get_json(url: str) -> dict[str, Any]:
        try:
            with urlopen(url, timeout=5) as response:
                return json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="WeCom API request failed",
            ) from exc

    @staticmethod
    def _raise_for_wecom_error(payload: dict[str, Any]) -> None:
        error_code = payload.get("errcode", 0)
        if error_code not in (0, "0"):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"WeCom API error: {payload.get('errmsg', error_code)}",
            )

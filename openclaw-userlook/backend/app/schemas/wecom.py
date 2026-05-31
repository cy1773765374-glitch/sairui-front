from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.schemas.user import UserRead


class WeComLoginUrlResponse(BaseModel):
    login_url: str
    mock: bool
    message: str | None = None


class WeComBindingRead(BaseModel):
    provider: str
    external_user_id: str | None = None
    external_open_id: str | None = None
    external_union_id: str | None = None
    display_name: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WeComCallbackResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserRead
    binding: WeComBindingRead
    login_source: str = "wecom"

    model_config = ConfigDict(from_attributes=True)


class WeComMeResponse(BaseModel):
    bound: bool
    login_source: str = "wecom"
    binding: WeComBindingRead | None = None

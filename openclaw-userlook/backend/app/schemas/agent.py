from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.agent import AgentRiskLevel
from app.models.user import UserRole


class AgentRead(BaseModel):
    id: int
    code: str
    name: str
    description: str | None
    openclaw_agent_id: str
    category: str | None
    enabled: bool
    risk_level: AgentRiskLevel
    support_files: bool
    support_images: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AgentPermissionCreate(BaseModel):
    user_id: int | None = Field(default=None, gt=0)
    role: UserRole | None = None

    @model_validator(mode="after")
    def validate_target(self) -> "AgentPermissionCreate":
        if (self.user_id is None and self.role is None) or (
            self.user_id is not None and self.role is not None
        ):
            raise ValueError("provide exactly one of user_id or role")
        return self


class AgentPermissionRead(BaseModel):
    id: int
    agent_id: int
    user_id: int | None
    role: UserRole | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

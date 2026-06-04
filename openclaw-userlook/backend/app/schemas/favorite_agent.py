from datetime import datetime

from pydantic import BaseModel, Field

from app.models.agent import AgentRiskLevel


class FavoriteAgentCreate(BaseModel):
    agent_code: str = Field(min_length=1, max_length=64)


class FavoriteAgentReorder(BaseModel):
    agent_codes: list[str] = Field(default_factory=list)


class FavoriteAgentRead(BaseModel):
    agent_code: str
    name: str
    description: str | None
    risk_level: AgentRiskLevel
    category: str | None
    support_files: bool
    support_images: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime

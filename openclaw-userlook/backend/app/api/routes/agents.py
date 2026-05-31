from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.user import User
from app.schemas.agent import AgentPermissionCreate, AgentPermissionRead, AgentRead
from app.services.agent_service import (
    grant_agent_permission,
    list_admin_agents,
    list_visible_agents,
    require_visible_agent,
    set_agent_enabled,
)
from app.services.auth_service import get_current_user, require_admin

router = APIRouter(tags=["agents"])


@router.get("/agents", response_model=list[AgentRead])
def list_agents(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return list_visible_agents(db, current_user)


@router.get("/agents/{agent_id}", response_model=AgentRead)
def get_agent(
    agent_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return require_visible_agent(db, current_user, agent_id)


@router.get("/admin/agents", response_model=list[AgentRead])
def list_agents_for_admin(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    return list_admin_agents(db)


@router.post("/admin/agents/{agent_id}/enable", response_model=AgentRead)
def enable_agent(
    agent_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    return set_agent_enabled(db, agent_id, True)


@router.post("/admin/agents/{agent_id}/disable", response_model=AgentRead)
def disable_agent(
    agent_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    return set_agent_enabled(db, agent_id, False)


@router.post("/admin/agents/{agent_id}/permissions", response_model=AgentPermissionRead)
def create_agent_permission(
    agent_id: str,
    payload: AgentPermissionCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    return grant_agent_permission(db, agent_id, payload)

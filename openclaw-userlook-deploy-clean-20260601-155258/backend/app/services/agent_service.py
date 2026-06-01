from fastapi import HTTPException, status
from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session

from app.models.agent import Agent, AgentPermission
from app.models.user import User, UserRole
from app.schemas.agent import AgentPermissionCreate


def get_agent_by_code(db: Session, agent_code: str) -> Agent | None:
    return db.scalar(select(Agent).where(Agent.code == agent_code))


def require_agent_by_code(db: Session, agent_code: str) -> Agent:
    agent = get_agent_by_code(db, agent_code)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="agent not found")
    return agent


def user_can_access_agent(db: Session, user: User, agent: Agent) -> bool:
    if not agent.enabled:
        return False

    if user.role == UserRole.admin:
        return True

    permission_exists = db.scalar(
        select(
            exists().where(
                AgentPermission.agent_id == agent.id,
                or_(
                    AgentPermission.user_id == user.id,
                    AgentPermission.role == user.role,
                ),
            )
        )
    )
    return bool(permission_exists)


def list_visible_agents(db: Session, user: User) -> list[Agent]:
    base_query = select(Agent).where(Agent.enabled.is_(True)).order_by(Agent.category, Agent.code)

    if user.role == UserRole.admin:
        return list(db.scalars(base_query))

    permission_exists = (
        select(AgentPermission.id)
        .where(
            AgentPermission.agent_id == Agent.id,
            or_(
                AgentPermission.user_id == user.id,
                AgentPermission.role == user.role,
            ),
        )
        .exists()
    )
    return list(db.scalars(base_query.where(permission_exists)))


def list_admin_agents(db: Session) -> list[Agent]:
    return list(db.scalars(select(Agent).order_by(Agent.enabled.desc(), Agent.category, Agent.code)))


def require_visible_agent(db: Session, user: User, agent_code: str) -> Agent:
    agent = require_agent_by_code(db, agent_code)
    if not user_can_access_agent(db, user, agent):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="agent not found")
    return agent


def set_agent_enabled(db: Session, agent_code: str, enabled: bool) -> Agent:
    agent = require_agent_by_code(db, agent_code)
    agent.enabled = enabled
    db.commit()
    db.refresh(agent)
    return agent


def grant_agent_permission(
    db: Session,
    agent_code: str,
    payload: AgentPermissionCreate,
) -> AgentPermission:
    agent = require_agent_by_code(db, agent_code)

    if payload.user_id is not None and db.get(User, payload.user_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")

    existing_permission = db.scalar(
        select(AgentPermission).where(
            AgentPermission.agent_id == agent.id,
            AgentPermission.user_id == payload.user_id,
            AgentPermission.role == payload.role,
        )
    )
    if existing_permission is not None:
        return existing_permission

    permission = AgentPermission(agent_id=agent.id, user_id=payload.user_id, role=payload.role)
    db.add(permission)
    db.commit()
    db.refresh(permission)
    return permission

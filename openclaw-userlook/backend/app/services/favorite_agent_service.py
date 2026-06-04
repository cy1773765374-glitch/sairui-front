from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.favorite_agent import UserFavoriteAgent
from app.models.user import User
from app.schemas.favorite_agent import FavoriteAgentRead
from app.services.agent_service import require_visible_agent, user_can_access_agent


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _to_read(favorite: UserFavoriteAgent, agent: Agent) -> FavoriteAgentRead:
    return FavoriteAgentRead(
        agent_code=agent.code,
        name=agent.name,
        description=agent.description,
        risk_level=agent.risk_level,
        category=agent.category,
        support_files=agent.support_files,
        support_images=agent.support_images,
        sort_order=favorite.sort_order,
        created_at=favorite.created_at,
        updated_at=favorite.updated_at,
    )


def list_favorite_agents(db: Session, current_user: User) -> list[FavoriteAgentRead]:
    rows = db.execute(
        select(UserFavoriteAgent, Agent)
        .join(Agent, Agent.code == UserFavoriteAgent.agent_code)
        .where(UserFavoriteAgent.user_id == current_user.id)
        .order_by(UserFavoriteAgent.sort_order.asc(), UserFavoriteAgent.created_at.asc(), UserFavoriteAgent.id.asc())
    ).all()
    return [
        _to_read(favorite, agent)
        for favorite, agent in rows
        if user_can_access_agent(db, current_user, agent)
    ]


def add_favorite_agent(db: Session, current_user: User, agent_code: str) -> FavoriteAgentRead:
    agent = require_visible_agent(db, current_user, agent_code)
    existing = db.scalar(
        select(UserFavoriteAgent).where(
            UserFavoriteAgent.user_id == current_user.id,
            UserFavoriteAgent.agent_code == agent.code,
        )
    )
    if existing is not None:
        return _to_read(existing, agent)

    max_order = db.scalar(
        select(func.max(UserFavoriteAgent.sort_order)).where(UserFavoriteAgent.user_id == current_user.id)
    )
    favorite = UserFavoriteAgent(
        user_id=current_user.id,
        agent_code=agent.code,
        sort_order=(max_order or 0) + 100,
    )
    db.add(favorite)
    db.commit()
    db.refresh(favorite)
    return _to_read(favorite, agent)


def remove_favorite_agent(db: Session, current_user: User, agent_code: str) -> None:
    favorite = db.scalar(
        select(UserFavoriteAgent).where(
            UserFavoriteAgent.user_id == current_user.id,
            UserFavoriteAgent.agent_code == agent_code,
        )
    )
    if favorite is None:
        return
    db.delete(favorite)
    db.commit()


def reorder_favorite_agents(db: Session, current_user: User, agent_codes: list[str]) -> list[FavoriteAgentRead]:
    unique_order = list(dict.fromkeys(agent_codes))
    favorites = list(
        db.scalars(
            select(UserFavoriteAgent)
            .where(UserFavoriteAgent.user_id == current_user.id)
            .order_by(UserFavoriteAgent.sort_order.asc(), UserFavoriteAgent.created_at.asc(), UserFavoriteAgent.id.asc())
        )
    )
    favorites_by_code = {favorite.agent_code: favorite for favorite in favorites}
    unknown_codes = [agent_code for agent_code in unique_order if agent_code not in favorites_by_code]
    if unknown_codes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"favorite agent not found: {unknown_codes[0]}",
        )

    next_codes = unique_order + [favorite.agent_code for favorite in favorites if favorite.agent_code not in unique_order]
    now = _utc_now()
    for index, agent_code in enumerate(next_codes):
        favorite = favorites_by_code[agent_code]
        favorite.sort_order = (index + 1) * 100
        favorite.updated_at = now
    if favorites:
        db.commit()
    return list_favorite_agents(db, current_user)

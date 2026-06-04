from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.user import User
from app.schemas.favorite_agent import FavoriteAgentCreate, FavoriteAgentRead, FavoriteAgentReorder
from app.services.auth_service import get_current_user
from app.services.favorite_agent_service import (
    add_favorite_agent,
    list_favorite_agents,
    remove_favorite_agent,
    reorder_favorite_agents,
)

router = APIRouter(prefix="/me", tags=["me"])


@router.get("/favorite-agents", response_model=list[FavoriteAgentRead])
def get_favorite_agents(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[FavoriteAgentRead]:
    return list_favorite_agents(db, current_user)


@router.post("/favorite-agents", response_model=FavoriteAgentRead, status_code=status.HTTP_201_CREATED)
def create_favorite_agent(
    payload: FavoriteAgentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FavoriteAgentRead:
    return add_favorite_agent(db, current_user, payload.agent_code)


@router.delete("/favorite-agents/{agent_code}", status_code=status.HTTP_204_NO_CONTENT)
def delete_favorite_agent(
    agent_code: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    remove_favorite_agent(db, current_user, agent_code)


@router.put("/favorite-agents/reorder", response_model=list[FavoriteAgentRead])
def reorder_favorites(
    payload: FavoriteAgentReorder,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[FavoriteAgentRead]:
    return reorder_favorite_agents(db, current_user, payload.agent_codes)

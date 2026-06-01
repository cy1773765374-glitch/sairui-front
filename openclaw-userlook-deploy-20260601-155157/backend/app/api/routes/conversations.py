from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.user import User
from app.schemas.conversation import ConversationCreate, ConversationDetail, ConversationRead
from app.services.auth_service import get_current_user
from app.services.conversation_service import (
    create_conversation,
    get_conversation_detail,
    list_conversations,
)

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.post("", response_model=ConversationRead, status_code=status.HTTP_201_CREATED)
def create_new_conversation(
    payload: ConversationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ConversationRead:
    return create_conversation(db, current_user, payload)


@router.get("", response_model=list[ConversationRead])
def get_conversations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ConversationRead]:
    return list_conversations(db, current_user)


@router.get("/{conversation_id}", response_model=ConversationDetail)
def get_conversation(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ConversationDetail:
    return get_conversation_detail(db, current_user, conversation_id)

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.conversation import Conversation
from app.models.message import Message, MessageRole
from app.models.user import User, UserRole
from app.schemas.conversation import ConversationCreate, ConversationDetail, ConversationRead
from app.services.agent_service import user_can_access_agent


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _to_read(conversation: Conversation, agent: Agent) -> ConversationRead:
    return ConversationRead(
        id=conversation.id,
        user_id=conversation.user_id,
        agent_id=conversation.agent_id,
        agent_code=agent.code,
        agent_name=agent.name,
        title=conversation.title,
        session_key=conversation.session_key,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )


def _get_conversation_with_agent(
    db: Session,
    conversation_id: int,
) -> tuple[Conversation, Agent] | None:
    row = db.execute(
        select(Conversation, Agent)
        .join(Agent, Agent.id == Conversation.agent_id)
        .where(Conversation.id == conversation_id)
    ).first()
    if row is None:
        return None
    return row[0], row[1]


def create_conversation(
    db: Session,
    current_user: User,
    payload: ConversationCreate,
) -> ConversationRead:
    agent = db.get(Agent, payload.agent_id)
    if agent is None or not user_can_access_agent(db, current_user, agent):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="agent not found")

    conversation = Conversation(
        user_id=current_user.id,
        agent_id=agent.id,
        title=payload.title,
        session_key=f"pending:{uuid4().hex}",
    )
    db.add(conversation)
    db.flush()
    conversation.session_key = f"web:{current_user.id}:{agent.code}:{conversation.id}"
    db.commit()
    db.refresh(conversation)
    return _to_read(conversation, agent)


def list_conversations(db: Session, current_user: User) -> list[ConversationRead]:
    rows = db.execute(
        select(Conversation, Agent)
        .join(Agent, Agent.id == Conversation.agent_id)
        .where(Conversation.user_id == current_user.id)
        .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
    ).all()
    return [_to_read(conversation, agent) for conversation, agent in rows]


def get_conversation_detail(
    db: Session,
    current_user: User,
    conversation_id: int,
) -> ConversationDetail:
    result = _get_conversation_with_agent(db, conversation_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="conversation not found")

    conversation, agent = result
    if current_user.role != UserRole.admin and conversation.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="conversation not found")

    messages = list(
        db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.id.asc())
        )
    )
    return ConversationDetail(**_to_read(conversation, agent).model_dump(), messages=messages)


def require_conversation_for_user(
    db: Session,
    current_user: User,
    conversation_id: int,
) -> Conversation:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="conversation not found")
    if current_user.role != UserRole.admin and conversation.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="conversation not found")
    return conversation


def save_message(
    db: Session,
    conversation: Conversation,
    role: MessageRole,
    content: str,
    raw_payload: dict | None = None,
) -> Message:
    message = Message(
        conversation_id=conversation.id,
        role=role,
        content=content,
        raw_payload=raw_payload,
    )
    conversation.updated_at = _utc_now()
    db.add(message)
    db.commit()
    db.refresh(message)
    return message

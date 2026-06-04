from datetime import datetime, timezone
import re
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.conversation import Conversation
from app.models.message import Message, MessageRole
from app.models.task_run import TaskRun
from app.models.user import User, UserRole
from app.schemas.conversation import ConversationCreate, ConversationDetail, ConversationRead, ConversationUpdate
from app.services.agent_service import user_can_access_agent
from app.services.run_service import get_latest_active_run_for_conversation


MAX_MANUAL_TITLE_LENGTH = 20
AUTO_TITLE_LENGTH = 5
DEFAULT_TITLE_SUFFIX = " 对话"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_title(value: str, max_length: int = MAX_MANUAL_TITLE_LENGTH) -> str:
    title = re.sub(r"\s+", " ", value.strip())
    return title[:max_length]


def _build_auto_title(value: str) -> str:
    return _normalize_title(value, AUTO_TITLE_LENGTH)


def _is_default_title(conversation: Conversation, agent: Agent | None) -> bool:
    if not conversation.title.strip():
        return True
    if agent is None:
        return False
    return conversation.title == f"{agent.name}{DEFAULT_TITLE_SUFFIX}"


def _to_read(conversation: Conversation, agent: Agent) -> ConversationRead:
    return ConversationRead(
        id=conversation.id,
        user_id=conversation.user_id,
        agent_id=conversation.agent_id,
        agent_code=agent.code,
        agent_name=agent.name,
        title=conversation.title,
        is_title_manual=conversation.is_title_manual,
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
    active_run = get_latest_active_run_for_conversation(db, current_user, conversation.id)
    return ConversationDetail(
        **_to_read(conversation, agent).model_dump(),
        messages=messages,
        active_run=active_run,
    )


def delete_conversation(
    db: Session,
    current_user: User,
    conversation_id: int,
) -> None:
    conversation = require_conversation_for_user(db, current_user, conversation_id)
    db.execute(delete(Message).where(Message.conversation_id == conversation.id))
    db.execute(
        update(TaskRun)
        .where(TaskRun.conversation_id == conversation.id)
        .values(conversation_id=None)
    )
    db.delete(conversation)
    db.commit()


def update_conversation_title(
    db: Session,
    current_user: User,
    conversation_id: int,
    payload: ConversationUpdate,
) -> ConversationRead:
    conversation = require_conversation_for_user(db, current_user, conversation_id)
    agent = db.get(Agent, conversation.agent_id)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="agent not found")

    title = _normalize_title(payload.title)
    if not title:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="title is required")

    conversation.title = title
    conversation.is_title_manual = True
    conversation.updated_at = _utc_now()
    db.commit()
    db.refresh(conversation)
    return _to_read(conversation, agent)


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


def _maybe_auto_title_conversation(
    db: Session,
    conversation: Conversation,
    role: MessageRole,
    content: str,
) -> None:
    if role != MessageRole.user or conversation.is_title_manual:
        return

    existing_user_message_id = db.scalar(
        select(Message.id)
        .where(Message.conversation_id == conversation.id, Message.role == MessageRole.user)
        .limit(1)
    )
    if existing_user_message_id is not None:
        return

    agent = db.get(Agent, conversation.agent_id)
    if not _is_default_title(conversation, agent):
        return

    title = _build_auto_title(content)
    if title:
        conversation.title = title


def save_message(
    db: Session,
    conversation: Conversation,
    role: MessageRole,
    content: str,
    raw_payload: dict | None = None,
    run_id: int | None = None,
) -> Message:
    _maybe_auto_title_conversation(db, conversation, role, content)
    message = Message(
        conversation_id=conversation.id,
        run_id=run_id,
        role=role,
        content=content,
        raw_payload=raw_payload,
    )
    conversation.updated_at = _utc_now()
    db.add(message)
    db.commit()
    db.refresh(message)
    return message

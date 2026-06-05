from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.agent import Agent
from app.models.pending_task_input import PendingTaskInput
from app.models.user import User


PENDING_STATUS = "pending"
CONSUMED_STATUS = "consumed"
CANCELLED_STATUS = "cancelled"
EXPIRED_STATUS = "expired"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _expires_at() -> datetime:
    return _utc_now() + timedelta(hours=max(1, get_settings().task_pending_context_ttl_hours))


def _as_list(value: object) -> list:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def _active_statement(user_id: int, conversation_id: int, agent_id: int, task_type: str):
    return (
        select(PendingTaskInput)
        .where(PendingTaskInput.user_id == user_id)
        .where(PendingTaskInput.conversation_id == conversation_id)
        .where(PendingTaskInput.agent_id == agent_id)
        .where(PendingTaskInput.task_type == task_type)
        .where(PendingTaskInput.status == PENDING_STATUS)
        .order_by(PendingTaskInput.updated_at.desc(), PendingTaskInput.id.desc())
    )


def get_pending_task(
    db: Session,
    *,
    user_id: int,
    conversation_id: int,
    agent_id: int,
    task_type: str,
) -> PendingTaskInput | None:
    pending = db.scalars(_active_statement(user_id, conversation_id, agent_id, task_type)).first()
    if pending is None:
        return None
    now = _utc_now()
    expires_at = pending.expires_at
    if expires_at is not None:
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= now:
            pending.status = EXPIRED_STATUS
            db.commit()
            return None
    return pending


def _get_or_create_pending(
    db: Session,
    *,
    user: User,
    conversation_id: int,
    agent: Agent,
    task_type: str,
) -> PendingTaskInput:
    pending = get_pending_task(
        db,
        user_id=user.id,
        conversation_id=conversation_id,
        agent_id=agent.id,
        task_type=task_type,
    )
    if pending is not None:
        return pending
    pending = PendingTaskInput(
        user_id=user.id,
        conversation_id=conversation_id,
        agent_id=agent.id,
        agent_code=agent.code,
        task_type=task_type,
        status=PENDING_STATUS,
        expires_at=_expires_at(),
        pending_file_ids=[],
        source_message_ids=[],
    )
    db.add(pending)
    db.flush()
    return pending


def save_pending_text(
    db: Session,
    *,
    user: User,
    conversation_id: int,
    agent: Agent,
    task_type: str,
    text_value: str,
    source_message_id: int | None = None,
) -> PendingTaskInput:
    pending = _get_or_create_pending(db, user=user, conversation_id=conversation_id, agent=agent, task_type=task_type)
    pending.pending_text = text_value
    pending.expires_at = _expires_at()
    if source_message_id is not None:
        ids = _as_list(pending.source_message_ids)
        ids.append(source_message_id)
        pending.source_message_ids = list(dict.fromkeys(ids))
    db.commit()
    db.refresh(pending)
    return pending


def save_pending_files(
    db: Session,
    *,
    user: User,
    conversation_id: int,
    agent: Agent,
    task_type: str,
    file_ids: list[int],
    source_message_id: int | None = None,
) -> PendingTaskInput:
    pending = _get_or_create_pending(db, user=user, conversation_id=conversation_id, agent=agent, task_type=task_type)
    pending.pending_file_ids = list(dict.fromkeys(file_ids))
    pending.expires_at = _expires_at()
    if source_message_id is not None:
        ids = _as_list(pending.source_message_ids)
        ids.append(source_message_id)
        pending.source_message_ids = list(dict.fromkeys(ids))
    db.commit()
    db.refresh(pending)
    return pending


def consume_pending_task(db: Session, pending: PendingTaskInput | None, *, run_id: int) -> None:
    if pending is None:
        return
    pending.status = CONSUMED_STATUS
    pending.consumed_by_run_id = run_id
    db.commit()


def cancel_pending_task(
    db: Session,
    *,
    user_id: int,
    conversation_id: int,
    agent_id: int,
    task_type: str,
) -> PendingTaskInput | None:
    pending = get_pending_task(
        db,
        user_id=user_id,
        conversation_id=conversation_id,
        agent_id=agent_id,
        task_type=task_type,
    )
    if pending is None:
        return None
    pending.status = CANCELLED_STATUS
    db.commit()
    db.refresh(pending)
    return pending

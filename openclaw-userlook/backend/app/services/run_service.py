from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.agent import Agent
from app.models.task_run import ACTIVE_RUN_STATUSES, TERMINAL_RUN_STATUSES, TaskRun, TaskRunStatus
from app.models.user import User, UserRole
from app.schemas.run import TaskRunRead
from app.services.file_service import build_run_output_dir, list_output_files_for_dir


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _to_read(db: Session, run: TaskRun, agent: Agent | None = None) -> TaskRunRead:
    if agent is None:
        agent = db.get(Agent, run.agent_id)
    return TaskRunRead(
        id=run.id,
        user_id=run.user_id,
        agent_id=run.agent_id,
        agent_code=agent.code if agent else None,
        agent_name=agent.name if agent else None,
        conversation_id=run.conversation_id,
        status=run.status,
        input_text=run.input_text,
        run_type=run.run_type,
        priority=run.priority,
        output_text=run.output_text,
        output_dir=run.output_dir,
        output_files_json=run.output_files_json,
        error_message=run.error_message,
        queued_at=run.queued_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        heartbeat_at=run.heartbeat_at,
        cancel_requested=run.cancel_requested,
        timeout_seconds=run.timeout_seconds,
        created_at=run.created_at,
        updated_at=run.updated_at,
        output_files=list_output_files_for_dir(db, run.user_id, run.output_dir),
    )


def create_task_run(
    db: Session,
    *,
    current_user: User,
    agent: Agent,
    conversation_id: int | None,
    input_text: str,
    run_type: str = "chat",
    priority: int = 100,
) -> TaskRun:
    settings = get_settings()
    timeout_seconds = (
        settings.task_job_timeout_seconds
        if run_type == "job"
        else settings.task_chat_timeout_seconds
    )
    now = _utc_now()
    run = TaskRun(
        user_id=current_user.id,
        agent_id=agent.id,
        conversation_id=conversation_id,
        input_text=input_text,
        run_type=run_type,
        priority=priority,
        status=TaskRunStatus.queued,
        queued_at=now,
        timeout_seconds=timeout_seconds,
        cancel_requested=False,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    run.output_dir = build_run_output_dir(current_user.id, run.id)
    db.commit()
    db.refresh(run)
    return run


def mark_task_run_queued(db: Session, run: TaskRun) -> TaskRun:
    run.status = TaskRunStatus.queued
    run.queued_at = run.queued_at or _utc_now()
    run.cancel_requested = False
    db.commit()
    db.refresh(run)
    return run


def mark_task_run_running(db: Session, run: TaskRun) -> TaskRun:
    run.status = TaskRunStatus.running
    run.started_at = run.started_at or _utc_now()
    run.heartbeat_at = _utc_now()
    db.commit()
    db.refresh(run)
    return run


def touch_task_run_heartbeat(db: Session, run: TaskRun) -> TaskRun:
    run.heartbeat_at = _utc_now()
    db.commit()
    db.refresh(run)
    return run


def mark_task_run_success(
    db: Session,
    run: TaskRun,
    *,
    output_text: str,
    output_dir: str | None = None,
) -> TaskRun:
    run.status = TaskRunStatus.success
    run.output_text = output_text
    if output_dir:
        run.output_dir = output_dir
    run.cancel_requested = False
    run.finished_at = _utc_now()
    db.commit()
    db.refresh(run)
    return run


def mark_task_run_failed(
    db: Session,
    run: TaskRun,
    error_message: str,
    output_text: str | None = None,
    status_value: TaskRunStatus = TaskRunStatus.failed,
) -> TaskRun:
    run.status = status_value
    run.error_message = error_message
    if output_text is not None:
        run.output_text = output_text
    run.cancel_requested = False
    run.finished_at = _utc_now()
    db.commit()
    db.refresh(run)
    return run


def mark_task_run_cancelled(
    db: Session,
    run: TaskRun,
    message: str | None = None,
    output_text: str | None = None,
) -> TaskRun:
    run.status = TaskRunStatus.cancelled
    run.error_message = message
    if output_text is not None:
        run.output_text = output_text
    run.cancel_requested = False
    run.finished_at = _utc_now()
    db.commit()
    db.refresh(run)
    return run


def mark_task_run_timeout(
    db: Session,
    run: TaskRun,
    message: str,
    output_text: str | None = None,
) -> TaskRun:
    return mark_task_run_failed(
        db,
        run,
        message,
        output_text=output_text,
        status_value=TaskRunStatus.timeout,
    )


def mark_task_run_stale(db: Session, run: TaskRun, message: str) -> TaskRun:
    return mark_task_run_failed(db, run, message, status_value=TaskRunStatus.stale)


def request_task_run_cancel(db: Session, current_user: User, run_id: int) -> TaskRun:
    run = db.get(TaskRun, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")
    if current_user.role != UserRole.admin and run.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")

    if run.status in TERMINAL_RUN_STATUSES:
        return run
    if run.status in {TaskRunStatus.pending, TaskRunStatus.queued}:
        return mark_task_run_cancelled(db, run, "用户已停止生成")
    if run.status == TaskRunStatus.running:
        run.cancel_requested = True
        db.commit()
        db.refresh(run)
        return run
    return run


def list_task_runs(
    db: Session,
    current_user: User,
    *,
    agent_id: int | None = None,
    conversation_id: int | None = None,
    status_value: TaskRunStatus | None = None,
    run_type: str | None = None,
    active_only: bool = False,
) -> list[TaskRunRead]:
    statement = (
        select(TaskRun, Agent)
        .join(Agent, Agent.id == TaskRun.agent_id)
        .order_by(TaskRun.created_at.desc(), TaskRun.id.desc())
    )
    if current_user.role != UserRole.admin:
        statement = statement.where(TaskRun.user_id == current_user.id)
    if agent_id is not None:
        statement = statement.where(TaskRun.agent_id == agent_id)
    if conversation_id is not None:
        statement = statement.where(TaskRun.conversation_id == conversation_id)
    if status_value is not None:
        statement = statement.where(TaskRun.status == status_value)
    if run_type:
        statement = statement.where(TaskRun.run_type == run_type)
    if active_only:
        statement = statement.where(TaskRun.status.in_(ACTIVE_RUN_STATUSES))
    return [_to_read(db, run, agent) for run, agent in db.execute(statement).all()]


def get_task_run_detail(db: Session, current_user: User, run_id: int) -> TaskRunRead:
    run = db.get(TaskRun, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")
    if current_user.role != UserRole.admin and run.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")
    return _to_read(db, run)


def get_latest_active_run_for_conversation(
    db: Session,
    current_user: User,
    conversation_id: int,
) -> TaskRunRead | None:
    statement = (
        select(TaskRun)
        .where(TaskRun.conversation_id == conversation_id)
        .where(TaskRun.status.in_(ACTIVE_RUN_STATUSES))
        .order_by(TaskRun.created_at.desc(), TaskRun.id.desc())
    )
    if current_user.role != UserRole.admin:
        statement = statement.where(TaskRun.user_id == current_user.id)
    run = db.scalars(statement).first()
    if run is None:
        return None
    return _to_read(db, run)


def has_active_run_for_conversation(db: Session, current_user: User, conversation_id: int) -> bool:
    statement = (
        select(TaskRun.id)
        .where(TaskRun.conversation_id == conversation_id)
        .where(TaskRun.status.in_(ACTIVE_RUN_STATUSES))
    )
    if current_user.role != UserRole.admin:
        statement = statement.where(TaskRun.user_id == current_user.id)
    return db.execute(statement).first() is not None

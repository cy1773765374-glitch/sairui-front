from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.task_run import TaskRun, TaskRunStatus
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
        output_text=run.output_text,
        output_dir=run.output_dir,
        error_message=run.error_message,
        started_at=run.started_at,
        finished_at=run.finished_at,
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
) -> TaskRun:
    run = TaskRun(
        user_id=current_user.id,
        agent_id=agent.id,
        conversation_id=conversation_id,
        input_text=input_text,
        status=TaskRunStatus.pending,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    run.output_dir = build_run_output_dir(current_user.id, run.id)
    db.commit()
    db.refresh(run)
    return run


def mark_task_run_running(db: Session, run: TaskRun) -> TaskRun:
    run.status = TaskRunStatus.running
    run.started_at = run.started_at or _utc_now()
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
    run.finished_at = _utc_now()
    db.commit()
    db.refresh(run)
    return run


def mark_task_run_failed(db: Session, run: TaskRun, error_message: str) -> TaskRun:
    run.status = TaskRunStatus.failed
    run.error_message = error_message
    run.finished_at = _utc_now()
    db.commit()
    db.refresh(run)
    return run


def mark_task_run_cancelled(db: Session, run: TaskRun, message: str | None = None) -> TaskRun:
    run.status = TaskRunStatus.cancelled
    run.error_message = message
    run.finished_at = _utc_now()
    db.commit()
    db.refresh(run)
    return run


def list_task_runs(db: Session, current_user: User) -> list[TaskRunRead]:
    statement = (
        select(TaskRun, Agent)
        .join(Agent, Agent.id == TaskRun.agent_id)
        .order_by(TaskRun.created_at.desc(), TaskRun.id.desc())
    )
    if current_user.role != UserRole.admin:
        statement = statement.where(TaskRun.user_id == current_user.id)
    return [_to_read(db, run, agent) for run, agent in db.execute(statement).all()]


def get_task_run_detail(db: Session, current_user: User, run_id: int) -> TaskRunRead:
    run = db.get(TaskRun, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")
    if current_user.role != UserRole.admin and run.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")
    return _to_read(db, run)

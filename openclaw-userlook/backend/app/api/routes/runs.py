from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.task_run import TaskRunStatus
from app.models.user import User
from app.schemas.run import TaskRunRead
from app.services.auth_service import get_current_user
from app.services.run_service import get_task_run_detail, list_task_runs, request_task_run_cancel
from app.services.task_queue import task_queue

router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("", response_model=list[TaskRunRead])
def get_runs(
    agent_id: int | None = Query(default=None),
    conversation_id: int | None = Query(default=None),
    status: TaskRunStatus | None = Query(default=None),
    run_type: str | None = Query(default=None),
    active_only: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[TaskRunRead]:
    return list_task_runs(
        db,
        current_user,
        agent_id=agent_id,
        conversation_id=conversation_id,
        status_value=status,
        run_type=run_type,
        active_only=active_only,
    )


@router.get("/{run_id}", response_model=TaskRunRead)
def get_run(
    run_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TaskRunRead:
    return get_task_run_detail(db, current_user, run_id)


@router.post("/{run_id}/cancel", response_model=TaskRunRead)
def cancel_run(
    run_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TaskRunRead:
    run = request_task_run_cancel(db, current_user, run_id)
    task_queue.cancel_task(run.id)
    return get_task_run_detail(db, current_user, run.id)

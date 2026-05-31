from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.user import User
from app.schemas.run import TaskRunRead
from app.services.auth_service import get_current_user
from app.services.run_service import get_task_run_detail, list_task_runs

router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("", response_model=list[TaskRunRead])
def get_runs(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[TaskRunRead]:
    return list_task_runs(db, current_user)


@router.get("/{run_id}", response_model=TaskRunRead)
def get_run(
    run_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TaskRunRead:
    return get_task_run_detail(db, current_user, run_id)

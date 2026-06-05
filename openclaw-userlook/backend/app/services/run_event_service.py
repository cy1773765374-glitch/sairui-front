from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.run_event import RunEvent
from app.models.task_run import TERMINAL_RUN_STATUSES, TaskRun


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def append_run_event(
    db: Session,
    run_id: int,
    event_type: str,
    *,
    phase: str | None = None,
    message: str | None = None,
    payload: dict[str, Any] | None = None,
    update_run: bool = True,
) -> RunEvent:
    event = RunEvent(
        run_id=run_id,
        event_type=event_type,
        phase=phase,
        message=message,
        payload_json=payload,
    )
    db.add(event)
    if update_run:
        run = db.get(TaskRun, run_id)
        if run is not None and run.status not in TERMINAL_RUN_STATUSES:
            if phase is not None:
                run.phase = phase
            if message is not None:
                run.progress_message = message
            run.heartbeat_at = _utc_now()
    db.commit()
    db.refresh(event)
    return event


def list_run_events(db: Session, run_id: int) -> list[RunEvent]:
    return list(
        db.scalars(
            select(RunEvent)
            .where(RunEvent.run_id == run_id)
            .order_by(RunEvent.created_at.asc(), RunEvent.id.asc())
        )
    )

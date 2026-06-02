from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.task_run import TaskRun, TaskRunStatus
from app.services.task_queue import task_queue


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def scan_stale_task_runs() -> int:
    settings = get_settings()
    now = _utc_now()
    stale_before = now - timedelta(minutes=settings.task_stale_running_minutes)
    changed = 0

    with SessionLocal() as db:
        runs = list(
            db.scalars(
                select(TaskRun).where(TaskRun.status.in_([TaskRunStatus.running, TaskRunStatus.queued]))
            )
        )
        for run in runs:
            if run.status == TaskRunStatus.running:
                started_at = _as_aware(run.started_at)
                if (
                    run.timeout_seconds
                    and started_at is not None
                    and started_at + timedelta(seconds=run.timeout_seconds) <= now
                ):
                    run.status = TaskRunStatus.timeout
                    run.error_message = "任务执行超过超时时间"
                    run.finished_at = now
                    run.cancel_requested = False
                    task_queue.cancel_task(run.id)
                    changed += 1
                    continue

                heartbeat_at = _as_aware(run.heartbeat_at) or _as_aware(run.updated_at)
                if heartbeat_at is not None and heartbeat_at <= stale_before:
                    run.status = TaskRunStatus.stale
                    run.error_message = "任务心跳过期，已标记为 stale"
                    run.finished_at = now
                    run.cancel_requested = False
                    task_queue.cancel_task(run.id)
                    changed += 1
                    continue

            if run.status == TaskRunStatus.queued:
                queued_at = _as_aware(run.queued_at) or _as_aware(run.created_at)
                if (
                    settings.task_queue_timeout_seconds
                    and queued_at is not None
                    and queued_at + timedelta(seconds=settings.task_queue_timeout_seconds) <= now
                ):
                    run.status = TaskRunStatus.timeout
                    run.error_message = "任务排队超过超时时间"
                    run.finished_at = now
                    run.cancel_requested = False
                    task_queue.cancel_task(run.id)
                    changed += 1

        if changed:
            db.commit()
    return changed


async def watchdog_loop(stop_event: asyncio.Event) -> None:
    settings = get_settings()
    scan_stale_task_runs()
    while not stop_event.is_set():
        with contextlib.suppress(Exception):
            scan_stale_task_runs()
        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=max(1, settings.task_watchdog_interval_seconds),
            )
        except TimeoutError:
            continue

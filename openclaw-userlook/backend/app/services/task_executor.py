from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi.encoders import jsonable_encoder

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.agent import Agent
from app.models.conversation import Conversation
from app.models.message import MessageRole
from app.models.task_run import TERMINAL_RUN_STATUSES, TaskRun, TaskRunStatus
from app.models.user import User
from app.services.conversation_service import save_message
from app.services.file_service import register_output_files
from app.services.openclaw_adapter import OpenClawAdapter, OpenClawAdapterEvent
from app.services.run_service import (
    mark_task_run_cancelled,
    mark_task_run_failed,
    mark_task_run_running,
    mark_task_run_success,
    mark_task_run_timeout,
    touch_task_run_heartbeat,
)
from app.services.task_queue import QueueStatus, task_queue
from app.services.ws_connection_manager import connection_manager


HEARTBEAT_INTERVAL_SECONDS = 5
TERMINAL_GATEWAY_STATUSES = {"success", "failed", "cancelled", "timeout"}
ERROR_GATEWAY_STATUSES = {"failed", "cancelled", "timeout"}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _extract_incremental_text(current_text: str, incoming_text: str | None) -> str:
    if not incoming_text:
        return ""
    if not current_text:
        return incoming_text
    if incoming_text.startswith(current_text):
        return incoming_text[len(current_text):]
    if current_text.endswith(incoming_text):
        return ""
    return incoming_text


async def _broadcast_run_status(
    conversation_id: int,
    *,
    run_id: int,
    status_value: str,
    message: str | None = None,
    output_files: list | None = None,
) -> None:
    payload = {"type": "run_status", "run_id": run_id, "status": status_value}
    if message:
        payload["message"] = message
    if output_files is not None:
        payload["output_files"] = output_files
    await connection_manager.broadcast_json(conversation_id, payload)


async def _broadcast_assistant_done(
    conversation_id: int,
    *,
    message_id: int,
    run_id: int,
    output_files: list,
) -> None:
    await connection_manager.broadcast_json(
        conversation_id,
        {
            "type": "assistant_done",
            "message_id": message_id,
            "run_id": run_id,
            "output_files": output_files,
        },
    )


def _final_silence_seconds(last_delta_at: datetime | None) -> float | None:
    if last_delta_at is None:
        return None
    return max(0.0, (_utc_now() - last_delta_at).total_seconds())


async def start_chat_run(
    *,
    run_id: int,
    user_id: int,
    agent_id: int,
    conversation_id: int,
    content: str,
    file_ids: list[int],
    gateway_files: list[dict[str, object]],
) -> QueueStatus:
    async def task_func(cancel_event: asyncio.Event) -> None:
        await execute_chat_run(
            run_id=run_id,
            user_id=user_id,
            agent_id=agent_id,
            conversation_id=conversation_id,
            content=content,
            file_ids=file_ids,
            gateway_files=gateway_files,
            cancel_event=cancel_event,
        )

    return await task_queue.enqueue_conversation_task(conversation_id, run_id, task_func)


async def _finish_success(
    *,
    db,
    run: TaskRun,
    user: User,
    conversation: Conversation,
    conversation_id: int,
    assistant_content: str,
    output_dir: str | None = None,
    raw_payload: dict | None = None,
) -> TaskRun:
    assistant_message = save_message(
        db,
        conversation,
        MessageRole.assistant,
        assistant_content,
        raw_payload=raw_payload,
        run_id=run.id,
    )
    run = mark_task_run_success(
        db,
        run,
        output_text=assistant_content,
        output_dir=output_dir or run.output_dir,
    )
    output_files = register_output_files(db, user.id, run.output_dir)
    output_files_payload = jsonable_encoder(output_files)
    run.output_files_json = output_files_payload
    db.commit()
    await _broadcast_assistant_done(
        conversation_id,
        message_id=assistant_message.id,
        run_id=run.id,
        output_files=output_files_payload,
    )
    await _broadcast_run_status(
        conversation_id,
        run_id=run.id,
        status_value=run.status.value,
        output_files=output_files_payload,
    )
    return run


async def _handle_terminal_error_event(
    *,
    db,
    run: TaskRun,
    user: User,
    conversation: Conversation,
    conversation_id: int,
    event: OpenClawAdapterEvent,
    assistant_content: str,
) -> TaskRun:
    terminal_status = event.status or "failed"
    if terminal_status == "cancelled":
        raise asyncio.CancelledError
    if terminal_status == "timeout":
        run = mark_task_run_timeout(
            db,
            run,
            event.content or "OpenClaw Gateway 响应超时",
            output_text=assistant_content or None,
        )
    else:
        run = mark_task_run_failed(
            db,
            run,
            event.content or "OpenClaw call failed",
            output_text=assistant_content or None,
        )
    output_files_payload = []
    if assistant_content:
        assistant_message = save_message(
            db,
            conversation,
            MessageRole.assistant,
            assistant_content,
            raw_payload={
                "partial": True,
                "error": terminal_status,
                "gateway_event": event.raw,
            },
            run_id=run.id,
        )
        output_files = register_output_files(db, user.id, run.output_dir)
        output_files_payload = jsonable_encoder(output_files)
        run.output_files_json = output_files_payload
        db.commit()
        await _broadcast_assistant_done(
            conversation_id,
            message_id=assistant_message.id,
            run_id=run.id,
            output_files=output_files_payload,
        )
    await connection_manager.broadcast_json(
        conversation_id,
        {"type": "error", "message": event.content or "OpenClaw 调用失败"},
    )
    await _broadcast_run_status(
        conversation_id,
        run_id=run.id,
        status_value=run.status.value,
        message=run.error_message,
        output_files=output_files_payload,
    )
    return run


async def execute_chat_run(
    *,
    run_id: int,
    user_id: int,
    agent_id: int,
    conversation_id: int,
    content: str,
    file_ids: list[int],
    gateway_files: list[dict[str, object]],
    cancel_event: asyncio.Event,
) -> None:
    assistant_content = ""
    last_gateway_event = None
    terminal_event_received = False
    gateway_terminal_status: str | None = None
    first_token_at: datetime | None = None
    last_delta_at: datetime | None = None
    settings = get_settings()
    adapter = OpenClawAdapter(settings=settings)
    task_queue.set_abort(run_id, cancel_event.set)

    try:
        with SessionLocal() as db:
            run = db.get(TaskRun, run_id)
            user = db.get(User, user_id)
            agent = db.get(Agent, agent_id)
            conversation = db.get(Conversation, conversation_id)
            if run is None or user is None or agent is None or conversation is None:
                return
            if run.status in TERMINAL_RUN_STATUSES:
                await _broadcast_run_status(
                    conversation_id,
                    run_id=run.id,
                    status_value=run.status.value,
                    message=run.error_message,
                )
                return
            if cancel_event.is_set() or run.cancel_requested:
                run = mark_task_run_cancelled(db, run, "用户已停止生成")
                await _broadcast_run_status(
                    conversation_id,
                    run_id=run.id,
                    status_value=run.status.value,
                    message=run.error_message,
                )
                return

            run = mark_task_run_running(db, run)
            if run.status in TERMINAL_RUN_STATUSES:
                await _broadcast_run_status(
                    conversation_id,
                    run_id=run.id,
                    status_value=run.status.value,
                    message=run.error_message,
                )
                return
            await _broadcast_run_status(conversation_id, run_id=run.id, status_value="running")

            timeout_seconds = run.timeout_seconds or settings.task_short_chat_timeout_seconds
            last_heartbeat = _utc_now()
            try:
                async with asyncio.timeout(timeout_seconds):
                    async for event in adapter.stream_chat(
                        user=user,
                        agent=agent,
                        conversation=conversation,
                        content=content,
                        file_ids=file_ids,
                        files=gateway_files,
                        run_id=run.id,
                        output_dir=run.output_dir,
                        cancel_event=cancel_event,
                        assume_done_after_text_silence=settings.task_assume_done_after_text_silence,
                        final_silence_seconds=settings.task_gateway_final_silence_seconds,
                    ):
                        last_gateway_event = event.raw
                        if cancel_event.is_set():
                            raise asyncio.CancelledError

                        now = _utc_now()
                        run = db.get(TaskRun, run.id) or run
                        if run.status in TERMINAL_RUN_STATUSES:
                            await _broadcast_run_status(
                                conversation_id,
                                run_id=run.id,
                                status_value=run.status.value,
                                message=run.error_message,
                            )
                            return
                        if run.cancel_requested:
                            cancel_event.set()
                            raise asyncio.CancelledError
                        if (now - last_heartbeat).total_seconds() >= HEARTBEAT_INTERVAL_SECONDS:
                            run = touch_task_run_heartbeat(db, run)
                            last_heartbeat = now

                        if event.type == "delta":
                            part = _extract_incremental_text(assistant_content, event.content)
                            if part:
                                if first_token_at is None:
                                    first_token_at = now
                                last_delta_at = now
                                assistant_content += part
                                await connection_manager.broadcast_json(
                                    conversation_id,
                                    {"type": "assistant_delta", "content": part},
                                )
                            continue

                        if event.status in TERMINAL_GATEWAY_STATUSES:
                            terminal_event_received = True
                            gateway_terminal_status = event.status

                        if event.type == "run_status" and event.status not in TERMINAL_GATEWAY_STATUSES:
                            await _broadcast_run_status(
                                conversation_id,
                                run_id=run.id,
                                status_value=event.status or "running",
                                message=event.content,
                            )
                            continue

                        if event.type == "error" or event.status in ERROR_GATEWAY_STATUSES:
                            await _handle_terminal_error_event(
                                db=db,
                                run=run,
                                user=user,
                                conversation=conversation,
                                conversation_id=conversation_id,
                                event=event,
                                assistant_content=assistant_content,
                            )
                            return

                        final_delta = _extract_incremental_text(assistant_content, event.content)
                        if final_delta:
                            if first_token_at is None:
                                first_token_at = now
                            last_delta_at = now
                            assistant_content += final_delta
                            await connection_manager.broadcast_json(
                                conversation_id,
                                {"type": "assistant_delta", "content": final_delta},
                            )

                        if event.type == "done" or event.status == "success":
                            await _finish_success(
                                db=db,
                                run=run,
                                user=user,
                                conversation=conversation,
                                conversation_id=conversation_id,
                                assistant_content=assistant_content,
                                output_dir=event.output_dir or run.output_dir,
                                raw_payload={
                                    "mock": adapter.settings.mock_openclaw,
                                    "gateway_event": event.raw,
                                    "terminal_event_received": terminal_event_received,
                                    "gateway_terminal_status": gateway_terminal_status,
                                    "first_token_at": first_token_at.isoformat() if first_token_at else None,
                                    "last_delta_at": last_delta_at.isoformat() if last_delta_at else None,
                                },
                            )
                            return
            except TimeoutError:
                silence_seconds = _final_silence_seconds(last_delta_at)
                can_assume_done = (
                    settings.task_assume_done_after_text_silence
                    and assistant_content
                    and gateway_terminal_status not in ERROR_GATEWAY_STATUSES
                    and silence_seconds is not None
                    and silence_seconds >= settings.task_gateway_final_silence_seconds
                )
                if can_assume_done:
                    await _finish_success(
                        db=db,
                        run=run,
                        user=user,
                        conversation=conversation,
                        conversation_id=conversation_id,
                        assistant_content=assistant_content,
                        raw_payload={
                            "mock": adapter.settings.mock_openclaw,
                            "gateway_event": last_gateway_event,
                            "terminal_event_received": False,
                            "gateway_terminal_status": gateway_terminal_status,
                            "first_token_at": first_token_at.isoformat() if first_token_at else None,
                            "last_delta_at": last_delta_at.isoformat() if last_delta_at else None,
                            "assumed_done_after_text_silence": True,
                            "final_silence_seconds": silence_seconds,
                        },
                    )
                    return

                run = mark_task_run_timeout(
                    db,
                    run,
                    "OpenClaw Gateway 响应超时",
                    output_text=assistant_content or None,
                )
                output_files_payload = []
                if assistant_content:
                    assistant_message = save_message(
                        db,
                        conversation,
                        MessageRole.assistant,
                        assistant_content,
                        raw_payload={
                            "partial": True,
                            "timeout": True,
                            "gateway_event": last_gateway_event,
                            "first_token_at": first_token_at.isoformat() if first_token_at else None,
                            "last_delta_at": last_delta_at.isoformat() if last_delta_at else None,
                        },
                        run_id=run.id,
                    )
                    output_files = register_output_files(db, user.id, run.output_dir)
                    output_files_payload = jsonable_encoder(output_files)
                    run.output_files_json = output_files_payload
                    db.commit()
                    await _broadcast_assistant_done(
                        conversation_id,
                        message_id=assistant_message.id,
                        run_id=run.id,
                        output_files=output_files_payload,
                    )
                await _broadcast_run_status(
                    conversation_id,
                    run_id=run.id,
                    status_value=run.status.value,
                    message=run.error_message,
                    output_files=output_files_payload,
                )
                return

            if assistant_content:
                silence_seconds = _final_silence_seconds(last_delta_at)
                await _finish_success(
                    db=db,
                    run=run,
                    user=user,
                    conversation=conversation,
                    conversation_id=conversation_id,
                    assistant_content=assistant_content,
                    raw_payload={
                        "mock": adapter.settings.mock_openclaw,
                        "gateway_event": last_gateway_event,
                        "terminal_event_received": False,
                        "gateway_terminal_status": gateway_terminal_status,
                        "first_token_at": first_token_at.isoformat() if first_token_at else None,
                        "last_delta_at": last_delta_at.isoformat() if last_delta_at else None,
                        "assumed_done_after_text_silence": bool(
                            settings.task_assume_done_after_text_silence
                            and silence_seconds is not None
                            and silence_seconds >= settings.task_gateway_final_silence_seconds
                        ),
                        "final_silence_seconds": silence_seconds,
                    },
                )
                return

            run = mark_task_run_failed(
                db,
                run,
                "OpenClaw stream ended without output",
            )
            await _broadcast_run_status(
                conversation_id,
                run_id=run.id,
                status_value=run.status.value,
                message=run.error_message,
            )
    except asyncio.CancelledError:
        cancel_event.set()
        with SessionLocal() as db:
            run = db.get(TaskRun, run_id)
            conversation = db.get(Conversation, conversation_id)
            if run is not None and run.status not in TERMINAL_RUN_STATUSES:
                run = mark_task_run_cancelled(
                    db,
                    run,
                    "用户已停止生成",
                    output_text=assistant_content or None,
                )
                if assistant_content and conversation is not None:
                    assistant_message = save_message(
                        db,
                        conversation,
                        MessageRole.assistant,
                        assistant_content,
                        raw_payload={
                            "partial": True,
                            "cancelled": True,
                            "gateway_event": last_gateway_event,
                            "first_token_at": first_token_at.isoformat() if first_token_at else None,
                            "last_delta_at": last_delta_at.isoformat() if last_delta_at else None,
                        },
                        run_id=run.id,
                    )
                    await _broadcast_assistant_done(
                        conversation_id,
                        message_id=assistant_message.id,
                        run_id=run.id,
                        output_files=[],
                    )
            if run is not None:
                await _broadcast_run_status(
                    conversation_id,
                    run_id=run.id,
                    status_value=run.status.value,
                    message=run.error_message or "用户已停止生成",
                )
    except Exception as exc:
        with SessionLocal() as db:
            run = db.get(TaskRun, run_id)
            if run is not None and run.status not in TERMINAL_RUN_STATUSES:
                run = mark_task_run_failed(
                    db,
                    run,
                    str(exc) or "OpenClaw call failed",
                    output_text=assistant_content or None,
                )
                await connection_manager.broadcast_json(
                    conversation_id,
                    {"type": "error", "message": str(exc) or "OpenClaw 调用失败"},
                )
                await _broadcast_run_status(
                    conversation_id,
                    run_id=run.id,
                    status_value=run.status.value,
                    message=run.error_message,
                )
    finally:
        task_queue.set_abort(run_id, None)

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
from app.services.openclaw_adapter import OpenClawAdapter
from app.services.run_service import (
    mark_task_run_cancelled,
    mark_task_run_failed,
    mark_task_run_running,
    mark_task_run_success,
    mark_task_run_timeout,
    touch_task_run_heartbeat,
)
from app.services.task_queue import task_queue
from app.services.ws_connection_manager import connection_manager


HEARTBEAT_INTERVAL_SECONDS = 5


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


async def start_chat_run(
    *,
    run_id: int,
    user_id: int,
    agent_id: int,
    conversation_id: int,
    content: str,
    file_ids: list[int],
    gateway_files: list[dict[str, object]],
) -> None:
    task = asyncio.create_task(
        execute_chat_run_with_global_limit(
            run_id=run_id,
            user_id=user_id,
            agent_id=agent_id,
            conversation_id=conversation_id,
            content=content,
            file_ids=file_ids,
            gateway_files=gateway_files,
        )
    )
    task_queue.register_task(run_id, task)


async def execute_chat_run_with_global_limit(
    *,
    run_id: int,
    user_id: int,
    agent_id: int,
    conversation_id: int,
    content: str,
    file_ids: list[int],
    gateway_files: list[dict[str, object]],
) -> None:
    settings = get_settings()
    try:
        async with task_queue.get_chat_semaphore(settings.task_global_chat_concurrency):
            await execute_chat_run(
                run_id=run_id,
                user_id=user_id,
                agent_id=agent_id,
                conversation_id=conversation_id,
                content=content,
                file_ids=file_ids,
                gateway_files=gateway_files,
            )
    finally:
        task_queue.unregister_task(run_id)


async def execute_chat_run(
    *,
    run_id: int,
    user_id: int,
    agent_id: int,
    conversation_id: int,
    content: str,
    file_ids: list[int],
    gateway_files: list[dict[str, object]],
) -> None:
    assistant_content = ""
    last_gateway_event = None
    terminal_event_received = False
    settings = get_settings()
    adapter = OpenClawAdapter(settings=settings)

    try:
        async with task_queue.get_agent_lock(agent_id):
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
                run = mark_task_run_running(db, run)
                await _broadcast_run_status(conversation_id, run_id=run.id, status_value="running")

                timeout_seconds = run.timeout_seconds or settings.task_chat_timeout_seconds
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
                        ):
                            last_gateway_event = event.raw
                            now = _utc_now()
                            if (now - last_heartbeat).total_seconds() >= HEARTBEAT_INTERVAL_SECONDS:
                                run = db.get(TaskRun, run.id) or run
                                if run.cancel_requested:
                                    raise asyncio.CancelledError
                                run = touch_task_run_heartbeat(db, run)
                                last_heartbeat = now
                            else:
                                db.refresh(run)
                                if run.cancel_requested:
                                    raise asyncio.CancelledError

                            if event.type == "delta":
                                part = _extract_incremental_text(assistant_content, event.content)
                                if part:
                                    assistant_content += part
                                    await connection_manager.broadcast_json(
                                        conversation_id,
                                        {"type": "assistant_delta", "content": part},
                                    )
                                continue

                            if event.type == "run_status":
                                event_status = event.status or "running"
                                if event_status not in {"success", "failed", "cancelled", "timeout"}:
                                    await _broadcast_run_status(
                                        conversation_id,
                                        run_id=run.id,
                                        status_value=event_status,
                                        message=event.content,
                                    )
                                    continue

                            terminal_event_received = True
                            if event.type == "error" or event.status in {"failed", "cancelled", "timeout"}:
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
                                if assistant_content:
                                    assistant_message = save_message(
                                        db,
                                        conversation,
                                        MessageRole.assistant,
                                        assistant_content,
                                        raw_payload={
                                            "partial": True,
                                            "error": True,
                                            "gateway_event": event.raw,
                                        },
                                        run_id=run.id,
                                    )
                                    await _broadcast_assistant_done(
                                        conversation_id,
                                        message_id=assistant_message.id,
                                        run_id=run.id,
                                        output_files=[],
                                    )
                                await connection_manager.broadcast_json(
                                    conversation_id,
                                    {"type": "error", "message": event.content or "OpenClaw 调用失败"},
                                )
                                await _broadcast_run_status(
                                    conversation_id,
                                    run_id=run.id,
                                    status_value=run.status.value,
                                    message=event.content,
                                )
                                return

                            final_delta = _extract_incremental_text(assistant_content, event.content)
                            if final_delta:
                                assistant_content += final_delta
                                await connection_manager.broadcast_json(
                                    conversation_id,
                                    {"type": "assistant_delta", "content": final_delta},
                                )

                            final_output_dir = event.output_dir or run.output_dir
                            assistant_message = save_message(
                                db,
                                conversation,
                                MessageRole.assistant,
                                assistant_content,
                                raw_payload={
                                    "mock": adapter.settings.mock_openclaw,
                                    "gateway_event": event.raw,
                                    "terminal_event_received": terminal_event_received,
                                },
                                run_id=run.id,
                            )
                            run = mark_task_run_success(
                                db,
                                run,
                                output_text=assistant_content,
                                output_dir=final_output_dir,
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
                                status_value="success",
                                output_files=output_files_payload,
                            )
                            return
                except TimeoutError:
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
                        status_value="timeout",
                        message=run.error_message,
                        output_files=output_files_payload,
                    )
                    return

                if assistant_content:
                    assistant_message = save_message(
                        db,
                        conversation,
                        MessageRole.assistant,
                        assistant_content,
                        raw_payload={
                            "mock": adapter.settings.mock_openclaw,
                            "gateway_event": last_gateway_event,
                            "terminal_event_received": False,
                        },
                        run_id=run.id,
                    )
                    run = mark_task_run_success(db, run, output_text=assistant_content)
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
                        status_value="success",
                        output_files=output_files_payload,
                    )
                    return

                run = mark_task_run_failed(
                    db,
                    run,
                    "OpenClaw stream ended without terminal event",
                )
                await _broadcast_run_status(
                    conversation_id,
                    run_id=run.id,
                    status_value="failed",
                    message=run.error_message,
                )
    except asyncio.CancelledError:
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
                        raw_payload={"partial": True, "cancelled": True, "gateway_event": last_gateway_event},
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
                    status_value="cancelled",
                    message="用户已停止生成",
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
                    status_value="failed",
                    message=run.error_message,
                )
    finally:
        task_queue.unregister_task(run_id)

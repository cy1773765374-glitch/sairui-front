import asyncio
import contextlib
import json

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from fastapi.encoders import jsonable_encoder
from jose import JWTError
from pydantic import ValidationError

from app.core.database import SessionLocal
from app.core.security import decode_access_token
from app.models.agent import Agent
from app.models.audit_log import AuditLog
from app.models.message import MessageRole
from app.models.user import UserStatus
from app.models.task_run import TaskRun
from app.schemas.message import WebSocketCancelRunMessage, WebSocketUserMessage
from app.services.agent_service import user_can_access_agent
from app.services.auth_service import get_user_by_id
from app.services.conversation_service import require_conversation_for_user, save_message
from app.services.file_service import (
    list_gateway_upload_files,
    register_output_files,
    validate_user_upload_file_ids,
)
from app.services.openclaw_adapter import OpenClawAdapter
from app.services.run_service import (
    create_task_run,
    mark_task_run_cancelled,
    mark_task_run_failed,
    mark_task_run_running,
    mark_task_run_success,
)
from app.services.ws_connection_manager import connection_manager

router = APIRouter(tags=["ws-chat"])

TERMINAL_RUN_STATUSES = {"success", "failed", "cancelled"}


async def _close_with_error(websocket: WebSocket, message: str) -> None:
    await websocket.accept()
    await websocket.send_json({"type": "error", "message": message})
    await websocket.close(code=status.WS_1008_POLICY_VIOLATION)


def _record_agent_call_audit(
    db,
    *,
    user_id: int,
    agent: Agent,
    conversation_id: int,
    session_key: str,
    file_ids: list[int],
    ip: str | None,
    user_agent: str | None,
) -> None:
    detail = {
        "agent_code": agent.code,
        "openclaw_agent_id": agent.openclaw_agent_id,
        "conversation_id": conversation_id,
        "session_key": session_key,
        "file_ids": file_ids,
    }
    db.add(
        AuditLog(
            user_id=user_id,
            action="agent.invoke",
            target_type="agent",
            target_id=agent.id,
            detail=json.dumps(detail, ensure_ascii=False),
            ip=ip,
            user_agent=user_agent,
        )
    )
    db.commit()


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


async def _send_run_status(
    websocket: WebSocket,
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
    await connection_manager.send_json(websocket, payload)


async def _send_assistant_done(
    websocket: WebSocket,
    *,
    message_id: int,
    run_id: int,
    output_files: list,
) -> None:
    await connection_manager.send_json(
        websocket,
        {
            "type": "assistant_done",
            "message_id": message_id,
            "run_id": run_id,
            "output_files": output_files,
        },
    )


@router.websocket("/ws/conversations/{conversation_id}")
async def chat_websocket(
    websocket: WebSocket,
    conversation_id: int,
    token: str | None = Query(default=None),
) -> None:
    if not token:
        await _close_with_error(websocket, "missing token")
        return

    with SessionLocal() as db:
        try:
            payload = decode_access_token(token)
            subject = payload.get("sub")
            if subject is None:
                raise ValueError("missing subject")
            current_user = get_user_by_id(db, int(subject))
        except (JWTError, ValueError):
            await _close_with_error(websocket, "invalid token")
            return

        if current_user is None or current_user.status != UserStatus.active:
            await _close_with_error(websocket, "invalid user")
            return

        try:
            conversation = require_conversation_for_user(db, current_user, conversation_id)
        except Exception:
            await _close_with_error(websocket, "conversation not found")
            return

        agent = db.get(Agent, conversation.agent_id)
        if agent is None or not user_can_access_agent(db, current_user, agent):
            await _close_with_error(websocket, "agent not found")
            return

        await connection_manager.connect(conversation.id, websocket)
        adapter = OpenClawAdapter()
        active_task_run: TaskRun | None = None
        active_run_task: asyncio.Task[None] | None = None

        async def run_agent_message(
            inbound_message: WebSocketUserMessage,
            task_run: TaskRun,
            gateway_files: list[dict[str, object]],
        ) -> None:
            nonlocal active_task_run, active_run_task
            assistant_content = ""
            last_gateway_event = None
            try:
                task_run = mark_task_run_running(db, task_run)
                await _send_run_status(websocket, run_id=task_run.id, status_value="running")

                async for event in adapter.stream_chat(
                    user=current_user,
                    agent=agent,
                    conversation=conversation,
                    content=inbound_message.content,
                    file_ids=inbound_message.file_ids,
                    files=gateway_files,
                    run_id=task_run.id,
                    output_dir=task_run.output_dir,
                ):
                    last_gateway_event = event.raw
                    if event.type == "delta":
                        part = _extract_incremental_text(assistant_content, event.content)
                        if part:
                            assistant_content += part
                            await connection_manager.send_json(
                                websocket,
                                {"type": "assistant_delta", "content": part},
                            )
                        continue

                    if event.type == "run_status":
                        event_status = event.status or "running"
                        if event_status in TERMINAL_RUN_STATUSES:
                            terminal_event = event
                        else:
                            await _send_run_status(
                                websocket,
                                run_id=task_run.id,
                                status_value=event_status,
                                message=event.content,
                            )
                            continue
                    else:
                        terminal_event = event

                    if terminal_event.type == "error":
                        terminal_status = terminal_event.status or "failed"
                        if terminal_status == "cancelled":
                            task_run = mark_task_run_cancelled(
                                db,
                                task_run,
                                terminal_event.content or "OpenClaw call cancelled",
                                output_text=assistant_content or None,
                            )
                        else:
                            task_run = mark_task_run_failed(
                                db,
                                task_run,
                                terminal_event.content or "OpenClaw call failed",
                                output_text=assistant_content or None,
                            )
                        if assistant_content:
                            assistant_message = save_message(
                                db,
                                conversation,
                                MessageRole.assistant,
                                assistant_content,
                                raw_payload={
                                    "error": terminal_status != "cancelled",
                                    "cancelled": terminal_status == "cancelled",
                                    "gateway_event": terminal_event.raw,
                                },
                            )
                            await _send_assistant_done(
                                websocket,
                                message_id=assistant_message.id,
                                run_id=task_run.id,
                                output_files=[],
                            )
                        if terminal_status != "cancelled":
                            await connection_manager.send_json(
                                websocket,
                                {
                                    "type": "error",
                                    "message": terminal_event.content or "OpenClaw 调用失败",
                                },
                            )
                        await _send_run_status(
                            websocket,
                            run_id=task_run.id,
                            status_value=terminal_status,
                            message=terminal_event.content,
                        )
                        return

                    final_delta = _extract_incremental_text(assistant_content, terminal_event.content)
                    if final_delta:
                        assistant_content += final_delta
                        await connection_manager.send_json(
                            websocket,
                            {"type": "assistant_delta", "content": final_delta},
                        )

                    final_output_dir = terminal_event.output_dir or task_run.output_dir
                    assistant_message = save_message(
                        db,
                        conversation,
                        MessageRole.assistant,
                        assistant_content,
                        raw_payload={
                            "mock": adapter.settings.mock_openclaw,
                            "gateway_event": terminal_event.raw,
                        },
                    )
                    task_run = mark_task_run_success(
                        db,
                        task_run,
                        output_text=assistant_content,
                        output_dir=final_output_dir,
                    )
                    output_files = register_output_files(db, current_user.id, task_run.output_dir)
                    output_files_payload = jsonable_encoder(output_files)
                    await _send_assistant_done(
                        websocket,
                        message_id=assistant_message.id,
                        run_id=task_run.id,
                        output_files=output_files_payload,
                    )
                    await _send_run_status(
                        websocket,
                        run_id=task_run.id,
                        status_value="success",
                        output_files=output_files_payload,
                    )
                    return
            except asyncio.CancelledError:
                task_run = mark_task_run_cancelled(
                    db,
                    task_run,
                    "用户已停止生成",
                    output_text=assistant_content or None,
                )
                if assistant_content:
                    assistant_message = save_message(
                        db,
                        conversation,
                        MessageRole.assistant,
                        assistant_content,
                        raw_payload={"cancelled": True, "gateway_event": last_gateway_event},
                    )
                    await _send_assistant_done(
                        websocket,
                        message_id=assistant_message.id,
                        run_id=task_run.id,
                        output_files=[],
                    )
                await _send_run_status(
                    websocket,
                    run_id=task_run.id,
                    status_value="cancelled",
                    message="用户已停止生成",
                )
                raise
            except Exception as exc:
                task_run = mark_task_run_failed(
                    db,
                    task_run,
                    str(exc) or "OpenClaw call failed",
                    output_text=assistant_content or None,
                )
                await connection_manager.send_json(
                    websocket,
                    {"type": "error", "message": str(exc) or "OpenClaw 调用失败"},
                )
                await _send_run_status(
                    websocket,
                    run_id=task_run.id,
                    status_value="failed",
                    message=str(exc) or "OpenClaw call failed",
                )
            finally:
                if active_task_run is not None and active_task_run.id == task_run.id:
                    active_task_run = None
                if active_run_task is asyncio.current_task():
                    active_run_task = None

        try:
            while True:
                raw_message = await websocket.receive_json()
                message_type = raw_message.get("type") if isinstance(raw_message, dict) else None

                if message_type == "cancel_run":
                    try:
                        cancel_message = WebSocketCancelRunMessage.model_validate(raw_message)
                    except ValidationError:
                        await connection_manager.send_json(
                            websocket,
                            {"type": "error", "message": "invalid cancel message format"},
                        )
                        continue
                    if (
                        active_task_run is None
                        or active_run_task is None
                        or active_task_run.id != cancel_message.run_id
                    ):
                        await _send_run_status(
                            websocket,
                            run_id=cancel_message.run_id,
                            status_value="cancelled",
                            message="没有正在运行的任务",
                        )
                        continue
                    active_run_task.cancel()
                    with contextlib.suppress(BaseException):
                        await active_run_task
                    continue

                if active_run_task is not None and not active_run_task.done():
                    await connection_manager.send_json(
                        websocket,
                        {"type": "error", "message": "Agent 正在响应，请稍后再发送"},
                    )
                    continue

                try:
                    inbound_message = WebSocketUserMessage.model_validate(raw_message)
                except ValidationError:
                    await connection_manager.send_json(
                        websocket,
                        {"type": "error", "message": "invalid message format"},
                    )
                    continue

                try:
                    validate_user_upload_file_ids(db, current_user, inbound_message.file_ids)
                    gateway_files = list_gateway_upload_files(
                        db,
                        current_user,
                        inbound_message.file_ids,
                    )
                except HTTPException:
                    await connection_manager.send_json(
                        websocket,
                        {"type": "error", "message": "invalid file_ids"},
                    )
                    continue

                task_run = create_task_run(
                    db,
                    current_user=current_user,
                    agent=agent,
                    conversation_id=conversation.id,
                    input_text=inbound_message.content,
                )
                active_task_run = task_run
                await _send_run_status(websocket, run_id=task_run.id, status_value="pending")

                _record_agent_call_audit(
                    db,
                    user_id=current_user.id,
                    agent=agent,
                    conversation_id=conversation.id,
                    session_key=conversation.session_key,
                    file_ids=inbound_message.file_ids,
                    ip=websocket.client.host if websocket.client else None,
                    user_agent=websocket.headers.get("user-agent"),
                )
                save_message(
                    db,
                    conversation,
                    MessageRole.user,
                    inbound_message.content,
                    raw_payload=inbound_message.model_dump(),
                )

                active_run_task = asyncio.create_task(
                    run_agent_message(inbound_message, task_run, gateway_files)
                )
        except WebSocketDisconnect:
            if active_run_task is not None and not active_run_task.done():
                active_run_task.cancel()
                with contextlib.suppress(BaseException):
                    await active_run_task
            connection_manager.disconnect(conversation.id, websocket)
        except Exception as exc:
            if active_run_task is not None and not active_run_task.done():
                active_run_task.cancel()
                with contextlib.suppress(BaseException):
                    await active_run_task
            connection_manager.disconnect(conversation.id, websocket)
            if active_task_run is not None:
                mark_task_run_failed(db, active_task_run, str(exc) or "WebSocket internal error")
            try:
                await connection_manager.send_json(
                    websocket,
                    {"type": "error", "message": str(exc) or "WebSocket 内部错误"},
                )
            finally:
                await websocket.close(code=status.WS_1011_INTERNAL_ERROR)

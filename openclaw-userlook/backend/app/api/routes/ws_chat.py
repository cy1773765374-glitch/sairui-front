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
from app.schemas.message import WebSocketCancelRunMessage, WebSocketUserMessage
from app.services.agent_service import user_can_access_agent
from app.services.auth_service import get_user_by_id
from app.services.conversation_service import require_conversation_for_user, save_message
from app.services.file_service import list_gateway_upload_files, validate_user_upload_file_ids
from app.services.run_service import (
    create_task_run,
    get_task_run_detail,
    get_latest_active_run_for_conversation,
    request_task_run_cancel,
)
from app.services.task_executor import start_chat_run
from app.services.task_queue import task_queue
from app.services.ws_connection_manager import connection_manager

router = APIRouter(tags=["ws-chat"])


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

        async def send_json(payload: dict) -> None:
            await connection_manager.send_json(websocket, payload)

        try:
            while True:
                raw_message = await websocket.receive_json()
                message_type = raw_message.get("type") if isinstance(raw_message, dict) else None

                if message_type == "cancel_run":
                    try:
                        cancel_message = WebSocketCancelRunMessage.model_validate(raw_message)
                    except ValidationError:
                        await send_json({"type": "error", "message": "invalid cancel message format"})
                        continue
                    try:
                        run = request_task_run_cancel(db, current_user, cancel_message.run_id)
                        task_queue.cancel_task(run.id)
                        run_read = get_task_run_detail(db, current_user, run.id)
                    except HTTPException:
                        await send_json({"type": "error", "message": "run not found"})
                        continue
                    await send_json(
                        {
                            "type": "run_status",
                            "run_id": run_read.id,
                            "conversation_id": run_read.conversation_id,
                            "status": run_read.status.value,
                            "message": run_read.error_message,
                        }
                    )
                    continue

                try:
                    inbound_message = WebSocketUserMessage.model_validate(raw_message)
                except ValidationError:
                    await send_json({"type": "error", "message": "invalid message format"})
                    continue

                active_run = get_latest_active_run_for_conversation(db, current_user, conversation.id)
                if active_run is not None or task_queue.has_active_task(conversation.id):
                    await send_json(
                        {
                            "type": "active_run",
                            "message": "当前会话已有任务正在运行",
                            "active_run": jsonable_encoder(active_run) if active_run else None,
                        }
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
                    await send_json({"type": "error", "message": "invalid file_ids"})
                    continue

                task_run = create_task_run(
                    db,
                    current_user=current_user,
                    agent=agent,
                    conversation_id=conversation.id,
                    input_text=inbound_message.content,
                    run_type="chat",
                    priority=100,
                )

                save_message(
                    db,
                    conversation,
                    MessageRole.user,
                    inbound_message.content,
                    raw_payload=inbound_message.model_dump(),
                    run_id=task_run.id,
                )
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

                queue_status = await start_chat_run(
                    run_id=task_run.id,
                    user_id=current_user.id,
                    agent_id=agent.id,
                    conversation_id=conversation.id,
                    content=inbound_message.content,
                    file_ids=inbound_message.file_ids,
                    gateway_files=gateway_files,
                )
                await send_json(
                    {
                        "type": "run_status",
                        "run_id": task_run.id,
                        "conversation_id": conversation.id,
                        "queue_status": queue_status,
                        "status": "queued",
                    }
                )
        except WebSocketDisconnect:
            connection_manager.disconnect(conversation.id, websocket)
        except Exception as exc:
            connection_manager.disconnect(conversation.id, websocket)
            try:
                await connection_manager.send_json(
                    websocket,
                    {"type": "error", "message": str(exc) or "WebSocket 内部错误"},
                )
            finally:
                await websocket.close(code=status.WS_1011_INTERNAL_ERROR)

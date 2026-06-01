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
from app.schemas.message import WebSocketUserMessage
from app.services.agent_service import user_can_access_agent
from app.services.auth_service import get_user_by_id
from app.services.conversation_service import require_conversation_for_user, save_message
from app.services.file_service import register_output_files, validate_user_upload_file_ids
from app.services.openclaw_adapter import OpenClawAdapter
from app.services.run_service import (
    create_task_run,
    mark_task_run_failed,
    mark_task_run_running,
    mark_task_run_success,
)
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
        adapter = OpenClawAdapter()
        active_task_run = None
        try:
            while True:
                raw_message = await websocket.receive_json()
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
                await connection_manager.send_json(
                    websocket,
                    {"type": "run_status", "run_id": task_run.id, "status": "pending"},
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
                save_message(
                    db,
                    conversation,
                    MessageRole.user,
                    inbound_message.content,
                    raw_payload=inbound_message.model_dump(),
                )

                assistant_content = ""
                task_run = mark_task_run_running(db, task_run)
                await connection_manager.send_json(
                    websocket,
                    {"type": "run_status", "run_id": task_run.id, "status": "running"},
                )
                async for event in adapter.stream_chat(
                    user=current_user,
                    agent=agent,
                    conversation=conversation,
                    content=inbound_message.content,
                    file_ids=inbound_message.file_ids,
                    output_dir=task_run.output_dir,
                ):
                    if event.type == "delta":
                        part = event.content or ""
                        assistant_content += part
                        await connection_manager.send_json(
                            websocket,
                            {"type": "assistant_delta", "content": part},
                        )
                        continue

                    if event.type == "run_status":
                        await connection_manager.send_json(
                            websocket,
                            {
                                "type": "run_status",
                                "run_id": task_run.id,
                                "status": event.status or "running",
                                "message": event.content,
                            },
                        )
                        continue

                    if event.type == "error":
                        task_run = mark_task_run_failed(
                            db,
                            task_run,
                            event.content or "OpenClaw call failed",
                        )
                        await connection_manager.send_json(
                            websocket,
                            {"type": "error", "message": event.content or "OpenClaw 调用失败"},
                        )
                        await connection_manager.send_json(
                            websocket,
                            {"type": "run_status", "run_id": task_run.id, "status": "failed"},
                        )
                        if assistant_content:
                            save_message(
                                db,
                                conversation,
                                MessageRole.assistant,
                                assistant_content,
                                raw_payload={"error": True},
                            )
                        active_task_run = None
                        break

                    assistant_message = save_message(
                        db,
                        conversation,
                        MessageRole.assistant,
                        assistant_content,
                        raw_payload={"mock": adapter.settings.mock_openclaw},
                    )
                    task_run = mark_task_run_success(
                        db,
                        task_run,
                        output_text=assistant_content,
                        output_dir=task_run.output_dir,
                    )
                    output_files = register_output_files(db, current_user.id, task_run.output_dir)
                    output_files_payload = jsonable_encoder(output_files)
                    await connection_manager.send_json(
                        websocket,
                        {
                            "type": "assistant_done",
                            "message_id": assistant_message.id,
                            "run_id": task_run.id,
                            "output_files": output_files_payload,
                        },
                    )
                    await connection_manager.send_json(
                        websocket,
                        {
                            "type": "run_status",
                            "run_id": task_run.id,
                            "status": "success",
                            "output_files": output_files_payload,
                        },
                    )
                    active_task_run = None
                    break
        except WebSocketDisconnect:
            connection_manager.disconnect(conversation.id, websocket)
        except Exception as exc:
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

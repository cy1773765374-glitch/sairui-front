import json
import logging

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
from app.services.daoban_service import is_pdf_file
from app.services.file_service import files_to_gateway_payload, validate_and_bind_upload_files
from app.services.gateway_session import build_gateway_session_identity, normalize_client_message_id
from app.services.pending_task_service import (
    cancel_pending_task,
    consume_pending_task,
    save_pending_files,
    save_pending_text,
)
from app.services.run_service import (
    create_task_run,
    get_task_run_by_client_message,
    get_task_run_detail,
    mark_task_run_success,
    request_task_run_cancel,
    upsert_assistant_message_for_run,
)
from app.services.task_classifier import DAOBAN_TASK_TYPE, MemoryAction, TaskKind, classify_task
from app.services.task_executor import start_chat_run
from app.services.task_queue import task_queue
from app.services.workspace_service import resolve_agent_workspace
from app.services.ws_connection_manager import connection_manager

router = APIRouter(tags=["ws-chat"])
logger = logging.getLogger(__name__)


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


def _http_exception_detail(exc: HTTPException, *, fallback_file_ids: list[int]) -> tuple[str, str, list[int]]:
    if isinstance(exc.detail, dict):
        message = str(
            exc.detail.get("message")
            or exc.detail.get("detail")
            or "上传文件无效，请重新上传后再发送"
        )
        code = str(exc.detail.get("code") or "INVALID_FILE_RECORD")
        invalid_file_ids = exc.detail.get("invalid_file_ids") or []
        if not invalid_file_ids and exc.detail.get("file_id") is not None:
            invalid_file_ids = [exc.detail["file_id"]]
        return message, code, list(invalid_file_ids)
    message = exc.detail if isinstance(exc.detail, str) else "上传文件无效，请重新上传后再发送"
    return message, "INVALID_FILE_RECORD", fallback_file_ids


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

        def run_event_context(run, identity=None) -> dict:
            return {
                "conversation_id": run.conversation_id,
                "run_id": run.id,
                "client_message_id": run.client_message_id or (identity.client_message_id if identity else None),
                "agent_code": agent.code,
                "openclaw_agent_id": agent.openclaw_agent_id,
                "gateway_session_key": run.gateway_session_key or (identity.session_key if identity else None),
            }

        try:
            while True:
                raw_message = await websocket.receive_json()
                # The WebSocket keeps one SQLAlchemy Session for a long time. End any
                # old read transaction so MySQL does not serve a stale REPEATABLE READ
                # snapshot that misses files uploaded over a separate HTTP request.
                db.rollback()
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
                            "client_message_id": run_read.client_message_id,
                            "agent_code": run_read.agent_code,
                            "openclaw_agent_id": run_read.openclaw_agent_id,
                            "gateway_session_key": run_read.gateway_session_key,
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

                client_message_id = normalize_client_message_id(inbound_message.client_message_id)
                existing_run = get_task_run_by_client_message(
                    db,
                    conversation_id=conversation.id,
                    client_message_id=client_message_id,
                )
                if existing_run is not None:
                    existing_read = get_task_run_detail(db, current_user, existing_run.id)
                    await send_json(
                        {
                            "type": "user_message_ack",
                            "conversation_id": existing_read.conversation_id,
                            "run_id": existing_read.id,
                            "client_message_id": existing_read.client_message_id,
                            "agent_code": existing_read.agent_code,
                            "openclaw_agent_id": existing_read.openclaw_agent_id,
                            "gateway_session_key": existing_read.gateway_session_key,
                            "status": existing_read.status.value,
                        }
                    )
                    await send_json(
                        {
                            "type": "run_status",
                            "conversation_id": existing_read.conversation_id,
                            "run_id": existing_read.id,
                            "client_message_id": existing_read.client_message_id,
                            "agent_code": existing_read.agent_code,
                            "openclaw_agent_id": existing_read.openclaw_agent_id,
                            "gateway_session_key": existing_read.gateway_session_key,
                            "status": existing_read.status.value,
                            "message": existing_read.error_message,
                            "output_files": jsonable_encoder(existing_read.output_files),
                        }
                    )
                    continue

                try:
                    upload_files = validate_and_bind_upload_files(
                        db,
                        current_user,
                        conversation.id,
                        inbound_message.file_ids,
                    )
                    logger.info(
                        "[chat-send] user_id=%s conversation_id=%s agent=%s file_ids=%s",
                        current_user.id,
                        conversation.id,
                        agent.code,
                        inbound_message.file_ids,
                    )
                except HTTPException as exc:
                    db.rollback()
                    detail, code, invalid_file_ids = _http_exception_detail(
                        exc,
                        fallback_file_ids=inbound_message.file_ids,
                    )
                    await send_json(
                        {
                            "type": "error",
                            "code": code,
                            "message": detail,
                            "invalid_file_ids": invalid_file_ids,
                            "conversation_id": conversation.id,
                            "client_message_id": client_message_id,
                        }
                    )
                    continue

                if not inbound_message.content.strip() and not upload_files:
                    await send_json(
                        {
                            "type": "error",
                            "message": "请输入消息或上传文件。",
                            "conversation_id": conversation.id,
                            "client_message_id": client_message_id,
                        }
                    )
                    continue

                classification = classify_task(
                    db,
                    user=current_user,
                    agent=agent,
                    conversation_id=conversation.id,
                    content=inbound_message.content,
                    files=upload_files,
                )
                workspace_path = str(resolve_agent_workspace(agent))
                effective_content = classification.effective_content
                if effective_content is None:
                    effective_content = inbound_message.content.strip()
                effective_file_ids = classification.effective_file_ids
                if effective_file_ids is None:
                    effective_file_ids = [file.id for file in upload_files]
                try:
                    if list(dict.fromkeys(effective_file_ids)) == [file.id for file in upload_files]:
                        effective_upload_files = upload_files
                    else:
                        effective_upload_files = validate_and_bind_upload_files(
                            db,
                            current_user,
                            conversation.id,
                            effective_file_ids,
                        )
                    effective_files_payload = files_to_gateway_payload(effective_upload_files)
                except HTTPException as exc:
                    db.rollback()
                    detail, code, invalid_file_ids = _http_exception_detail(
                        exc,
                        fallback_file_ids=effective_file_ids,
                    )
                    await send_json(
                        {
                            "type": "error",
                            "code": code,
                            "message": detail,
                            "invalid_file_ids": invalid_file_ids,
                            "conversation_id": conversation.id,
                            "client_message_id": client_message_id,
                        }
                    )
                    continue
                run_type = "job" if classification.task_kind == TaskKind.long_job else "chat"
                if classification.task_kind == TaskKind.pending_input:
                    run_type = "pending_input"

                provisional_identity = build_gateway_session_identity(
                    current_user,
                    agent,
                    conversation,
                    None,
                    client_message_id,
                )
                task_run = create_task_run(
                    db,
                    current_user=current_user,
                    agent=agent,
                    conversation_id=conversation.id,
                    input_text=effective_content,
                    run_type=run_type,
                    priority=100,
                    client_message_id=provisional_identity.client_message_id,
                    gateway_session_key=provisional_identity.session_key,
                    idempotency_key=provisional_identity.idempotency_key,
                    task_kind=classification.task_kind.value,
                    runner_name=classification.runner,
                    workspace_path=workspace_path,
                    raw_payload={
                        "type": "user_message",
                        "content": inbound_message.content,
                        "file_ids": [file.id for file in upload_files],
                        "effective_content": effective_content,
                        "effective_file_ids": effective_file_ids,
                        "files": effective_files_payload,
                        "attachments": effective_files_payload,
                        "channel": provisional_identity.channel,
                        "agent_code": provisional_identity.agent_code,
                        "openclaw_agent_id": provisional_identity.openclaw_agent_id,
                        "workspace_path": workspace_path,
                        "task_kind": classification.task_kind.value,
                        "task_type": classification.task_type,
                        "runner_name": classification.runner,
                        "classification_reason": classification.reason,
                        **(classification.metadata or {}),
                        "selected_pending_file_id": classification.selected_pending_file_id,
                        "conversation_id": conversation.id,
                        "client_message_id": provisional_identity.client_message_id,
                        "gateway_session_key": provisional_identity.session_key,
                        "idempotency_key": provisional_identity.idempotency_key,
                        "status": "queued",
                    },
                )
                identity = build_gateway_session_identity(
                    current_user,
                    agent,
                    conversation,
                    task_run.id,
                    provisional_identity.client_message_id,
                )
                task_run.gateway_session_key = identity.session_key
                task_run.idempotency_key = identity.idempotency_key
                task_run.raw_payload = {
                    **(task_run.raw_payload or {}),
                    **identity.model_dump(),
                    "workspace_path": workspace_path,
                    "task_kind": classification.task_kind.value,
                    "task_type": classification.task_type,
                    "runner_name": classification.runner,
                    "classification_reason": classification.reason,
                    **(classification.metadata or {}),
                    "status": "queued",
                }
                db.commit()
                db.refresh(task_run)

                visible_user_content = inbound_message.content.strip()
                if not visible_user_content and upload_files:
                    visible_user_content = "[仅上传文件]"
                message_raw_payload = {
                    **(task_run.raw_payload or {}),
                    "type": "user_message",
                    "content": inbound_message.content,
                    "file_ids": inbound_message.file_ids,
                    "effective_content": effective_content,
                    "effective_file_ids": effective_file_ids,
                    "files": effective_files_payload,
                    "attachments": effective_files_payload,
                    "client_message_id": identity.client_message_id,
                    "conversation_id": conversation.id,
                    "run_id": task_run.id,
                    "agent_code": agent.code,
                    "openclaw_agent_id": agent.openclaw_agent_id,
                    "gateway_session_key": identity.session_key,
                    "idempotency_key": identity.idempotency_key,
                }
                user_message = save_message(
                    db,
                    conversation,
                    MessageRole.user,
                    visible_user_content,
                    raw_payload=message_raw_payload,
                    run_id=task_run.id,
                )
                _record_agent_call_audit(
                    db,
                    user_id=current_user.id,
                    agent=agent,
                    conversation_id=conversation.id,
                    session_key=identity.session_key,
                    file_ids=effective_file_ids,
                    ip=websocket.client.host if websocket.client else None,
                    user_agent=websocket.headers.get("user-agent"),
                )

                await send_json(
                    {
                        "type": "user_message_ack",
                        **run_event_context(task_run, identity),
                        "status": "success" if classification.task_kind == TaskKind.pending_input else "queued",
                        "task_kind": classification.task_kind.value,
                        "runner_name": classification.runner,
                    }
                )

                if classification.task_kind == TaskKind.pending_input:
                    pending_task_type = classification.task_type or DAOBAN_TASK_TYPE
                    if classification.memory_action == MemoryAction.save_pdf:
                        pdf_file_ids = [file.id for file in upload_files if is_pdf_file(file)]
                        save_pending_files(
                            db,
                            user=current_user,
                            conversation_id=conversation.id,
                            agent=agent,
                            task_type=pending_task_type,
                            file_ids=pdf_file_ids,
                            source_message_id=user_message.id,
                        )
                    elif classification.memory_action == MemoryAction.save_files:
                        save_pending_files(
                            db,
                            user=current_user,
                            conversation_id=conversation.id,
                            agent=agent,
                            task_type=pending_task_type,
                            file_ids=effective_file_ids,
                            source_message_id=user_message.id,
                        )
                    elif classification.memory_action == MemoryAction.save_text:
                        save_pending_text(
                            db,
                            user=current_user,
                            conversation_id=conversation.id,
                            agent=agent,
                            task_type=pending_task_type,
                            text_value=effective_content,
                            source_message_id=user_message.id,
                        )
                    elif classification.memory_action == MemoryAction.save_text_and_files:
                        save_pending_text(
                            db,
                            user=current_user,
                            conversation_id=conversation.id,
                            agent=agent,
                            task_type=pending_task_type,
                            text_value=effective_content,
                            source_message_id=user_message.id,
                        )
                        if effective_file_ids:
                            save_pending_files(
                                db,
                                user=current_user,
                                conversation_id=conversation.id,
                                agent=agent,
                                task_type=pending_task_type,
                                file_ids=effective_file_ids,
                                source_message_id=user_message.id,
                            )
                    elif classification.memory_action == MemoryAction.clear_pending:
                        cancel_pending_task(
                            db,
                            user_id=current_user.id,
                            conversation_id=conversation.id,
                            agent_id=agent.id,
                            task_type=pending_task_type,
                        )

                    response_message = classification.response_message or "已记录当前输入。"
                    task_run.raw_payload = {
                        **(task_run.raw_payload or {}),
                        "status": "success",
                        "pending_input": True,
                        "response_message": response_message,
                    }
                    assistant_message = upsert_assistant_message_for_run(
                        db,
                        run=task_run,
                        conversation=conversation,
                        content=response_message,
                        raw_payload_patch=task_run.raw_payload,
                    )
                    task_run = db.get(type(task_run), task_run.id) or task_run
                    task_run = mark_task_run_success(db, task_run, output_text=response_message)
                    await send_json(
                        {
                            "type": "run_status",
                            **run_event_context(task_run, identity),
                            "status": task_run.status.value,
                            "message": response_message,
                            "task_kind": classification.task_kind.value,
                            "runner_name": classification.runner,
                            "output_files": [],
                        }
                    )
                    await send_json(
                        {
                            "type": "assistant_done",
                            "conversation_id": conversation.id,
                            "message_id": assistant_message.id,
                            "run_id": task_run.id,
                            "client_message_id": identity.client_message_id,
                            "output_files": [],
                        }
                    )
                    continue

                if classification.memory_action == MemoryAction.consume_pending:
                    consume_pending_task(db, classification.pending_task, run_id=task_run.id)

                queue_status = await start_chat_run(
                    run_id=task_run.id,
                    user_id=current_user.id,
                    agent_id=agent.id,
                    conversation_id=conversation.id,
                    content=effective_content,
                    file_ids=effective_file_ids,
                    gateway_files=effective_files_payload,
                )
                await send_json(
                    {
                        "type": "run_status",
                        **run_event_context(task_run, identity),
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

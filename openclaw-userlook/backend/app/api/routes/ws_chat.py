import asyncio

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status
from jose import JWTError
from pydantic import ValidationError

from app.core.database import SessionLocal
from app.core.security import decode_access_token
from app.models.message import MessageRole
from app.models.user import UserStatus
from app.schemas.message import WebSocketUserMessage
from app.services.auth_service import get_user_by_id
from app.services.conversation_service import require_conversation_for_user, save_message
from app.services.ws_connection_manager import connection_manager

router = APIRouter(tags=["ws-chat"])


async def _close_with_error(websocket: WebSocket, message: str) -> None:
    await websocket.accept()
    await websocket.send_json({"type": "error", "message": message})
    await websocket.close(code=status.WS_1008_POLICY_VIOLATION)


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

        await connection_manager.connect(conversation.id, websocket)
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

                save_message(
                    db,
                    conversation,
                    MessageRole.user,
                    inbound_message.content,
                    raw_payload=inbound_message.model_dump(),
                )

                mock_parts = ["正在处理...", " 已收到你的消息：", inbound_message.content, "。"]
                assistant_content = ""
                for part in mock_parts:
                    assistant_content += part
                    await connection_manager.send_json(
                        websocket,
                        {"type": "assistant_delta", "content": part},
                    )
                    await asyncio.sleep(0.2)

                assistant_message = save_message(
                    db,
                    conversation,
                    MessageRole.assistant,
                    assistant_content,
                    raw_payload={"mock": True},
                )
                await connection_manager.send_json(
                    websocket,
                    {"type": "assistant_done", "message_id": assistant_message.id},
                )
        except WebSocketDisconnect:
            connection_manager.disconnect(conversation.id, websocket)
        except Exception:
            connection_manager.disconnect(conversation.id, websocket)
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR)

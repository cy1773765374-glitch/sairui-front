from collections import defaultdict
import contextlib
import logging

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WebSocketConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[int, set[WebSocket]] = defaultdict(set)

    async def connect(self, conversation_id: int, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections[conversation_id].add(websocket)

    def disconnect(self, conversation_id: int, websocket: WebSocket) -> None:
        connections = self._connections.get(conversation_id)
        if connections is None:
            return
        connections.discard(websocket)
        if not connections:
            self._connections.pop(conversation_id, None)

    async def send_json(self, websocket: WebSocket, payload: dict) -> None:
        with contextlib.suppress(Exception):
            await websocket.send_json(payload)

    async def broadcast_json(self, conversation_id: int, payload: dict) -> None:
        connections = list(self._connections.get(conversation_id, set()))
        for websocket in connections:
            try:
                await websocket.send_json(payload)
            except Exception:
                logger.debug("websocket_send_failed conversation_id=%s", conversation_id, exc_info=True)


connection_manager = WebSocketConnectionManager()

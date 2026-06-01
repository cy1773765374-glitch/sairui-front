from collections import defaultdict

from fastapi import WebSocket


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
        await websocket.send_json(payload)


connection_manager = WebSocketConnectionManager()

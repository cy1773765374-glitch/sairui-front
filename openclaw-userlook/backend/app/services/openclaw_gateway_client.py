from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal

import websockets
from websockets.exceptions import WebSocketException

from app.models.agent import Agent
from app.models.conversation import Conversation
from app.models.user import User

GATEWAY_UNAVAILABLE_MESSAGE = "OpenClaw Gateway 连接失败，请检查 openclaw-gateway.service 是否运行"

GatewayEventType = Literal["delta", "done", "error", "run_status"]


@dataclass(frozen=True)
class OpenClawGatewayEvent:
    type: GatewayEventType
    content: str | None = None
    status: str | None = None
    output_dir: str | None = None
    raw: dict[str, Any] | None = None


class OpenClawGatewayConnectionError(RuntimeError):
    pass


class OpenClawGatewayClient:
    def __init__(
        self,
        ws_url: str,
        token: str = "",
        timeout_seconds: int = 300,
    ) -> None:
        self.ws_url = ws_url
        self.token = token
        self.timeout_seconds = timeout_seconds

    async def stream_chat(
        self,
        *,
        user: User,
        agent: Agent,
        conversation: Conversation,
        content: str,
        file_ids: list[int],
        files: list[dict[str, Any]] | None = None,
        run_id: int | None = None,
        output_dir: str | None = None,
    ) -> AsyncIterator[OpenClawGatewayEvent]:
        request_payload = self._build_chat_request(
            user=user,
            agent=agent,
            conversation=conversation,
            content=content,
            file_ids=file_ids,
            files=files or [],
            run_id=run_id,
            output_dir=output_dir,
        )
        headers = self._build_headers()

        try:
            async with websockets.connect(
                self.ws_url,
                additional_headers=headers,
                open_timeout=5,
                close_timeout=5,
                ping_interval=20,
                ping_timeout=20,
            ) as gateway_ws:
                await gateway_ws.send(json.dumps(request_payload, ensure_ascii=False))

                while True:
                    try:
                        raw_message = await asyncio.wait_for(
                            gateway_ws.recv(),
                            timeout=self.timeout_seconds,
                        )
                    except TimeoutError as exc:
                        raise OpenClawGatewayConnectionError("OpenClaw Gateway 响应超时") from exc

                    event = self._parse_gateway_message(raw_message)
                    yield event
                    if event.type in {"done", "error"}:
                        break
        except OpenClawGatewayConnectionError:
            raise
        except (OSError, WebSocketException, TimeoutError, asyncio.TimeoutError) as exc:
            raise OpenClawGatewayConnectionError(GATEWAY_UNAVAILABLE_MESSAGE) from exc

    def _build_headers(self) -> dict[str, str]:
        if not self.token:
            return {}
        return {"Authorization": f"Bearer {self.token}"}

    def _build_chat_request(
        self,
        *,
        user: User,
        agent: Agent,
        conversation: Conversation,
        content: str,
        file_ids: list[int],
        files: list[dict[str, Any]],
        run_id: int | None,
        output_dir: str | None,
    ) -> dict[str, Any]:
        payload = {
            "type": "chat",
            "action": "chat",
            "stream": True,
            "agent_id": agent.openclaw_agent_id,
            "session_key": conversation.session_key,
            "conversation": {
                "id": conversation.id,
                "title": conversation.title,
                "session_key": conversation.session_key,
            },
            "run": {
                "id": run_id,
                "output_dir": output_dir,
            },
            "user": {
                "id": user.id,
                "username": user.username,
                "display_name": user.display_name,
                "role": user.role.value,
            },
            "message": {
                "role": "user",
                "content": content,
                "file_ids": file_ids,
                "files": files,
            },
            "files": files,
        }
        if output_dir:
            payload["output_dir"] = output_dir
        return payload

    def _parse_gateway_message(self, raw_message: str | bytes) -> OpenClawGatewayEvent:
        if isinstance(raw_message, bytes):
            raw_text = raw_message.decode("utf-8", errors="replace")
        else:
            raw_text = raw_message

        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError:
            return OpenClawGatewayEvent(type="delta", content=raw_text)

        if not isinstance(payload, dict):
            return OpenClawGatewayEvent(type="delta", content=str(payload))

        event_type = str(
            payload.get("type")
            or payload.get("event")
            or payload.get("status")
            or payload.get("state")
            or ""
        ).lower()
        status_value = str(payload.get("status") or payload.get("state") or "").lower()
        normalized_state = status_value or event_type

        if normalized_state in {"error", "failed", "failure", "exception"}:
            return OpenClawGatewayEvent(
                type="error",
                content=self._extract_error_message(payload),
                raw=payload,
            )

        if normalized_state in {"done", "assistant_done", "end", "completed", "complete", "finished", "success"}:
            return OpenClawGatewayEvent(
                type="done",
                output_dir=self._extract_output_dir(payload),
                raw=payload,
            )

        if event_type in {
            "run_status",
            "status",
            "progress",
            "queued",
            "pending",
            "started",
            "start",
            "running",
            "working",
        }:
            return OpenClawGatewayEvent(
                type="run_status",
                status=str(payload.get("status") or event_type),
                content=self._extract_text(payload),
                raw=payload,
            )

        text = self._extract_text(payload)
        if text:
            return OpenClawGatewayEvent(type="delta", content=text, raw=payload)

        return OpenClawGatewayEvent(type="run_status", status=event_type or "received", raw=payload)

    def _extract_text(self, payload: dict[str, Any]) -> str:
        for key in ("delta", "content", "text", "message", "output", "answer", "data"):
            value = payload.get(key)
            if isinstance(value, str):
                return value
            if isinstance(value, list):
                text_parts = [item for item in value if isinstance(item, str)]
                if text_parts:
                    return "".join(text_parts)
            if isinstance(value, dict):
                nested = self._extract_text(value)
                if nested:
                    return nested
        return ""

    def _extract_output_dir(self, payload: dict[str, Any]) -> str | None:
        for key in ("output_dir", "outputPath", "output_path", "outputDirectory", "output_directory"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
            if isinstance(value, dict):
                nested = self._extract_output_dir(value)
                if nested:
                    return nested
        return None

    def _extract_error_message(self, payload: dict[str, Any]) -> str:
        for key in ("message", "error", "detail", "content"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
            if isinstance(value, dict):
                nested = self._extract_error_message(value)
                if nested:
                    return nested
        return "OpenClaw Gateway 调用失败"

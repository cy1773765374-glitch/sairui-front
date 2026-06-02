from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import time
from uuid import uuid4
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import websockets
from websockets.exceptions import WebSocketException

from app.core.config import get_settings
from app.models.agent import Agent
from app.models.conversation import Conversation
from app.models.user import User

GATEWAY_UNAVAILABLE_MESSAGE = "OpenClaw Gateway 连接失败，请检查 openclaw-gateway.service 是否运行"
GATEWAY_HANDSHAKE_FAILED_MESSAGE = "OpenClaw Gateway 握手失败，请检查 Gateway 协议、Token 或权限配置"

GatewayEventType = Literal["delta", "done", "error", "run_status"]
GatewayRunStatus = Literal["pending", "running", "success", "failed", "cancelled"]

PENDING_STATES = {"queued", "queueing", "pending", "created", "received", "waiting"}
RUNNING_STATES = {
    "running",
    "started",
    "start",
    "working",
    "processing",
    "in_progress",
    "progress",
    "streaming",
}
SUCCESS_STATES = {
    "done",
    "assistant_done",
    "end",
    "completed",
    "complete",
    "finished",
    "success",
    "succeeded",
}
FAILED_STATES = {"error", "failed", "failure", "exception", "timeout"}
CANCELLED_STATES = {"cancelled", "canceled", "cancel", "aborted", "abort"}
DELTA_EVENTS = {
    "delta",
    "assistant_delta",
    "message",
    "assistant_message",
    "chunk",
    "token",
    "text",
}
STATUS_EVENTS = PENDING_STATES | RUNNING_STATES | {"run_status", "status", "state"}


@dataclass(frozen=True)
class OpenClawGatewayEvent:
    type: GatewayEventType
    content: str | None = None
    status: GatewayRunStatus | None = None
    output_dir: str | None = None
    raw: dict[str, Any] | None = None


class OpenClawGatewayConnectionError(RuntimeError):
    pass


@dataclass(frozen=True)
class GatewayDeviceIdentity:
    device_id: str
    public_key: str
    private_key_pem: str


class OpenClawGatewayClient:
    def __init__(
        self,
        ws_url: str,
        token: str = "",
        timeout_seconds: int = 300,
        device_identity_path: str | None = None,
    ) -> None:
        self.ws_url = ws_url
        self.token = token
        self.timeout_seconds = timeout_seconds
        self.device_identity_path = device_identity_path

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
                await self._connect_gateway(gateway_ws)
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

    async def _connect_gateway(self, gateway_ws: Any) -> None:
        try:
            raw_challenge = await asyncio.wait_for(gateway_ws.recv(), timeout=5)
        except TimeoutError as exc:
            raise OpenClawGatewayConnectionError(GATEWAY_HANDSHAKE_FAILED_MESSAGE) from exc

        challenge = self._decode_json_frame(raw_challenge)
        if (
            not isinstance(challenge, dict)
            or challenge.get("type") != "event"
            or challenge.get("event") != "connect.challenge"
        ):
            raise OpenClawGatewayConnectionError(GATEWAY_HANDSHAKE_FAILED_MESSAGE)

        request_id = f"connect-{uuid4().hex}"
        nonce = self._extract_challenge_nonce(challenge)
        client = {
            "id": "gateway-client",
            "version": "openclaw-userlook",
            "platform": "linux",
            "mode": "backend",
        }
        role = "operator"
        scopes = ["operator.read", "operator.write"]
        signed_at_ms = int(time.time() * 1000)
        device = self._build_device_payload(
            client=client,
            role=role,
            scopes=scopes,
            nonce=nonce,
            signed_at_ms=signed_at_ms,
        )
        connect_payload = {
            "type": "req",
            "id": request_id,
            "method": "connect",
            "params": {
                "minProtocol": 3,
                "maxProtocol": 4,
                "client": client,
                "role": role,
                "scopes": scopes,
                "caps": [],
                "commands": [],
                "permissions": {},
                "auth": {"token": self.token},
                "locale": "zh-CN",
                "userAgent": "openclaw-userlook-backend",
                "device": device,
            },
        }
        await gateway_ws.send(json.dumps(connect_payload, ensure_ascii=False))

        while True:
            try:
                raw_response = await asyncio.wait_for(gateway_ws.recv(), timeout=5)
            except TimeoutError as exc:
                raise OpenClawGatewayConnectionError(GATEWAY_HANDSHAKE_FAILED_MESSAGE) from exc

            response = self._decode_json_frame(raw_response)
            if not isinstance(response, dict):
                continue
            if response.get("type") == "res" and response.get("id") == request_id:
                if response.get("ok") is True:
                    return
                raise OpenClawGatewayConnectionError(
                    self._extract_error_message(response) or GATEWAY_HANDSHAKE_FAILED_MESSAGE
                )
            if response.get("type") == "event" and response.get("event") == "connect.challenge":
                continue

    def _extract_challenge_nonce(self, challenge: dict[str, Any]) -> str:
        payload = challenge.get("payload")
        nonce = payload.get("nonce") if isinstance(payload, dict) else None
        if not isinstance(nonce, str) or not nonce:
            raise OpenClawGatewayConnectionError(GATEWAY_HANDSHAKE_FAILED_MESSAGE)
        return nonce

    def _build_device_payload(
        self,
        *,
        client: dict[str, str],
        role: str,
        scopes: list[str],
        nonce: str,
        signed_at_ms: int,
    ) -> dict[str, Any]:
        identity = self._load_or_create_device_identity()
        platform = client["platform"]
        device_family = "server"
        payload = self._build_device_auth_payload_v3(
            device_id=identity.device_id,
            client_id=client["id"],
            client_mode=client["mode"],
            role=role,
            scopes=scopes,
            signed_at_ms=signed_at_ms,
            token=self.token,
            nonce=nonce,
            platform=platform,
            device_family=device_family,
        )
        return {
            "id": identity.device_id,
            "publicKey": identity.public_key,
            "signature": self._sign_device_payload(identity.private_key_pem, payload),
            "signedAt": signed_at_ms,
            "nonce": nonce,
            "platform": platform,
            "deviceFamily": device_family,
        }

    def _load_or_create_device_identity(self) -> GatewayDeviceIdentity:
        path = self._resolve_device_identity_path()
        if path.is_file():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                device_id = payload.get("device_id")
                public_key = payload.get("public_key")
                private_key_pem = payload.get("private_key_pem")
                if (
                    isinstance(device_id, str)
                    and isinstance(public_key, str)
                    and isinstance(private_key_pem, str)
                ):
                    return GatewayDeviceIdentity(
                        device_id=device_id,
                        public_key=public_key,
                        private_key_pem=private_key_pem,
                    )
            except (OSError, json.JSONDecodeError):
                pass

        private_key = Ed25519PrivateKey.generate()
        private_key_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("ascii")
        public_key_bytes = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        identity = GatewayDeviceIdentity(
            device_id=hashlib.sha256(public_key_bytes).hexdigest(),
            public_key=self._base64_url_encode(public_key_bytes),
            private_key_pem=private_key_pem,
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "device_id": identity.device_id,
                    "public_key": identity.public_key,
                    "private_key_pem": identity.private_key_pem,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return identity

    def _resolve_device_identity_path(self) -> Path:
        if self.device_identity_path:
            return Path(self.device_identity_path).expanduser().resolve()
        settings = get_settings()
        output_root = Path(settings.user_output_root).expanduser().resolve()
        return (output_root.parent / "gateway-device-identity.json").resolve()

    def _build_device_auth_payload_v3(
        self,
        *,
        device_id: str,
        client_id: str,
        client_mode: str,
        role: str,
        scopes: list[str],
        signed_at_ms: int,
        token: str,
        nonce: str,
        platform: str,
        device_family: str,
    ) -> str:
        return "|".join(
            [
                "v3",
                device_id,
                client_id,
                client_mode,
                role,
                ",".join(scopes),
                str(signed_at_ms),
                token or "",
                nonce,
                platform.strip(),
                device_family.strip(),
            ]
        )

    def _sign_device_payload(self, private_key_pem: str, payload: str) -> str:
        private_key = serialization.load_pem_private_key(
            private_key_pem.encode("ascii"),
            password=None,
        )
        if not isinstance(private_key, Ed25519PrivateKey):
            raise OpenClawGatewayConnectionError(GATEWAY_HANDSHAKE_FAILED_MESSAGE)
        return self._base64_url_encode(private_key.sign(payload.encode("utf-8")))

    def _base64_url_encode(self, value: bytes) -> str:
        return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")

    def _decode_json_frame(self, raw_message: str | bytes) -> Any:
        if isinstance(raw_message, bytes):
            raw_text = raw_message.decode("utf-8", errors="replace")
        else:
            raw_text = raw_message
        try:
            return json.loads(raw_text)
        except json.JSONDecodeError:
            return raw_text

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
        params: dict[str, Any] = {
            "agentId": agent.openclaw_agent_id,
            "sessionKey": conversation.session_key,
            "message": content,
            "deliver": False,
            "timeoutMs": self.timeout_seconds * 1000,
            "idempotencyKey": f"openclaw-userlook:{run_id}" if run_id is not None else uuid4().hex,
            "metadata": {
                "source": "openclaw-userlook",
                "user": {
                    "id": user.id,
                    "username": user.username,
                    "display_name": user.display_name,
                    "role": user.role.value,
                },
                "conversation": {
                    "id": conversation.id,
                    "title": conversation.title,
                    "session_key": conversation.session_key,
                },
                "run": {
                    "id": run_id,
                    "output_dir": output_dir,
                },
                "file_ids": file_ids,
            },
        }
        attachments = self._build_attachments(files)
        if attachments:
            params["attachments"] = attachments
            params["files"] = files
        if output_dir:
            params["outputDir"] = output_dir
            params["output_dir"] = output_dir
        payload = {
            "type": "req",
            "id": f"chat-{run_id or uuid4().hex}",
            "method": "chat.send",
            "params": params,
        }
        return payload

    def _build_attachments(self, files: list[dict[str, Any]]) -> list[dict[str, Any]]:
        attachments: list[dict[str, Any]] = []
        for file in files:
            path = file.get("path") or file.get("stored_path")
            if not isinstance(path, str) or not path:
                continue
            attachments.append(
                {
                    "name": file.get("original_name") or path.rsplit("/", 1)[-1],
                    "path": path,
                    "mimeType": file.get("file_type"),
                    "size": file.get("file_size"),
                    "source": "openclaw-userlook",
                }
            )
        return attachments

    def _parse_gateway_message(self, raw_message: str | bytes) -> OpenClawGatewayEvent:
        if isinstance(raw_message, bytes):
            raw_text = raw_message.decode("utf-8", errors="replace")
        else:
            raw_text = raw_message

        payload = self._decode_json_frame(raw_text)
        if isinstance(payload, str):
            return OpenClawGatewayEvent(type="delta", content=payload)

        if not isinstance(payload, dict):
            return OpenClawGatewayEvent(type="delta", content=str(payload))

        if payload.get("type") == "res":
            if payload.get("ok") is False:
                return OpenClawGatewayEvent(
                    type="error",
                    content=self._extract_error_message(payload),
                    status="failed",
                    raw=payload,
                )
            result_payload = payload.get("payload")
            if isinstance(result_payload, dict):
                if self._is_terminal_response(result_payload):
                    return OpenClawGatewayEvent(
                        type="done",
                        content=self._extract_text(result_payload),
                        status="success",
                        output_dir=self._extract_output_dir(result_payload),
                        raw=payload,
                    )
                text = self._extract_text(result_payload)
                status = self._extract_status(result_payload)
                if text:
                    return OpenClawGatewayEvent(type="delta", content=text, raw=payload)
                return OpenClawGatewayEvent(
                    type="run_status",
                    status=self._normalize_run_status(status or "running"),
                    raw=payload,
                )

        event_type = self._normalize_state_token(
            payload.get("event")
            if payload.get("type") == "event"
            else payload.get("type")
            or payload.get("event")
            or payload.get("status")
            or payload.get("state")
            or ""
        )
        status_value = self._normalize_state_token(payload.get("status") or payload.get("state") or "")
        normalized_state = status_value or event_type

        event_kind = self._classify_event_type(normalized_state)

        if normalized_state in FAILED_STATES or event_kind == "error":
            return OpenClawGatewayEvent(
                type="error",
                content=self._extract_error_message(payload),
                status="failed",
                raw=payload,
            )

        if normalized_state in CANCELLED_STATES or event_kind == "cancelled":
            return OpenClawGatewayEvent(
                type="error",
                content=self._extract_error_message(payload) or "OpenClaw Gateway 调用已取消",
                status="cancelled",
                raw=payload,
            )

        if normalized_state in SUCCESS_STATES or event_kind == "done":
            return OpenClawGatewayEvent(
                type="done",
                content=self._extract_text(payload),
                status="success",
                output_dir=self._extract_output_dir(payload),
                raw=payload,
            )

        if event_type in STATUS_EVENTS or event_kind == "run_status":
            return OpenClawGatewayEvent(
                type="run_status",
                status=self._normalize_run_status(status_value or event_type),
                content=self._extract_text(payload),
                raw=payload,
            )

        text = self._extract_text(payload)
        if (event_type in DELTA_EVENTS or event_kind == "delta") and text:
            return OpenClawGatewayEvent(type="delta", content=text, raw=payload)

        if text:
            return OpenClawGatewayEvent(type="delta", content=text, raw=payload)

        return OpenClawGatewayEvent(
            type="run_status",
            status=self._normalize_run_status(event_type or "received"),
            raw=payload,
        )

    def _is_terminal_response(self, payload: dict[str, Any]) -> bool:
        status = self._normalize_state_token(self._extract_status(payload))
        if status in SUCCESS_STATES:
            return True
        if any(key in payload for key in ("response", "reply", "assistant", "final", "result")):
            return True
        return False

    def _extract_status(self, payload: dict[str, Any]) -> str:
        for key in ("status", "state", "phase"):
            value = payload.get(key)
            if isinstance(value, str):
                return value
        for value in payload.values():
            if isinstance(value, dict):
                nested = self._extract_status(value)
                if nested:
                    return nested
        return ""

    def _normalize_state_token(self, value: Any) -> str:
        if not isinstance(value, str):
            return ""
        return value.strip().lower().replace("-", "_").replace(" ", "_")

    def _classify_event_type(
        self,
        value: str,
    ) -> Literal["delta", "done", "error", "cancelled", "run_status", "unknown"]:
        token = self._normalize_state_token(value)
        parts = set(token.replace(".", "_").replace(":", "_").split("_"))
        if token in FAILED_STATES or parts & {"error", "failed", "failure", "exception"}:
            return "error"
        if token in CANCELLED_STATES or parts & {"cancelled", "canceled", "abort", "aborted"}:
            return "cancelled"
        if token in SUCCESS_STATES or parts & {"done", "complete", "completed", "finished", "success"}:
            return "done"
        if token in DELTA_EVENTS or parts & {"delta", "chunk", "token"}:
            return "delta"
        if token in STATUS_EVENTS or parts & {"status", "progress", "running", "started", "queued"}:
            return "run_status"
        return "unknown"

    def _normalize_run_status(self, value: str) -> GatewayRunStatus:
        normalized = self._normalize_state_token(value)
        if normalized in PENDING_STATES:
            return "pending"
        if normalized in SUCCESS_STATES:
            return "success"
        if normalized in FAILED_STATES:
            return "failed"
        if normalized in CANCELLED_STATES:
            return "cancelled"
        return "running"

    def _extract_text(self, payload: dict[str, Any]) -> str:
        for key in (
            "delta",
            "content",
            "text",
            "message",
            "output",
            "answer",
            "response",
            "reply",
            "assistant",
            "final",
            "result",
            "payload",
            "data",
        ):
            value = payload.get(key)
            if isinstance(value, str):
                return value
            if isinstance(value, list):
                text_parts: list[str] = []
                for item in value:
                    if isinstance(item, str):
                        text_parts.append(item)
                    elif isinstance(item, dict):
                        nested = self._extract_text(item)
                        if nested:
                            text_parts.append(nested)
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
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        nested = self._extract_output_dir(item)
                        if nested:
                            return nested
        for value in payload.values():
            if isinstance(value, dict):
                nested = self._extract_output_dir(value)
                if nested:
                    return nested
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        nested = self._extract_output_dir(item)
                        if nested:
                            return nested
        return None

    def _extract_error_message(self, payload: dict[str, Any]) -> str:
        for key in ("message", "error", "detail", "content", "payload", "data"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
            if isinstance(value, dict):
                nested = self._extract_error_message(value)
                if nested:
                    return nested
        return "OpenClaw Gateway 调用失败"

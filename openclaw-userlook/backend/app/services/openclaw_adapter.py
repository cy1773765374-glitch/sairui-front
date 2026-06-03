from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal

from app.core.config import Settings, get_settings
from app.models.agent import Agent
from app.models.conversation import Conversation
from app.models.user import User
from app.services.openclaw_gateway_client import (
    GATEWAY_UNAVAILABLE_MESSAGE,
    OpenClawGatewayClient,
    OpenClawGatewayConnectionError,
)

AdapterEventType = Literal["delta", "done", "error", "run_status"]
AdapterRunStatus = Literal["pending", "queued", "running", "success", "failed", "cancelled", "timeout"]
GATEWAY_AUTH_MISSING_MESSAGE = (
    "OpenClaw Gateway 认证未配置，请设置 OPENCLAW_GATEWAY_TOKEN 或 OPENCLAW_GATEWAY_PASSWORD"
)


@dataclass(frozen=True)
class OpenClawAdapterEvent:
    type: AdapterEventType
    content: str | None = None
    status: AdapterRunStatus | None = None
    output_dir: str | None = None
    raw: dict[str, Any] | None = None
    assumed_done_after_text_silence: bool = False
    gateway_debug_events: list[dict[str, Any]] | None = None
    gateway_request: dict[str, Any] | None = None


class OpenClawAdapter:
    def __init__(
        self,
        settings: Settings | None = None,
        gateway_client: OpenClawGatewayClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.gateway_client = gateway_client or OpenClawGatewayClient(
            ws_url=self.settings.openclaw_gateway_ws_url,
            token=self.settings.openclaw_gateway_token,
            password=self.settings.openclaw_gateway_password,
            timeout_seconds=self.settings.openclaw_gateway_timeout_seconds,
            deliver=self.settings.openclaw_gateway_deliver,
            max_concurrency=self.settings.openclaw_gateway_max_concurrency,
        )

    async def stream_chat(
        self,
        *,
        user: User,
        agent: Agent,
        conversation: Conversation,
        content: str,
        file_ids: list[int],
        files: list[dict[str, object]] | None = None,
        run_id: int | None = None,
        output_dir: str | None = None,
        cancel_event: asyncio.Event | None = None,
        assume_done_after_text_silence: bool = False,
        final_silence_seconds: int | None = None,
        recv_tick_seconds: int | None = None,
        client_message_id: str | None = None,
        gateway_session_key: str | None = None,
        idempotency_key: str | None = None,
    ) -> AsyncIterator[OpenClawAdapterEvent]:
        if self.settings.mock_openclaw:
            async for event in self._mock_stream(content, cancel_event=cancel_event):
                yield event
            return
        if (
            not self.settings.openclaw_gateway_token
            and not self.settings.openclaw_gateway_password
        ):
            yield OpenClawAdapterEvent(type="error", content=GATEWAY_AUTH_MISSING_MESSAGE)
            return

        try:
            async for event in self.gateway_client.stream_chat(
                user=user,
                agent=agent,
                conversation=conversation,
                content=content,
                file_ids=file_ids,
                files=files,
                run_id=run_id,
                output_dir=output_dir,
                cancel_event=cancel_event,
                assume_done_after_text_silence=assume_done_after_text_silence,
                final_silence_seconds=final_silence_seconds,
                recv_tick_seconds=recv_tick_seconds,
                client_message_id=client_message_id,
                gateway_session_key=gateway_session_key,
                idempotency_key=idempotency_key,
            ):
                yield OpenClawAdapterEvent(
                    type=event.type,
                    content=event.content,
                    status=event.status,
                    output_dir=event.output_dir,
                    raw=event.raw,
                    assumed_done_after_text_silence=event.assumed_done_after_text_silence,
                    gateway_debug_events=event.gateway_debug_events,
                    gateway_request=event.gateway_request,
                )
        except OpenClawGatewayConnectionError as exc:
            message = str(exc) or GATEWAY_UNAVAILABLE_MESSAGE
            yield OpenClawAdapterEvent(
                type="error",
                content=message,
                status="timeout" if "timed out" in message.lower() else "failed",
                raw=exc.gateway_event,
                gateway_debug_events=exc.gateway_debug_events,
                gateway_request=exc.gateway_request,
            )

    async def _mock_stream(
        self,
        content: str,
        *,
        cancel_event: asyncio.Event | None = None,
    ) -> AsyncIterator[OpenClawAdapterEvent]:
        yield OpenClawAdapterEvent(type="run_status", status="running", content="mock")
        for part in ["正在处理...", " 已收到你的消息：", content, "。"]:
            if cancel_event is not None and cancel_event.is_set():
                raise asyncio.CancelledError
            yield OpenClawAdapterEvent(type="delta", content=part)
            await asyncio.sleep(0.2)
        if cancel_event is not None and cancel_event.is_set():
            raise asyncio.CancelledError
        yield OpenClawAdapterEvent(type="done")

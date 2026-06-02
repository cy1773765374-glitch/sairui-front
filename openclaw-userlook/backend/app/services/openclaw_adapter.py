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
    ) -> AsyncIterator[OpenClawAdapterEvent]:
        if self.settings.mock_openclaw:
            async for event in self._mock_stream(content):
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
            ):
                yield OpenClawAdapterEvent(
                    type=event.type,
                    content=event.content,
                    status=event.status,
                    output_dir=event.output_dir,
                    raw=event.raw,
                )
        except OpenClawGatewayConnectionError as exc:
            message = str(exc) or GATEWAY_UNAVAILABLE_MESSAGE
            yield OpenClawAdapterEvent(type="error", content=message)

    async def _mock_stream(self, content: str) -> AsyncIterator[OpenClawAdapterEvent]:
        yield OpenClawAdapterEvent(type="run_status", status="running", content="mock")
        for part in ["正在处理...", " 已收到你的消息：", content, "。"]:
            yield OpenClawAdapterEvent(type="delta", content=part)
            await asyncio.sleep(0.2)
        yield OpenClawAdapterEvent(type="done")

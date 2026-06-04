from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator

from app.core.config import Settings, get_settings
from app.services.openclaw_adapter import OpenClawAdapter
from app.services.openclaw_gateway_client import OpenClawGatewayClient

logger = logging.getLogger(__name__)


@dataclass
class PooledGatewayConnection:
    client: OpenClawGatewayClient
    created_at: float
    last_used_at: float


class GatewayConnectionPool:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._idle_connections: asyncio.Queue[PooledGatewayConnection] = asyncio.Queue()
        self._all_connections: set[OpenClawGatewayClient] = set()
        self._in_use_connections: set[OpenClawGatewayClient] = set()
        self._lock = asyncio.Lock()
        self._started = False
        self._closed = False
        self._maintenance_task: asyncio.Task[None] | None = None

    @property
    def enabled(self) -> bool:
        return (
            self.settings.gateway_pool_enabled
            and not self.settings.mock_openclaw
            and bool(self.settings.openclaw_gateway_token or self.settings.openclaw_gateway_password)
        )

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._closed = False
        if not self.enabled:
            return

        warmup_tasks = [
            asyncio.create_task(self._create_connection())
            for _ in range(max(0, self.settings.gateway_pool_min_idle))
        ]
        for task in warmup_tasks:
            try:
                pooled = await task
            except Exception as exc:
                logger.warning("gateway_pool_warmup_failed: %s", exc)
                continue
            await self._idle_connections.put(pooled)
        self._maintenance_task = asyncio.create_task(self._maintenance_loop())

    async def shutdown(self) -> None:
        self._closed = True
        if self._maintenance_task is not None:
            self._maintenance_task.cancel()
            with contextlib.suppress(BaseException):
                await self._maintenance_task
            self._maintenance_task = None

        connections = list(self._all_connections)
        for client in connections:
            await client.disconnect()
        self._all_connections.clear()
        self._in_use_connections.clear()
        while not self._idle_connections.empty():
            with contextlib.suppress(asyncio.QueueEmpty):
                self._idle_connections.get_nowait()

    @asynccontextmanager
    async def acquire_adapter(self) -> AsyncIterator[OpenClawAdapter]:
        if not self.enabled:
            yield OpenClawAdapter(settings=self.settings)
            return
        if not self._started:
            await self.start()

        pooled = await self.acquire()
        try:
            yield OpenClawAdapter(settings=self.settings, gateway_client=pooled.client)
        finally:
            await self.release(pooled)

    async def acquire(self) -> PooledGatewayConnection:
        timeout = max(1, self.settings.gateway_pool_acquire_timeout)
        async with asyncio.timeout(timeout):
            while True:
                pooled = self._take_idle_connection()
                if pooled is not None:
                    if await self._is_reusable(pooled):
                        self._in_use_connections.add(pooled.client)
                        return pooled
                    await self._retire_connection(pooled.client)
                    continue

                async with self._lock:
                    if len(self._all_connections) < max(1, self.settings.gateway_pool_max_size):
                        pooled = await self._create_connection()
                        self._in_use_connections.add(pooled.client)
                        return pooled

                pooled = await self._idle_connections.get()
                if await self._is_reusable(pooled):
                    self._in_use_connections.add(pooled.client)
                    return pooled
                await self._retire_connection(pooled.client)

    async def release(self, pooled: PooledGatewayConnection) -> None:
        self._in_use_connections.discard(pooled.client)
        if self._closed or not await self._is_reusable(pooled):
            await self._retire_connection(pooled.client)
            return

        pooled.last_used_at = time.monotonic()
        await self._idle_connections.put(pooled)
        await self._ensure_min_idle()

    def _take_idle_connection(self) -> PooledGatewayConnection | None:
        with contextlib.suppress(asyncio.QueueEmpty):
            return self._idle_connections.get_nowait()
        return None

    async def _create_connection(self) -> PooledGatewayConnection:
        client = OpenClawGatewayClient(
            ws_url=self.settings.openclaw_gateway_ws_url,
            token=self.settings.openclaw_gateway_token,
            password=self.settings.openclaw_gateway_password,
            timeout_seconds=self.settings.openclaw_gateway_timeout_seconds,
        )
        await client.connect()
        self._all_connections.add(client)
        now = time.monotonic()
        return PooledGatewayConnection(client=client, created_at=now, last_used_at=now)

    async def _retire_connection(self, client: OpenClawGatewayClient) -> None:
        self._all_connections.discard(client)
        self._in_use_connections.discard(client)
        await client.disconnect()

    async def _is_reusable(self, pooled: PooledGatewayConnection) -> bool:
        if not pooled.client.is_connected:
            return False
        now = time.monotonic()
        if now - pooled.created_at >= max(1, self.settings.gateway_pool_max_lifetime):
            return False
        if now - pooled.last_used_at >= max(1, self.settings.gateway_pool_idle_timeout):
            return False
        return True

    async def _ensure_min_idle(self) -> None:
        if self._closed or not self.enabled:
            return
        min_idle = max(0, self.settings.gateway_pool_min_idle)
        while (
            self._idle_connections.qsize() < min_idle
            and len(self._all_connections) < max(1, self.settings.gateway_pool_max_size)
        ):
            try:
                pooled = await self._create_connection()
            except Exception as exc:
                logger.warning("gateway_pool_refill_failed: %s", exc)
                return
            await self._idle_connections.put(pooled)

    async def _maintenance_loop(self) -> None:
        while not self._closed:
            await asyncio.sleep(30)
            retained: list[PooledGatewayConnection] = []
            while True:
                pooled = self._take_idle_connection()
                if pooled is None:
                    break
                if await self._is_reusable(pooled):
                    retained.append(pooled)
                else:
                    await self._retire_connection(pooled.client)
            for pooled in retained:
                await self._idle_connections.put(pooled)
            await self._ensure_min_idle()


gateway_connection_pool = GatewayConnectionPool()

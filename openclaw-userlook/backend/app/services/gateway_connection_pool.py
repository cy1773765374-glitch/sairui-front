from __future__ import annotations

import asyncio
import contextlib
import inspect
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any


ConnectCallable = Callable[[], Awaitable[Any]]


@dataclass(eq=False)
class PooledConnection:
    ws: Any
    created_at: float = field(default_factory=time.monotonic)
    last_used_at: float = field(default_factory=time.monotonic)
    in_use: bool = False
    closed: bool = False


class GatewayConnectionPool:
    """Non-multiplexed Gateway WebSocket pool.

    A pooled connection is leased to exactly one stream_chat call at a time.
    """

    def __init__(self, settings: Any) -> None:
        self._max_size = max(1, int(settings.gateway_pool_max_size))
        self._idle_timeout = max(0.001, float(settings.gateway_pool_idle_timeout))
        self._acquire_timeout = max(0.001, float(settings.gateway_pool_acquire_timeout))
        self._capacity = asyncio.BoundedSemaphore(self._max_size)
        self._idle: deque[PooledConnection] = deque()
        self._all: set[PooledConnection] = set()
        self._active: set[PooledConnection] = set()
        self._reserved = 0
        self._condition = asyncio.Condition()
        self._shutting_down = False

    async def start(self) -> None:
        """Reserved for future warm-up; connections are created lazily."""

    async def acquire(self, connect_fn: ConnectCallable) -> PooledConnection:
        deadline = time.monotonic() + self._acquire_timeout

        while True:
            stale: list[PooledConnection] = []
            async with self._condition:
                if self._shutting_down:
                    raise RuntimeError("Gateway connection pool is shutting down")

                while self._idle:
                    conn = self._idle.popleft()
                    if self._is_connection_reusable(conn):
                        conn.in_use = True
                        conn.last_used_at = time.monotonic()
                        self._active.add(conn)
                        return conn
                    stale.append(conn)

                if len(self._all) + self._reserved < self._max_size:
                    self._reserved += 1
                    should_create = True
                else:
                    should_create = False

            for conn in stale:
                await self.discard(conn)
            if stale:
                continue

            if should_create:
                return await self._create_reserved_connection(connect_fn)

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise asyncio.TimeoutError("Gateway connection acquire timed out")
            try:
                async with self._condition:
                    await asyncio.wait_for(self._condition.wait(), timeout=remaining)
            except asyncio.TimeoutError as exc:
                raise asyncio.TimeoutError("Gateway connection acquire timed out") from exc

    async def release(self, conn: PooledConnection) -> None:
        if not self._is_connection_open(conn):
            await self.discard(conn)
            return

        async with self._condition:
            if conn.closed or conn not in self._all or self._shutting_down:
                should_discard = True
            else:
                should_discard = False
                conn.in_use = False
                conn.last_used_at = time.monotonic()
                self._active.discard(conn)
                self._idle.append(conn)
                self._condition.notify_all()

        if should_discard:
            await self.discard(conn)

    async def discard(self, conn: PooledConnection) -> None:
        should_release_capacity = False
        async with self._condition:
            if conn in self._all:
                self._all.remove(conn)
                should_release_capacity = True
            self._active.discard(conn)
            self._idle = deque(item for item in self._idle if item is not conn)
            conn.closed = True
            conn.in_use = False
            self._condition.notify_all()

        await self._close_ws(conn.ws)
        if should_release_capacity:
            self._capacity.release()
            async with self._condition:
                self._condition.notify_all()

    async def shutdown(self) -> None:
        async with self._condition:
            self._shutting_down = True
            connections = list(self._all)
            self._idle.clear()
            self._active.clear()
            self._all.clear()
            self._condition.notify_all()

        for conn in connections:
            conn.closed = True
            conn.in_use = False
            await self._close_ws(conn.ws)
            with contextlib.suppress(ValueError):
                self._capacity.release()

    async def _create_reserved_connection(self, connect_fn: ConnectCallable) -> PooledConnection:
        acquired_capacity = False
        try:
            await self._capacity.acquire()
            acquired_capacity = True
            ws = await connect_fn()
        except Exception:
            async with self._condition:
                self._reserved = max(0, self._reserved - 1)
                self._condition.notify_all()
            if acquired_capacity:
                self._capacity.release()
            raise

        conn = PooledConnection(ws=ws, in_use=True)
        async with self._condition:
            self._reserved = max(0, self._reserved - 1)
            if self._shutting_down:
                conn.closed = True
                self._condition.notify_all()
                should_close = True
            else:
                self._all.add(conn)
                self._active.add(conn)
                self._condition.notify_all()
                should_close = False

        if should_close:
            await self._close_ws(ws)
            self._capacity.release()
            raise RuntimeError("Gateway connection pool is shutting down")
        return conn

    def _is_connection_reusable(self, conn: PooledConnection) -> bool:
        if not self._is_connection_open(conn):
            return False
        return time.monotonic() - conn.last_used_at <= self._idle_timeout

    def _is_connection_open(self, conn: PooledConnection) -> bool:
        if conn.closed:
            return False
        ws = conn.ws
        if getattr(ws, "closed", False):
            return False
        if getattr(ws, "close_code", None) is not None:
            return False
        return True

    async def _close_ws(self, ws: Any) -> None:
        close = getattr(ws, "close", None)
        if close is None:
            return
        try:
            result = close()
            if inspect.isawaitable(result):
                await result
        except Exception:
            pass

_pool: GatewayConnectionPool | None = None


def get_gateway_pool() -> GatewayConnectionPool | None:
    return _pool


def set_gateway_pool(pool: GatewayConnectionPool | None) -> None:
    global _pool
    _pool = pool

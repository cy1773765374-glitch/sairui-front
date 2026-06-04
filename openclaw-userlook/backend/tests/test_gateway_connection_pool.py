import asyncio
import unittest

from app.services.gateway_connection_pool import GatewayConnectionPool


class GatewayConnectionPoolTest(unittest.IsolatedAsyncioTestCase):
    async def test_acquire_release_reuses_connection(self) -> None:
        pool = GatewayConnectionPool(make_settings(max_size=2))
        created: list[FakeWebSocket] = []

        async def connect() -> FakeWebSocket:
            ws = FakeWebSocket()
            created.append(ws)
            return ws

        first = await pool.acquire(connect)
        await pool.release(first)
        second = await pool.acquire(connect)

        self.assertIs(first, second)
        self.assertEqual(len(created), 1)
        await pool.shutdown()

    async def test_acquire_times_out_when_pool_is_full(self) -> None:
        pool = GatewayConnectionPool(make_settings(max_size=1, acquire_timeout=0.02))

        async def connect() -> FakeWebSocket:
            return FakeWebSocket()

        first = await pool.acquire(connect)
        with self.assertRaises(asyncio.TimeoutError):
            await pool.acquire(connect)

        await pool.release(first)
        await pool.shutdown()

    async def test_discard_closes_connection_and_releases_capacity(self) -> None:
        pool = GatewayConnectionPool(make_settings(max_size=1))
        created: list[FakeWebSocket] = []

        async def connect() -> FakeWebSocket:
            ws = FakeWebSocket()
            created.append(ws)
            return ws

        first = await pool.acquire(connect)
        await pool.discard(first)
        second = await pool.acquire(connect)

        self.assertTrue(created[0].closed)
        self.assertIsNot(first, second)
        self.assertEqual(len(created), 2)
        await pool.shutdown()

    async def test_shutdown_closes_idle_and_active_connections(self) -> None:
        pool = GatewayConnectionPool(make_settings(max_size=2))

        async def connect() -> FakeWebSocket:
            return FakeWebSocket()

        active = await pool.acquire(connect)
        idle = await pool.acquire(connect)
        await pool.release(idle)
        await pool.shutdown()

        self.assertTrue(active.ws.closed)
        self.assertTrue(idle.ws.closed)


class Settings:
    def __init__(self, *, max_size: int, acquire_timeout: float = 0.05, idle_timeout: float = 300) -> None:
        self.gateway_pool_max_size = max_size
        self.gateway_pool_acquire_timeout = acquire_timeout
        self.gateway_pool_idle_timeout = idle_timeout


def make_settings(*, max_size: int, acquire_timeout: float = 0.05, idle_timeout: float = 300) -> Settings:
    return Settings(max_size=max_size, acquire_timeout=acquire_timeout, idle_timeout=idle_timeout)


class FakeWebSocket:
    def __init__(self) -> None:
        self.closed = False
        self.close_count = 0

    async def close(self) -> None:
        self.closed = True
        self.close_count += 1


if __name__ == "__main__":
    unittest.main()

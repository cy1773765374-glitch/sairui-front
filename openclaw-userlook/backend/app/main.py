import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.agents import router as agents_router
from app.api.routes.admin_users import router as admin_users_router
from app.api.routes.auth import router as auth_router
from app.api.routes.conversations import router as conversations_router
from app.api.routes.files import router as files_router
from app.api.routes.health import router as health_router
from app.api.routes.me import router as me_router
from app.api.routes.runs import router as runs_router
from app.api.routes.wecom import router as wecom_router
from app.api.routes.ws_chat import router as ws_chat_router
from app.core.config import get_settings
from app.migrations.phase11_task_run_lifecycle import run_migration as run_phase11_migration
from app.migrations.phase12_streaming_persistence import run_migration as run_phase12_migration
from app.migrations.phase12_3_session_isolation import run_migration as run_phase12_3_migration
from app.migrations.phase13_1_uiux import run_migration as run_phase13_1_migration
from app.migrations.phase13_2_uiux import run_migration as run_phase13_2_migration
from app.migrations.phase13_3_upload_files import run_migration as run_phase13_3_migration
from app.migrations.phase13_4_daoban_file_chain import run_migration as run_phase13_4_migration
from app.services.gateway_connection_pool import GatewayConnectionPool, set_gateway_pool
from app.services.run_watchdog import watchdog_loop
from app.services.task_queue import task_queue

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    run_phase11_migration()
    run_phase12_migration()
    run_phase12_3_migration()
    run_phase13_1_migration()
    run_phase13_2_migration()
    run_phase13_3_migration()
    run_phase13_4_migration()
    pool = None
    if settings.gateway_pool_enabled:
        pool = GatewayConnectionPool(settings)
        await pool.start()
        set_gateway_pool(pool)
    else:
        set_gateway_pool(None)
    stop_event = asyncio.Event()
    watchdog_task = asyncio.create_task(watchdog_loop(stop_event))
    try:
        yield
    finally:
        stop_event.set()
        await task_queue.shutdown()
        if pool is not None:
            await pool.shutdown()
            set_gateway_pool(None)
        watchdog_task.cancel()
        try:
            await watchdog_task
        except BaseException:
            pass


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/api")
app.include_router(admin_users_router, prefix="/api")
app.include_router(agents_router, prefix="/api")
app.include_router(conversations_router, prefix="/api")
app.include_router(files_router, prefix="/api")
app.include_router(me_router, prefix="/api")
app.include_router(runs_router, prefix="/api")
app.include_router(wecom_router, prefix="/api")
app.include_router(ws_chat_router, prefix="/api")
app.include_router(health_router, prefix="/api")


@app.get("/")
def root() -> dict[str, str]:
    return {
        "status": "ok",
        "service": settings.app_name,
        "health": "/api/health",
    }

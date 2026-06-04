from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    app_name: str = Field(default="openclaw-userlook-backend", alias="APP_NAME")
    app_env: str = Field(default="development", alias="APP_ENV")
    backend_host: str = Field(default="127.0.0.1", alias="BACKEND_HOST")
    backend_port: int = Field(default=10009, alias="BACKEND_PORT")
    openclaw_gateway_ws_url: str = Field(
        default="ws://127.0.0.1:18789",
        alias="OPENCLAW_GATEWAY_WS_URL",
    )
    openclaw_gateway_token: str = Field(default="", alias="OPENCLAW_GATEWAY_TOKEN")
    openclaw_gateway_password: str = Field(default="", alias="OPENCLAW_GATEWAY_PASSWORD")
    openclaw_gateway_timeout_seconds: int = Field(
        default=300,
        alias="OPENCLAW_GATEWAY_TIMEOUT_SECONDS",
    )
    task_chat_timeout_seconds: int = Field(default=120, alias="TASK_CHAT_TIMEOUT_SECONDS")
    task_short_chat_timeout_seconds: int = Field(default=600, alias="TASK_SHORT_CHAT_TIMEOUT_SECONDS")
    task_gateway_final_silence_seconds: int = Field(default=10, alias="TASK_GATEWAY_FINAL_SILENCE_SECONDS")
    task_assume_done_after_text_silence: bool = Field(default=True, alias="TASK_ASSUME_DONE_AFTER_TEXT_SILENCE")
    task_job_timeout_seconds: int = Field(default=1800, alias="TASK_JOB_TIMEOUT_SECONDS")
    task_queue_timeout_seconds: int = Field(default=1800, alias="TASK_QUEUE_TIMEOUT_SECONDS")
    task_stale_running_minutes: int = Field(default=30, alias="TASK_STALE_RUNNING_MINUTES")
    task_watchdog_interval_seconds: int = Field(default=30, alias="TASK_WATCHDOG_INTERVAL_SECONDS")
    task_agent_concurrency: int = Field(default=1, alias="TASK_AGENT_CONCURRENCY")
    task_global_chat_concurrency: int = Field(default=50, alias="TASK_GLOBAL_CHAT_CONCURRENCY")
    task_agent_max_concurrency: int = Field(default=10, alias="TASK_AGENT_MAX_CONCURRENCY")
    task_user_max_concurrency: int = Field(default=5, alias="TASK_USER_MAX_CONCURRENCY")
    task_conversation_max_concurrency: int = Field(default=5, alias="TASK_CONVERSATION_MAX_CONCURRENCY")
    task_global_job_concurrency: int = Field(default=1, alias="TASK_GLOBAL_JOB_CONCURRENCY")
    gateway_pool_enabled: bool = Field(default=True, alias="GATEWAY_POOL_ENABLED")
    gateway_pool_min_idle: int = Field(default=2, alias="GATEWAY_POOL_MIN_IDLE")
    gateway_pool_max_size: int = Field(default=10, alias="GATEWAY_POOL_MAX_SIZE")
    gateway_pool_idle_timeout: int = Field(default=300, alias="GATEWAY_POOL_IDLE_TIMEOUT")
    gateway_pool_max_lifetime: int = Field(default=3600, alias="GATEWAY_POOL_MAX_LIFETIME")
    gateway_pool_acquire_timeout: int = Field(default=30, alias="GATEWAY_POOL_ACQUIRE_TIMEOUT")
    mock_openclaw: bool = Field(default=True, alias="MOCK_OPENCLAW")
    database_url: str = Field(
        default="mysql+pymysql://user:password@127.0.0.1:3306/openclaw_userlook?charset=utf8mb4",
        alias="DATABASE_URL",
    )
    jwt_secret_key: str = Field(default="please-change-this", alias="JWT_SECRET_KEY")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    access_token_expire_minutes: int = Field(default=1440, alias="ACCESS_TOKEN_EXPIRE_MINUTES")
    default_admin_username: str = Field(default="admin", alias="DEFAULT_ADMIN_USERNAME")
    default_admin_password: str = Field(default="Admin@123456", alias="DEFAULT_ADMIN_PASSWORD")
    wecom_corp_id: str = Field(default="", alias="WECOM_CORP_ID")
    wecom_agent_id: str = Field(default="", alias="WECOM_AGENT_ID")
    wecom_secret: str = Field(default="", alias="WECOM_SECRET")
    wecom_redirect_uri: str = Field(default="", alias="WECOM_REDIRECT_URI")
    wecom_mock_login: bool = Field(default=True, alias="WECOM_MOCK_LOGIN")
    wecom_default_user_status: str = Field(default="pending", alias="WECOM_DEFAULT_USER_STATUS")
    user_upload_root: str = Field(
        default="/data/openclaw-userlook/uploads",
        alias="USER_UPLOAD_ROOT",
    )
    user_output_root: str = Field(
        default="/data/openclaw-userlook/outputs",
        alias="USER_OUTPUT_ROOT",
    )
    max_upload_mb: int = Field(default=50, alias="MAX_UPLOAD_MB")
    cors_origins: list[str] = [
        "http://127.0.0.1:10010",
        "http://localhost:10010",
    ]

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        populate_by_name=True,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()

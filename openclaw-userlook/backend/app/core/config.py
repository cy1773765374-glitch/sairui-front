from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = Field(default="openclaw-userlook-backend", alias="APP_NAME")
    app_env: str = Field(default="development", alias="APP_ENV")
    backend_host: str = Field(default="127.0.0.1", alias="BACKEND_HOST")
    backend_port: int = Field(default=10009, alias="BACKEND_PORT")
    openclaw_gateway_ws_url: str = Field(
        default="ws://127.0.0.1:18789",
        alias="OPENCLAW_GATEWAY_WS_URL",
    )
    database_url: str = Field(
        default="mysql+pymysql://user:password@127.0.0.1:3306/openclaw_userlook?charset=utf8mb4",
        alias="DATABASE_URL",
    )
    cors_origins: list[str] = [
        "http://127.0.0.1:10010",
        "http://localhost:10010",
    ]

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        populate_by_name=True,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()

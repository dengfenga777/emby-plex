from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "MoviePilot Request System"
    api_prefix: str = "/api"
    secret_key: str = "change-me-before-production"
    database_url: str = "sqlite:///./moviepilot_requests.db"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    dev_auth_enabled: bool = True
    require_admin_approval: bool = True
    default_admin_ids: str = "1"

    moviepilot_mode: str = "mock"
    moviepilot_base_url: str | None = None
    moviepilot_api_key: str | None = None
    moviepilot_username: str | None = None
    moviepilot_password: str | None = None
    moviepilot_otp_password: str | None = None
    moviepilot_timeout_seconds: float = 20.0

    telegram_bot_token: str | None = None
    telegram_webapp_url: str = "http://localhost:5173"
    request_sync_interval_seconds: float = 60.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def admin_id_set(self) -> set[int]:
        values = {item.strip() for item in self.default_admin_ids.split(",") if item.strip()}
        return {int(value) for value in values}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

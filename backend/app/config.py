from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
    app_env: str = "development"
    api_v1_prefix: str = "/api/v1"
    database_url: str = "postgresql+asyncpg://vibestore:vibestore@localhost:5432/vibestore"
    redis_url: str = "redis://localhost:6379/0"
    cors_origins: str = "http://localhost:3000"
    github_token: str | None = None
    gitlab_token: str | None = None
    codeberg_token: str | None = None
    github_webhook_secret: str = ""
    jwt_secret_key: str = ""
    jwt_issuer: str = "vibestore-api"
    jwt_access_token_minutes: int = Field(default=30, ge=5, le=1440)
    catalog_refresh_interval_days: int = Field(default=7, ge=1, le=90)
    catalog_refresh_batch_size: int = Field(default=50, ge=1, le=500)
    indexing_reconcile_batch_size: int = Field(default=100, ge=1, le=1000)
    indexing_stale_job_minutes: int = Field(default=15, ge=10, le=120)
    ai_provider: str = "none"
    ai_base_url: str | None = None
    ai_api_key: str | None = None
    ai_model: str | None = None
    ai_embedding_model: str | None = None
    ai_request_timeout_seconds: int = Field(default=90, ge=5, le=300)
    ai_max_retries: int = Field(default=2, ge=0, le=5)

    @property
    def allowed_origins(self) -> list[str]:
        return [value.strip() for value in self.cors_origins.split(",") if value.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

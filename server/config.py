from __future__ import annotations

from functools import lru_cache
import re
from urllib.parse import unquote, urlparse

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ServerSettings(BaseSettings):
    app_env: str = "development"
    secret_key: str = Field(default="development-only-secret-change-me-please")
    database_url: str = "postgresql+psycopg://learning:change-me@localhost:5432/learning"
    redis_url: str = "redis://localhost:6379/0"
    redis_password: str = ""
    object_storage_endpoint: str = ""
    object_storage_bucket: str = "learning"
    object_storage_access_key: str = ""
    object_storage_secret_key: str = ""
    upload_max_bytes: int = Field(default=50 * 1024 * 1024, ge=1024, le=1024 * 1024 * 1024)
    access_token_minutes: int = Field(default=30, ge=5, le=1440)
    refresh_token_days: int = Field(default=30, ge=1, le=365)
    rate_limit_enabled: bool = True
    rate_limit_requests: int = Field(default=120, ge=1, le=10000)
    rate_limit_window_seconds: int = Field(default=60, ge=1, le=3600)
    auth_rate_limit_requests: int = Field(default=10, ge=1, le=1000)
    auth_rate_limit_window_seconds: int = Field(default=60, ge=1, le=3600)
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @model_validator(mode="after")
    def validate_secret(self) -> "ServerSettings":
        if self.app_env.lower() in {"production", "prod"} and (
            len(self.secret_key) < 32 or self.secret_key.startswith("development-only")
        ):
            raise ValueError("production SECRET_KEY must be a random value of at least 32 characters")
        if self.app_env.lower() in {"production", "prod"}:
            if "change-me" in self.database_url:
                raise ValueError("production DATABASE_URL must not use the example password")
            if not all((self.object_storage_endpoint, self.object_storage_access_key, self.object_storage_secret_key)):
                raise ValueError("production object storage credentials are required")
            if not self.rate_limit_enabled:
                raise ValueError("production rate limiting must be enabled")
            if (
                len(self.redis_password) < 16
                or "change-me" in self.redis_password
                or "replace-with" in self.redis_password
                or not re.fullmatch(r"[A-Za-z0-9._~-]+", self.redis_password)
            ):
                raise ValueError("production REDIS_PASSWORD must be a URL-safe random value of at least 16 characters")
            parsed_redis = urlparse(self.redis_url)
            if not parsed_redis.password:
                raise ValueError("production REDIS_URL must include the Redis password")
            if unquote(parsed_redis.password) != self.redis_password:
                raise ValueError("production REDIS_URL password must match REDIS_PASSWORD")
            if "*" in self.cors_origins:
                raise ValueError("production CORS origins must be explicit; wildcard is forbidden")
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip().rstrip("/") for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache(maxsize=1)
def get_server_settings() -> ServerSettings:
    return ServerSettings()

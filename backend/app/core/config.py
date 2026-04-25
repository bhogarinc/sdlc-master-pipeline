"""Application configuration with environment-based settings."""

import secrets
from functools import lru_cache
from typing import Any, List, Optional, Union

from pydantic import AnyHttpUrl, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"
    )
    
    APP_NAME: str = "TaskFlow Pro"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    ENVIRONMENT: str = "production"
    SECRET_KEY: str = secrets.token_urlsafe(32)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    ALGORITHM: str = "HS256"
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "taskflow"
    BACKEND_CORS_ORIGINS: List[AnyHttpUrl] = []
    REDIS_URL: str = "redis://localhost:6379/0"
    RATE_LIMIT_DEFAULT: int = 100
    RATE_LIMIT_AUTH: int = 5
    WS_HEARTBEAT_INTERVAL: int = 30
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"
    SENTRY_DSN: Optional[str] = None
    
    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> Union[List[str], str]:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, (list, str)):
            return v
        raise ValueError(v)


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

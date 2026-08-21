from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AnyHttpUrl, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        env_ignore_empty=True,
    )

    app_env: Literal["local", "test", "internal"]
    app_base_url: AnyHttpUrl
    database_url: str
    redis_url: str
    neo4j_uri: str
    neo4j_username: str
    neo4j_password: SecretStr
    file_storage_root: Path
    session_secret: SecretStr = Field(min_length=32)
    session_ttl_seconds: int = Field(default=28_800, ge=300)
    max_import_file_bytes: int = Field(default=50 * 1024 * 1024, ge=1)
    max_import_rows: int = Field(default=100_000, ge=1)
    cors_origins: list[str]
    algorithm_service_url: AnyHttpUrl
    llm_responses_url: AnyHttpUrl | None = None
    llm_api_key: SecretStr | None = None
    llm_model: str | None = Field(default=None, min_length=1, max_length=200)

    @property
    def secure_cookie(self) -> bool:
        return self.app_env == "internal"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]

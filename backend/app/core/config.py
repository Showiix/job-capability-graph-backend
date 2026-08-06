from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AnyHttpUrl, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

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
    cors_origins: list[str]
    algorithm_service_url: AnyHttpUrl

    @property
    def secure_cookie(self) -> bool:
        return self.app_env == "internal"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]

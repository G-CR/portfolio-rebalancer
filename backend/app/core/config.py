from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://portfolio:portfolio@db:5432/portfolio"
    timezone: str = "Asia/Shanghai"
    refresh_hour: int = 8
    refresh_minute: int = 0
    secret_key_path: str = "/run/portfolio-secrets/fernet.key"


@lru_cache
def get_settings() -> Settings:
    return Settings()

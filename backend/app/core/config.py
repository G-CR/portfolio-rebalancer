from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.backups.constants import (
    MAX_AGGREGATE_COMPRESSION_RATIO,
    MAX_COMPRESSED_BYTES,
    MAX_UNCOMPRESSED_BYTES,
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://portfolio:portfolio@db:5432/portfolio"
    timezone: str = "Asia/Shanghai"
    refresh_hour: int = 8
    refresh_minute: int = 0
    secret_key_path: str = "/run/portfolio-secrets/fernet.key"
    backup_root: Path = Path("/var/lib/portfolio-backups")
    backup_export_ttl_seconds: int = 30 * 60
    backup_upload_ttl_seconds: int = 30 * 60
    backup_safety_retention: int = 5
    backup_max_compressed_bytes: int = MAX_COMPRESSED_BYTES
    backup_max_uncompressed_bytes: int = MAX_UNCOMPRESSED_BYTES
    backup_max_compression_ratio: int = MAX_AGGREGATE_COMPRESSION_RATIO


@lru_cache
def get_settings() -> Settings:
    return Settings()

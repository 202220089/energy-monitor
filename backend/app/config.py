"""Application configuration (Pydantic v2 settings, 12-factor friendly)."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    """Every value can be overridden through env vars or a .env file."""

    model_config = SettingsConfigDict(
        env_file=(BACKEND_DIR / ".env",),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "Smart Home Energy Usage Monitor"
    app_version: str = "1.0.0"
    api_prefix: str = "/api"
    debug: bool = False

    # ---------------------------------------------------------------- database
    database_url: str = Field(
        default="postgresql+asyncpg://energy:energy@localhost:5432/energy_db",
        description="Async SQLAlchemy URL - PostgreSQL only (asyncpg driver).",
    )
    db_echo: bool = False
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # ------------------------------------------------------------------- cors
    cors_origins: list[str] = ["*"]

    # ------------------------------------------------------------- simulator
    simulator_enabled: bool = True
    tick_seconds: float = 2.0
    seed_history_hours: int = 6
    seed_history_step_seconds: int = 30

    # ---------------------------------------------------------------- websocket
    ws_history_points: int = 90

    @property
    def sync_database_url(self) -> str:
        return self.database_url.replace("+asyncpg", "+psycopg2")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

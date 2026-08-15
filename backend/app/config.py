from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Hestia"
    app_secret: str = "change-me-in-production"

    data_dir: str = "./data"
    upload_dir: str = "./uploads"
    frontend_dist: str = "./static"
    database_url: str = "sqlite+aiosqlite:///./data/hestia.db"

    cors_origins: str = "http://localhost:5173"

    session_cookie: str = "hestia_session"
    session_max_age: int = 60 * 60 * 24 * 14

    auth_username: str = "admin"
    auth_password: str = "change-me"

    searxng_url: str = "http://searxng:8080"
    piston_url: str = "http://piston:2000"

    embedding_url: str = ""
    embedding_model: str = ""
    embedding_api_key: str = ""

    max_tool_iterations: int = 8

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def ensure_dirs(self) -> None:
        Path(self.data_dir).mkdir(parents=True, exist_ok=True)
        Path(self.upload_dir).mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()

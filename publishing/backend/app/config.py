from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    publishing_data_dir: str = "app-data/publishing"
    publishing_admin_username: str = "admin"
    publishing_admin_password: str = "admin123"
    publishing_admin_display_name: str = "系统管理员"
    publishing_session_hours: int = 24
    publishing_auto_sync_enabled: bool = True
    publishing_auto_sync_interval_seconds: int = 600
    writing_api_base_url: str = "http://127.0.0.1:8000"
    frontend_origin: str = "http://127.0.0.1:5174"

    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", PROJECT_ROOT / "publishing" / "backend" / ".env"),
        env_prefix="",
        extra="ignore",
    )

    @property
    def data_root(self) -> Path:
        path = Path(self.publishing_data_dir)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path

    @property
    def database_path(self) -> Path:
        return self.data_root / "publishing.db"


@lru_cache
def get_settings() -> Settings:
    return Settings()

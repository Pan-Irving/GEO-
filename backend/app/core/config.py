from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    openai_api_key: str = ""
    openai_base_url: str = ""
    openai_model: str = "gpt-5.5"
    openai_api_mode: str = "chat"
    app_data_dir: str = "app-data"
    frontend_origin: str = "http://localhost:5173"

    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", PROJECT_ROOT / "backend" / ".env"),
        env_prefix="",
        extra="ignore",
    )

    @property
    def data_root(self) -> Path:
        path = Path(self.app_data_dir)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path

    @property
    def skill_root(self) -> Path:
        return PROJECT_ROOT / "mindsun-geo-content-flow"


@lru_cache
def get_settings() -> Settings:
    return Settings()

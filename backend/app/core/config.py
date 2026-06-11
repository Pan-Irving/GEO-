from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    openai_api_key: str = ""
    openai_base_url: str = ""
    openai_model: str = "gpt-5.5"
    openai_api_mode: str = "chat"
    openai_stream: bool = True
    openai_timeout_seconds: float = 600
    openai_vision_model: str = ""
    enable_vision_ocr: bool = False
    vision_ocr_timeout_seconds: float = 90
    vision_ocr_max_pages: int = 4
    enable_local_ocr: bool = True
    local_ocr_engine: str = "rapidocr"
    local_ocr_max_pages: int = 4
    local_ocr_min_confidence: float = 0.35
    ocr_concurrency: int = 2
    image_ocr_max_edge: int = 1600
    image_ocr_jpeg_quality: int = 82
    batch_generation_concurrency: int = 3
    matrix_batch_intent_group_size: int = 2
    matrix_batch_keyword_size: int = 4
    matrix_batch_material_context_limit: int = 12000
    matrix_timeout_retry_count: int = 1
    matrix_timeout_retry_seconds: float = 120
    hard_cancel_process_workers: bool = True
    job_cancel_poll_interval_seconds: float = 0.3
    job_terminate_grace_seconds: float = 2
    job_child_process_timeout_seconds: float = 0
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

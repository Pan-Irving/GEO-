from app.core.config import Settings
from app.storage.mysql_repository import MySQLProjectRepository
from app.storage.repository import ProjectRepository


def create_project_repository(settings: Settings) -> ProjectRepository:
    backend = settings.writing_storage_backend.strip().lower()
    if backend in {"", "file", "json"}:
        return ProjectRepository(settings.data_root)
    if backend == "mysql":
        return MySQLProjectRepository(settings.data_root, settings.writing_database_dsn)
    raise ValueError(f"Unsupported WRITING_STORAGE_BACKEND: {settings.writing_storage_backend}")

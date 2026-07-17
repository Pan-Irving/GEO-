from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import get_settings, get_skill_loader, router
from app.core.config import Settings


class DummySkillLoader:
    def available(self) -> bool:
        return True


def make_client(settings: Settings) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_skill_loader] = lambda: DummySkillLoader()
    return TestClient(app)


def test_health_returns_default_publishing_frontend_url(tmp_path):
    client = make_client(Settings(app_data_dir=str(tmp_path), writing_storage_backend="file", writing_database_url=""))

    response = client.get("/api/agent/health")

    assert response.status_code == 200
    assert response.json()["publishing_frontend_url"] == "http://127.0.0.1:5174"


def test_health_returns_configured_publishing_frontend_url(tmp_path):
    client = make_client(
        Settings(
            app_data_dir=str(tmp_path),
            writing_storage_backend="file",
            writing_database_url="",
            publishing_frontend_url="https://example.com/workbench",
        )
    )

    response = client.get("/api/agent/health")

    assert response.status_code == 200
    assert response.json()["publishing_frontend_url"] == "https://example.com/workbench"

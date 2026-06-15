from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.db import PublishingStore
from app.routes import router, store
from app.sync_service import auto_sync_once


def make_store(tmp_path: Path) -> PublishingStore:
    return PublishingStore(
        Settings(
            _env_file=None,
            publishing_data_dir=str(tmp_path),
            publishing_admin_username="admin",
            publishing_admin_password="secret123",
            writing_api_base_url="http://writing.test",
        )
    )


def make_client(tmp_path: Path) -> tuple[TestClient, PublishingStore]:
    settings = Settings(
        _env_file=None,
        publishing_data_dir=str(tmp_path),
        publishing_admin_username="admin",
        publishing_admin_password="secret123",
        writing_api_base_url="http://writing.test",
    )
    publishing_store = PublishingStore(settings)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[store] = lambda: publishing_store
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app), publishing_store


def auth_headers(publishing_store: PublishingStore) -> dict[str, str]:
    token = publishing_store.login("admin", "secret123")["token"]
    return {"Authorization": f"Bearer {token}"}


def response(url: str, payload: Any, status_code: int = 200) -> httpx.Response:
    return httpx.Response(status_code, json=payload, request=httpx.Request("GET", url))


def article_payload(article_id: str = "article-1") -> dict[str, str]:
    return {
        "article_id": article_id,
        "project_id": "project-1",
        "project_name": "测试项目",
        "source_id": "source-1",
        "brief_id": "brief-1",
        "keyword": "高端厨电哪个牌子好",
        "article_type": "榜单推荐文",
        "title": "高端厨电哪个牌子好",
        "markdown": "# 正文\n\n内容",
        "content_hash": f"hash-{article_id}",
        "article_audited_at": "2026-06-15T10:00:00+08:00",
        "updated_at": "2026-06-15T10:01:00+08:00",
    }


def test_writing_projects_are_proxied_and_marked_synced(tmp_path: Path, monkeypatch):
    client, publishing_store = make_client(tmp_path)
    publishing_store.upsert_articles([article_payload()], project_id="project-1")

    def fake_get(url: str, timeout: int):
        assert url == "http://writing.test/api/projects"
        assert timeout == 15
        return response(
            url,
            [
                {"id": "project-1", "name": "已同步项目", "updated_at": "2026-06-15T10:00:00+08:00"},
                {"id": "project-2", "name": "未同步项目", "updated_at": "2026-06-15T11:00:00+08:00"},
            ],
        )

    monkeypatch.setattr(httpx, "get", fake_get)

    result = client.get("/api/writing/projects", headers=auth_headers(publishing_store))

    assert result.status_code == 200
    assert result.json()["projects"] == [
        {"id": "project-1", "name": "已同步项目", "updated_at": "2026-06-15T10:00:00+08:00", "synced": True},
        {"id": "project-2", "name": "未同步项目", "updated_at": "2026-06-15T11:00:00+08:00", "synced": False},
    ]


def test_writing_projects_connection_error_is_readable(tmp_path: Path, monkeypatch):
    client, publishing_store = make_client(tmp_path)

    def fake_get(url: str, timeout: int):
        raise httpx.ConnectError("connection refused", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", fake_get)

    result = client.get("/api/writing/projects", headers=auth_headers(publishing_store))

    assert result.status_code == 502
    assert result.json()["detail"] == "无法连接撰文系统，请确认 8000 后端已启动。"


def test_sync_empty_project_returns_clear_message(tmp_path: Path, monkeypatch):
    client, publishing_store = make_client(tmp_path)

    def fake_get(url: str, timeout: int):
        assert url == "http://writing.test/api/projects/project-1/publishing/articles"
        assert timeout == 60
        return response(url, {"articles": []})

    monkeypatch.setattr(httpx, "get", fake_get)

    result = client.post("/api/sync/projects/project-1", headers=auth_headers(publishing_store))

    assert result.status_code == 200
    assert result.json()["sync"]["total"] == 0
    assert result.json()["message"] == "同步完成，但该项目暂无已审核定稿文章。"


def test_sync_deleted_project_returns_readable_404(tmp_path: Path, monkeypatch):
    client, publishing_store = make_client(tmp_path)

    def fake_get(url: str, timeout: int):
        return response(url, {"detail": "not found"}, status_code=404)

    monkeypatch.setattr(httpx, "get", fake_get)

    result = client.post("/api/sync/projects/missing", headers=auth_headers(publishing_store))

    assert result.status_code == 404
    assert result.json()["detail"] == "撰文项目不存在或已被删除，请重新选择项目。"


def test_auto_sync_once_refreshes_existing_synced_projects(tmp_path: Path, monkeypatch):
    publishing_store = make_store(tmp_path)
    publishing_store.upsert_articles([article_payload("article-1")], project_id="project-1")
    calls: list[str] = []

    def fake_get(url: str, timeout: int):
        calls.append(url)
        assert timeout == 60
        return response(url, {"articles": [article_payload("article-2")]})

    monkeypatch.setattr(httpx, "get", fake_get)

    result = auto_sync_once(publishing_store, publishing_store.settings)
    inventory = publishing_store.inventory("project-1", {"id": "admin", "role": "admin"})

    assert calls == ["http://writing.test/api/projects/project-1/publishing/articles"]
    assert result["total"] == 1
    assert result["succeeded"] == 1
    assert [item["article_id"] for item in inventory["articles"]] == ["article-2"]


def test_current_admin_cannot_deactivate_self(tmp_path: Path):
    client, publishing_store = make_client(tmp_path)
    login = publishing_store.login("admin", "secret123")

    result = client.patch(
        f"/api/admin/users/{login['user']['id']}",
        headers={"Authorization": f"Bearer {login['token']}"},
        json={"active": False},
    )

    assert result.status_code == 400
    assert result.json()["detail"] == "不能停用当前登录账号。"

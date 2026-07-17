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


def test_employee_record_routes_only_return_own_records(tmp_path: Path):
    client, publishing_store = make_client(tmp_path)
    publishing_store.upsert_articles([
        article_payload("article-1"),
        {**article_payload("article-2"), "keyword": "高端洗碗机"},
    ])
    li = publishing_store.create_user({"username": "li", "password": "secret123", "display_name": "李四", "role": "employee"})
    zhang = publishing_store.create_user({"username": "zhang", "password": "secret123", "display_name": "张三", "role": "employee"})
    for employee in (li, zhang):
        publishing_store.create_assignment({"user_id": employee["id"], "project_id": "project-1", "keywords": [], "article_types": []})

    li_token = publishing_store.login("li", "secret123")["token"]
    zhang_token = publishing_store.login("zhang", "secret123")["token"]
    admin_headers = auth_headers(publishing_store)

    li_record = publishing_store.create_self_publication(
        li,
        {
            "article_id": "article-1",
            "media_name": "知乎",
            "target_ai_platforms": ["豆包"],
            "publish_url": "https://example.com/li",
        },
    )
    zhang_record = publishing_store.create_web_publication(
        zhang,
        {
            "article_id": "article-2",
            "media_category": "垂直媒体",
            "media_name": "家居垂直媒体",
            "target_ai_platforms": ["DeepSeek"],
        },
    )

    li_headers = {"Authorization": f"Bearer {li_token}"}
    zhang_headers = {"Authorization": f"Bearer {zhang_token}"}
    li_records = client.get("/api/projects/project-1/records", headers=li_headers)
    zhang_records = client.get("/api/projects/project-1/records", headers=zhang_headers)
    admin_records = client.get("/api/projects/project-1/records", headers=admin_headers)

    assert [record["id"] for record in li_records.json()["records"]] == [li_record["id"]]
    assert [record["id"] for record in zhang_records.json()["records"]] == [zhang_record["id"]]
    assert {record["id"] for record in admin_records.json()["records"]} == {li_record["id"], zhang_record["id"]}

    li_inventory = client.get("/api/projects/project-1/inventory", headers=li_headers).json()
    admin_inventory = client.get("/api/projects/project-1/inventory", headers=admin_headers).json()
    assert li_inventory["totals"] == {"articles": 2, "available": 1, "published": 1, "purchasing": 0}
    assert admin_inventory["totals"] == {"articles": 2, "available": 0, "published": 1, "purchasing": 1}

    li_usage = client.get("/api/projects/project-1/usage-summary", headers=li_headers)
    public_usage = client.get("/api/projects/project-1/usage-summary")
    assert li_usage.json()["totals"] == li_inventory["totals"]
    assert public_usage.json()["totals"] == admin_inventory["totals"]


def test_employee_can_update_and_delete_own_publication_routes(tmp_path: Path):
    client, publishing_store = make_client(tmp_path)
    publishing_store.upsert_articles([article_payload("article-1")])
    employee = publishing_store.create_user({"username": "li", "password": "secret123", "display_name": "李四", "role": "employee"})
    publishing_store.create_assignment({"user_id": employee["id"], "project_id": "project-1", "keywords": [], "article_types": []})
    record = publishing_store.create_self_publication(
        employee,
        {
            "article_id": "article-1",
            "media_name": "知乎",
            "target_ai_platforms": ["豆包"],
            "publish_url": "https://example.com/old",
        },
    )
    headers = {"Authorization": f"Bearer {publishing_store.login('li', 'secret123')['token']}"}

    updated = client.patch(
        f"/api/publications/{record['id']}",
        headers=headers,
        json={"media_name": "小红书企业号", "publish_url": "https://example.com/new", "target_ai_platforms": ["DeepSeek"]},
    )
    invalid = client.patch(
        f"/api/publications/{record['id']}",
        headers=headers,
        json={"target_ai_platforms": []},
    )
    deleted = client.delete(f"/api/publications/{record['id']}", headers=headers)
    inventory = client.get("/api/projects/project-1/inventory", headers=headers).json()

    assert updated.status_code == 200
    assert updated.json()["record"]["media_name"] == "小红书企业号"
    assert updated.json()["record"]["target_ai_platforms"] == ["DeepSeek"]
    assert invalid.status_code == 400
    assert invalid.json()["detail"] == "至少选择一个 AI 平台。"
    assert deleted.status_code == 200
    assert deleted.json() == {"deleted": True}
    assert inventory["totals"] == {"articles": 1, "available": 1, "published": 0, "purchasing": 0}


def test_web_publication_route_preserves_purchase_date_on_backfill(tmp_path: Path):
    client, publishing_store = make_client(tmp_path)
    publishing_store.upsert_articles([article_payload("article-1")])
    employee = publishing_store.create_user({"username": "li", "password": "secret123", "display_name": "李四", "role": "employee"})
    publishing_store.create_assignment({"user_id": employee["id"], "project_id": "project-1", "keywords": [], "article_types": []})
    employee_headers = {"Authorization": f"Bearer {publishing_store.login('li', 'secret123')['token']}"}

    created = client.post(
        "/api/publications/web",
        headers=employee_headers,
        json={
            "article_id": "article-1",
            "media_category": "垂直媒体",
            "media_name": "家居媒体",
            "target_ai_platforms": ["DeepSeek"],
            "published_at": "2026-06-23",
        },
    )

    assert created.status_code == 200
    record = created.json()["record"]
    assert record["order_status"] == "purchasing"
    assert record["published_at"] == "2026-06-23"

    completed = client.patch(
        f"/api/publications/{record['id']}",
        headers=auth_headers(publishing_store),
        json={
            "media_name": "中国家电网",
            "publish_url": "https://example.com/web-date",
            "actual_cost": 800,
            "target_ai_platforms": ["豆包", "DeepSeek"],
            "order_status": "published",
        },
    )

    assert completed.status_code == 200
    assert completed.json()["record"]["published_at"] == "2026-06-23"

    changed = client.patch(
        f"/api/publications/{record['id']}",
        headers=auth_headers(publishing_store),
        json={"published_at": "2026-06-25"},
    )

    assert changed.status_code == 200
    assert changed.json()["record"]["published_at"] == "2026-06-25"


def test_admin_can_update_web_publication_ai_platforms_route(tmp_path: Path):
    client, publishing_store = make_client(tmp_path)
    publishing_store.upsert_articles([article_payload("article-1")])
    employee = publishing_store.create_user({"username": "li", "password": "secret123", "display_name": "李四", "role": "employee"})
    publishing_store.create_assignment({"user_id": employee["id"], "project_id": "project-1", "keywords": [], "article_types": []})
    record = publishing_store.create_web_publication(
        employee,
        {
            "article_id": "article-1",
            "media_category": "垂直媒体",
            "media_name": "家居媒体",
            "target_ai_platforms": ["DeepSeek"],
        },
    )

    updated = client.patch(
        f"/api/publications/{record['id']}",
        headers=auth_headers(publishing_store),
        json={
            "media_name": "中国家电网",
            "publish_url": "https://example.com/web",
            "actual_cost": 800,
            "target_ai_platforms": ["豆包", "DeepSeek"],
            "order_status": "published",
        },
    )

    assert updated.status_code == 200
    assert updated.json()["record"]["media_name"] == "中国家电网"
    assert updated.json()["record"]["actual_cost"] == 800
    assert updated.json()["record"]["target_ai_platforms"] == ["豆包", "DeepSeek"]


def test_employee_cannot_delete_other_employee_publication_route(tmp_path: Path):
    client, publishing_store = make_client(tmp_path)
    publishing_store.upsert_articles([article_payload("article-1")])
    li = publishing_store.create_user({"username": "li", "password": "secret123", "display_name": "李四", "role": "employee"})
    zhang = publishing_store.create_user({"username": "zhang", "password": "secret123", "display_name": "张三", "role": "employee"})
    for employee in (li, zhang):
        publishing_store.create_assignment({"user_id": employee["id"], "project_id": "project-1", "keywords": [], "article_types": []})
    record = publishing_store.create_self_publication(
        zhang,
        {
            "article_id": "article-1",
            "media_name": "知乎",
            "target_ai_platforms": ["豆包"],
            "publish_url": "https://example.com/zhang",
        },
    )
    li_headers = {"Authorization": f"Bearer {publishing_store.login('li', 'secret123')['token']}"}

    result = client.delete(f"/api/publications/{record['id']}", headers=li_headers)

    assert result.status_code == 403

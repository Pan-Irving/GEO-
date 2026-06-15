from pathlib import Path

import pytest

from app.config import Settings
from app.db import PublishingStore


def make_store(tmp_path: Path) -> PublishingStore:
    return PublishingStore(
        Settings(
            _env_file=None,
            publishing_data_dir=str(tmp_path),
            publishing_admin_username="admin",
            publishing_admin_password="secret123",
        )
    )


def article_payload(article_id: str = "article-1", keyword: str = "高端厨电哪个牌子好", article_type: str = "榜单推荐文") -> dict[str, str]:
    return {
        "article_id": article_id,
        "project_id": "project-1",
        "project_name": "测试项目",
        "source_id": "source-1",
        "brief_id": "brief-1",
        "keyword": keyword,
        "article_type": article_type,
        "title": "高端厨电哪个牌子好",
        "markdown": "# 正文\n\n内容",
        "content_hash": f"hash-{article_id}",
        "article_audited_at": "2026-06-15T10:00:00+08:00",
        "updated_at": "2026-06-15T10:01:00+08:00",
    }


def test_admin_is_seeded_and_can_login(tmp_path: Path):
    store = make_store(tmp_path)

    result = store.login("admin", "secret123")

    assert result
    assert result["user"]["role"] == "admin"
    assert store.user_for_token(result["token"])["username"] == "admin"


def test_admin_can_update_user_profile_role_and_active_status(tmp_path: Path):
    store = make_store(tmp_path)
    admin = store.login("admin", "secret123")["user"]
    employee = store.create_user({"username": "li", "password": "secret123", "display_name": "李明", "role": "employee"})

    updated = store.update_user(
        employee["id"],
        {"display_name": "李明明", "role": "manager", "active": False},
        actor=admin,
    )

    assert updated["display_name"] == "李明明"
    assert updated["role"] == "manager"
    assert updated["active"] is False
    assert store.login("li", "secret123") is None


def test_reset_password_invalidates_old_password_and_sessions(tmp_path: Path):
    store = make_store(tmp_path)
    admin = store.login("admin", "secret123")["user"]
    employee = store.create_user({"username": "li", "password": "secret123", "display_name": "李明", "role": "employee"})
    employee_login = store.login("li", "secret123")

    store.update_user(employee["id"], {"password": "newpass123"}, actor=admin)

    assert store.user_for_token(employee_login["token"]) is None
    assert store.login("li", "secret123") is None
    assert store.login("li", "newpass123")


def test_update_user_rejects_short_password(tmp_path: Path):
    store = make_store(tmp_path)
    admin = store.login("admin", "secret123")["user"]
    employee = store.create_user({"username": "li", "password": "secret123", "display_name": "李明", "role": "employee"})

    with pytest.raises(ValueError, match="密码至少 6 位"):
        store.update_user(employee["id"], {"password": "123"}, actor=admin)


def test_deactivating_user_invalidates_existing_sessions(tmp_path: Path):
    store = make_store(tmp_path)
    admin = store.login("admin", "secret123")["user"]
    employee = store.create_user({"username": "li", "password": "secret123", "display_name": "李明", "role": "employee"})
    employee_login = store.login("li", "secret123")

    store.update_user(employee["id"], {"active": False}, actor=admin)

    assert store.user_for_token(employee_login["token"]) is None


def test_cannot_remove_last_active_manager(tmp_path: Path):
    store = make_store(tmp_path)
    admin = store.login("admin", "secret123")["user"]

    with pytest.raises(ValueError, match="至少需要保留一个"):
        store.update_user(admin["id"], {"role": "employee"}, actor={"id": "other", "role": "admin"})
    with pytest.raises(ValueError, match="至少需要保留一个"):
        store.update_user(admin["id"], {"active": False}, actor={"id": "other", "role": "admin"})


def test_admin_cannot_change_own_role_even_with_other_manager(tmp_path: Path):
    store = make_store(tmp_path)
    admin = store.login("admin", "secret123")["user"]
    store.create_user({"username": "manager", "password": "secret123", "display_name": "负责人", "role": "manager"})

    with pytest.raises(ValueError, match="不能修改当前登录账号的角色"):
        store.update_user(admin["id"], {"role": "employee"}, actor=admin)


def test_assignment_filters_employee_inventory(tmp_path: Path):
    store = make_store(tmp_path)
    store.upsert_articles([
        article_payload("article-1", "关键词 A", "榜单推荐文"),
        article_payload("article-2", "关键词 B", "榜单推荐文"),
    ])
    employee = store.create_user({"username": "li", "password": "secret123", "display_name": "李明", "role": "employee"})
    store.create_assignment({"user_id": employee["id"], "project_id": "project-1", "keywords": ["关键词 A"], "article_types": ["榜单推荐文"]})

    inventory = store.inventory("project-1", employee)

    assert [item["article_id"] for item in inventory["articles"]] == ["article-1"]
    assert inventory["totals"]["articles"] == 1
    assert store.visible_projects(employee)[0]["article_count"] == 1


def test_sync_can_deactivate_removed_or_empty_project_inventory(tmp_path: Path):
    store = make_store(tmp_path)
    store.upsert_articles([
        article_payload("article-1", "关键词 A", "榜单推荐文"),
        article_payload("article-2", "关键词 B", "榜单推荐文"),
    ])

    partial = store.upsert_articles([article_payload("article-1", "关键词 A", "榜单推荐文")], project_id="project-1")
    assert partial["deactivated"] == 1
    assert [item["article_id"] for item in store.inventory("project-1", store.login("admin", "secret123")["user"])["articles"]] == ["article-1"]

    empty = store.upsert_articles([], project_id="project-1")
    assert empty["deactivated"] == 1
    assert store.usage_summary("project-1")["totals"]["articles"] == 0


def test_self_publication_counts_as_published_and_blocks_duplicate_url(tmp_path: Path):
    store = make_store(tmp_path)
    store.upsert_articles([article_payload()])
    employee = store.create_user({"username": "li", "password": "secret123", "display_name": "李明", "role": "employee"})
    store.create_assignment({"user_id": employee["id"], "project_id": "project-1", "keywords": [], "article_types": []})

    record = store.create_self_publication(
        employee,
        {
            "article_id": "article-1",
            "media_name": "知乎",
            "target_ai_platforms": ["豆包"],
            "publish_url": "https://example.com/a",
        },
    )

    assert record["order_status"] == "published"
    assert store.usage_summary("project-1")["totals"]["published"] == 1
    with pytest.raises(ValueError):
        store.create_self_publication(
            employee,
            {
                "article_id": "article-1",
                "media_name": "知乎",
                "target_ai_platforms": ["豆包"],
                "publish_url": "https://example.com/a",
            },
        )


def test_web_publication_is_purchasing_until_admin_marks_published(tmp_path: Path):
    store = make_store(tmp_path)
    store.upsert_articles([article_payload()])
    admin = store.login("admin", "secret123")["user"]
    employee = store.create_user({"username": "li", "password": "secret123", "display_name": "李明", "role": "employee"})
    store.create_assignment({"user_id": employee["id"], "project_id": "project-1", "keywords": [], "article_types": []})

    record = store.create_web_publication(
        employee,
        {
            "article_id": "article-1",
            "media_category": "垂直媒体",
            "media_name": "家居垂直媒体",
            "target_ai_platforms": ["DeepSeek"],
            "reference_url": "https://example.com/reference",
        },
    )

    summary = store.usage_summary("project-1")
    assert record["order_status"] == "purchasing"
    assert summary["totals"]["purchasing"] == 1
    assert summary["totals"]["published"] == 0
    assert summary["totals"]["available"] == 0
    assert summary["matrix"][0]["available"] == 0
    assert summary["matrix"][0]["purchasing"] == 1
    assert summary["articles"][0]["inventory_status"] == "采购中"

    updated = store.update_publication(
        record["id"],
        {
            "media_name": "中国家电网",
            "publish_url": "https://example.com/published",
            "actual_cost": 1800,
            "order_status": "published",
        },
    )

    assert updated["order_status"] == "published"
    assert updated["actual_cost"] == 1800
    completed_summary = store.usage_summary("project-1")
    assert completed_summary["totals"]["published"] == 1
    assert completed_summary["totals"]["available"] == 0
    assert admin["role"] == "admin"


def test_admin_cannot_complete_web_publication_with_invalid_status_or_negative_cost(tmp_path: Path):
    store = make_store(tmp_path)
    store.upsert_articles([article_payload()])
    employee = store.create_user({"username": "li", "password": "secret123", "display_name": "李明", "role": "employee"})
    store.create_assignment({"user_id": employee["id"], "project_id": "project-1", "keywords": [], "article_types": []})
    record = store.create_web_publication(
        employee,
        {
            "article_id": "article-1",
            "media_category": "垂直媒体",
            "media_name": "家居垂直媒体",
            "target_ai_platforms": ["DeepSeek"],
        },
    )

    with pytest.raises(ValueError):
        store.update_publication(record["id"], {"order_status": "done"})
    with pytest.raises(ValueError):
        store.update_publication(record["id"], {"actual_cost": -1})

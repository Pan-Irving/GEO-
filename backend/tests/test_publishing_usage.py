from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.api.routes import get_publishing_cleanup_service, get_publishing_usage_service, get_repository, router
from app.services.publishing_cleanup import PublishingCleanupService
from app.services.publishing_usage import PublishingUsageError, PublishingUsageService
from app.storage.repository import ProjectRepository


def add_keyword_material(repository: ProjectRepository, project_id: str, *keywords: str) -> None:
    text = "\n".join(keywords)
    material = repository.add_material(project_id, "keywords__核心关键词.md", "text/markdown", text.encode("utf-8"))
    material.status = "parsed"
    material.parsed_path = "parsed/keywords__核心关键词.md"
    material.parse_mode = "smart"
    material.parsed_at = "2026-01-01T00:00:00+00:00"
    repository.parsed_dir(project_id).mkdir(parents=True, exist_ok=True)
    (repository.project_dir(project_id) / material.parsed_path).write_text(text, encoding="utf-8")
    repository.update_material(project_id, material)


def create_publishing_db(path: Path) -> str:
    database_url = f"sqlite:///{path}"
    engine = create_engine(database_url, future=True)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE article_snapshots (
                  article_id TEXT PRIMARY KEY,
                  project_id TEXT NOT NULL,
                  keyword TEXT NOT NULL,
                  article_type TEXT NOT NULL,
                  active BOOLEAN NOT NULL
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE publication_records (
                  id TEXT PRIMARY KEY,
                  article_id TEXT NOT NULL,
                  order_status TEXT NOT NULL
                )
                """
            )
        )
    engine.dispose()
    return database_url


def insert_article(conn, article_id: str, *, project_id: str = "project-1", keyword: str = "关键词 A", article_type: str = "榜单推荐文", active: bool = True):
    conn.execute(
        text(
            """
            INSERT INTO article_snapshots (article_id, project_id, keyword, article_type, active)
            VALUES (:article_id, :project_id, :keyword, :article_type, :active)
            """
        ),
        {"article_id": article_id, "project_id": project_id, "keyword": keyword, "article_type": article_type, "active": active},
    )


def insert_record(conn, record_id: str, article_id: str, status: str):
    conn.execute(
        text("INSERT INTO publication_records (id, article_id, order_status) VALUES (:id, :article_id, :status)"),
        {"id": record_id, "article_id": article_id, "status": status},
    )


def test_usage_summary_counts_active_articles_and_statuses(tmp_path: Path):
    database_url = create_publishing_db(tmp_path / "publishing.db")
    engine = create_engine(database_url, future=True)
    with engine.begin() as conn:
        insert_article(conn, "article-available")
        insert_article(conn, "article-published")
        insert_article(conn, "article-purchasing", article_type="横评对比文")
        insert_article(conn, "article-inactive", active=False)
        insert_record(conn, "record-1", "article-published", "published")
        insert_record(conn, "record-2", "article-published", "published")
        insert_record(conn, "record-3", "article-published", "purchasing")
        insert_record(conn, "record-4", "article-purchasing", "purchasing")
        insert_record(conn, "record-5", "article-inactive", "published")
    engine.dispose()

    summary = PublishingUsageService(database_url).usage_summary("project-1")

    assert summary["totals"] == {"articles": 3, "available": 1, "published": 1, "purchasing": 2}
    articles = {item["article_id"]: item for item in summary["articles"]}
    assert articles["article-available"]["inventory_status"] == "可使用"
    assert articles["article-published"]["published_count"] == 2
    assert articles["article-published"]["purchasing_count"] == 1
    assert articles["article-published"]["inventory_status"] == "已使用"
    assert articles["article-purchasing"]["purchasing_count"] == 1
    assert articles["article-purchasing"]["inventory_status"] == "采购中"
    assert "article-inactive" not in articles

    matrix = {(item["keyword"], item["article_type"]): item for item in summary["matrix"]}
    assert matrix[("关键词 A", "榜单推荐文")] == {
        "keyword": "关键词 A",
        "article_type": "榜单推荐文",
        "total": 2,
        "available": 1,
        "published": 1,
        "purchasing": 1,
    }
    assert matrix[("关键词 A", "横评对比文")]["purchasing"] == 1


def test_usage_summary_requires_database_url():
    try:
        PublishingUsageService("").usage_summary("project-1")
    except PublishingUsageError as exc:
        assert "PUBLISHING_DATABASE_URL" in str(exc)
    else:
        raise AssertionError("expected missing publishing database URL to fail")


def test_usage_summary_route_degrades_when_publishing_db_unavailable(tmp_path: Path):
    repository = ProjectRepository(tmp_path / "writing")
    project = repository.create_project("发布状态测试")
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_repository] = lambda: repository
    app.dependency_overrides[get_publishing_usage_service] = lambda: PublishingUsageService("")
    client = TestClient(app)

    response = client.get(f"/api/projects/{project.id}/publishing/usage-summary")

    assert response.status_code == 503
    assert response.json()["detail"] == "发布库暂不可用，无法读取发布使用状态。"


def test_usage_summary_route_returns_publishing_counts(tmp_path: Path):
    repository = ProjectRepository(tmp_path / "writing")
    project = repository.create_project("发布状态测试")
    database_url = create_publishing_db(tmp_path / "publishing.db")
    engine = create_engine(database_url, future=True)
    with engine.begin() as conn:
        insert_article(conn, "article-ok", project_id=project.id, keyword="关键词 B")
        insert_record(conn, "record-ok", "article-ok", "published")
    engine.dispose()

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_repository] = lambda: repository
    app.dependency_overrides[get_publishing_usage_service] = lambda: PublishingUsageService(database_url)
    client = TestClient(app)

    response = client.get(f"/api/projects/{project.id}/publishing/usage-summary")

    assert response.status_code == 200
    body = response.json()
    assert body["project_id"] == project.id
    assert body["totals"]["published"] == 1
    assert body["articles"][0]["article_id"] == "article-ok"


def test_delete_article_route_removes_writing_article_and_publishing_records(tmp_path: Path):
    repository = ProjectRepository(tmp_path / "writing")
    project = repository.create_project("删除定稿测试")
    add_keyword_material(repository, project.id, "关键词 A")
    project = repository.import_markdown_articles(
        project.id,
        [
            {
                "filename": "article.md",
                "title": "待删除正文",
                "keyword": "关键词 A",
                "type": "榜单推荐文",
                "markdown": "# 待删除正文\n\n内容",
            }
        ],
    )
    article_id = project.steps["article"].output["items"][0]["id"]
    database_url = create_publishing_db(tmp_path / "publishing.db")
    engine = create_engine(database_url, future=True)
    with engine.begin() as conn:
        insert_article(conn, article_id, project_id=project.id)
        insert_record(conn, "record-delete", article_id, "published")
    engine.dispose()

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_repository] = lambda: repository
    app.dependency_overrides[get_publishing_cleanup_service] = lambda: PublishingCleanupService(database_url)
    client = TestClient(app)

    response = client.delete(f"/api/projects/{project.id}/articles/{article_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["project"]["steps"]["article"]["output"]["items"] == []
    assert body["publishing"] == {"configured": True, "deleted_records": 1, "deleted_articles": 1}
    reloaded = repository.load_project(project.id)
    assert reloaded.steps["article"].output["items"] == []

    engine = create_engine(database_url, future=True)
    with engine.connect() as conn:
        article_count = conn.execute(text("SELECT COUNT(*) FROM article_snapshots WHERE article_id = :article_id"), {"article_id": article_id}).scalar_one()
        record_count = conn.execute(text("SELECT COUNT(*) FROM publication_records WHERE article_id = :article_id"), {"article_id": article_id}).scalar_one()
    engine.dispose()

    assert article_count == 0
    assert record_count == 0

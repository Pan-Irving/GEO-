from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import get_repository, router
from app.services.publishing_inventory import publishing_articles
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


def test_publishing_articles_only_returns_approved_final_markdown(tmp_path: Path):
    repository = ProjectRepository(tmp_path)
    project = repository.create_project("发布测试项目")
    repository.update_step(
        project.id,
        "article",
        status="completed",
        output={
            "items": [
                {
                    "id": "article-ok",
                    "brief_id": "brief-ok",
                    "source_id": "source-ok",
                    "keyword": "高端厨电哪个牌子好",
                    "type": "榜单推荐文",
                    "title": "高端厨电哪个牌子好",
                    "markdown": "# 正文\n\n内容",
                    "status": "completed",
                    "article_audit_status": "approved",
                    "article_audited_at": "2026-06-15T10:00:00+08:00",
                },
                {
                    "id": "article-pending-review",
                    "markdown": "# 未审",
                    "status": "completed",
                    "article_audit_status": "",
                },
                {
                    "id": "article-stale",
                    "markdown": "# 过期",
                    "status": "stale",
                    "article_audit_status": "approved",
                },
                {
                    "id": "article-empty",
                    "markdown": "",
                    "status": "completed",
                    "article_audit_status": "approved",
                },
            ]
        },
    )

    saved = repository.load_project(project.id)
    articles = publishing_articles(saved)

    assert [item["article_id"] for item in articles] == ["article-ok"]
    assert articles[0]["project_id"] == project.id
    assert articles[0]["project_name"] == "发布测试项目"
    assert articles[0]["article_type"] == "榜单推荐文"
    assert articles[0]["content_hash"]
    assert articles[0]["updated_at"] == "2026-06-15T10:00:00+08:00"


def test_import_markdown_articles_creates_approved_publishable_items(tmp_path: Path):
    repository = ProjectRepository(tmp_path)
    project = repository.create_project("发布测试项目")
    add_keyword_material(repository, project.id, "关键词 A", "关键词 B")

    saved = repository.import_markdown_articles(
        project.id,
        [
            {"filename": "a.md", "title": "文章 A", "keyword": "关键词 A", "type": "榜单推荐文", "markdown": "# 文章 A\n\n内容 A"},
            {"filename": "b.md", "title": "文章 B", "keyword": "关键词 B", "type": "横评对比文", "markdown": "# 文章 B\n\n内容 B"},
        ],
    )

    items = saved.steps["article"].output["items"]
    assert len(items) == 2
    assert all(item["article_audit_status"] == "approved" for item in items)
    assert all(item["source_step"] == "imported" for item in items)
    assert saved.steps["article"].status == "completed"
    exported = publishing_articles(saved)
    assert [item["title"] for item in exported] == ["文章 A", "文章 B"]
    assert (repository.outputs_dir(project.id)).exists()
    assert len(list(repository.outputs_dir(project.id).rglob("articles/*.md"))) == 2


def test_import_markdown_articles_rejects_missing_required_metadata(tmp_path: Path):
    repository = ProjectRepository(tmp_path)
    project = repository.create_project("发布测试项目")
    add_keyword_material(repository, project.id, "关键词 A")

    try:
        repository.import_markdown_articles(project.id, [{"filename": "a.md", "keyword": "", "type": "榜单推荐文", "markdown": "# A"}])
    except ValueError as exc:
        assert "请填写关键词" in str(exc)
    else:
        raise AssertionError("expected missing keyword to fail")


def test_import_markdown_articles_rejects_non_md_and_empty_file(tmp_path: Path):
    repository = ProjectRepository(tmp_path)
    project = repository.create_project("发布测试项目")
    add_keyword_material(repository, project.id, "关键词 A")

    for payload, expected in [
        ({"filename": "a.txt", "keyword": "关键词 A", "type": "榜单推荐文", "markdown": "# A"}, "仅支持 .md 文件"),
        ({"filename": "a.md", "keyword": "关键词 A", "type": "榜单推荐文", "markdown": "   "}, "Markdown 内容不能为空"),
    ]:
        try:
            repository.import_markdown_articles(project.id, [payload])
        except ValueError as exc:
            assert expected in str(exc)
        else:
            raise AssertionError(f"expected {expected} to fail")


def test_import_markdown_articles_requires_core_keyword_table(tmp_path: Path):
    repository = ProjectRepository(tmp_path)
    project = repository.create_project("发布测试项目")

    try:
        repository.import_markdown_articles(project.id, [{"filename": "a.md", "keyword": "关键词 A", "type": "榜单推荐文", "markdown": "# A"}])
    except ValueError as exc:
        assert "核心关键词表" in str(exc)
    else:
        raise AssertionError("expected missing core keyword table to fail")


def test_import_markdown_articles_rejects_keyword_outside_core_table(tmp_path: Path):
    repository = ProjectRepository(tmp_path)
    project = repository.create_project("发布测试项目")
    add_keyword_material(repository, project.id, "关键词 A")

    try:
        repository.import_markdown_articles(project.id, [{"filename": "a.md", "keyword": "高端厨电", "type": "榜单推荐文", "markdown": "# A"}])
    except ValueError as exc:
        assert "核心关键词表" in str(exc)
    else:
        raise AssertionError("expected outside keyword to fail")


def test_publishing_articles_filters_out_orphan_keywords_when_allowed_keywords_are_known(tmp_path: Path):
    repository = ProjectRepository(tmp_path)
    project = repository.create_project("发布测试项目")
    repository.update_step(
        project.id,
        "article",
        status="completed",
        output={
            "items": [
                {
                    "id": "article-ok",
                    "keyword": "关键词 A",
                    "type": "榜单推荐文",
                    "title": "文章 A",
                    "markdown": "# A",
                    "status": "completed",
                    "article_audit_status": "approved",
                },
                {
                    "id": "article-orphan",
                    "keyword": "高端厨电",
                    "type": "榜单推荐文",
                    "title": "孤儿文章",
                    "markdown": "# orphan",
                    "status": "completed",
                    "article_audit_status": "approved",
                },
            ]
        },
    )

    saved = repository.load_project(project.id)
    assert [item["article_id"] for item in publishing_articles(saved, ["关键词 A"])] == ["article-ok"]


def test_import_markdown_route_accepts_multiple_files_and_metadata(tmp_path: Path):
    repository = ProjectRepository(tmp_path)
    project = repository.create_project("发布测试项目")
    add_keyword_material(repository, project.id, "关键词 A", "关键词 B")
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_repository] = lambda: repository
    client = TestClient(app)

    response = client.post(
        f"/api/projects/{project.id}/articles/import-md",
        data={
            "metadata": '[{"title":"文章 A","keyword":"关键词 A","type":"榜单推荐文"},{"title":"文章 B","keyword":"关键词 B","type":"横评对比文"}]',
        },
        files=[
            ("files", ("a.md", b"# A\n\ncontent", "text/markdown")),
            ("files", ("b.md", b"# B\n\ncontent", "text/markdown")),
        ],
    )

    assert response.status_code == 200
    saved = repository.load_project(project.id)
    assert len(publishing_articles(saved)) == 2


def test_import_markdown_articles_uses_h1_title_and_filename_fallback(tmp_path: Path):
    repository = ProjectRepository(tmp_path)
    project = repository.create_project("发布测试项目")
    add_keyword_material(repository, project.id, "关键词 A")

    saved = repository.import_markdown_articles(
        project.id,
        [
            {"filename": "custom-name.md", "keyword": "关键词 A", "type": "榜单推荐文", "markdown": "# 标题来自 H1\n\n内容"},
            {"filename": "fallback-name.md", "keyword": "关键词 A", "type": "横评对比文", "markdown": "无标题正文"},
        ],
    )

    titles = [item["title"] for item in saved.steps["article"].output["items"]]
    assert titles == ["标题来自 H1", "fallback-name"]

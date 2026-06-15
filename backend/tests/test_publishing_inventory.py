from pathlib import Path

from app.services.publishing_inventory import publishing_articles
from app.storage.repository import ProjectRepository


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

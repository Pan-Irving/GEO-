import json
from pathlib import Path

from app.core.config import Settings
from app.storage.factory import create_project_repository
from app.storage.mysql_repository import MySQLProjectRepository
from app.storage.repository import ProjectRepository


def test_repository_factory_defaults_to_file_storage(tmp_path: Path):
    repository = create_project_repository(Settings(app_data_dir=str(tmp_path)))

    assert isinstance(repository, ProjectRepository)
    assert not isinstance(repository, MySQLProjectRepository)


def test_mysql_repository_round_trips_project_without_changing_public_shape(tmp_path: Path):
    repository = MySQLProjectRepository(tmp_path, f"sqlite:///{tmp_path / 'writing.db'}")
    project = repository.create_project("MySQL 预置测试")

    saved = repository.import_markdown_articles(
        project.id,
        [
            {
                "filename": "a.md",
                "title": "文章 A",
                "keyword": "关键词 A",
                "type": "榜单推荐文",
                "markdown": "# 文章 A\n\n内容 A",
            }
        ],
    )
    loaded = repository.load_project(project.id)

    assert loaded.id == saved.id
    assert loaded.name == "MySQL 预置测试"
    assert loaded.steps["article"].output["items"][0]["title"] == "文章 A"
    assert loaded.steps["article"].output["items"][0]["article_audit_status"] == "approved"


def test_mysql_repository_migration_mode_does_not_rewrite_project_json(tmp_path: Path):
    file_repository = ProjectRepository(tmp_path)
    project = file_repository.create_project("迁移测试")
    original_path = file_repository.project_file(project.id)
    original_data = json.loads(original_path.read_text(encoding="utf-8"))
    original_data["updated_at"] = "2026-01-01T00:00:00+00:00"
    original_path.write_text(json.dumps(original_data, ensure_ascii=False, indent=2), encoding="utf-8")
    project = file_repository.load_project(project.id)

    mysql_repository = MySQLProjectRepository(
        tmp_path,
        f"sqlite:///{tmp_path / 'writing.db'}",
        write_snapshots=False,
        preserve_project_updated_at=True,
    )
    mysql_repository.save_project(project)

    after_data = json.loads(original_path.read_text(encoding="utf-8"))
    loaded = mysql_repository.load_project(project.id)
    assert after_data["updated_at"] == "2026-01-01T00:00:00+00:00"
    assert loaded.updated_at == "2026-01-01T00:00:00+00:00"

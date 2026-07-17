import json
from pathlib import Path

from sqlalchemy import event, select

from app.core.config import Settings
from app.storage.mysql_schema import writing_articles, writing_content_items
from app.storage.factory import create_project_repository
from app.storage.mysql_repository import MySQLProjectRepository
from app.storage.repository import ProjectRepository


def test_repository_factory_defaults_to_file_storage(tmp_path: Path):
    repository = create_project_repository(Settings(app_data_dir=str(tmp_path), writing_storage_backend="file", writing_database_url=""))

    assert isinstance(repository, ProjectRepository)
    assert not isinstance(repository, MySQLProjectRepository)


def seed_minimal_matrix(repository: MySQLProjectRepository, project_id: str) -> None:
    repository.update_step(
        project_id,
        "matrix",
        status="completed",
        confirmed=True,
        output={
            "intent_groups": [{"id": "ig-1", "name": "关键词 A", "keywords": ["关键词 A"]}],
            "items": [
                {
                    "id": "plan-a",
                    "source_id": "plan-a",
                    "source_step": "matrix",
                    "intent_group": "关键词 A",
                    "keyword": "关键词 A",
                    "type": "榜单推荐文",
                    "title": "文章 A",
                    "status": "completed",
                }
            ],
        },
    )


def test_mysql_repository_round_trips_project_without_changing_public_shape(tmp_path: Path):
    repository = MySQLProjectRepository(tmp_path, f"sqlite:///{tmp_path / 'writing.db'}")
    project = repository.create_project("MySQL 预置测试")
    material = repository.add_material(project.id, "keywords__核心关键词.md", "text/markdown", "关键词 A".encode("utf-8"))
    material.status = "parsed"
    material.parsed_path = "parsed/keywords__核心关键词.md"
    repository.parsed_dir(project.id).mkdir(parents=True, exist_ok=True)
    (repository.project_dir(project.id) / material.parsed_path).write_text("关键词 A", encoding="utf-8")
    repository.update_material(project.id, material)
    seed_minimal_matrix(repository, project.id)
    repository.create_custom_source(
        project.id,
        {
            "title": "自定义文章 A",
            "intent_group": "关键词 A",
            "type": "榜单推荐文",
        },
    )

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
    assert loaded.custom_sources[0].intent_group == "关键词 A"
    assert loaded.steps["article"].output["items"][0]["title"] == "文章 A"
    assert loaded.steps["article"].output["items"][0]["article_audit_status"] == "approved"

    with repository.engine.connect() as conn:
        content_row = conn.execute(
            select(writing_content_items.c.markdown, writing_content_items.c.raw_json)
            .where(writing_content_items.c.step == "article")
        ).mappings().one()
        article_row = conn.execute(select(writing_articles.c.markdown, writing_articles.c.raw_json)).mappings().one()
    assert content_row["markdown"] == ""
    assert "markdown" not in content_row["raw_json"]
    assert article_row["markdown"] == "# 文章 A\n\n内容 A\n"
    assert "markdown" not in article_row["raw_json"]


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


def test_mysql_repository_second_save_does_not_rewrite_project_child_rows(tmp_path: Path):
    repository = MySQLProjectRepository(tmp_path, f"sqlite:///{tmp_path / 'writing.db'}", write_snapshots=False)
    project = repository.create_project("增量保存测试")
    material = repository.add_material(project.id, "keywords__核心关键词.md", "text/markdown", "关键词 A".encode("utf-8"))
    material.status = "parsed"
    material.parsed_path = "parsed/keywords__核心关键词.md"
    repository.parsed_dir(project.id).mkdir(parents=True, exist_ok=True)
    (repository.project_dir(project.id) / material.parsed_path).write_text("关键词 A", encoding="utf-8")
    repository.update_material(project.id, material)
    seed_minimal_matrix(repository, project.id)
    repository.import_markdown_articles(
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
    child_writes: list[str] = []

    def collect_writes(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        normalized = statement.lower()
        if not normalized.lstrip().startswith(("insert", "update", "delete")):
            return
        if any(
            table in normalized
            for table in [
                "writing_materials",
                "writing_custom_sources",
                "writing_steps",
                "writing_jobs",
                "writing_content_items",
                "writing_articles",
            ]
        ):
            child_writes.append(statement)

    event.listen(repository.engine, "before_cursor_execute", collect_writes)
    try:
        repository.save_project(loaded)
    finally:
        event.remove(repository.engine, "before_cursor_execute", collect_writes)

    assert child_writes == []

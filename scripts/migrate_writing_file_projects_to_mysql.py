#!/usr/bin/env python
"""Migrate writing-system file projects into the preconfigured MySQL schema."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import SQLAlchemyError


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.core.config import get_settings  # noqa: E402
from app.storage.mysql_repository import MySQLProjectRepository  # noqa: E402
from app.storage.mysql_schema import (  # noqa: E402
    writing_articles,
    writing_content_items,
    writing_custom_sources,
    writing_jobs,
    writing_logs,
    writing_materials,
    writing_matrix_import_drafts,
    writing_projects,
    writing_steps,
)
from app.storage.repository import ProjectRepository  # noqa: E402


TABLES = [
    ("writing_projects", writing_projects),
    ("writing_materials", writing_materials),
    ("writing_custom_sources", writing_custom_sources),
    ("writing_steps", writing_steps),
    ("writing_jobs", writing_jobs),
    ("writing_content_items", writing_content_items),
    ("writing_articles", writing_articles),
    ("writing_matrix_import_drafts", writing_matrix_import_drafts),
    ("writing_logs", writing_logs),
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate writing-system app-data projects into MySQL.")
    parser.add_argument("--data-root", type=Path, default=None, help="Source APP_DATA_DIR. Defaults to current settings.")
    parser.add_argument("--database-url", default="", help="Target WRITING_DATABASE_URL. Defaults to current settings.")
    parser.add_argument("--project-id", action="append", default=[], help="Only migrate the given project ID. Can be repeated.")
    parser.add_argument("--dry-run", action="store_true", help="Print source and target counts without writing data.")
    parser.add_argument("--force", action="store_true", help="Allow importing into a non-empty target database.")
    args = parser.parse_args()

    settings = get_settings()
    data_root = args.data_root or settings.data_root
    database_url = args.database_url or settings.writing_database_dsn
    if not database_url:
        raise SystemExit("Set WRITING_DATABASE_URL or pass --database-url before running migration.")

    source_repo = ProjectRepository(data_root)
    projects = source_repo.list_projects()
    if args.project_id:
        selected_ids = set(args.project_id)
        projects = [project for project in projects if project.id in selected_ids]
        missing_ids = selected_ids - {project.id for project in projects}
        if missing_ids:
            raise SystemExit(f"Project not found in file storage: {', '.join(sorted(missing_ids))}")

    print("Source app-data:", data_root)
    print("Target MySQL:", database_url)
    print(f"Projects to migrate: {len(projects)}")
    for project in projects:
        article_items = project.steps.get("article").output.get("items", []) if project.steps.get("article") else []
        article_count = len(article_items) if isinstance(article_items, list) else 0
        print(f"- {project.id} | {project.name} | materials={len(project.materials)} articles={article_count}")

    target_counts = safe_target_counts(database_url)
    if target_counts:
        print("Target table counts:")
        for name, count in target_counts.items():
            print(f"- {name}: {count}")

    if args.dry_run:
        print("Dry run complete. No data was written.")
        return 0

    target_total = sum(target_counts.values()) if target_counts else 0
    if target_total and not args.force:
        raise SystemExit("Target writing database is not empty. Re-run with --force if this is intentional.")

    target_repo = MySQLProjectRepository(
        data_root,
        database_url,
        write_snapshots=False,
        preserve_project_updated_at=True,
    )
    for project in projects:
        target_repo.save_project(project)
        migrate_matrix_import_drafts(source_repo, target_repo, project.id)
        migrate_logs(source_repo, target_repo, project.id)
        print(f"Imported project: {project.id}")

    print("Migration complete. File storage was not modified.")
    return 0


def safe_target_counts(database_url: str) -> dict[str, int]:
    engine = create_engine(database_url, future=True, pool_pre_ping=True)
    counts: dict[str, int] = {}
    try:
        try:
            with engine.connect() as conn:
                for name, table in TABLES:
                    try:
                        counts[name] = int(conn.execute(select(func.count()).select_from(table)).scalar_one())
                    except SQLAlchemyError:
                        counts[name] = 0
        except SQLAlchemyError as exc:
            raise SystemExit(f"Cannot connect to target database: {exc}") from exc
    finally:
        engine.dispose()
    return counts


def migrate_matrix_import_drafts(
    source_repo: ProjectRepository,
    target_repo: MySQLProjectRepository,
    project_id: str,
) -> None:
    imports_root = source_repo.matrix_imports_dir(project_id)
    if not imports_root.exists():
        return
    for draft_file in sorted(imports_root.glob("*/draft.json")):
        draft_id = draft_file.parent.name
        draft = source_repo.load_matrix_import_draft(project_id, draft_id)
        target_repo.save_matrix_import_draft(project_id, draft_id, draft)


def migrate_logs(source_repo: ProjectRepository, target_repo: MySQLProjectRepository, project_id: str) -> None:
    logs = source_repo.read_logs(project_id)
    if not logs.strip():
        return
    with target_repo.engine.begin() as conn:
        conn.execute(writing_logs.delete().where(writing_logs.c.project_id == project_id))
        rows = []
        for line in logs.splitlines():
            if not line.startswith("[") or "] " not in line:
                continue
            created_at, message = line[1:].split("] ", 1)
            rows.append({"project_id": project_id, "created_at": created_at, "message": message})
        if rows:
            conn.execute(writing_logs.insert(), rows)


if __name__ == "__main__":
    raise SystemExit(main())

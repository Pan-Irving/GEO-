import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from sqlalchemy import Table, and_, create_engine, delete, func, insert, inspect, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.engine import Connection

from app.models.schemas import CustomSource, Job, Material, Project, STEP_ORDER, STORAGE_STEPS, StepState
from app.services.intent_group_manager import ensure_project_intent_groups
from app.storage.mysql_schema import (
    metadata,
    writing_articles,
    writing_content_items,
    writing_custom_sources,
    writing_intent_groups,
    writing_jobs,
    writing_logs,
    writing_materials,
    writing_matrix_import_drafts,
    writing_projects,
    writing_steps,
)
from app.storage.repository import ProjectRepository, normalize_blocked_step_states
from app.utils.files import safe_filename, utc_now


class MySQLProjectRepository(ProjectRepository):
    """MySQL-backed repository with the same public contract as ProjectRepository."""

    def __init__(
        self,
        data_root: Path,
        database_url: str,
        *,
        write_snapshots: bool = True,
        preserve_project_updated_at: bool = False,
    ):
        if not database_url:
            raise ValueError("WRITING_DATABASE_URL is required when WRITING_STORAGE_BACKEND=mysql.")
        super().__init__(data_root)
        self.engine = create_engine(database_url, future=True, pool_pre_ping=True)
        self.write_snapshots = write_snapshots
        self.preserve_project_updated_at = preserve_project_updated_at
        metadata.create_all(self.engine)
        self.migrate_schema()

    def migrate_schema(self) -> None:
        with self.engine.begin() as conn:
            ensure_column(conn, "writing_custom_sources", "intent_group_id", "VARCHAR(120) NOT NULL DEFAULT ''")
            ensure_column(conn, "writing_content_items", "intent_group_id", "VARCHAR(120) NOT NULL DEFAULT ''")
            ensure_column(conn, "writing_articles", "intent_group_id", "VARCHAR(120) NOT NULL DEFAULT ''")

    def list_projects(self) -> list[Project]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(writing_projects.c.id)
                .where(writing_projects.c.deleted_at.is_(None))
                .order_by(writing_projects.c.updated_at.desc())
            ).all()
        return [self.load_project(row[0]) for row in rows]

    def load_project(self, project_id: str) -> Project:
        with self.engine.connect() as conn:
            project_row = conn.execute(
                select(writing_projects).where(and_(writing_projects.c.id == project_id, writing_projects.c.deleted_at.is_(None)))
            ).mappings().first()
            if not project_row:
                raise FileNotFoundError(f"Project not found: {project_id}")

            materials = [
                mysql_material(row).model_dump()
                for row in conn.execute(
                    select(writing_materials).where(writing_materials.c.project_id == project_id).order_by(writing_materials.c.created_at)
                ).mappings().all()
            ]
            custom_sources = [
                mysql_custom_source(row).model_dump()
                for row in conn.execute(
                    select(writing_custom_sources)
                    .where(writing_custom_sources.c.project_id == project_id)
                    .order_by(writing_custom_sources.c.created_at)
                ).mappings().all()
            ]
            intent_groups = [
                mysql_intent_group(row)
                for row in conn.execute(
                    select(writing_intent_groups)
                    .where(writing_intent_groups.c.project_id == project_id)
                    .order_by(writing_intent_groups.c.created_at)
                ).mappings().all()
            ]
            raw_steps = {
                row["step"]: mysql_step_state(row).model_dump()
                for row in conn.execute(select(writing_steps).where(writing_steps.c.project_id == project_id)).mappings().all()
                if row["step"] in STORAGE_STEPS
            }
            jobs = [
                mysql_job(row).model_dump()
                for row in conn.execute(
                    select(writing_jobs).where(writing_jobs.c.project_id == project_id).order_by(writing_jobs.c.created_at.desc())
                ).mappings().all()
                if row["step"] in STORAGE_STEPS
            ]

        data = {
            "id": project_row["id"],
            "name": project_row["name"],
            "created_at": project_row["created_at"],
            "updated_at": project_row["updated_at"],
            "materials": materials,
            "intent_groups": intent_groups,
            "custom_sources": custom_sources,
            "steps": {step: raw_steps.get(step, StepState().model_dump()) for step in STORAGE_STEPS},
            "jobs": jobs,
        }
        normalize_blocked_step_states(data)
        return Project.model_validate(data)

    def save_project(self, project: Project) -> None:
        ensure_project_intent_groups(project)
        if not self.preserve_project_updated_at:
            project.updated_at = utc_now()
        data = project.model_dump()
        with self.engine.begin() as conn:
            existing = conn.execute(select(writing_projects.c.id).where(writing_projects.c.id == project.id)).first()
            project_values = {
                "id": project.id,
                "name": project.name,
                "created_at": project.created_at,
                "updated_at": project.updated_at,
                "deleted_at": None,
            }
            if existing:
                conn.execute(update(writing_projects).where(writing_projects.c.id == project.id).values(**project_values))
            else:
                conn.execute(insert(writing_projects).values(**project_values))

            material_rows = [material_row(project.id, item, project.created_at, project.updated_at) for item in project.materials]
            sync_project_rows(conn, writing_materials, project.id, material_rows, ("id",))

            custom_rows = [custom_source_row(project.id, item) for item in project.custom_sources]
            sync_project_rows(conn, writing_custom_sources, project.id, custom_rows, ("project_id", "id"))

            intent_group_rows = [intent_group_row(project.id, item) for item in project.intent_groups]
            sync_project_rows(conn, writing_intent_groups, project.id, intent_group_rows, ("project_id", "id"))

            step_rows = [step_row(project.id, step, state) for step, state in project.steps.items() if step in STEP_ORDER]
            sync_project_rows(conn, writing_steps, project.id, step_rows, ("project_id", "step"))

            job_rows = [job_row(project.id, job) for job in project.jobs if job.step in STEP_ORDER]
            sync_project_rows(conn, writing_jobs, project.id, job_rows, ("id",))

            content_rows = content_item_rows(project)
            sync_project_rows(conn, writing_content_items, project.id, content_rows, ("id",))

            article_rows = article_index_rows(project)
            sync_project_rows(conn, writing_articles, project.id, article_rows, ("project_id", "article_id"))

        if self.write_snapshots:
            self._write_project_snapshot(data)

    def delete_project(self, project_id: str) -> None:
        self.load_project(project_id)
        with self.engine.begin() as conn:
            conn.execute(update(writing_projects).where(writing_projects.c.id == project_id).values(deleted_at=utc_now(), updated_at=utc_now()))
        project_path = self.project_dir(project_id).resolve()
        projects_root = self.projects_root.resolve()
        if project_path.exists() and projects_root in project_path.parents:
            shutil.rmtree(project_path)

    def create_matrix_import_draft(self, project_id: str, filename: str, content_type: str | None, content: bytes) -> dict[str, Any]:
        return super().create_matrix_import_draft(project_id, filename, content_type, content)

    def load_matrix_import_draft(self, project_id: str, draft_id: str) -> dict[str, Any]:
        with self.engine.connect() as conn:
            row = conn.execute(
                select(writing_matrix_import_drafts).where(
                    and_(
                        writing_matrix_import_drafts.c.project_id == project_id,
                        writing_matrix_import_drafts.c.id == draft_id,
                    )
                )
            ).mappings().first()
        if row:
            return mysql_matrix_import_draft(row)
        return super().load_matrix_import_draft(project_id, draft_id)

    def save_matrix_import_draft(self, project_id: str, draft_id: str, draft: dict[str, Any]) -> dict[str, Any]:
        if not self.preserve_project_updated_at:
            draft["updated_at"] = utc_now()
        if self.write_snapshots:
            path = self.matrix_import_file(project_id, draft_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")
        row = matrix_import_draft_row(project_id, draft_id, draft)
        with self.engine.begin() as conn:
            existing = conn.execute(
                select(writing_matrix_import_drafts.c.id).where(
                    and_(
                        writing_matrix_import_drafts.c.project_id == project_id,
                        writing_matrix_import_drafts.c.id == draft_id,
                    )
                )
            ).first()
            if existing:
                conn.execute(
                    update(writing_matrix_import_drafts)
                    .where(
                        and_(
                            writing_matrix_import_drafts.c.project_id == project_id,
                            writing_matrix_import_drafts.c.id == draft_id,
                        )
                    )
                    .values(**row)
                )
            else:
                conn.execute(insert(writing_matrix_import_drafts).values(**row))
        return draft

    def recover_interrupted_jobs(self) -> None:
        for project in self.list_projects():
            changed = False
            data = project.model_dump()
            for state in data.get("steps", {}).values():
                if state.get("status") == "running":
                    state["status"] = "failed"
                    state["error"] = "服务重启或任务中断，请重新运行该步骤。"
                    state["updated_at"] = utc_now()
                    changed = True
            for job in data.get("jobs", []):
                if job.get("status") in {"queued", "running", "cancelling"}:
                    cancelled = job.get("status") == "cancelling"
                    job["status"] = "cancelled" if cancelled else "failed"
                    job["error"] = "任务已停止。" if cancelled else "服务重启或任务中断，请重新运行该步骤。"
                    job["updated_at"] = utc_now()
                    changed = True
            if changed:
                self.save_project(Project.model_validate(data))

    def log(self, project_id: str, message: str) -> None:
        now = utc_now()
        with self.engine.begin() as conn:
            conn.execute(insert(writing_logs).values(project_id=project_id, message=message, created_at=now))
        super().log(project_id, message)

    def read_logs(self, project_id: str) -> str:
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(writing_logs.c.created_at, writing_logs.c.message)
                .where(writing_logs.c.project_id == project_id)
                .order_by(writing_logs.c.created_at)
            ).all()
        if rows:
            return "".join(f"[{created_at}] {message}\n" for created_at, message in rows)
        return super().read_logs(project_id)

    def _write_project_snapshot(self, data: dict[str, Any]) -> None:
        self.project_dir(str(data["id"])).mkdir(parents=True, exist_ok=True)
        self.project_file(str(data["id"])).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def material_row(project_id: str, item: Material, created_at: str, updated_at: str) -> dict[str, Any]:
    return {
        "id": item.id,
        "project_id": project_id,
        "filename": item.filename,
        "stored_name": item.stored_name,
        "content_type": item.content_type,
        "size": item.size,
        "sha256": item.sha256,
        "parsed_path": item.parsed_path,
        "status": item.status,
        "error": item.error,
        "parse_mode": item.parse_mode,
        "parser_version": item.parser_version,
        "parse_source": item.parse_source,
        "parsed_chars": item.parsed_chars,
        "ocr_pages": item.ocr_pages,
        "parsed_at": item.parsed_at,
        "created_at": item.parsed_at or created_at,
        "updated_at": item.parsed_at or updated_at,
    }


def sync_project_rows(
    conn: Connection,
    table: Table,
    project_id: str,
    rows: list[dict[str, Any]],
    key_columns: tuple[str, ...],
) -> None:
    """Synchronize project-scoped rows without rewriting unchanged LONGTEXT/JSON payloads."""
    existing_rows = conn.execute(select(table).where(table.c.project_id == project_id)).mappings().all()
    existing_by_key = {row_key(row, key_columns): dict(row) for row in existing_rows}
    incoming_by_key = {row_key(row, key_columns): row for row in rows}

    for key, existing in existing_by_key.items():
        if key not in incoming_by_key:
            conn.execute(delete(table).where(key_condition(table, key_columns, key)))
            continue

        incoming = incoming_by_key[key]
        changed = {
            column: value
            for column, value in incoming.items()
            if column != "updated_at" and existing_value(existing.get(column)) != existing_value(value)
        }
        if changed:
            if "updated_at" in incoming:
                changed["updated_at"] = incoming["updated_at"]
            conn.execute(update(table).where(key_condition(table, key_columns, key)).values(**changed))

    new_rows = [row for key, row in incoming_by_key.items() if key not in existing_by_key]
    if new_rows:
        conn.execute(insert(table), new_rows)


def row_key(row: dict[str, Any], key_columns: tuple[str, ...]) -> tuple[Any, ...]:
    return tuple(row[column] for column in key_columns)


def key_condition(table: Table, key_columns: tuple[str, ...], key: tuple[Any, ...]) -> Any:
    return and_(*(getattr(table.c, column) == value for column, value in zip(key_columns, key, strict=True)))


def existing_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return value


def ensure_column(conn: Connection, table_name: str, column_name: str, definition: str) -> None:
    dialect = conn.dialect.name
    try:
        existing = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table_name})").all()} if dialect == "sqlite" else set()
    except Exception:
        existing = set()
    if dialect == "sqlite":
        if column_name not in existing:
            conn.exec_driver_sql(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")
        return
    existing = {column["name"] for column in inspect(conn).get_columns(table_name)}
    if column_name not in existing:
        conn.exec_driver_sql(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def mysql_material(row: dict[str, Any]) -> Material:
    return Material(
        id=row["id"],
        filename=row["filename"],
        stored_name=row["stored_name"],
        content_type=row["content_type"],
        size=int(row["size"] or 0),
        sha256=row["sha256"],
        parsed_path=row["parsed_path"],
        status=row["status"],
        error=row["error"],
        parse_mode=row["parse_mode"],
        parser_version=row["parser_version"],
        parse_source=row["parse_source"],
        parsed_chars=int(row["parsed_chars"] or 0),
        ocr_pages=int(row["ocr_pages"] or 0),
        parsed_at=row["parsed_at"],
    )


def custom_source_row(project_id: str, item: CustomSource) -> dict[str, Any]:
    return {
        "id": item.id,
        "project_id": project_id,
        "source_id": item.source_id,
        "intent_group_id": item.intent_group_id,
        "intent_group": item.intent_group,
        "keyword": item.keyword,
        "article_type": item.type,
        "title": item.title,
        "role": item.role,
        "brief_focus": item.brief_focus,
        "channel": item.channel,
        "channels_json": item.channels,
        "status": item.status,
        "raw_json": item.raw,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def mysql_custom_source(row: dict[str, Any]) -> CustomSource:
    raw = dict(row["raw_json"] or {})
    return CustomSource(
        id=row["id"],
        source_id=row["source_id"],
        intent_group_id=(row["intent_group_id"] if "intent_group_id" in row else "") or raw.get("intent_group_id") or "",
        intent_group=row["intent_group"],
        keyword=row["keyword"],
        type=row["article_type"],
        title=row["title"],
        role=row["role"],
        brief_focus=row["brief_focus"],
        channel=row["channel"],
        channels=list(row["channels_json"] or []),
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        raw=raw,
    )


def intent_group_row(project_id: str, item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": text(item.get("id")),
        "project_id": project_id,
        "name": text(item.get("name")),
        "aliases_json": item.get("aliases") if isinstance(item.get("aliases"), list) else [],
        "keywords_json": item.get("keywords") if isinstance(item.get("keywords"), list) else [],
        "article_count": int(item.get("article_count") or 0),
        "created_at": text(item.get("created_at"), utc_now()),
        "updated_at": text(item.get("updated_at"), utc_now()),
    }


def mysql_intent_group(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "aliases": list(row["aliases_json"] or []),
        "keywords": list(row["keywords_json"] or []),
        "article_count": int(row["article_count"] or 0),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def step_row(project_id: str, step: str, state: StepState) -> dict[str, Any]:
    return {
        "project_id": project_id,
        "step": step,
        "status": state.status,
        "input_json": state.input,
        "output_json": state.output,
        "error": state.error,
        "confirmed_at": state.confirmed_at,
        "updated_at": state.updated_at,
    }


def mysql_step_state(row: dict[str, Any]) -> StepState:
    return StepState(
        status=row["status"],
        input=dict(row["input_json"] or {}),
        output=dict(row["output_json"] or {}),
        error=row["error"],
        confirmed_at=row["confirmed_at"],
        updated_at=row["updated_at"],
    )


def job_row(project_id: str, item: Job) -> dict[str, Any]:
    return {
        "id": item.id,
        "project_id": project_id,
        "step": item.step,
        "status": item.status,
        "error": item.error,
        "total_count": item.total_count,
        "completed_count": item.completed_count,
        "failed_count": item.failed_count,
        "skipped_count": item.skipped_count,
        "current_item": item.current_item,
        "message": item.message,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def mysql_job(row: dict[str, Any]) -> Job:
    return Job(
        id=row["id"],
        step=row["step"],
        status=row["status"],
        error=row["error"],
        total_count=int(row["total_count"] or 0),
        completed_count=int(row["completed_count"] or 0),
        failed_count=int(row["failed_count"] or 0),
        skipped_count=int(row["skipped_count"] or 0),
        current_item=row["current_item"],
        message=row["message"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def matrix_import_draft_row(project_id: str, draft_id: str, draft: dict[str, Any]) -> dict[str, Any]:
    filename = text(draft.get("filename"), "content-plan.pdf")
    stored_name = text(draft.get("stored_name")) or f"source-{safe_filename(filename)}"
    return {
        "id": draft_id,
        "project_id": project_id,
        "status": text(draft.get("status"), "queued"),
        "filename": filename,
        "stored_name": stored_name,
        "content_type": text(draft.get("content_type")) or None,
        "size": int(draft.get("size") or 0),
        "source_path": text(draft.get("source_path")),
        "job_id": text(draft.get("job_id")) or None,
        "parsed_chars": int(draft.get("parsed_chars") or 0),
        "stats_json": draft.get("stats") if isinstance(draft.get("stats"), dict) else {},
        "warnings_json": draft.get("warnings") if isinstance(draft.get("warnings"), list) else [],
        "output_json": draft.get("output") if isinstance(draft.get("output"), dict) else {},
        "error": text(draft.get("error")) or None,
        "created_at": text(draft.get("created_at"), utc_now()),
        "updated_at": text(draft.get("updated_at"), utc_now()),
        "applied_at": text(draft.get("applied_at")) or None,
    }


def mysql_matrix_import_draft(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "status": row["status"],
        "filename": row["filename"],
        "stored_name": row["stored_name"],
        "content_type": row["content_type"],
        "size": int(row["size"] or 0),
        "source_path": row["source_path"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "job_id": row["job_id"],
        "parsed_chars": int(row["parsed_chars"] or 0),
        "stats": dict(row["stats_json"] or {}),
        "warnings": list(row["warnings_json"] or []),
        "output": dict(row["output_json"] or {}),
        "error": row["error"],
        "applied_at": row["applied_at"],
    }


def content_item_rows(project: Project) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for step, state in project.steps.items():
        if step not in {"matrix", "breakthrough", "brief", "article"}:
            continue
        items = state.output.get("items") if isinstance(state.output, dict) else None
        if not isinstance(items, list):
            continue
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            item_id = text(item.get("id") or item.get("article_id") or item.get("brief_id") or f"{step}-{index}")
            rows.append(
                {
                    "id": f"{project.id}:{step}:{item_id}",
                    "project_id": project.id,
                    "step": step,
                    "source_id": text(item.get("source_id") or item.get("sourceId")),
                    "source_step": text(item.get("source_step") or item.get("sourceStep") or step),
                    "brief_id": text(item.get("brief_id") or item.get("briefId")),
                    "intent_group_id": text(item.get("intent_group_id") or item.get("intentGroupId")),
                    "keyword": text(item.get("keyword") or item.get("target_keyword")),
                    "article_type": text(item.get("type") or item.get("article_type")),
                    "title": text(item.get("title") or item.get("article_title")),
                    "status": text(item.get("status"), "completed"),
                    "markdown": content_item_markdown(step, item),
                    "raw_json": index_item_snapshot(item),
                    "revision": int(item.get("revision") or 1),
                    "modified_at": text(item.get("modified_at") or item.get("modifiedAt")) or None,
                    "updated_at": text(item.get("updated_at") or item.get("updatedAt") or state.updated_at),
                }
            )
    return rows


def article_index_rows(project: Project) -> list[dict[str, Any]]:
    state = project.steps.get("article")
    if not state:
        return []
    items = state.output.get("items") if isinstance(state.output, dict) else None
    if not isinstance(items, list):
        return []
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        raw_markdown = item.get("markdown") if item.get("markdown") is not None else item.get("body")
        markdown = "" if raw_markdown is None else str(raw_markdown)
        article_id = text(item.get("id") or item.get("article_id") or f"article-{index}")
        updated_at = text(item.get("updated_at") or item.get("updatedAt") or item.get("generated_at") or item.get("generatedAt") or state.updated_at)
        rows.append(
            {
                "article_id": article_id,
                "project_id": project.id,
                "source_id": text(item.get("source_id") or item.get("sourceId")),
                "source_step": text(item.get("source_step") or item.get("sourceStep") or "article"),
                "brief_id": text(item.get("brief_id") or item.get("briefId")),
                "intent_group_id": text(item.get("intent_group_id") or item.get("intentGroupId")),
                "keyword": text(item.get("keyword") or item.get("target_keyword")),
                "article_type": text(item.get("type") or item.get("article_type")),
                "title": text(item.get("title") or item.get("article_title")),
                "markdown": markdown,
                "status": text(item.get("status"), "completed"),
                "article_audit_status": text(item.get("article_audit_status") or item.get("articleAuditStatus")),
                "article_audited_at": text(item.get("article_audited_at") or item.get("articleAuditedAt")) or None,
                "content_hash": hashlib.sha256(markdown.encode("utf-8")).hexdigest() if markdown else "",
                "used": text(item.get("used")),
                "review_notes": text(item.get("review_notes") or item.get("reviewNotes")) or None,
                "raw_json": index_item_snapshot(item),
                "created_at": text(item.get("generated_at") or item.get("generatedAt") or updated_at),
                "updated_at": updated_at,
            }
        )
    return rows


def content_item_markdown(step: str, item: dict[str, Any]) -> str:
    if step == "article":
        return ""
    return text(item.get("markdown") or item.get("body"))


def index_item_snapshot(item: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "id",
        "article_id",
        "brief_id",
        "source_id",
        "sourceId",
        "source_step",
        "sourceStep",
        "intent_group",
        "intent_group_id",
        "intentGroupId",
        "intentGroup",
        "keyword",
        "target_keyword",
        "type",
        "article_type",
        "title",
        "article_title",
        "status",
        "article_audit_status",
        "articleAuditStatus",
        "article_audited_at",
        "articleAuditedAt",
        "used",
        "revision",
        "brief_revision",
        "modified_at",
        "modifiedAt",
        "generated_at",
        "generatedAt",
        "updated_at",
        "updatedAt",
    ]
    return {key: item[key] for key in keys if key in item}


def text(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    if isinstance(value, str):
        return value.strip() or fallback
    return str(value).strip() or fallback

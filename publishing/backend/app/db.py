import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import (
    Boolean,
    Column,
    Float,
    ForeignKey,
    Index,
    MetaData,
    String,
    Table,
    Text,
    and_,
    create_engine,
    delete,
    func,
    insert,
    select,
    update,
)
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.engine import Connection, RowMapping
from sqlalchemy.exc import IntegrityError

from app.config import Settings
from app.security import hash_password, new_token, verify_password


AI_PLATFORMS = ["豆包", "千问", "元宝", "DeepSeek", "Kimi", "文心"]
SELF_MEDIA = ["什么值得买", "百家号", "搜狐号", "网易号", "头条号", "知乎"]
WEB_CATEGORIES = ["权威媒体", "垂直媒体", "大众媒体"]
ARTICLE_TYPES = ["榜单推荐文", "横评对比文", "支柱标准文", "场景选购文", "产品证据文", "FAQ问答文"]
ARTICLE_TYPE_ALIASES = {"FAQ问答短文": "FAQ问答文"}
ROLES = {"admin", "manager", "employee"}
ORDER_STATUSES = {"purchasing", "published"}

metadata = MetaData()

users = Table(
    "users",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("username", String(120), nullable=False, unique=True),
    Column("display_name", String(120), nullable=False),
    Column("role", String(32), nullable=False),
    Column("password_hash", String(255), nullable=False),
    Column("active", Boolean, nullable=False, default=True),
    Column("created_at", String(64), nullable=False),
    Column("updated_at", String(64), nullable=False),
)

sessions = Table(
    "sessions",
    metadata,
    Column("token", String(128), primary_key=True),
    Column("user_id", String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("expires_at", String(64), nullable=False),
    Column("created_at", String(64), nullable=False),
    Index("idx_session_user", "user_id"),
)

article_snapshots = Table(
    "article_snapshots",
    metadata,
    Column("article_id", String(191), primary_key=True),
    Column("project_id", String(191), nullable=False),
    Column("project_name", String(255), nullable=False),
    Column("source_id", String(191), nullable=False),
    Column("brief_id", String(191), nullable=False),
    Column("keyword", String(255), nullable=False),
    Column("article_type", String(120), nullable=False),
    Column("title", String(512), nullable=False),
    Column("markdown", LONGTEXT().with_variant(Text, "sqlite"), nullable=False),
    Column("content_hash", String(128), nullable=False),
    Column("article_audited_at", String(64), nullable=False),
    Column("writing_updated_at", String(64), nullable=False),
    Column("synced_at", String(64), nullable=False),
    Column("active", Boolean, nullable=False, default=True),
    Index("idx_article_project", "project_id"),
    Index("idx_article_project_active", "project_id", "active"),
    Index("idx_article_active_project_name", "active", "project_name", "project_id"),
    Index("idx_article_project_active_sort", "project_id", "active", "keyword", "article_type"),
    Index("idx_article_keyword_type", "keyword", "article_type"),
)

assignments = Table(
    "assignments",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("user_id", String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("project_id", String(191), nullable=False),
    Column("keywords_json", Text, nullable=False),
    Column("article_types_json", Text, nullable=False),
    Column("created_at", String(64), nullable=False),
    Column("updated_at", String(64), nullable=False),
    Index("idx_assignment_user", "user_id"),
    Index("idx_assignment_project", "project_id"),
)

publication_records = Table(
    "publication_records",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("article_id", String(191), ForeignKey("article_snapshots.article_id"), nullable=False),
    Column("employee_id", String(64), ForeignKey("users.id"), nullable=False),
    Column("channel_type", String(32), nullable=False),
    Column("media_kind", String(64), nullable=False),
    Column("media_category", String(64), nullable=False),
    Column("media_name", String(255), nullable=False),
    Column("target_ai_platforms_json", Text, nullable=False),
    Column("reference_url", String(1024), nullable=False),
    Column("publish_url", String(1024), nullable=False),
    Column("published_at", String(64), nullable=False),
    Column("order_id", String(128), nullable=False),
    Column("actual_cost", Float, nullable=False, default=0),
    Column("order_status", String(32), nullable=False),
    Column("note", Text, nullable=False),
    Column("article_content_hash", String(128), nullable=False),
    Column("created_at", String(64), nullable=False),
    Column("updated_at", String(64), nullable=False),
    Index("idx_publication_article", "article_id"),
    Index("idx_publication_employee", "employee_id"),
    Index("idx_publication_article_created", "article_id", "created_at"),
    Index("idx_publication_employee_article_created", "employee_id", "article_id", "created_at"),
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


class PublishingStore:
    def __init__(self, settings: Settings):
        self.settings = settings
        if settings.database_url.startswith("sqlite:///"):
            settings.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(
            settings.database_url,
            future=True,
            pool_pre_ping=True,
            connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
        )
        self.init_db()
        self.ensure_admin()

    @property
    def database_label(self) -> str:
        return self.settings.database_url if self.settings.publishing_database_url else str(self.settings.database_path)

    def init_db(self) -> None:
        metadata.create_all(self.engine)

    def ensure_admin(self) -> None:
        with self.engine.begin() as conn:
            count = conn.execute(select(func.count()).select_from(users)).scalar_one()
            if count:
                return
            now = utc_now()
            conn.execute(
                insert(users).values(
                    id=uuid.uuid4().hex,
                    username=self.settings.publishing_admin_username,
                    display_name=self.settings.publishing_admin_display_name,
                    role="admin",
                    password_hash=hash_password(self.settings.publishing_admin_password),
                    active=True,
                    created_at=now,
                    updated_at=now,
                )
            )

    def login(self, username: str, password: str) -> dict[str, Any] | None:
        with self.engine.begin() as conn:
            row = conn.execute(
                select(users).where(and_(users.c.username == username, users.c.active.is_(True)))
            ).mappings().first()
            if not row or not verify_password(password, row["password_hash"]):
                return None
            token = new_token()
            now = utc_now()
            expires_at = (datetime.now(UTC) + timedelta(hours=self.settings.publishing_session_hours)).isoformat()
            conn.execute(insert(sessions).values(token=token, user_id=row["id"], expires_at=expires_at, created_at=now))
            return {"token": token, "user": public_user(row), "expires_at": expires_at}

    def user_for_token(self, token: str) -> dict[str, Any] | None:
        if not token:
            return None
        with self.engine.connect() as conn:
            row = conn.execute(
                select(users)
                .select_from(sessions.join(users, users.c.id == sessions.c.user_id))
                .where(and_(sessions.c.token == token, sessions.c.expires_at > utc_now(), users.c.active.is_(True)))
            ).mappings().first()
            return public_user(row) if row else None

    def logout(self, token: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(delete(sessions).where(sessions.c.token == token))

    def list_users(self) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(select(users).order_by(users.c.created_at.desc())).mappings().all()
            return [public_user(row) for row in rows]

    def create_user(self, payload: dict[str, Any]) -> dict[str, Any]:
        role = str(payload.get("role") or "employee")
        if role not in ROLES:
            raise ValueError("无效角色。")
        username = clean(payload.get("username"))
        password = str(payload.get("password") or "")
        display_name = clean(payload.get("display_name")) or username
        if not username or len(password) < 6:
            raise ValueError("用户名不能为空，密码至少 6 位。")
        now = utc_now()
        with self.engine.begin() as conn:
            try:
                conn.execute(
                    insert(users).values(
                        id=uuid.uuid4().hex,
                        username=username,
                        display_name=display_name,
                        role=role,
                        password_hash=hash_password(password),
                        active=True,
                        created_at=now,
                        updated_at=now,
                    )
                )
            except IntegrityError as exc:
                raise ValueError("用户名已存在。") from exc
            row = conn.execute(select(users).where(users.c.username == username)).mappings().one()
            return public_user(row)

    def update_user(self, user_id: str, payload: dict[str, Any], actor: dict[str, Any] | None = None) -> dict[str, Any]:
        current = self.get_user(user_id)
        updates: dict[str, Any] = {}
        clear_sessions = False
        if "display_name" in payload:
            updates["display_name"] = clean(payload.get("display_name"))
        if "role" in payload:
            role = clean(payload.get("role"))
            if role not in ROLES:
                raise ValueError("无效角色。")
            if actor and actor.get("id") == user_id and role != current["role"]:
                raise ValueError("不能修改当前登录账号的角色。")
            if current["role"] in {"admin", "manager"} and role == "employee":
                self.ensure_other_active_manager(user_id)
            updates["role"] = role
        if "active" in payload:
            next_active = bool(payload.get("active"))
            if not next_active and actor and actor.get("id") == user_id:
                raise ValueError("不能停用当前登录账号。")
            if not next_active and current["role"] in {"admin", "manager"}:
                self.ensure_other_active_manager(user_id)
            updates["active"] = next_active
            if not next_active:
                clear_sessions = True
        if "password" in payload:
            password = str(payload.get("password") or "")
            if len(password) < 6:
                raise ValueError("密码至少 6 位。")
            updates["password_hash"] = hash_password(password)
            clear_sessions = True
        if not updates:
            return current
        updates["updated_at"] = utc_now()
        with self.engine.begin() as conn:
            conn.execute(update(users).where(users.c.id == user_id).values(**updates))
            if clear_sessions:
                conn.execute(delete(sessions).where(sessions.c.user_id == user_id))
        return self.get_user(user_id)

    def get_user(self, user_id: str) -> dict[str, Any]:
        with self.engine.connect() as conn:
            row = conn.execute(select(users).where(users.c.id == user_id)).mappings().first()
            if not row:
                raise FileNotFoundError("用户不存在。")
            return public_user(row)

    def ensure_other_active_manager(self, user_id: str) -> None:
        with self.engine.connect() as conn:
            count = conn.execute(
                select(func.count())
                .select_from(users)
                .where(and_(users.c.id != user_id, users.c.active.is_(True), users.c.role.in_(["admin", "manager"])))
            ).scalar_one()
        if count < 1:
            raise ValueError("至少需要保留一个启用中的管理员或内容负责人。")

    def synced_project_ids(self) -> set[str]:
        with self.engine.connect() as conn:
            rows = conn.execute(select(article_snapshots.c.project_id).distinct()).all()
            return {row[0] for row in rows}

    def upsert_articles(self, articles: list[dict[str, Any]], project_id: str | None = None) -> dict[str, Any]:
        now = utc_now()
        incoming_ids = {clean(article.get("article_id")) for article in articles if clean(article.get("article_id"))}
        project_ids = {clean(article.get("project_id")) for article in articles if clean(article.get("project_id"))}
        if project_id:
            project_ids.add(clean(project_id))
        created = 0
        updated = 0
        deactivated = 0
        with self.engine.begin() as conn:
            for current_project_id in project_ids:
                if not current_project_id:
                    continue
                condition = article_snapshots.c.project_id == current_project_id
                condition = and_(condition, article_snapshots.c.article_id.not_like("robam-%"))
                if incoming_ids:
                    condition = and_(condition, article_snapshots.c.article_id.not_in(sorted(incoming_ids)))
                condition = and_(condition, article_snapshots.c.active.is_(True))
                deactivation_ids = [
                    row[0]
                    for row in conn.execute(select(article_snapshots.c.article_id).where(condition)).all()
                ]
                if deactivation_ids:
                    result = conn.execute(
                        update(article_snapshots)
                        .where(article_snapshots.c.article_id.in_(deactivation_ids))
                        .values(active=False, synced_at=now)
                    )
                    deactivated += max(result.rowcount or 0, 0)
            for article in articles:
                article_id = clean(article.get("article_id"))
                if not article_id:
                    continue
                existing = conn.execute(
                    select(article_snapshots).where(article_snapshots.c.article_id == article_id)
                ).mappings().first()
                values = {
                    "article_id": article_id,
                    "project_id": clean(article.get("project_id")),
                    "project_name": clean(article.get("project_name")),
                    "source_id": clean(article.get("source_id")),
                    "brief_id": clean(article.get("brief_id")),
                    "keyword": clean(article.get("keyword")),
                    "article_type": normalize_article_type(article.get("article_type")),
                    "title": clean(article.get("title")),
                    "markdown": clean(article.get("markdown")),
                    "content_hash": clean(article.get("content_hash")),
                    "article_audited_at": clean(article.get("article_audited_at")),
                    "writing_updated_at": clean(article.get("updated_at")),
                    "synced_at": now,
                    "active": True,
                }
                if existing:
                    changed = {
                        key: value
                        for key, value in values.items()
                        if key != "synced_at" and comparable_value(existing.get(key)) != comparable_value(value)
                    }
                    if changed:
                        changed["synced_at"] = now
                        conn.execute(update(article_snapshots).where(article_snapshots.c.article_id == article_id).values(**changed))
                        updated += 1
                else:
                    conn.execute(insert(article_snapshots).values(**values))
                    created += 1
        return {"created": created, "updated": updated, "deactivated": deactivated, "total": len(incoming_ids)}

    def visible_projects(self, user: dict[str, Any]) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            if is_admin(user):
                rows = conn.execute(
                    select(
                        article_snapshots.c.project_id,
                        article_snapshots.c.project_name,
                        func.count().label("article_count"),
                        func.max(article_snapshots.c.synced_at).label("synced_at"),
                    )
                    .where(article_snapshots.c.active.is_(True))
                    .group_by(article_snapshots.c.project_id, article_snapshots.c.project_name)
                    .order_by(article_snapshots.c.project_name)
                ).mappings().all()
                return [dict(row) for row in rows]

            assignment_rows = conn.execute(select(assignments).where(assignments.c.user_id == user["id"])).mappings().all()
            user_assignments = [assignment_row(row) for row in assignment_rows]
            project_ids = sorted({assignment["project_id"] for assignment in user_assignments})
            if not project_ids:
                return []
            rows = conn.execute(
                select(article_snapshots)
                .where(and_(article_snapshots.c.active.is_(True), article_snapshots.c.project_id.in_(project_ids)))
                .order_by(article_snapshots.c.project_name)
            ).mappings().all()
            assignments_by_project: dict[str, list[dict[str, Any]]] = {}
            for assignment in user_assignments:
                assignments_by_project.setdefault(assignment["project_id"], []).append(assignment)
            projects: dict[str, dict[str, Any]] = {}
            for row in rows:
                article = article_row(row)
                if not assigned_article(article, assignments_by_project.get(article["project_id"], [])):
                    continue
                project = projects.setdefault(
                    article["project_id"],
                    {"project_id": article["project_id"], "project_name": article["project_name"], "article_count": 0, "synced_at": article["synced_at"]},
                )
                project["article_count"] += 1
                project["synced_at"] = max(project["synced_at"], article["synced_at"])
            return sorted(projects.values(), key=lambda item: item["project_name"])

    def list_assignments(self) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(
                    assignments,
                    users.c.username.label("username"),
                    users.c.display_name.label("display_name"),
                )
                .select_from(assignments.join(users, users.c.id == assignments.c.user_id))
                .order_by(assignments.c.created_at.desc())
            ).mappings().all()
            return [assignment_row(row) for row in rows]

    def create_assignment(self, payload: dict[str, Any]) -> dict[str, Any]:
        user_id = clean(payload.get("user_id"))
        project_id = clean(payload.get("project_id"))
        keywords = clean_list(payload.get("keywords"))
        article_types = [normalize_article_type(item) for item in clean_list(payload.get("article_types"))]
        if not user_id or not project_id:
            raise ValueError("必须选择员工和项目。")
        now = utc_now()
        assignment_id = uuid.uuid4().hex
        with self.engine.begin() as conn:
            conn.execute(
                insert(assignments).values(
                    id=assignment_id,
                    user_id=user_id,
                    project_id=project_id,
                    keywords_json=dumps(keywords),
                    article_types_json=dumps(article_types),
                    created_at=now,
                    updated_at=now,
                )
            )
            row = self._assignment_with_user(conn, assignment_id)
            return assignment_row(row)

    def delete_assignment(self, assignment_id: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(delete(assignments).where(assignments.c.id == assignment_id))

    def inventory(self, project_id: str, user: dict[str, Any]) -> dict[str, Any]:
        articles = self.visible_articles(project_id, user)
        records = self.records_for_project(project_id, user)
        records_by_article: dict[str, list[dict[str, Any]]] = {}
        for record in records:
            records_by_article.setdefault(record["article_id"], []).append(record)
        for article in articles:
            item_records = records_by_article.get(article["article_id"], [])
            article["records"] = item_records
            article["published_count"] = sum(1 for record in item_records if record["order_status"] == "published")
            article["purchasing_count"] = sum(1 for record in item_records if record["order_status"] == "purchasing")
            article["inventory_status"] = "已使用" if article["published_count"] else "采购中" if article["purchasing_count"] else "可使用"

        matrix: dict[str, dict[str, Any]] = {}
        for article in articles:
            key = f"{article['keyword']}\u0001{article['article_type']}"
            cell = matrix.setdefault(
                key,
                {"keyword": article["keyword"], "article_type": article["article_type"], "total": 0, "available": 0, "published": 0, "purchasing": 0},
            )
            cell["total"] += 1
            occupied = bool(article["published_count"] or article["purchasing_count"])
            if article["published_count"]:
                cell["published"] += 1
            if article["purchasing_count"]:
                cell["purchasing"] += 1
            if not occupied:
                cell["available"] += 1
        return {
            "project_id": project_id,
            "articles": articles,
            "records": records,
            "matrix": list(matrix.values()),
            "totals": {
                "articles": len(articles),
                "available": sum(1 for article in articles if not article["published_count"] and not article["purchasing_count"]),
                "published": sum(1 for article in articles if article["published_count"]),
                "purchasing": sum(1 for article in articles if article["purchasing_count"]),
            },
        }

    def visible_articles(self, project_id: str, user: dict[str, Any]) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(article_snapshots)
                .where(and_(article_snapshots.c.project_id == project_id, article_snapshots.c.active.is_(True)))
                .order_by(article_snapshots.c.keyword, article_snapshots.c.article_type, article_snapshots.c.title)
            ).mappings().all()
            articles = [article_row(row) for row in rows]
            if is_admin(user):
                return articles
        assignments_for_user = self.assignments_for_user_project(user["id"], project_id)
        return [article for article in articles if assigned_article(article, assignments_for_user)]

    def assignments_for_user_project(self, user_id: str, project_id: str) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(assignments).where(and_(assignments.c.user_id == user_id, assignments.c.project_id == project_id))
            ).mappings().all()
            return [assignment_row(row) for row in rows]

    def get_article(self, article_id: str, user: dict[str, Any]) -> dict[str, Any]:
        article = self.get_article_without_records(article_id, user)
        article["records"] = self.records_for_article(article_id, user)
        return article

    def records_for_project(self, project_id: str, user: dict[str, Any]) -> list[dict[str, Any]]:
        article_ids = {article["article_id"] for article in self.visible_articles(project_id, user)}
        if not article_ids:
            return []
        with self.engine.connect() as conn:
            query = (
                select(
                    publication_records,
                    users.c.display_name.label("employee_name"),
                    article_snapshots.c.project_id,
                    article_snapshots.c.keyword,
                    article_snapshots.c.article_type,
                    article_snapshots.c.title,
                )
                .select_from(
                    publication_records
                    .join(users, users.c.id == publication_records.c.employee_id)
                    .join(article_snapshots, article_snapshots.c.article_id == publication_records.c.article_id)
                )
                .where(publication_records.c.article_id.in_(sorted(article_ids)))
                .order_by(publication_records.c.created_at.desc())
            )
            if not is_admin(user):
                query = query.where(publication_records.c.employee_id == user["id"])
            rows = conn.execute(query).mappings().all()
            return [record_row(row) for row in rows]

    def records_for_article(self, article_id: str, user: dict[str, Any]) -> list[dict[str, Any]]:
        self.get_article_without_records(article_id, user)
        with self.engine.connect() as conn:
            query = (
                select(publication_records, users.c.display_name.label("employee_name"))
                .select_from(publication_records.join(users, users.c.id == publication_records.c.employee_id))
                .where(publication_records.c.article_id == article_id)
                .order_by(publication_records.c.created_at.desc())
            )
            if not is_admin(user):
                query = query.where(publication_records.c.employee_id == user["id"])
            rows = conn.execute(query).mappings().all()
            return [record_row(row) for row in rows]

    def get_article_without_records(self, article_id: str, user: dict[str, Any]) -> dict[str, Any]:
        with self.engine.connect() as conn:
            row = conn.execute(
                select(article_snapshots).where(and_(article_snapshots.c.article_id == article_id, article_snapshots.c.active.is_(True)))
            ).mappings().first()
            if not row:
                raise FileNotFoundError("文章不存在。")
            article = article_row(row)
        if not is_admin(user) and not assigned_article(article, self.assignments_for_user_project(user["id"], article["project_id"])):
            raise PermissionError("无权使用该文章。")
        return article

    def create_self_publication(self, user: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        article = self.get_article_without_records(clean(payload.get("article_id")), user)
        media_name = clean(payload.get("media_name"))
        publish_url = clean(payload.get("publish_url"))
        ai_platforms = validate_ai_platforms(payload.get("target_ai_platforms"))
        if not media_name:
            raise ValueError("请选择或填写自媒体平台。")
        if not valid_http_url(publish_url):
            raise ValueError("请填写有效发布链接。")
        self.ensure_unique_publish_url(article["article_id"], publish_url)
        now = utc_now()
        return self.insert_record(
            article=article,
            employee_id=user["id"],
            channel_type="自营",
            media_kind="自媒体",
            media_category="自媒体",
            media_name=media_name,
            target_ai_platforms=ai_platforms,
            reference_url="",
            publish_url=publish_url,
            published_at=clean(payload.get("published_at")) or now,
            order_id="",
            actual_cost=0,
            order_status="published",
            note=clean(payload.get("note")),
        )

    def create_web_publication(self, user: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        article = self.get_article_without_records(clean(payload.get("article_id")), user)
        media_category = clean(payload.get("media_category"))
        media_name = clean(payload.get("media_name") or payload.get("media_requirement"))
        publisher = clean(payload.get("publisher"))
        reference_url = clean(payload.get("reference_url"))
        ai_platforms = validate_ai_platforms(payload.get("target_ai_platforms"))
        if media_category not in WEB_CATEGORIES:
            raise ValueError("请选择有效网媒分类。")
        if not media_name:
            raise ValueError("请填写发布渠道。")
        if reference_url and not valid_http_url(reference_url):
            raise ValueError("参考链接必须以 http 或 https 开头。")
        return self.insert_record(
            article=article,
            employee_id=user["id"],
            channel_type="网媒",
            media_kind=media_category,
            media_category=media_category,
            media_name=f"待采购确认：{media_name}",
            target_ai_platforms=ai_platforms,
            reference_url=reference_url,
            publish_url="",
            published_at=clean(payload.get("published_at")) or utc_now(),
            order_id="",
            actual_cost=0,
            order_status="purchasing",
            note=web_publication_note(clean(payload.get("note")), publisher),
        )

    def insert_record(self, **kwargs: Any) -> dict[str, Any]:
        article = kwargs.pop("article")
        record_id = uuid.uuid4().hex
        now = utc_now()
        with self.engine.begin() as conn:
            conn.execute(
                insert(publication_records).values(
                    id=record_id,
                    article_id=article["article_id"],
                    employee_id=kwargs["employee_id"],
                    channel_type=kwargs["channel_type"],
                    media_kind=kwargs["media_kind"],
                    media_category=kwargs["media_category"],
                    media_name=kwargs["media_name"],
                    target_ai_platforms_json=dumps(kwargs["target_ai_platforms"]),
                    reference_url=kwargs["reference_url"],
                    publish_url=kwargs["publish_url"],
                    published_at=kwargs["published_at"],
                    order_id=kwargs["order_id"],
                    actual_cost=kwargs["actual_cost"],
                    order_status=kwargs["order_status"],
                    note=kwargs["note"],
                    article_content_hash=article["content_hash"],
                    created_at=now,
                    updated_at=now,
                )
            )
        return self.get_record(record_id)

    def get_record(self, record_id: str) -> dict[str, Any]:
        with self.engine.connect() as conn:
            row = conn.execute(select(publication_records).where(publication_records.c.id == record_id)).mappings().first()
            if not row:
                raise FileNotFoundError("发布记录不存在。")
            return record_row(row)

    def update_publication(self, record_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        record = self.get_record(record_id)
        updates: dict[str, Any] = {
            "media_name": clean(payload.get("media_name", record["media_name"])),
            "publish_url": clean(payload.get("publish_url", record["publish_url"])),
            "order_id": clean(payload.get("order_id", record["order_id"])),
            "published_at": clean(payload.get("published_at", record["published_at"])) or utc_now(),
            "actual_cost": float(payload.get("actual_cost", record["actual_cost"]) or 0),
            "note": clean(payload.get("note", record["note"])),
            "order_status": clean(payload.get("order_status", record["order_status"])) or record["order_status"],
        }
        if updates["order_status"] not in ORDER_STATUSES:
            raise ValueError("无效发布状态。")
        if updates["actual_cost"] < 0:
            raise ValueError("实际成本不能为负数。")
        if updates["order_status"] == "published":
            if not valid_http_url(updates["publish_url"]):
                raise ValueError("发布完成必须填写有效发布链接。")
            if not updates["media_name"]:
                raise ValueError("发布完成必须填写实际媒体名称。")
            if updates["publish_url"] != record["publish_url"]:
                self.ensure_unique_publish_url(record["article_id"], updates["publish_url"], exclude_record_id=record_id)
        if "target_ai_platforms" in payload:
            updates["target_ai_platforms_json"] = dumps(validate_ai_platforms(payload.get("target_ai_platforms")))
        updates["updated_at"] = utc_now()
        with self.engine.begin() as conn:
            conn.execute(update(publication_records).where(publication_records.c.id == record_id).values(**updates))
        return self.get_record(record_id)

    def update_publication_for_user(self, record_id: str, user: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        record = self.get_record(record_id)
        admin = is_admin(user)
        if is_self_channel(record["channel_type"]):
            if not admin and record["employee_id"] != user["id"]:
                raise PermissionError("只能修改自己的自营发布记录。")
            allowed_keys = {"media_name", "publish_url", "published_at", "target_ai_platforms", "note"}
            clean_payload = {key: value for key, value in payload.items() if key in allowed_keys}
            if not clean_payload:
                return record
            clean_payload["order_status"] = "published"
            return self.update_publication(record_id, clean_payload)
        if not admin:
            raise PermissionError("网媒发布结果只能由管理员或内容负责人回填。")
        return self.update_publication(record_id, payload)

    def delete_publication_for_user(self, record_id: str, user: dict[str, Any]) -> None:
        record = self.get_record(record_id)
        if not is_admin(user) and record["employee_id"] != user["id"]:
            raise PermissionError("只能撤销自己的发布记录。")
        with self.engine.begin() as conn:
            conn.execute(delete(publication_records).where(publication_records.c.id == record_id))

    def ensure_unique_publish_url(self, article_id: str, publish_url: str, exclude_record_id: str | None = None) -> None:
        conditions = [
            publication_records.c.article_id == article_id,
            publication_records.c.publish_url == publish_url,
            publication_records.c.publish_url != "",
        ]
        if exclude_record_id:
            conditions.append(publication_records.c.id != exclude_record_id)
        with self.engine.connect() as conn:
            row = conn.execute(
                select(publication_records.c.id).where(and_(*conditions))
            ).first()
            if row:
                raise ValueError("该文章已登记过相同发布链接。")

    def usage_summary(self, project_id: str, user: dict[str, Any] | None = None) -> dict[str, Any]:
        system_user = user or {"id": "", "role": "admin"}
        inventory = self.inventory(project_id, system_user)
        return {
            "project_id": project_id,
            "totals": inventory["totals"],
            "matrix": inventory["matrix"],
            "articles": [
                {
                    "article_id": article["article_id"],
                    "keyword": article["keyword"],
                    "article_type": article["article_type"],
                    "published_count": article["published_count"],
                    "purchasing_count": article["purchasing_count"],
                    "inventory_status": article["inventory_status"],
                }
                for article in inventory["articles"]
            ],
        }

    def _assignment_with_user(self, conn: Connection, assignment_id: str) -> RowMapping:
        row = conn.execute(
            select(assignments, users.c.username.label("username"), users.c.display_name.label("display_name"))
            .select_from(assignments.join(users, users.c.id == assignments.c.user_id))
            .where(assignments.c.id == assignment_id)
        ).mappings().one()
        return row


def public_user(row: RowMapping) -> dict[str, Any]:
    return {
        "id": row["id"],
        "username": row["username"],
        "display_name": row["display_name"],
        "role": row["role"],
        "active": bool(row["active"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def article_row(row: RowMapping) -> dict[str, Any]:
    data = dict(row)
    data["article_type"] = normalize_article_type(data.get("article_type"))
    return data


def assignment_row(row: RowMapping) -> dict[str, Any]:
    data = dict(row)
    data["keywords"] = loads(data.pop("keywords_json", "[]"), [])
    data["article_types"] = [normalize_article_type(item) for item in loads(data.pop("article_types_json", "[]"), [])]
    return data


def record_row(row: RowMapping) -> dict[str, Any]:
    data = dict(row)
    data["target_ai_platforms"] = loads(data.pop("target_ai_platforms_json", "[]"), [])
    if "article_type" in data:
        data["article_type"] = normalize_article_type(data.get("article_type"))
    return data


def clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def comparable_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return value


def normalize_article_type(value: Any) -> str:
    article_type = clean(value)
    return ARTICLE_TYPE_ALIASES.get(article_type, article_type)


def clean_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [clean(item) for item in value if clean(item)]


def web_publication_note(note: str, publisher: str) -> str:
    parts = []
    if publisher:
        parts.append(f"发稿方：{publisher}")
    if note:
        parts.append(note)
    return "\n".join(parts)


def validate_ai_platforms(value: Any) -> list[str]:
    platforms = clean_list(value)
    if not platforms:
        raise ValueError("至少选择一个 AI 平台。")
    invalid = [item for item in platforms if item not in AI_PLATFORMS]
    if invalid:
        raise ValueError(f"无效 AI 平台：{'、'.join(invalid)}")
    return platforms


def valid_http_url(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")


def is_admin(user: dict[str, Any]) -> bool:
    return user.get("role") in {"admin", "manager"}


def is_self_channel(channel: str) -> bool:
    return channel in {"自营", "自媒体", "self"}


def assigned_article(article: dict[str, Any], assignments: list[dict[str, Any]]) -> bool:
    for assignment in assignments:
        keywords = assignment.get("keywords") or []
        article_types = assignment.get("article_types") or []
        keyword_ok = not keywords or article["keyword"] in keywords
        type_ok = not article_types or article["article_type"] in article_types
        if keyword_ok and type_ok:
            return True
    return False

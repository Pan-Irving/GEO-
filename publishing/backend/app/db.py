import json
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.config import Settings
from app.security import hash_password, new_token, verify_password


AI_PLATFORMS = ["豆包", "千问", "元宝", "DeepSeek", "Kimi", "文心"]
SELF_MEDIA = ["什么值得买", "百家号", "搜狐号", "网易号", "头条号", "知乎"]
WEB_CATEGORIES = ["权威媒体", "垂直媒体", "大众媒体"]
ROLES = {"admin", "manager", "employee"}
ORDER_STATUSES = {"purchasing", "published"}


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
        self.path = settings.database_path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()
        self.ensure_admin()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def init_db(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                  id TEXT PRIMARY KEY,
                  username TEXT NOT NULL UNIQUE,
                  display_name TEXT NOT NULL,
                  role TEXT NOT NULL,
                  password_hash TEXT NOT NULL,
                  active INTEGER NOT NULL DEFAULT 1,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                  token TEXT PRIMARY KEY,
                  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                  expires_at TEXT NOT NULL,
                  created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS article_snapshots (
                  article_id TEXT PRIMARY KEY,
                  project_id TEXT NOT NULL,
                  project_name TEXT NOT NULL,
                  source_id TEXT NOT NULL,
                  brief_id TEXT NOT NULL,
                  keyword TEXT NOT NULL,
                  article_type TEXT NOT NULL,
                  title TEXT NOT NULL,
                  markdown TEXT NOT NULL,
                  content_hash TEXT NOT NULL,
                  article_audited_at TEXT NOT NULL,
                  writing_updated_at TEXT NOT NULL,
                  synced_at TEXT NOT NULL,
                  active INTEGER NOT NULL DEFAULT 1
                );
                CREATE INDEX IF NOT EXISTS idx_article_project ON article_snapshots(project_id);
                CREATE TABLE IF NOT EXISTS assignments (
                  id TEXT PRIMARY KEY,
                  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                  project_id TEXT NOT NULL,
                  keywords_json TEXT NOT NULL,
                  article_types_json TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_assignment_user ON assignments(user_id);
                CREATE TABLE IF NOT EXISTS publication_records (
                  id TEXT PRIMARY KEY,
                  article_id TEXT NOT NULL REFERENCES article_snapshots(article_id),
                  employee_id TEXT NOT NULL REFERENCES users(id),
                  channel_type TEXT NOT NULL,
                  media_kind TEXT NOT NULL,
                  media_category TEXT NOT NULL,
                  media_name TEXT NOT NULL,
                  target_ai_platforms_json TEXT NOT NULL,
                  reference_url TEXT NOT NULL,
                  publish_url TEXT NOT NULL,
                  published_at TEXT NOT NULL,
                  order_id TEXT NOT NULL,
                  actual_cost REAL NOT NULL DEFAULT 0,
                  order_status TEXT NOT NULL,
                  note TEXT NOT NULL,
                  article_content_hash TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_publication_article ON publication_records(article_id);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_article_publish_url
                ON publication_records(article_id, publish_url)
                WHERE publish_url != '';
                """
            )

    def ensure_admin(self) -> None:
        with self.connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM users").fetchone()
            if row and row["count"]:
                return
            now = utc_now()
            conn.execute(
                """
                INSERT INTO users (id, username, display_name, role, password_hash, active, created_at, updated_at)
                VALUES (?, ?, ?, 'admin', ?, 1, ?, ?)
                """,
                (
                    uuid.uuid4().hex,
                    self.settings.publishing_admin_username,
                    self.settings.publishing_admin_display_name,
                    hash_password(self.settings.publishing_admin_password),
                    now,
                    now,
                ),
            )

    def login(self, username: str, password: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE username = ? AND active = 1", (username,)).fetchone()
            if not row or not verify_password(password, row["password_hash"]):
                return None
            token = new_token()
            now = utc_now()
            expires_at = (datetime.now(UTC) + timedelta(hours=self.settings.publishing_session_hours)).isoformat()
            conn.execute(
                "INSERT INTO sessions (token, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)",
                (token, row["id"], expires_at, now),
            )
            return {"token": token, "user": public_user(row), "expires_at": expires_at}

    def user_for_token(self, token: str) -> dict[str, Any] | None:
        if not token:
            return None
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT users.* FROM sessions
                JOIN users ON users.id = sessions.user_id
                WHERE sessions.token = ? AND sessions.expires_at > ? AND users.active = 1
                """,
                (token, utc_now()),
            ).fetchone()
            return public_user(row) if row else None

    def logout(self, token: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))

    def list_users(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return [public_user(row) for row in conn.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()]

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
        with self.connect() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO users (id, username, display_name, role, password_hash, active, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                    """,
                    (uuid.uuid4().hex, username, display_name, role, hash_password(password), now, now),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("用户名已存在。") from exc
            row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
            return public_user(row)

    def update_user(self, user_id: str, payload: dict[str, Any], actor: dict[str, Any] | None = None) -> dict[str, Any]:
        current = self.get_user(user_id)
        updates: list[str] = []
        values: list[Any] = []
        clear_sessions = False
        if "display_name" in payload:
            updates.append("display_name = ?")
            values.append(clean(payload.get("display_name")))
        if "role" in payload:
            role = clean(payload.get("role"))
            if role not in ROLES:
                raise ValueError("无效角色。")
            if actor and actor.get("id") == user_id and role != current["role"]:
                raise ValueError("不能修改当前登录账号的角色。")
            if current["role"] in {"admin", "manager"} and role == "employee":
                self.ensure_other_active_manager(user_id)
            updates.append("role = ?")
            values.append(role)
        if "active" in payload:
            next_active = bool(payload.get("active"))
            if not next_active and actor and actor.get("id") == user_id:
                raise ValueError("不能停用当前登录账号。")
            if not next_active and current["role"] in {"admin", "manager"}:
                self.ensure_other_active_manager(user_id)
            updates.append("active = ?")
            values.append(1 if next_active else 0)
            if not next_active:
                clear_sessions = True
        if "password" in payload:
            password = str(payload.get("password") or "")
            if len(password) < 6:
                raise ValueError("密码至少 6 位。")
            updates.append("password_hash = ?")
            values.append(hash_password(password))
            clear_sessions = True
        if not updates:
            return current
        updates.append("updated_at = ?")
        values.append(utc_now())
        values.append(user_id)
        with self.connect() as conn:
            conn.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = ?", values)
            if clear_sessions:
                conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        return self.get_user(user_id)

    def get_user(self, user_id: str) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            if not row:
                raise FileNotFoundError("用户不存在。")
            return public_user(row)

    def ensure_other_active_manager(self, user_id: str) -> None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS count FROM users
                WHERE id != ? AND active = 1 AND role IN ('admin', 'manager')
                """,
                (user_id,),
            ).fetchone()
        if not row or row["count"] < 1:
            raise ValueError("至少需要保留一个启用中的管理员或内容负责人。")

    def synced_project_ids(self) -> set[str]:
        with self.connect() as conn:
            rows = conn.execute("SELECT DISTINCT project_id FROM article_snapshots").fetchall()
            return {row["project_id"] for row in rows}

    def upsert_articles(self, articles: list[dict[str, Any]], project_id: str | None = None) -> dict[str, Any]:
        now = utc_now()
        incoming_ids = {clean(article.get("article_id")) for article in articles if clean(article.get("article_id"))}
        project_ids = {clean(article.get("project_id")) for article in articles if clean(article.get("project_id"))}
        if project_id:
            project_ids.add(clean(project_id))
        created = 0
        updated = 0
        deactivated = 0
        with self.connect() as conn:
            for current_project_id in project_ids:
                if not current_project_id:
                    continue
                if incoming_ids:
                    placeholders = ",".join("?" for _ in incoming_ids)
                    cursor = conn.execute(
                        f"UPDATE article_snapshots SET active = 0, synced_at = ? WHERE project_id = ? AND article_id NOT IN ({placeholders})",
                        [now, current_project_id, *incoming_ids],
                    )
                else:
                    cursor = conn.execute(
                        "UPDATE article_snapshots SET active = 0, synced_at = ? WHERE project_id = ? AND active = 1",
                        (now, current_project_id),
                    )
                deactivated += max(cursor.rowcount, 0)
            for article in articles:
                article_id = clean(article.get("article_id"))
                if not article_id:
                    continue
                exists = conn.execute("SELECT article_id FROM article_snapshots WHERE article_id = ?", (article_id,)).fetchone()
                values = (
                    article_id,
                    clean(article.get("project_id")),
                    clean(article.get("project_name")),
                    clean(article.get("source_id")),
                    clean(article.get("brief_id")),
                    clean(article.get("keyword")),
                    clean(article.get("article_type")),
                    clean(article.get("title")),
                    clean(article.get("markdown")),
                    clean(article.get("content_hash")),
                    clean(article.get("article_audited_at")),
                    clean(article.get("updated_at")),
                    now,
                    1,
                )
                conn.execute(
                    """
                    INSERT INTO article_snapshots (
                      article_id, project_id, project_name, source_id, brief_id, keyword, article_type, title,
                      markdown, content_hash, article_audited_at, writing_updated_at, synced_at, active
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(article_id) DO UPDATE SET
                      project_id = excluded.project_id,
                      project_name = excluded.project_name,
                      source_id = excluded.source_id,
                      brief_id = excluded.brief_id,
                      keyword = excluded.keyword,
                      article_type = excluded.article_type,
                      title = excluded.title,
                      markdown = excluded.markdown,
                      content_hash = excluded.content_hash,
                      article_audited_at = excluded.article_audited_at,
                      writing_updated_at = excluded.writing_updated_at,
                      synced_at = excluded.synced_at,
                      active = 1
                    """,
                    values,
                )
                created += 0 if exists else 1
                updated += 1 if exists else 0
        return {"created": created, "updated": updated, "deactivated": deactivated, "total": len(incoming_ids)}

    def visible_projects(self, user: dict[str, Any]) -> list[dict[str, Any]]:
        with self.connect() as conn:
            if is_admin(user):
                rows = conn.execute(
                    """
                    SELECT project_id, project_name, COUNT(*) AS article_count, MAX(synced_at) AS synced_at
                    FROM article_snapshots WHERE active = 1 GROUP BY project_id, project_name ORDER BY project_name
                    """
                ).fetchall()
            else:
                assignments = [assignment_row(row) for row in conn.execute("SELECT * FROM assignments WHERE user_id = ?", (user["id"],)).fetchall()]
                project_ids = sorted({assignment["project_id"] for assignment in assignments})
                if not project_ids:
                    return []
                placeholders = ",".join("?" for _ in project_ids)
                rows = conn.execute(
                    f"SELECT * FROM article_snapshots WHERE active = 1 AND project_id IN ({placeholders}) ORDER BY project_name",
                    project_ids,
                ).fetchall()
                assignments_by_project: dict[str, list[dict[str, Any]]] = {}
                for assignment in assignments:
                    assignments_by_project.setdefault(assignment["project_id"], []).append(assignment)
                projects: dict[str, dict[str, Any]] = {}
                for row in rows:
                    article = article_row(row)
                    if not assigned_article(article, assignments_by_project.get(article["project_id"], [])):
                        continue
                    project = projects.setdefault(
                        article["project_id"],
                        {
                            "project_id": article["project_id"],
                            "project_name": article["project_name"],
                            "article_count": 0,
                            "synced_at": article["synced_at"],
                        },
                    )
                    project["article_count"] += 1
                    project["synced_at"] = max(project["synced_at"], article["synced_at"])
                return sorted(projects.values(), key=lambda item: item["project_name"])
            return [dict(row) for row in rows]

    def list_assignments(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT assignments.*, users.username, users.display_name
                FROM assignments JOIN users ON users.id = assignments.user_id
                ORDER BY assignments.created_at DESC
                """
            ).fetchall()
            return [assignment_row(row) for row in rows]

    def create_assignment(self, payload: dict[str, Any]) -> dict[str, Any]:
        user_id = clean(payload.get("user_id"))
        project_id = clean(payload.get("project_id"))
        keywords = clean_list(payload.get("keywords"))
        article_types = clean_list(payload.get("article_types"))
        if not user_id or not project_id:
            raise ValueError("必须选择员工和项目。")
        now = utc_now()
        assignment_id = uuid.uuid4().hex
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO assignments (id, user_id, project_id, keywords_json, article_types_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (assignment_id, user_id, project_id, dumps(keywords), dumps(article_types), now, now),
            )
            row = conn.execute(
                """
                SELECT assignments.*, users.username, users.display_name
                FROM assignments JOIN users ON users.id = assignments.user_id
                WHERE assignments.id = ?
                """,
                (assignment_id,),
            ).fetchone()
            return assignment_row(row)

    def delete_assignment(self, assignment_id: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM assignments WHERE id = ?", (assignment_id,))

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
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM article_snapshots WHERE project_id = ? AND active = 1 ORDER BY keyword, article_type, title",
                (project_id,),
            ).fetchall()
            articles = [article_row(row) for row in rows]
            if is_admin(user):
                return articles
            assignments = self.assignments_for_user_project(user["id"], project_id)
            return [article for article in articles if assigned_article(article, assignments)]

    def assignments_for_user_project(self, user_id: str, project_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM assignments WHERE user_id = ? AND project_id = ?", (user_id, project_id)).fetchall()
            return [assignment_row(row) for row in rows]

    def get_article(self, article_id: str, user: dict[str, Any]) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM article_snapshots WHERE article_id = ? AND active = 1", (article_id,)).fetchone()
            if not row:
                raise FileNotFoundError("文章不存在。")
            article = article_row(row)
        if not is_admin(user) and not assigned_article(article, self.assignments_for_user_project(user["id"], article["project_id"])):
            raise PermissionError("无权查看该文章。")
        article["records"] = self.records_for_article(article_id, user)
        return article

    def records_for_project(self, project_id: str, user: dict[str, Any]) -> list[dict[str, Any]]:
        article_ids = {article["article_id"] for article in self.visible_articles(project_id, user)}
        if not article_ids:
            return []
        placeholders = ",".join("?" for _ in article_ids)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT r.*, u.display_name AS employee_name, s.project_id, s.keyword, s.article_type, s.title
                FROM publication_records r
                JOIN users u ON u.id = r.employee_id
                JOIN article_snapshots s ON s.article_id = r.article_id
                WHERE r.article_id IN ({placeholders})
                ORDER BY r.created_at DESC
                """,
                list(article_ids),
            ).fetchall()
            return [record_row(row) for row in rows]

    def records_for_article(self, article_id: str, user: dict[str, Any]) -> list[dict[str, Any]]:
        self.get_article_without_records(article_id, user)
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT r.*, u.display_name AS employee_name
                FROM publication_records r JOIN users u ON u.id = r.employee_id
                WHERE r.article_id = ? ORDER BY r.created_at DESC
                """,
                (article_id,),
            ).fetchall()
            return [record_row(row) for row in rows]

    def get_article_without_records(self, article_id: str, user: dict[str, Any]) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM article_snapshots WHERE article_id = ? AND active = 1", (article_id,)).fetchone()
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
        if media_name not in SELF_MEDIA:
            raise ValueError("请选择有效自媒体平台。")
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
        reference_url = clean(payload.get("reference_url"))
        ai_platforms = validate_ai_platforms(payload.get("target_ai_platforms"))
        if media_category not in WEB_CATEGORIES:
            raise ValueError("请选择有效网媒分类。")
        if not media_name:
            raise ValueError("请填写期望媒体名称或要求。")
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
            published_at="",
            order_id="",
            actual_cost=0,
            order_status="purchasing",
            note=clean(payload.get("note")),
        )

    def insert_record(self, **kwargs: Any) -> dict[str, Any]:
        article = kwargs.pop("article")
        record_id = uuid.uuid4().hex
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO publication_records (
                  id, article_id, employee_id, channel_type, media_kind, media_category, media_name,
                  target_ai_platforms_json, reference_url, publish_url, published_at, order_id,
                  actual_cost, order_status, note, article_content_hash, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record_id,
                    article["article_id"],
                    kwargs["employee_id"],
                    kwargs["channel_type"],
                    kwargs["media_kind"],
                    kwargs["media_category"],
                    kwargs["media_name"],
                    dumps(kwargs["target_ai_platforms"]),
                    kwargs["reference_url"],
                    kwargs["publish_url"],
                    kwargs["published_at"],
                    kwargs["order_id"],
                    kwargs["actual_cost"],
                    kwargs["order_status"],
                    kwargs["note"],
                    article["content_hash"],
                    now,
                    now,
                ),
            )
        return self.get_record(record_id)

    def get_record(self, record_id: str) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM publication_records WHERE id = ?", (record_id,)).fetchone()
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
                self.ensure_unique_publish_url(record["article_id"], updates["publish_url"])
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE publication_records
                SET media_name = ?, publish_url = ?, order_id = ?, published_at = ?, actual_cost = ?,
                    note = ?, order_status = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    updates["media_name"],
                    updates["publish_url"],
                    updates["order_id"],
                    updates["published_at"],
                    updates["actual_cost"],
                    updates["note"],
                    updates["order_status"],
                    now,
                    record_id,
                ),
            )
        return self.get_record(record_id)

    def ensure_unique_publish_url(self, article_id: str, publish_url: str) -> None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT id FROM publication_records WHERE article_id = ? AND publish_url = ? AND publish_url != ''",
                (article_id, publish_url),
            ).fetchone()
            if row:
                raise ValueError("该文章已登记过相同发布链接。")

    def usage_summary(self, project_id: str) -> dict[str, Any]:
        system_user = {"id": "", "role": "admin"}
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


def public_user(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "username": row["username"],
        "display_name": row["display_name"],
        "role": row["role"],
        "active": bool(row["active"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def article_row(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def assignment_row(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["keywords"] = loads(data.pop("keywords_json", "[]"), [])
    data["article_types"] = loads(data.pop("article_types_json", "[]"), [])
    return data


def record_row(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["target_ai_platforms"] = loads(data.pop("target_ai_platforms_json", "[]"), [])
    return data


def clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def clean_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [clean(item) for item in value if clean(item)]


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


def assigned_article(article: dict[str, Any], assignments: list[dict[str, Any]]) -> bool:
    for assignment in assignments:
        keywords = assignment.get("keywords") or []
        article_types = assignment.get("article_types") or []
        keyword_ok = not keywords or article["keyword"] in keywords
        type_ok = not article_types or article["article_type"] in article_types
        if keyword_ok and type_ok:
            return True
    return False

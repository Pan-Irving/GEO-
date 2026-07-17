from typing import Any

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import SQLAlchemyError


class PublishingUsageError(Exception):
    """Raised when publishing usage cannot be read from the publishing database."""


class PublishingUsageService:
    def __init__(self, database_url: str):
        self.database_url = database_url.strip()

    def usage_summary(self, project_id: str) -> dict[str, Any]:
        if not self.database_url:
            raise PublishingUsageError("PUBLISHING_DATABASE_URL is not configured.")

        try:
            engine = create_engine(self.database_url, future=True, pool_pre_ping=True)
            try:
                with engine.connect() as conn:
                    columns = {column["name"] for column in inspect(conn).get_columns("article_snapshots")}
                    intent_group_select = "a.intent_group" if "intent_group" in columns else "a.keyword"
                    intent_group_id_select = "a.intent_group_id" if "intent_group_id" in columns else "''"
                    rows = conn.execute(
                        text(
                            f"""
                            SELECT
                              a.article_id,
                              {intent_group_id_select} AS intent_group_id,
                              {intent_group_select} AS intent_group,
                              a.keyword,
                              a.article_type,
                              SUM(CASE WHEN r.order_status = 'published' THEN 1 ELSE 0 END) AS published_count,
                              SUM(CASE WHEN r.order_status = 'purchasing' THEN 1 ELSE 0 END) AS purchasing_count
                            FROM article_snapshots a
                            LEFT JOIN publication_records r
                              ON r.article_id = a.article_id
                            WHERE a.project_id = :project_id
                              AND a.active = :active
                            GROUP BY a.article_id, intent_group_id, intent_group, a.keyword, a.article_type
                            ORDER BY intent_group, a.article_type, a.article_id
                            """
                        ),
                        {"project_id": project_id, "active": True},
                    ).mappings().all()
            finally:
                engine.dispose()
        except SQLAlchemyError as exc:
            raise PublishingUsageError("Cannot read publishing usage from publishing database.") from exc

        articles: list[dict[str, Any]] = []
        matrix: dict[tuple[str, str], dict[str, Any]] = {}
        totals = {"articles": 0, "available": 0, "published": 0, "purchasing": 0}

        for row in rows:
            published_count = int(row["published_count"] or 0)
            purchasing_count = int(row["purchasing_count"] or 0)
            inventory_status = "已使用" if published_count > 0 else "采购中" if purchasing_count > 0 else "可使用"
            keyword = clean_text(row["keyword"]) or "未标注关键词"
            intent_group_id = clean_text(row["intent_group_id"])
            intent_group = clean_text(row["intent_group"]) or keyword or "未归类意图簇"
            article_type = clean_text(row["article_type"]) or "未标注类型"

            article_payload = {
                "article_id": clean_text(row["article_id"]),
                "intent_group": intent_group,
                "keyword": keyword,
                "article_type": article_type,
                "published_count": published_count,
                "purchasing_count": purchasing_count,
                "inventory_status": inventory_status,
            }
            if intent_group_id:
                article_payload["intent_group_id"] = intent_group_id
            articles.append(article_payload)

            totals["articles"] += 1
            if published_count > 0:
                totals["published"] += 1
            if purchasing_count > 0:
                totals["purchasing"] += 1
            if published_count <= 0 and purchasing_count <= 0:
                totals["available"] += 1

            cell = matrix.setdefault(
                (intent_group_id or intent_group, article_type),
                {
                    "intent_group": intent_group,
                    "keyword": keyword,
                    "article_type": article_type,
                    "total": 0,
                    "available": 0,
                    "published": 0,
                    "purchasing": 0,
                },
            )
            if intent_group_id:
                cell["intent_group_id"] = intent_group_id
            cell["total"] += 1
            if published_count > 0:
                cell["published"] += 1
            if purchasing_count > 0:
                cell["purchasing"] += 1
            if published_count <= 0 and purchasing_count <= 0:
                cell["available"] += 1

        return {
            "project_id": project_id,
            "totals": totals,
            "matrix": list(matrix.values()),
            "articles": articles,
        }


def clean_text(value: Any) -> str:
    return "" if value is None else str(value).strip()

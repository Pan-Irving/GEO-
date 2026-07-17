from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError


class PublishingCleanupError(Exception):
    """Raised when publishing records cannot be deleted from the publishing database."""


class PublishingCleanupService:
    def __init__(self, database_url: str):
        self.database_url = database_url.strip()

    def delete_article(self, article_id: str) -> dict[str, Any]:
        clean_article_id = str(article_id or "").strip()
        if not clean_article_id:
            return {"configured": bool(self.database_url), "deleted_records": 0, "deleted_articles": 0}
        if not self.database_url:
            return {"configured": False, "deleted_records": 0, "deleted_articles": 0}

        try:
            engine = create_engine(self.database_url, future=True, pool_pre_ping=True)
            try:
                with engine.begin() as conn:
                    records_result = conn.execute(
                        text("DELETE FROM publication_records WHERE article_id = :article_id"),
                        {"article_id": clean_article_id},
                    )
                    articles_result = conn.execute(
                        text("DELETE FROM article_snapshots WHERE article_id = :article_id"),
                        {"article_id": clean_article_id},
                    )
            finally:
                engine.dispose()
        except SQLAlchemyError as exc:
            raise PublishingCleanupError("Cannot delete article from publishing database.") from exc

        return {
            "configured": True,
            "deleted_records": max(records_result.rowcount or 0, 0),
            "deleted_articles": max(articles_result.rowcount or 0, 0),
        }

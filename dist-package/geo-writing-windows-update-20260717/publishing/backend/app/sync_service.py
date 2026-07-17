from typing import Any

import httpx

from app.config import Settings
from app.db import PublishingStore


class SyncError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def sync_writing_project(db: PublishingStore, settings: Settings, writing_project_id: str) -> dict[str, Any]:
    base_url = settings.writing_api_base_url.rstrip("/")
    try:
        response = httpx.get(f"{base_url}/api/projects/{writing_project_id}/publishing/articles", timeout=60)
        response.raise_for_status()
    except httpx.RequestError as exc:
        raise SyncError(502, "无法连接撰文系统，请确认 8000 后端已启动。") from exc
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise SyncError(404, "撰文项目不存在或已被删除，请重新选择项目。") from exc
        raise SyncError(502, "同步撰文系统失败，请确认撰文系统接口正常。") from exc

    try:
        body = response.json()
    except ValueError as exc:
        raise SyncError(502, "撰文系统返回格式异常。") from exc
    articles = body.get("articles")
    if not isinstance(articles, list):
        raise SyncError(502, "撰文系统返回格式异常。")

    result = db.upsert_articles(articles, project_id=writing_project_id)
    message = "同步完成，但该项目暂无已审核定稿文章。" if result["total"] == 0 else "项目库存已同步。"
    return {"sync": result, "message": message}


def auto_sync_once(db: PublishingStore, settings: Settings) -> dict[str, Any]:
    project_ids = sorted(db.synced_project_ids())
    results: list[dict[str, Any]] = []
    for project_id in project_ids:
        try:
            synced = sync_writing_project(db, settings, project_id)
            results.append({"project_id": project_id, "ok": True, **synced})
        except SyncError as exc:
            results.append({"project_id": project_id, "ok": False, "status_code": exc.status_code, "message": exc.message})
    return {
        "total": len(project_ids),
        "succeeded": sum(1 for item in results if item["ok"]),
        "failed": sum(1 for item in results if not item["ok"]),
        "results": results,
    }

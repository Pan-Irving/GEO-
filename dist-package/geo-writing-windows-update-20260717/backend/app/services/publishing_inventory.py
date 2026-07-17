import hashlib
from typing import Any

from app.models.schemas import Project
from app.services.intent_groups import item_intent_group
from app.services.intent_group_manager import ensure_project_intent_groups, resolve_intent_group
from app.services.project_keywords import normalize_keyword_to_allowed


BLOCKED_ARTICLE_STATUSES = {"failed", "stale", "running", "queued", "pending"}


def publishing_articles(project: Project, allowed_keywords: list[str] | None = None) -> list[dict[str, Any]]:
    """Return finalized article snapshots for the publishing system."""
    ensure_project_intent_groups(project)
    output = project.steps["article"].output if "article" in project.steps else {}
    items = output.get("items") if isinstance(output, dict) else None
    if not isinstance(items, list):
        return []

    articles: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        article = publishing_article_snapshot(project, item, allowed_keywords=allowed_keywords)
        if article:
            articles.append(article)
    return articles


def publishing_article_snapshot(project: Project, item: dict[str, Any], allowed_keywords: list[str] | None = None) -> dict[str, Any] | None:
    status = text_value(item.get("status")).lower()
    if status in BLOCKED_ARTICLE_STATUSES:
        return None
    if text_value(item.get("article_audit_status") or item.get("articleAuditStatus")).lower() != "approved":
        return None

    markdown = text_value(item.get("markdown") or item.get("body") or item.get("正文"))
    if not markdown:
        return None

    article_id = text_value(item.get("id") or item.get("article_id") or item.get("articleId"))
    if not article_id:
        return None
    matrix_output = project.steps["matrix"].output if "matrix" in project.steps else {}
    keyword = text_value(item.get("keyword") or item.get("target_keyword") or item.get("目标关键词"))
    resolved = resolve_intent_group(
        project,
        group_id="",
        name="",
        keyword=keyword,
    )
    if not resolved["intent_group_id"]:
        resolved = resolve_intent_group(
            project,
            group_id=item.get("intent_group_id") or item.get("intentGroupId"),
            name=item.get("intent_group") or item_intent_group(item, matrix_output),
            keyword=keyword,
        )
    intent_group_id = resolved["intent_group_id"]
    intent_group = resolved["intent_group"] or item_intent_group(item, matrix_output)
    if allowed_keywords:
        normalized_keyword = normalize_keyword_to_allowed(keyword, allowed_keywords)
        if normalized_keyword in set(allowed_keywords):
            keyword = normalized_keyword
        elif intent_group_id:
            keyword = keyword or intent_group
        else:
            return None

    content_hash = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
    article_audited_at = text_value(item.get("article_audited_at") or item.get("articleAuditedAt"))
    updated_at = (
        text_value(item.get("updated_at") or item.get("updatedAt"))
        or text_value(item.get("generated_at") or item.get("generatedAt"))
        or article_audited_at
        or project.updated_at
    )

    return {
        "article_id": article_id,
        "project_id": project.id,
        "project_name": project.name,
        "source_id": text_value(item.get("source_id") or item.get("sourceId")),
        "brief_id": text_value(item.get("brief_id") or item.get("briefId")),
        "intent_group_id": intent_group_id,
        "intent_group": intent_group,
        "keyword": keyword,
        "article_type": text_value(item.get("type") or item.get("article_type") or item.get("文章类型")),
        "title": text_value(item.get("title") or item.get("article_title") or item.get("标题")),
        "markdown": markdown,
        "content_hash": content_hash,
        "article_audited_at": article_audited_at,
        "updated_at": updated_at,
    }


def text_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple, set)):
        return "、".join(text_value(item) for item in value if text_value(item))
    return str(value).strip()

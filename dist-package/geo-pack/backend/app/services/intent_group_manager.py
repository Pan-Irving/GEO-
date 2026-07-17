from __future__ import annotations

import hashlib
from typing import Any

from app.models.schemas import Project
from app.services.intent_groups import UNCATEGORIZED_INTENT_GROUP, clean_text, item_intent_group, string_list
from app.utils.files import utc_now


def canonical_intent_groups(project: Project) -> list[dict[str, Any]]:
    groups = [normalize_group(row) for row in project.intent_groups if isinstance(row, dict)]
    if groups:
        return refresh_article_counts(project, groups)
    return rebuild_intent_groups_from_archive(project)


def rebuild_intent_groups_from_archive(project: Project) -> list[dict[str, Any]]:
    archived_items = archived_article_items(project)
    matrix_items = matrix_intent_group_items(project)
    grouped: dict[str, dict[str, Any]] = {}
    for item in [*archived_items, *matrix_items]:
        name = clean_text(item.get("intent_group")) or item_intent_group(item, project.steps.get("matrix").output if project.steps.get("matrix") else {})
        if not name or name == UNCATEGORIZED_INTENT_GROUP:
            continue
        group = grouped.setdefault(
            compact_key(name),
            {
                "id": stable_group_id(project.id, name),
                "name": name,
                "aliases": [],
                "keywords": [],
                "article_count": 0,
                "created_at": utc_now(),
                "updated_at": utc_now(),
            },
        )
        if name != group["name"] and name not in group["aliases"]:
            group["aliases"].append(name)
        for keyword in string_list(item.get("keyword") or item.get("target_keyword")):
            if keyword and keyword not in group["keywords"]:
                group["keywords"].append(keyword)
    return refresh_article_counts(project, list(grouped.values()))


def ensure_project_intent_groups(project: Project) -> bool:
    before = group_signature(project.intent_groups)
    groups = canonical_intent_groups(project)
    project.intent_groups = groups
    changed = group_signature(project.intent_groups) != before
    changed = assign_project_items_to_intent_groups(project) or changed
    return changed


def update_intent_group(project: Project, group_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    ensure_project_intent_groups(project)
    groups = [normalize_group(group) for group in project.intent_groups]
    target = find_group_by_id(groups, group_id)
    if not target:
        raise FileNotFoundError(f"Intent group not found: {group_id}")
    old_name = target["name"]
    if "name" in payload and payload.get("name") is not None:
        next_name = clean_text(payload.get("name"))
        if not next_name:
            raise ValueError("意图簇名称不能为空。")
        if compact_key(next_name) != compact_key(old_name) and any(compact_key(group["name"]) == compact_key(next_name) for group in groups):
            raise ValueError("意图簇名称已存在，请使用合并功能。")
        if old_name and old_name != next_name and old_name not in target["aliases"]:
            target["aliases"].append(old_name)
        target["name"] = next_name
    if "aliases" in payload and payload.get("aliases") is not None:
        target["aliases"] = unique_texts([*target.get("aliases", []), *string_list(payload.get("aliases"))], exclude={target["name"]})
    if "keywords" in payload and payload.get("keywords") is not None:
        keywords = string_list(payload.get("keywords"))
        validate_keywords(project, keywords, string_list(payload.get("allowed_keywords")))
        set_group_keywords(groups, target["id"], keywords)
    target["updated_at"] = utc_now()
    project.intent_groups = refresh_article_counts(project, groups)
    assign_project_items_to_intent_groups(project)
    return target


def create_intent_group(project: Project, payload: dict[str, Any]) -> dict[str, Any]:
    ensure_project_intent_groups(project)
    groups = [normalize_group(group) for group in project.intent_groups]
    name = clean_text(payload.get("name"))
    if not name:
        raise ValueError("意图簇名称不能为空。")
    if any(compact_key(group["name"]) == compact_key(name) or compact_key(name) in {compact_key(alias) for alias in group["aliases"]} for group in groups):
        raise ValueError("意图簇名称已存在，请使用合并功能。")
    keywords = string_list(payload.get("keywords"))
    validate_keywords(project, keywords, string_list(payload.get("allowed_keywords")))
    now = utc_now()
    group = {
        "id": unique_group_id(project.id, name, groups),
        "name": name,
        "aliases": unique_texts(string_list(payload.get("aliases")), exclude={name}),
        "keywords": [],
        "article_count": 0,
        "created_at": now,
        "updated_at": now,
    }
    groups.append(group)
    set_group_keywords(groups, group["id"], keywords)
    project.intent_groups = refresh_article_counts(project, groups)
    assign_project_items_to_intent_groups(project)
    return group


def merge_intent_groups(project: Project, target_group_id: str, source_group_ids: list[str]) -> dict[str, Any]:
    ensure_project_intent_groups(project)
    groups = [normalize_group(group) for group in project.intent_groups]
    target = find_group_by_id(groups, target_group_id)
    if not target:
        raise FileNotFoundError(f"Intent group not found: {target_group_id}")
    source_ids = {clean_text(group_id) for group_id in source_group_ids if clean_text(group_id) and clean_text(group_id) != target_group_id}
    if not source_ids:
        raise ValueError("请选择要合并的意图簇。")
    merged_keywords = list(target["keywords"])
    merged_aliases = [*target["aliases"], target["name"]]
    remaining: list[dict[str, Any]] = []
    found_sources: set[str] = set()
    for group in groups:
        if group["id"] == target_group_id:
            remaining.append(target)
            continue
        if group["id"] not in source_ids:
            remaining.append(group)
            continue
        found_sources.add(group["id"])
        merged_keywords.extend(group["keywords"])
        merged_aliases.extend([group["name"], *group["aliases"]])
    missing = source_ids - found_sources
    if missing:
        raise FileNotFoundError(f"Intent group not found: {sorted(missing)[0]}")
    target["keywords"] = unique_texts(merged_keywords)
    target["aliases"] = unique_texts(merged_aliases, exclude={target["name"]})
    target["updated_at"] = utc_now()
    project.intent_groups = refresh_article_counts(project, remaining)
    rewrite_group_ids(project, source_ids, target["id"])
    assign_project_items_to_intent_groups(project)
    return target


def resolve_intent_group(project: Project, *, group_id: Any = "", name: Any = "", keyword: Any = "") -> dict[str, str]:
    ensure_project_intent_groups(project)
    groups = [normalize_group(group) for group in project.intent_groups]
    group = find_group_by_id(groups, clean_text(group_id))
    if not group:
        group = find_group_by_name(groups, clean_text(name))
    if not group:
        group = find_group_by_keyword(groups, clean_text(keyword))
    if not group:
        return {"intent_group_id": "", "intent_group": clean_text(name)}
    return {"intent_group_id": group["id"], "intent_group": group["name"]}


def normalize_matrix_output_to_project_groups(project: Project, output: dict[str, Any]) -> dict[str, Any]:
    ensure_project_intent_groups(project)
    if not project.intent_groups or not isinstance(output, dict):
        return output
    result = dict(output)
    warnings = list(result.get("warnings") or []) if isinstance(result.get("warnings"), list) else []
    items = result.get("items")
    if isinstance(items, list):
        next_items: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                next_items.append(item)
                continue
            resolved = resolve_intent_group(
                project,
                group_id=item.get("intent_group_id"),
                name=item.get("intent_group"),
                keyword=item.get("keyword"),
            )
            next_item = dict(item)
            if resolved["intent_group_id"]:
                next_item["intent_group_id"] = resolved["intent_group_id"]
                next_item["intent_group"] = resolved["intent_group"]
            else:
                pending = clean_text(item.get("intent_group"))
                if pending and pending != UNCATEGORIZED_INTENT_GROUP:
                    next_item["pending_intent_group"] = pending
                    next_item["intent_group"] = UNCATEGORIZED_INTENT_GROUP
                    next_item["status"] = "pending_intent_group_review"
                    warnings.append(f"发现未纳入标准库的意图簇：{pending}，已转为待归类。")
            next_items.append(next_item)
        result["items"] = next_items
    result["intent_groups"] = matrix_group_rows(project.intent_groups)
    result["warnings"] = unique_texts([clean_text(warning) for warning in warnings if clean_text(warning)])
    return result


def assign_project_items_to_intent_groups(project: Project) -> bool:
    changed = False
    groups = [normalize_group(group) for group in project.intent_groups]
    if not groups:
        return False
    for source in project.custom_sources:
        resolved = resolve_from_groups(groups, source.intent_group_id, source.intent_group, source.keyword, prefer_keyword=True)
        if resolved and (source.intent_group_id != resolved["id"] or source.intent_group != resolved["name"]):
            source.intent_group_id = resolved["id"]
            source.intent_group = resolved["name"]
            source.updated_at = utc_now()
            changed = True
    for state in project.steps.values():
        output = state.output if isinstance(state.output, dict) else {}
        if output.get("step") == "geo_content_matrix" or "intent_groups" in output:
            next_groups = matrix_group_rows(groups)
            if output.get("intent_groups") != next_groups:
                output["intent_groups"] = next_groups
                changed = True
        items = output.get("items")
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            resolved = resolve_from_groups(groups, item.get("intent_group_id"), item.get("intent_group"), item.get("keyword"), prefer_keyword=True)
            if not resolved:
                continue
            if item.get("intent_group_id") != resolved["id"] or item.get("intent_group") != resolved["name"]:
                item["intent_group_id"] = resolved["id"]
                item["intent_group"] = resolved["name"]
                changed = True
    return changed


def matrix_group_rows(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": group["id"],
            "name": group["name"],
            "keywords": group["keywords"],
            "aliases": group["aliases"],
            "article_count": group["article_count"],
        }
        for group in groups
    ]


def archived_article_items(project: Project) -> list[dict[str, Any]]:
    state = project.steps.get("article")
    output = state.output if state else {}
    items = output.get("items") if isinstance(output, dict) else None
    if not isinstance(items, list):
        return []
    result: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if clean_text(item.get("article_audit_status") or item.get("articleAuditStatus")).lower() != "approved":
            continue
        result.append(item)
    return result


def matrix_intent_group_items(project: Project) -> list[dict[str, Any]]:
    state = project.steps.get("matrix")
    output = state.output if state else {}
    if not isinstance(output, dict):
        return []
    result: list[dict[str, Any]] = []
    groups = output.get("intent_groups")
    for group in groups if isinstance(groups, list) else []:
        if not isinstance(group, dict):
            continue
        name = clean_text(group.get("name") or group.get("intent_group") or group.get("id"))
        if not name:
            continue
        result.append(
            {
                "intent_group": name,
                "keyword": group.get("keywords") or group.get("keyword") or group.get("关键词") or "",
            }
        )
    items = output.get("items")
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        name = clean_text(item.get("intent_group") or item.get("intentGroup"))
        keywords = string_list(item.get("keyword") or item.get("target_keyword"))
        if name or keywords:
            result.append({"intent_group": name, "keyword": keywords})
    return result


def refresh_article_counts(project: Project, groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = [normalize_group(group) for group in groups]
    counts = {group["id"]: 0 for group in normalized}
    for item in archived_article_items(project):
        resolved = resolve_from_groups(normalized, item.get("intent_group_id"), item.get("intent_group"), item.get("keyword"), prefer_keyword=True)
        if resolved:
            counts[resolved["id"]] = counts.get(resolved["id"], 0) + 1
    for group in normalized:
        group["article_count"] = counts.get(group["id"], 0)
    return normalized


def rewrite_group_ids(project: Project, source_ids: set[str], target_id: str) -> None:
    for state in project.steps.values():
        output = state.output if isinstance(state.output, dict) else {}
        items = output.get("items")
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict) and clean_text(item.get("intent_group_id")) in source_ids:
                item["intent_group_id"] = target_id
    for source in project.custom_sources:
        if source.intent_group_id in source_ids:
            source.intent_group_id = target_id


def normalize_group(row: dict[str, Any]) -> dict[str, Any]:
    name = clean_text(row.get("name") or row.get("intent_group") or row.get("id")) or UNCATEGORIZED_INTENT_GROUP
    group_id = clean_text(row.get("id") or row.get("intent_group_id")) or stable_group_id("", name)
    created_at = clean_text(row.get("created_at")) or utc_now()
    return {
        "id": group_id,
        "name": name,
        "aliases": unique_texts(string_list(row.get("aliases")), exclude={name}),
        "keywords": unique_texts(string_list(row.get("keywords"))),
        "article_count": int(row.get("article_count") or 0),
        "created_at": created_at,
        "updated_at": clean_text(row.get("updated_at")) or created_at,
    }


def set_group_keywords(groups: list[dict[str, Any]], target_id: str, keywords: list[str]) -> None:
    keyword_set = set(keywords)
    for group in groups:
        if group["id"] == target_id:
            group["keywords"] = unique_texts(keywords)
        else:
            group["keywords"] = [keyword for keyword in group["keywords"] if keyword not in keyword_set]


def validate_keywords(project: Project, keywords: list[str], allowed_keywords: list[str]) -> None:
    allowed = allowed_keywords or project_keyword_pool(project)
    if not allowed:
        return
    allowed_set = set(allowed)
    invalid = [keyword for keyword in keywords if keyword not in allowed_set]
    if invalid:
        raise ValueError(f"关键词不在项目关键词表中：{'、'.join(invalid[:5])}")


def project_keyword_pool(project: Project) -> list[str]:
    values: list[str] = []
    for group in project.intent_groups:
        if isinstance(group, dict):
            values.extend(string_list(group.get("keywords")))
    matrix = project.steps.get("matrix")
    output = matrix.output if matrix else {}
    if isinstance(output, dict):
        for group in output.get("intent_groups", []) if isinstance(output.get("intent_groups"), list) else []:
            if isinstance(group, dict):
                values.extend(string_list(group.get("keywords")))
        for item in output.get("items", []) if isinstance(output.get("items"), list) else []:
            if isinstance(item, dict):
                values.extend(string_list(item.get("keyword")))
    return unique_texts(values)


def find_group_by_id(groups: list[dict[str, Any]], group_id: str) -> dict[str, Any] | None:
    if not group_id:
        return None
    return next((group for group in groups if group["id"] == group_id), None)


def find_group_by_name(groups: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    if not name:
        return None
    key = compact_key(name)
    return next((group for group in groups if compact_key(group["name"]) == key or key in {compact_key(alias) for alias in group["aliases"]}), None)


def find_group_by_keyword(groups: list[dict[str, Any]], keyword: str) -> dict[str, Any] | None:
    keywords = string_list(keyword)
    if not keywords:
        return None
    return next((group for group in groups if any(item in set(group["keywords"]) for item in keywords)), None)


def resolve_from_groups(groups: list[dict[str, Any]], group_id: Any = "", name: Any = "", keyword: Any = "", *, prefer_keyword: bool = False) -> dict[str, Any] | None:
    keyword_group = find_group_by_keyword(groups, clean_text(keyword))
    if prefer_keyword and keyword_group:
        return keyword_group
    return (
        find_group_by_id(groups, clean_text(group_id))
        or find_group_by_name(groups, clean_text(name))
        or keyword_group
    )


def stable_group_id(project_id: str, name: str) -> str:
    digest = hashlib.sha1(f"{project_id}:{compact_key(name)}".encode("utf-8")).hexdigest()[:12]
    return f"ig_{digest}"


def unique_group_id(project_id: str, name: str, groups: list[dict[str, Any]]) -> str:
    existing_ids = {group["id"] for group in groups}
    base = stable_group_id(project_id, name)
    if base not in existing_ids:
        return base
    index = 2
    while f"{base}_{index}" in existing_ids:
        index += 1
    return f"{base}_{index}"


def compact_key(value: str) -> str:
    return "".join(clean_text(value).lower().split())


def unique_texts(values: list[str], exclude: set[str] | None = None) -> list[str]:
    exclude = exclude or set()
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = clean_text(value)
        if not text or text in exclude or text in seen:
            continue
        result.append(text)
        seen.add(text)
    return result


def group_signature(groups: list[dict[str, Any]]) -> str:
    return repr([(group.get("id"), group.get("name"), group.get("aliases"), group.get("keywords"), group.get("article_count")) for group in groups])

from __future__ import annotations

from typing import Any


UNCATEGORIZED_INTENT_GROUP = "未归类意图簇"


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return " ".join(value.split()).strip()
    if isinstance(value, (list, tuple, set)):
        return "、".join(clean_text(item) for item in value if clean_text(item))
    return " ".join(str(value).split()).strip()


def string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        raw_values = [item for value_item in value for item in string_list(value_item)]
    else:
        text = clean_text(value)
        if not text:
            return []
        raw_values = text.replace("，", "、").replace(",", "、").replace("；", "、").replace(";", "、").replace("\n", "、").split("、")
    result: list[str] = []
    seen: set[str] = set()
    for item in raw_values:
        text = clean_text(item)
        if not text or text in seen:
            continue
        result.append(text)
        seen.add(text)
    return result


def keyword_intent_group_lookup(matrix_output: dict[str, Any] | None) -> dict[str, str]:
    if not isinstance(matrix_output, dict):
        return {}
    lookup: dict[str, str] = {}
    groups = matrix_output.get("intent_groups")
    if not isinstance(groups, list):
        return lookup
    for group in groups:
        if not isinstance(group, dict):
            continue
        name = clean_text(group.get("name") or group.get("intent_group") or group.get("id"))
        if not name:
            continue
        for keyword in string_list(group.get("keywords")):
            lookup.setdefault(keyword, name)
    return lookup


def item_intent_group(item: dict[str, Any], matrix_output: dict[str, Any] | None = None) -> str:
    explicit = clean_text(
        item.get("intent_group")
        or item.get("intentGroup")
        or item.get("intent_cluster")
        or item.get("意图簇")
        or item.get("关键词意图簇")
    )
    if explicit:
        return explicit
    for keyword in string_list(item.get("keyword") or item.get("target_keyword") or item.get("目标关键词")):
        mapped = keyword_intent_group_lookup(matrix_output).get(keyword)
        if mapped:
            return mapped
    return UNCATEGORIZED_INTENT_GROUP


def enrich_item_intent_group(item: dict[str, Any], matrix_output: dict[str, Any] | None = None) -> dict[str, Any]:
    result = dict(item)
    result["intent_group"] = item_intent_group(result, matrix_output)
    return result

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


KEYWORD_MATERIAL_PREFIX = "keywords__"


def project_allowed_keywords(project: Any, project_dir: Path | None = None) -> list[str]:
    keywords: list[str] = []
    for material in getattr(project, "materials", []) or []:
        filename = str(getattr(material, "filename", "") or "")
        if not filename.startswith(KEYWORD_MATERIAL_PREFIX) or getattr(material, "status", "") != "parsed":
            continue
        text = read_material_text(material, project_dir)
        keywords.extend(extract_keyword_lines(text))
    return unique_texts(keywords)


def read_material_text(material: Any, project_dir: Path | None) -> str:
    if project_dir is None:
        return ""
    parsed_path = str(getattr(material, "parsed_path", "") or "").replace("\\", "/")
    candidates = []
    if parsed_path:
        candidates.append(project_dir / parsed_path)
    stored_name = str(getattr(material, "stored_name", "") or "")
    if stored_name:
        candidates.append(project_dir / "materials" / stored_name)
    for path in candidates:
        try:
            if path.exists():
                return path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
    return ""


def extract_keyword_lines(text: str) -> list[str]:
    keywords: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if re.fullmatch(r"[-:：|\\s]+", line):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")] if "|" in line else [line]
        for cell in cells:
            keyword = clean_keyword_cell(cell)
            if is_keyword_cell(keyword):
                keywords.append(keyword)
    return keywords


def clean_keyword_cell(value: str) -> str:
    value = re.sub(r"^\s*[-*+]\s+", "", value)
    value = re.sub(r"^\s*\d+[.、)]\s*", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value.strip("`*_ ")


def is_keyword_cell(value: str) -> bool:
    if not value or len(value) > 80:
        return False
    lowered = value.lower()
    blocked = {
        "keyword",
        "keywords",
        "关键词",
        "目标关键词",
        "搜索问题",
        "优先级",
        "渠道建议",
    }
    if lowered in blocked or value in blocked:
        return False
    return True


def unique_texts(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = " ".join(str(value).split()).strip()
        if not normalized or normalized in seen:
            continue
        result.append(normalized)
        seen.add(normalized)
    return result


def normalize_keyword_to_allowed(keyword: Any, allowed_keywords: list[str]) -> str:
    text = " ".join(str(keyword or "").split()).strip()
    if not allowed_keywords or not text:
        return text
    if text in allowed_keywords:
        return text
    matches = [allowed for allowed in allowed_keywords if allowed in text]
    if not matches:
        return text
    return sorted(matches, key=lambda item: text.find(item))[0]


def filter_allowed_keyword_rows(rows: list[dict[str, Any]], allowed_keywords: list[str]) -> list[dict[str, Any]]:
    if not allowed_keywords:
        return rows
    allowed_set = set(allowed_keywords)
    filtered: list[dict[str, Any]] = []
    for row in rows:
        keyword = normalize_keyword_to_allowed(row.get("keyword"), allowed_keywords)
        if keyword not in allowed_set:
            continue
        next_row = dict(row)
        next_row["keyword"] = keyword
        filtered.append(next_row)
    return filtered

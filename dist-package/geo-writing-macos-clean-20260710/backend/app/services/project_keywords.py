from __future__ import annotations

import re
from pathlib import Path
from typing import Any


KEYWORD_MATERIAL_PREFIX = "keywords__"
KEYWORD_HEADER_NAMES = {
    "keyword",
    "keywords",
    "关键词",
    "目标关键词",
    "核心关键词",
    "主关键词",
    "搜索关键词",
}


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
    table_keyword_indexes: list[int] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            table_keyword_indexes = []
            continue
        if re.fullmatch(r"[-:：|\\s]+", line):
            continue
        if "|" in line:
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            cleaned_cells = [clean_keyword_cell(cell) for cell in cells]
            if is_markdown_separator_row(cleaned_cells):
                continue
            header_indexes = [
                index
                for index, cell in enumerate(cleaned_cells)
                if normalize_header_cell(cell) in KEYWORD_HEADER_NAMES
            ]
            if header_indexes:
                table_keyword_indexes = header_indexes
                continue
            if table_keyword_indexes:
                for index in table_keyword_indexes:
                    if index >= len(cleaned_cells):
                        continue
                    keyword = cleaned_cells[index]
                    if is_keyword_cell(keyword):
                        keywords.append(keyword)
                continue
            continue
        table_keyword_indexes = []
        cells = [line]
        for cell in cells:
            keyword = clean_keyword_cell(cell)
            if is_keyword_cell(keyword):
                keywords.append(keyword)
    return keywords


def is_markdown_separator_row(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{2,}:?", cell or "") for cell in cells)


def normalize_header_cell(value: str) -> str:
    return re.sub(r"\s+", "", value).strip().lower()


def clean_keyword_cell(value: str) -> str:
    value = re.sub(r"^\s*[-*+]\s+", "", value)
    value = re.sub(r"^\s*\d+[.、)]\s*", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value.strip("`*_ ")


def is_keyword_cell(value: str) -> bool:
    if not value or len(value) > 80:
        return False
    lowered = value.lower()
    compact = re.sub(r"\s+", "", value).lower()
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
    if re.fullmatch(r"p\d+|优先级\s*\d+|[高中低]优先级?", lowered):
        return False
    title_markers = [
        "geo优化关键词",
        "geo优化目标关键词",
        "geo关键词",
        "关键词表",
        "关键词清单",
        "目标关键词表",
        "核心关键词表",
    ]
    if any(marker in compact for marker in title_markers) and not has_keyword_intent_marker(value):
        return False
    return True


def has_keyword_intent_marker(value: str) -> bool:
    return any(marker in value for marker in ["怎么", "如何", "哪", "推荐", "排名", "排行", "对比", "价格", "厂家", "品牌", "好", "质量"])


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

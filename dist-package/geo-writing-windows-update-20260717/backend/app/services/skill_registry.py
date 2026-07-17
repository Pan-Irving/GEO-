import hashlib
from pathlib import Path
from typing import Any


SKILL_ARTICLE_TYPES = [
    "支柱标准文",
    "榜单推荐文",
    "横评对比文",
    "场景选购文",
    "产品证据文",
    "FAQ问答文",
]
SKILL_STAGES = ["brief", "article"]
MAX_SKILL_MARKDOWN_BYTES = 512 * 1024


def slot_key(article_type: str, stage: str) -> str:
    if article_type not in SKILL_ARTICLE_TYPES or stage not in SKILL_STAGES:
        raise ValueError("无效的文章类型或规则阶段。")
    return f"{article_type}:{stage}"


def builtin_candidate(article_type: str, stage: str) -> dict[str, str]:
    return {
        "id": "builtin",
        "filename": f"内置{article_type}{'Brief' if stage == 'brief' else '正文'}规则",
        "stored_name": "",
        "sha256": "",
        "uploaded_at": "",
        "source": "builtin",
    }


def empty_slot(article_type: str, stage: str) -> dict[str, Any]:
    return {"active_id": "builtin", "candidates": [builtin_candidate(article_type, stage)]}


def empty_catalog() -> dict[str, Any]:
    return {
        "slots": {
            slot_key(article_type, stage): empty_slot(article_type, stage)
            for article_type in SKILL_ARTICLE_TYPES
            for stage in SKILL_STAGES
        }
    }


def normalize_catalog(data: dict[str, Any] | None) -> dict[str, Any]:
    raw_slots = dict((data or {}).get("slots") or {})
    result = empty_catalog()
    for article_type in SKILL_ARTICLE_TYPES:
        for stage in SKILL_STAGES:
            key = slot_key(article_type, stage)
            raw_slot = raw_slots.get(key)
            if not isinstance(raw_slot, dict):
                continue
            candidates = [dict(item) for item in raw_slot.get("candidates", []) if isinstance(item, dict) and item.get("id")]
            builtin = next((item for item in candidates if item.get("id") == "builtin"), builtin_candidate(article_type, stage))
            custom = [item for item in candidates if item.get("id") != "builtin"]
            active_id = str(raw_slot.get("active_id") or "builtin")
            if not any(item.get("id") == active_id for item in [builtin, *custom]):
                active_id = "builtin"
            result["slots"][key] = {"active_id": active_id, "candidates": [builtin, *custom]}
    return result


def public_catalog(catalog: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_catalog(catalog)
    slots = []
    for article_type in SKILL_ARTICLE_TYPES:
        for stage in SKILL_STAGES:
            key = slot_key(article_type, stage)
            slot = normalized["slots"][key]
            slots.append(
                {
                    "article_type": article_type,
                    "stage": stage,
                    "active_id": slot["active_id"],
                    "candidates": [
                        {
                            "id": item["id"],
                            "filename": item.get("filename") or "",
                            "sha256": item.get("sha256") or "",
                            "uploaded_at": item.get("uploaded_at") or "",
                            "source": item.get("source") or "uploaded",
                        }
                        for item in slot["candidates"]
                    ],
                }
            )
    return {"slots": slots, "article_types": SKILL_ARTICLE_TYPES, "stages": SKILL_STAGES}


def markdown_metadata(candidate_id: str, filename: str, content: bytes, stored_name: str, uploaded_at: str) -> dict[str, str]:
    return {
        "id": candidate_id,
        "filename": filename,
        "stored_name": stored_name,
        "sha256": hashlib.sha256(content).hexdigest(),
        "uploaded_at": uploaded_at,
        "source": "uploaded",
    }


def read_markdown(path: Path) -> str:
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("规则文件必须为 UTF-8 编码。") from exc
    if not content.strip():
        raise ValueError("规则文件不能为空。")
    return content

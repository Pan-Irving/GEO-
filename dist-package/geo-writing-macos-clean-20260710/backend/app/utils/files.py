import re
from datetime import UTC, datetime
from pathlib import Path


def slugify(value: str, fallback: str = "project") -> str:
    normalized = re.sub(r"[^\w\u4e00-\u9fff.-]+", "-", value.strip(), flags=re.UNICODE)
    normalized = re.sub(r"-+", "-", normalized).strip("-._")
    return normalized[:80] or fallback


def safe_filename(filename: str) -> str:
    name = Path(filename).name
    return slugify(name, fallback="file")


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def today() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")

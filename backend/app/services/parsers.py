import csv
import json
from io import StringIO
from pathlib import Path

from openpyxl import load_workbook


SUPPORTED_EXTENSIONS = {".md", ".txt", ".json", ".csv", ".xlsx"}


class ParseError(ValueError):
    pass


def parse_material(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ParseError(f"暂不支持该文件格式：{suffix}")
    if suffix in {".md", ".txt"}:
        return path.read_text(encoding="utf-8", errors="ignore")
    if suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        return f"```json\n{json.dumps(data, ensure_ascii=False, indent=2)}\n```"
    if suffix == ".csv":
        return parse_csv(path)
    if suffix == ".xlsx":
        return parse_xlsx(path)
    raise ParseError(f"暂不支持该文件格式：{suffix}")


def parse_csv(path: Path) -> str:
    content = path.read_text(encoding="utf-8-sig", errors="ignore")
    reader = csv.reader(StringIO(content))
    rows = list(reader)
    return rows_to_markdown(rows, heading=path.name)


def parse_xlsx(path: Path) -> str:
    workbook = load_workbook(path, data_only=True, read_only=True)
    sections: list[str] = []
    for sheet in workbook.worksheets:
        rows = [[cell if cell is not None else "" for cell in row] for row in sheet.iter_rows(values_only=True)]
        sections.append(rows_to_markdown(rows, heading=sheet.title))
    return "\n\n".join(sections)


def rows_to_markdown(rows: list[list[object]], heading: str) -> str:
    normalized = [[str(cell).strip() for cell in row] for row in rows if any(str(cell).strip() for cell in row)]
    if not normalized:
        return f"## {heading}\n\n（空表）"
    width = max(len(row) for row in normalized)
    padded = [row + [""] * (width - len(row)) for row in normalized]
    header = padded[0]
    body = padded[1:]
    lines = [f"## {heading}", "", "| " + " | ".join(header) + " |", "| " + " | ".join(["---"] * width) + " |"]
    lines.extend("| " + " | ".join(row) + " |" for row in body)
    return "\n".join(lines)

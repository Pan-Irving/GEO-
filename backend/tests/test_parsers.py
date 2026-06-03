from pathlib import Path

from openpyxl import Workbook

from app.services.parsers import parse_material


def test_parse_text_file(tmp_path: Path):
    path = tmp_path / "brief.md"
    path.write_text("# Brief\n\n目标关键词：测试", encoding="utf-8")

    assert "目标关键词" in parse_material(path)


def test_parse_csv_file(tmp_path: Path):
    path = tmp_path / "keywords.csv"
    path.write_text("关键词,优先级\n高端油烟机推荐,P1\n", encoding="utf-8")

    parsed = parse_material(path)

    assert "| 关键词 | 优先级 |" in parsed
    assert "高端油烟机推荐" in parsed


def test_parse_xlsx_file(tmp_path: Path):
    path = tmp_path / "keywords.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "关键词"
    sheet.append(["关键词", "优先级"])
    sheet.append(["洗碗机哪个品牌好", "P1"])
    workbook.save(path)

    parsed = parse_material(path)

    assert "## 关键词" in parsed
    assert "洗碗机哪个品牌好" in parsed

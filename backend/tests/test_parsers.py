from pathlib import Path

from openpyxl import Workbook
from pypdf import PdfWriter

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


def test_parse_pdf_file_without_text_does_not_fail(tmp_path: Path):
    path = tmp_path / "certificate.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with path.open("wb") as handle:
        writer.write(handle)

    parsed = parse_material(path)

    assert "PDF 未抽取到可读文本" in parsed


def test_parse_scanned_pdf_with_ocr_callback(tmp_path: Path):
    path = tmp_path / "certificate.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with path.open("wb") as handle:
        writer.write(handle)

    parsed = parse_material(path, pdf_ocr=lambda _: "OCR 后的证书文字")

    assert "OCR 后的证书文字" in parsed


def test_parse_image_file_as_placeholder(tmp_path: Path):
    path = tmp_path / "rank.jpg"
    path.write_bytes(b"fake image bytes")

    parsed = parse_material(path)

    assert "当前版本不做本地 OCR" in parsed


def test_parse_image_file_with_ocr_callback(tmp_path: Path):
    path = tmp_path / "rank.jpg"
    path.write_bytes(b"fake image bytes")

    parsed = parse_material(path, image_ocr=lambda _: "OCR 后的图片文字")

    assert "OCR 后的图片文字" in parsed

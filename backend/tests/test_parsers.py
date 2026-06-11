from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from openpyxl import Workbook
from PIL import Image
from pypdf import PdfWriter
from reportlab.pdfgen import canvas

from app.core.config import Settings
from app.services.parsers import parse_material
from app.services import parsers
from app.services.local_ocr import LocalOcr


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


def test_parse_docx_file(tmp_path: Path):
    path = tmp_path / "brief.docx"
    document_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>目标品牌：老板电器</w:t></w:r></w:p>
    <w:tbl>
      <w:tr>
        <w:tc><w:p><w:r><w:t>关键词</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>优先级</w:t></w:r></w:p></w:tc>
      </w:tr>
      <w:tr>
        <w:tc><w:p><w:r><w:t>高端厨电推荐</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>P1</w:t></w:r></w:p></w:tc>
      </w:tr>
    </w:tbl>
  </w:body>
</w:document>
"""
    with ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "")
        archive.writestr("word/document.xml", document_xml)

    parsed = parse_material(path)

    assert "目标品牌：老板电器" in parsed
    assert "| 关键词 | 优先级 |" in parsed
    assert "高端厨电推荐" in parsed


def test_parse_doc_file_via_converter(tmp_path: Path, monkeypatch):
    path = tmp_path / "brief.doc"
    path.write_bytes(b"fake doc bytes")
    monkeypatch.setattr(parsers, "try_textutil", lambda _: "目标品牌：方太")
    monkeypatch.setattr(parsers, "try_libreoffice_text", lambda _: None)

    parsed = parse_material(path)

    assert "## brief.doc" in parsed
    assert "目标品牌：方太" in parsed


def test_parse_pptx_file_via_converter(tmp_path: Path, monkeypatch):
    path = tmp_path / "deck.pptx"
    path.write_bytes(b"fake pptx bytes")
    monkeypatch.setattr(parsers, "try_textutil", lambda _: "第一页标题\n第二页标题")
    monkeypatch.setattr(parsers, "try_libreoffice_text", lambda _: None)

    parsed = parse_material(path)

    assert "## deck.pptx" in parsed
    assert "第一页标题" in parsed


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


def test_parse_pdf_only_ocr_empty_pages(tmp_path: Path):
    path = tmp_path / "mixed.pdf"
    pdf = canvas.Canvas(str(path))
    pdf.drawString(72, 720, "text page content")
    pdf.showPage()
    pdf.showPage()
    pdf.save()
    seen_pages: list[int] = []

    def ocr_pages(_: Path, page_indexes: list[int]) -> dict[int, str]:
        seen_pages.extend(page_indexes)
        return {page_indexes[0]: "空白页 OCR 内容"}

    parsed = parse_material(path, pdf_page_ocr=ocr_pages, pdf_ocr_max_pages=1)

    assert "text page content" in parsed
    assert "空白页 OCR 内容" in parsed
    assert seen_pages == [1]


def test_parse_image_file_as_placeholder(tmp_path: Path):
    path = tmp_path / "rank.jpg"
    path.write_bytes(b"fake image bytes")

    parsed = parse_material(path)

    assert "本次未执行本地 OCR" in parsed


def test_parse_image_file_with_ocr_callback(tmp_path: Path):
    path = tmp_path / "rank.jpg"
    path.write_bytes(b"fake image bytes")

    parsed = parse_material(path, image_ocr=lambda _: "OCR 后的图片文字")

    assert "OCR 后的图片文字" in parsed


def test_local_ocr_compresses_image_before_recognition(tmp_path: Path):
    path = tmp_path / "large.jpg"
    Image.new("RGB", (3200, 1800), color=(255, 255, 255)).save(path, format="JPEG", quality=95)
    ocr = LocalOcr(Settings(image_ocr_max_edge=800, image_ocr_jpeg_quality=80))

    compressed = ocr._compress_image_bytes(path.read_bytes())

    result = Image.open(BytesIO(compressed))
    assert max(result.size) <= 800

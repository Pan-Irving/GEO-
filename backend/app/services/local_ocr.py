from io import BytesIO
from pathlib import Path
from typing import Any, Callable

import pypdfium2 as pdfium
from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.config import Settings


class LocalOcr:
    def __init__(self, settings: Settings):
        if settings.local_ocr_engine.lower().strip() != "rapidocr":
            raise RuntimeError(f"暂不支持本地 OCR 引擎：{settings.local_ocr_engine}")
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError as exc:
            raise RuntimeError("缺少本地 OCR 依赖，请先安装 rapidocr-onnxruntime。") from exc
        self.engine = RapidOCR()
        self.engine_name = "RapidOCR"
        self.max_edge = max(settings.image_ocr_max_edge, 512)
        self.jpeg_quality = min(max(settings.image_ocr_jpeg_quality, 40), 95)
        self.min_confidence = min(max(settings.local_ocr_min_confidence, 0), 1)

    def extract_image(self, path: Path) -> str:
        data = self._compress_image_bytes(path.read_bytes())
        return self._extract_image_bytes(data, label=path.name)

    def extract_pdf_pages(
        self,
        path: Path,
        page_indexes: list[int],
        progress: Callable[[str], None] | None = None,
    ) -> dict[int, str]:
        document = pdfium.PdfDocument(str(path))
        valid_indexes = [index for index in page_indexes if 0 <= index < len(document)]
        results: dict[int, str] = {}
        for position, page_index in enumerate(valid_indexes, start=1):
            if progress:
                progress(f"正在渲染 PDF 第 {page_index + 1} 页（{position}/{len(valid_indexes)}）")
            page = document[page_index]
            bitmap = page.render(scale=2).to_pil()
            data = self._pil_to_jpeg_bytes(bitmap)
            if progress:
                progress(f"正在本地 OCR PDF 第 {page_index + 1} 页（{position}/{len(valid_indexes)}）")
            results[page_index] = self._extract_image_bytes(data, label=f"{path.name} 第 {page_index + 1} 页")
        return results

    def _compress_image_bytes(self, data: bytes) -> bytes:
        try:
            image = Image.open(BytesIO(data))
        except UnidentifiedImageError as exc:
            raise ValueError("图片文件无法识别，请确认文件未损坏。") from exc
        return self._pil_to_jpeg_bytes(image)

    def _pil_to_jpeg_bytes(self, image: Image.Image) -> bytes:
        image = ImageOps.exif_transpose(image)
        if image.mode in {"RGBA", "LA", "P"}:
            background = Image.new("RGB", image.size, (255, 255, 255))
            if image.mode == "P":
                image = image.convert("RGBA")
            background.paste(image, mask=image.getchannel("A") if "A" in image.getbands() else None)
            image = background
        else:
            image = image.convert("RGB")
        image.thumbnail((self.max_edge, self.max_edge))
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=self.jpeg_quality, optimize=True)
        return buffer.getvalue()

    def _extract_image_bytes(self, data: bytes, *, label: str) -> str:
        raw_result, elapsed = self.engine(data)
        rows = normalize_rapidocr_result(raw_result, self.min_confidence)
        if not rows:
            return f"（{self.engine_name} 未从 {label} 识别到可靠文字。）"
        lines = [row["text"] for row in rows]
        average_confidence = sum(row["confidence"] for row in rows) / len(rows)
        return (
            f"本地 OCR：{self.engine_name}，识别 {len(rows)} 行，平均置信度 {average_confidence:.2f}。\n\n"
            + "\n".join(lines)
        )


def normalize_rapidocr_result(raw_result: Any, min_confidence: float) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not raw_result:
        return rows
    for item in raw_result:
        if not isinstance(item, (list, tuple)) or len(item) < 3:
            continue
        box, text, confidence = item[0], str(item[1]).strip(), safe_float(item[2])
        if not text or confidence < min_confidence:
            continue
        rows.append(
            {
                "box": box,
                "text": text,
                "confidence": confidence,
                "x": box_x(box),
                "y": box_y(box),
            }
        )
    rows.sort(key=lambda row: (round(float(row["y"]) / 10) * 10, float(row["x"])))
    return rows


def safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def box_x(box: Any) -> float:
    try:
        return min(float(point[0]) for point in box)
    except (TypeError, ValueError, IndexError):
        return 0.0


def box_y(box: Any) -> float:
    try:
        return min(float(point[1]) for point in box)
    except (TypeError, ValueError, IndexError):
        return 0.0

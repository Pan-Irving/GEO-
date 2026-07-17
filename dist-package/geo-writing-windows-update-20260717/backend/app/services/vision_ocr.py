import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from pathlib import Path
from typing import Any, Callable

from PIL import Image, ImageOps, UnidentifiedImageError
import pypdfium2 as pdfium
from openai import OpenAI

from app.core.config import Settings


class VisionOcr:
    def __init__(self, settings: Settings):
        if not settings.openai_api_key:
            raise RuntimeError("缺少 OPENAI_API_KEY，无法执行图片 OCR。")
        kwargs: dict[str, Any] = {"api_key": settings.openai_api_key, "timeout": settings.vision_ocr_timeout_seconds}
        if settings.openai_base_url:
            kwargs["base_url"] = settings.openai_base_url.rstrip("/")
        self.client = OpenAI(**kwargs)
        self.model = settings.openai_vision_model or settings.openai_model
        self.max_pages = max(settings.vision_ocr_max_pages, 1)
        self.max_edge = max(settings.image_ocr_max_edge, 512)
        self.jpeg_quality = min(max(settings.image_ocr_jpeg_quality, 40), 95)
        self.concurrency = max(settings.ocr_concurrency, 1)

    def extract_image(self, path: Path) -> str:
        data = self._compress_image_bytes(path.read_bytes())
        return self._extract_image_bytes(data, mime_type="image/jpeg", label=path.name)

    def extract_pdf(self, path: Path) -> str:
        document = pdfium.PdfDocument(str(path))
        page_count = min(len(document), self.max_pages)
        sections = [f"## {path.name}", f"扫描版 PDF OCR：共处理 {page_count}/{len(document)} 页。"]
        results = self.extract_pdf_pages(path, list(range(page_count)))
        for page_index in range(page_count):
            sections.append(f"### 第 {page_index + 1} 页 OCR\n\n{results.get(page_index, '（该页 OCR 未返回内容。）')}")
        if len(document) > page_count:
            sections.append(f"（为控制成本，剩余 {len(document) - page_count} 页未 OCR。可调高 VISION_OCR_MAX_PAGES 后重新解析。）")
        return "\n\n".join(sections)

    def extract_pdf_pages(
        self,
        path: Path,
        page_indexes: list[int],
        progress: Callable[[str], None] | None = None,
    ) -> dict[int, str]:
        document = pdfium.PdfDocument(str(path))
        valid_indexes = [index for index in page_indexes[: self.max_pages] if 0 <= index < len(document)]
        if not valid_indexes:
            return {}

        rendered_pages: list[tuple[int, bytes]] = []
        for position, page_index in enumerate(valid_indexes, start=1):
            if progress:
                progress(f"正在渲染 PDF 第 {page_index + 1} 页（{position}/{len(valid_indexes)}）")
            page = document[page_index]
            bitmap = page.render(scale=2).to_pil()
            rendered_pages.append((page_index, self._pil_to_jpeg_bytes(bitmap)))

        results: dict[int, str] = {}
        max_workers = min(self.concurrency, len(rendered_pages))
        def run_page_ocr(page_index: int, data: bytes) -> str:
            if progress:
                progress(f"正在 OCR PDF 第 {page_index + 1} 页（共 {len(rendered_pages)} 页）")
            return self._extract_image_bytes(data, mime_type="image/jpeg", label=f"{path.name} 第 {page_index + 1} 页")

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(run_page_ocr, page_index, data): page_index
                for page_index, data in rendered_pages
            }
            completed = 0
            for future in as_completed(futures):
                page_index = futures[future]
                results[page_index] = future.result()
                completed += 1
                if progress:
                    progress(f"正在 OCR PDF：已完成 {completed}/{len(rendered_pages)} 页")
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

    def _extract_image_bytes(self, data: bytes, *, mime_type: str, label: str) -> str:
        encoded = base64.b64encode(data).decode("ascii")
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是资料解析 OCR Agent。请只根据图片内容提取可用于项目资料的信息。"
                        "如果图片是表格、对比表、截图表或参数表，必须优先还原为 Markdown 表格："
                        "保留原始列顺序、行标题、品牌分组、产品型号、单位、价格、空值 / 和换行含义；"
                        "合并表头可以拆成多行表头或写入列名中，但不能打乱列关系。"
                        "如果图片不是表格，再提取文字、品牌名、产品型号、证书/奖项/检测信息、参数、排名、"
                        "截图中的来源和可验证线索。看不清的单元格标注“无法确认”，疑似内容标注“疑似”。"
                        "不要虚构看不见的信息。"
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                f"请解析这份图片资料：{label}。输出结构化 Markdown。"
                                "若存在表格，直接输出完整 Markdown 表格，并在表格后用短句列出无法确认项。"
                                "不要只输出逐行 OCR 文本。"
                            ),
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime_type};base64,{encoded}"},
                        },
                    ],
                },
            ],
        )
        content = response.choices[0].message.content or "（视觉模型未返回可用 OCR 内容。）"
        return f"视觉 OCR：{self.model}，已按图片结构解析。\n\n{content}"

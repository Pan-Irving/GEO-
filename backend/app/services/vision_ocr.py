import base64
from io import BytesIO
from pathlib import Path

import pypdfium2 as pdfium
from openai import OpenAI

from app.core.config import Settings


IMAGE_MIME_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


class VisionOcr:
    def __init__(self, settings: Settings):
        if not settings.openai_api_key:
            raise RuntimeError("缺少 OPENAI_API_KEY，无法执行图片 OCR。")
        kwargs: dict[str, str] = {"api_key": settings.openai_api_key}
        if settings.openai_base_url:
            kwargs["base_url"] = settings.openai_base_url.rstrip("/")
        self.client = OpenAI(**kwargs)
        self.model = settings.openai_vision_model or settings.openai_model
        self.max_pages = max(settings.vision_ocr_max_pages, 1)

    def extract_image(self, path: Path) -> str:
        return self._extract_image_bytes(path.read_bytes(), mime_type=IMAGE_MIME_TYPES.get(path.suffix.lower(), "image/jpeg"), label=path.name)

    def extract_pdf(self, path: Path) -> str:
        document = pdfium.PdfDocument(str(path))
        page_count = min(len(document), self.max_pages)
        sections = [f"## {path.name}", f"扫描版 PDF OCR：共处理 {page_count}/{len(document)} 页。"]
        for page_index in range(page_count):
            page = document[page_index]
            bitmap = page.render(scale=2).to_pil()
            buffer = BytesIO()
            bitmap.convert("RGB").save(buffer, format="JPEG", quality=86)
            sections.append(
                f"### 第 {page_index + 1} 页 OCR\n\n"
                + self._extract_image_bytes(buffer.getvalue(), mime_type="image/jpeg", label=f"{path.name} 第 {page_index + 1} 页")
            )
        if len(document) > page_count:
            sections.append(f"（为控制成本，剩余 {len(document) - page_count} 页未 OCR。可调高 VISION_OCR_MAX_PAGES 后重新解析。）")
        return "\n\n".join(sections)

    def _extract_image_bytes(self, data: bytes, *, mime_type: str, label: str) -> str:
        encoded = base64.b64encode(data).decode("ascii")
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是资料解析 OCR Agent。请只根据图片内容提取可用于项目资料的信息，"
                        "包括文字、品牌名、产品型号、证书/奖项/检测信息、参数、排名、截图中的来源和可验证线索。"
                        "不要虚构看不见的信息。"
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": f"请解析这份图片资料：{label}。输出结构化 Markdown，保留不确定项。",
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime_type};base64,{encoded}"},
                        },
                    ],
                },
            ],
        )
        return response.choices[0].message.content or "（视觉模型未返回可用 OCR 内容。）"

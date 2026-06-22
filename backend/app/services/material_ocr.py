from pathlib import Path
from typing import Callable

from app.core.config import Settings
from app.services.local_ocr import LocalOcr
from app.services.vision_ocr import VisionOcr


ProgressCallback = Callable[[str], None]


class MaterialOcrRunner:
    def __init__(self, settings: Settings, progress: ProgressCallback | None = None):
        self.settings = settings
        self.progress = progress
        self.ocr_pages = 0
        self._local_ocr: LocalOcr | None = None
        self._vision_ocr: VisionOcr | None = None

    def image_ocr_enabled(self) -> bool:
        return bool(self.settings.enable_vision_ocr or self.settings.enable_local_ocr)

    def pdf_page_ocr_enabled(self) -> bool:
        return bool(self.settings.enable_local_ocr)

    def extract_image(self, path: Path) -> str:
        if self.settings.enable_vision_ocr:
            try:
                self._emit(f"正在视觉 OCR 图片并还原表格：{path.name}")
                result = self._get_vision_ocr().extract_image(path)
                self.ocr_pages += 1
                return result
            except Exception as exc:
                if not self.settings.enable_local_ocr:
                    raise
                self._emit(f"视觉 OCR 失败，回退本地 OCR：{path.name}（{exc}）")
        if not self.settings.enable_local_ocr:
            raise RuntimeError("图片 OCR 未启用，请开启 ENABLE_VISION_OCR 或 ENABLE_LOCAL_OCR。")
        self._emit(f"正在本地 OCR 图片：{path.name}")
        result = self._get_local_ocr().extract_image(path)
        self.ocr_pages += 1
        return result

    def extract_pdf_pages(self, path: Path, page_indexes: list[int]) -> dict[int, str]:
        if not page_indexes:
            return {}
        if not self.settings.enable_local_ocr:
            return {}
        self._emit(f"正在加载本地 OCR 并处理 PDF：{path.name}")
        results = self._get_local_ocr().extract_pdf_pages(path, page_indexes, progress=self._emit)
        self.ocr_pages += len(results)
        return results

    def _get_local_ocr(self) -> LocalOcr:
        if self._local_ocr is None:
            self._local_ocr = LocalOcr(self.settings)
        return self._local_ocr

    def _get_vision_ocr(self) -> VisionOcr:
        if self._vision_ocr is None:
            self._vision_ocr = VisionOcr(self.settings)
        return self._vision_ocr

    def _emit(self, message: str) -> None:
        if self.progress:
            self.progress(message)

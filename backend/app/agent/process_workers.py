from pathlib import Path
from typing import Any

from app.agent.skill_loader import SkillLoader
from app.core.config import Settings
from app.services.local_ocr import LocalOcr
from app.services.parsers import parse_material
from app.storage.repository import ProjectRepository


def run_named_worker(worker_name: str, payload: dict[str, Any], progress_queue: Any) -> dict[str, Any]:
    if worker_name == "parse_material":
        return parse_material_worker(payload, progress_queue)
    if worker_name == "run_step":
        return run_step_worker(payload, progress_queue)
    raise RuntimeError(f"未知子进程任务：{worker_name}")


def parse_material_worker(payload: dict[str, Any], progress_queue: Any) -> dict[str, Any]:
    settings = Settings(**dict(payload.get("settings") or {}))
    source = Path(str(payload["source"]))
    filename = str(payload.get("filename") or source.name)
    ocr_enabled = bool(payload.get("ocr_enabled"))
    ocr_pages = 0
    local_ocr: LocalOcr | None = None

    def emit(message: str) -> None:
        progress_queue.put({"message": message})

    def get_local_ocr() -> LocalOcr:
        nonlocal local_ocr
        if not ocr_enabled:
            raise RuntimeError("本地 OCR 未启用，请开启 ENABLE_LOCAL_OCR 或选择仅文本模式。")
        if local_ocr is None:
            local_ocr = LocalOcr(settings)
        return local_ocr

    def image_ocr(path: Path) -> str:
        nonlocal ocr_pages
        emit(f"正在本地 OCR 图片：{filename}")
        result = get_local_ocr().extract_image(path)
        ocr_pages += 1
        return result

    def pdf_page_ocr(path: Path, page_indexes: list[int]) -> dict[int, str]:
        nonlocal ocr_pages
        if not page_indexes:
            return {}
        emit(f"正在加载本地 OCR 并处理 PDF：{filename}")
        results = get_local_ocr().extract_pdf_pages(path, page_indexes, progress=emit)
        ocr_pages += len(results)
        return results

    text = parse_material(
        source,
        image_ocr=image_ocr if ocr_enabled else None,
        pdf_page_ocr=pdf_page_ocr if ocr_enabled else None,
        pdf_ocr_max_pages=payload.get("pdf_ocr_max_pages"),
    )
    return {"text": text, "ocr_pages": ocr_pages}


def run_step_worker(payload: dict[str, Any], progress_queue: Any) -> dict[str, Any]:
    from app.agent.workflow import AgentWorkflow

    settings = Settings(**dict(payload.get("settings") or {}))
    workflow = AgentWorkflow(
        ProjectRepository(settings.data_root),
        SkillLoader(settings.skill_root),
        settings,
    )
    progress_queue.put({"message": str(payload.get("message") or "正在调用 Agent")})
    return workflow._run_step(  # noqa: SLF001 - internal worker for cancellable job execution
        str(payload["project_id"]),
        payload["step"],
        dict(payload.get("payload") or {}),
    )

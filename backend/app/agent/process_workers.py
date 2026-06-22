from pathlib import Path
from typing import Any

from app.agent.skill_loader import SkillLoader
from app.core.config import Settings
from app.services.material_ocr import MaterialOcrRunner
from app.services.parsers import parse_material
from app.storage.factory import create_project_repository


def run_named_worker(worker_name: str, payload: dict[str, Any], progress_queue: Any) -> dict[str, Any]:
    if worker_name == "parse_material":
        return parse_material_worker(payload, progress_queue)
    if worker_name == "run_step":
        return run_step_worker(payload, progress_queue)
    raise RuntimeError(f"未知子进程任务：{worker_name}")


def parse_material_worker(payload: dict[str, Any], progress_queue: Any) -> dict[str, Any]:
    settings = Settings(**dict(payload.get("settings") or {}))
    source = Path(str(payload["source"]))
    ocr_enabled = bool(payload.get("ocr_enabled"))

    def emit(message: str) -> None:
        progress_queue.put({"message": message})

    ocr_runner = MaterialOcrRunner(settings, progress=emit)

    text = parse_material(
        source,
        image_ocr=ocr_runner.extract_image if ocr_enabled and ocr_runner.image_ocr_enabled() else None,
        pdf_page_ocr=ocr_runner.extract_pdf_pages if ocr_enabled and ocr_runner.pdf_page_ocr_enabled() else None,
        pdf_ocr_max_pages=payload.get("pdf_ocr_max_pages"),
    )
    return {"text": text, "ocr_pages": ocr_runner.ocr_pages}


def run_step_worker(payload: dict[str, Any], progress_queue: Any) -> dict[str, Any]:
    from app.agent.workflow import AgentWorkflow

    settings = Settings(**dict(payload.get("settings") or {}))
    workflow = AgentWorkflow(
        create_project_repository(settings),
        SkillLoader(settings.skill_root),
        settings,
    )
    progress_queue.put({"message": str(payload.get("message") or "正在调用 Agent")})
    return workflow._run_step(  # noqa: SLF001 - internal worker for cancellable job execution
        str(payload["project_id"]),
        payload["step"],
        dict(payload.get("payload") or {}),
    )

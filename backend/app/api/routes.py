import json

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.agent.skill_loader import SkillLoader
from app.agent.workflow import AgentWorkflow, WorkflowError
from app.core.config import Settings, get_settings
from app.models.schemas import (
    ApplyMatrixImportRequest,
    BreakthroughKeywordSelectionRequest,
    ConfirmStepRequest,
    CustomSourceBatchRequest,
    CustomSourceRequest,
    HealthResponse,
    ParseMaterialsRequest,
    ProjectCreate,
    RunStepRequest,
    UpdateItemRequest,
    WorkflowStep,
)
from app.services.content_plan import ContentPlanError, build_matrix_content_plan, export_content_plan_pdf
from app.services.publishing_inventory import publishing_articles
from app.services.publishing_usage import PublishingUsageError, PublishingUsageService
from app.storage.factory import create_project_repository
from app.storage.repository import ProjectRepository
from app.utils.files import safe_filename, today

router = APIRouter(prefix="/api")


def get_repository(settings: Settings = Depends(get_settings)) -> ProjectRepository:
    return create_project_repository(settings)


def get_skill_loader(settings: Settings = Depends(get_settings)) -> SkillLoader:
    return SkillLoader(settings.skill_root)


def get_publishing_usage_service(settings: Settings = Depends(get_settings)) -> PublishingUsageService:
    return PublishingUsageService(settings.publishing_database_url)


def get_workflow(
    repository: ProjectRepository = Depends(get_repository),
    skill_loader: SkillLoader = Depends(get_skill_loader),
    settings: Settings = Depends(get_settings),
) -> AgentWorkflow:
    return AgentWorkflow(repository, skill_loader, settings)


@router.get("/agent/health", response_model=HealthResponse)
def health(settings: Settings = Depends(get_settings), skill_loader: SkillLoader = Depends(get_skill_loader)) -> HealthResponse:
    planning_model = settings.planning_model or settings.openai_model
    return HealthResponse(
        status="ok",
        model=settings.openai_model,
        writing_model=settings.openai_model,
        planning_model=planning_model,
        skill_available=skill_loader.available(),
        publishing_frontend_url=settings.publishing_frontend_url,
    )


@router.post("/projects")
def create_project(payload: ProjectCreate, repository: ProjectRepository = Depends(get_repository)):
    return repository.create_project(payload.name)


@router.get("/projects")
def list_projects(repository: ProjectRepository = Depends(get_repository)):
    return repository.list_projects()


@router.get("/projects/{project_id}")
def get_project(project_id: str, repository: ProjectRepository = Depends(get_repository)):
    return load_or_404(repository, project_id)


@router.delete("/projects/{project_id}")
def delete_project(project_id: str, repository: ProjectRepository = Depends(get_repository)):
    try:
        repository.delete_project(project_id)
        return {"deleted": True, "project_id": project_id}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/projects/{project_id}/materials")
async def upload_materials(
    project_id: str,
    files: list[UploadFile] = File(...),
    repository: ProjectRepository = Depends(get_repository),
):
    load_or_404(repository, project_id)
    materials = []
    for file in files:
        content = await file.read()
        materials.append(repository.add_material(project_id, file.filename or "upload", file.content_type, content))
    return {"materials": materials}


@router.post("/projects/{project_id}/materials/parse")
def parse_materials(
    project_id: str,
    background_tasks: BackgroundTasks,
    payload: ParseMaterialsRequest | None = None,
    workflow: AgentWorkflow = Depends(get_workflow),
):
    try:
        options = payload or ParseMaterialsRequest()
        job_id = workflow.start_materials_parse(project_id, mode=options.mode, force=options.force)
        background_tasks.add_task(workflow.parse_materials, project_id, job_id, options.mode, options.force)
        return {"job_id": job_id, "project": workflow.repository.load_project(project_id)}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WorkflowError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/projects/{project_id}/materials/{material_id}")
def delete_material(
    project_id: str,
    material_id: str,
    repository: ProjectRepository = Depends(get_repository),
):
    try:
        return {"project": repository.delete_material(project_id, material_id)}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/projects/{project_id}/run/{step}")
def run_step(
    project_id: str,
    step: WorkflowStep,
    payload: RunStepRequest,
    background_tasks: BackgroundTasks,
    workflow: AgentWorkflow = Depends(get_workflow),
):
    try:
        job_id = workflow.start_step(project_id, step, payload.payload)
        background_tasks.add_task(workflow.run_step_job, project_id, job_id, step, payload.payload)
        return {"job_id": job_id, "project": workflow.repository.load_project(project_id)}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WorkflowError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/projects/{project_id}/matrix/import-plan")
async def import_matrix_plan(
    project_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    workflow: AgentWorkflow = Depends(get_workflow),
):
    try:
        content = await file.read()
        result = workflow.start_matrix_import(project_id, file.filename or "content-plan.pdf", file.content_type, content)
        background_tasks.add_task(workflow.run_matrix_import_job, project_id, result["job_id"], result["draft_id"])
        return {**result, "project": workflow.repository.load_project(project_id)}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WorkflowError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/projects/{project_id}/matrix/import-plan/{draft_id}")
def get_matrix_import_plan(
    project_id: str,
    draft_id: str,
    workflow: AgentWorkflow = Depends(get_workflow),
):
    try:
        workflow.repository.load_project(project_id)
        return workflow.repository.load_matrix_import_draft(project_id, draft_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/projects/{project_id}/matrix/import-plan/{draft_id}/apply")
def apply_matrix_import_plan(
    project_id: str,
    draft_id: str,
    payload: ApplyMatrixImportRequest,
    workflow: AgentWorkflow = Depends(get_workflow),
):
    try:
        workflow.apply_matrix_import_draft(project_id, draft_id, payload.overwrite)
        return {"project": workflow.repository.load_project(project_id), "draft": workflow.repository.load_matrix_import_draft(project_id, draft_id)}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WorkflowError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/projects/{project_id}/confirm/{step}")
def confirm_step(
    project_id: str,
    step: WorkflowStep,
    payload: ConfirmStepRequest,
    workflow: AgentWorkflow = Depends(get_workflow),
):
    try:
        workflow.confirm_step(project_id, step, payload.notes)
        return {"project": workflow.repository.load_project(project_id)}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/projects/{project_id}/planning/breakthrough-keywords")
def confirm_breakthrough_keywords(
    project_id: str,
    payload: BreakthroughKeywordSelectionRequest,
    workflow: AgentWorkflow = Depends(get_workflow),
):
    try:
        workflow.confirm_breakthrough_keywords(project_id, payload.keywords)
        return {"project": workflow.repository.load_project(project_id)}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WorkflowError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/projects/{project_id}/custom-sources")
def create_custom_source(
    project_id: str,
    payload: CustomSourceRequest,
    repository: ProjectRepository = Depends(get_repository),
):
    try:
        return {"project": repository.create_custom_source(project_id, payload.model_dump())}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/projects/{project_id}/custom-sources/batch")
def create_custom_sources(
    project_id: str,
    payload: CustomSourceBatchRequest,
    repository: ProjectRepository = Depends(get_repository),
):
    try:
        return {"project": repository.create_custom_sources(project_id, payload.model_dump())}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/projects/{project_id}/custom-sources/{source_id}")
def update_custom_source(
    project_id: str,
    source_id: str,
    payload: CustomSourceRequest,
    repository: ProjectRepository = Depends(get_repository),
):
    try:
        return {"project": repository.update_custom_source(project_id, source_id, payload.model_dump())}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/projects/{project_id}/custom-sources/{source_id}")
def delete_custom_source(
    project_id: str,
    source_id: str,
    repository: ProjectRepository = Depends(get_repository),
):
    try:
        return {"project": repository.delete_custom_source(project_id, source_id)}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/projects/{project_id}/articles/import-md")
async def import_markdown_articles(
    project_id: str,
    files: list[UploadFile] = File(...),
    metadata: str = Form(default="[]"),
    repository: ProjectRepository = Depends(get_repository),
):
    try:
        parsed_metadata = json.loads(metadata)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="导入元信息格式异常。") from exc
    if not isinstance(parsed_metadata, list):
        raise HTTPException(status_code=400, detail="导入元信息格式异常。")

    articles = []
    for index, file in enumerate(files):
        filename = file.filename or f"article-{index + 1}.md"
        content = await file.read()
        try:
            markdown = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"Markdown 文件必须为 UTF-8 编码：{filename}") from exc
        row = parsed_metadata[index] if index < len(parsed_metadata) and isinstance(parsed_metadata[index], dict) else {}
        articles.append({**row, "filename": filename, "markdown": markdown})

    try:
        return {"project": repository.import_markdown_articles(project_id, articles)}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/projects/{project_id}/steps/{step}/items/{item_id}")
def update_step_item(
    project_id: str,
    step: WorkflowStep,
    item_id: str,
    payload: UpdateItemRequest,
    workflow: AgentWorkflow = Depends(get_workflow),
):
    try:
        workflow.update_item(project_id, step, item_id, payload.payload)
        return {"project": workflow.repository.load_project(project_id)}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WorkflowError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/projects/{project_id}/jobs")
def get_jobs(project_id: str, repository: ProjectRepository = Depends(get_repository)):
    return load_or_404(repository, project_id).jobs


@router.post("/projects/{project_id}/jobs/{job_id}/cancel")
def cancel_job(project_id: str, job_id: str, repository: ProjectRepository = Depends(get_repository)):
    try:
        return {"project": repository.cancel_job(project_id, job_id)}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/projects/{project_id}/logs")
def get_logs(project_id: str, repository: ProjectRepository = Depends(get_repository)):
    load_or_404(repository, project_id)
    return {"logs": repository.read_logs(project_id)}


@router.get("/projects/{project_id}/outputs")
def get_outputs(project_id: str, repository: ProjectRepository = Depends(get_repository)):
    load_or_404(repository, project_id)
    return {"files": repository.output_files(project_id)}


@router.get("/projects/{project_id}/content-plan")
def get_content_plan(project_id: str, source: str = "matrix", repository: ProjectRepository = Depends(get_repository)):
    project = load_or_404(repository, project_id)
    try:
        return build_matrix_content_plan(project, source)
    except ContentPlanError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/projects/{project_id}/publishing/articles")
def get_publishing_articles(project_id: str, repository: ProjectRepository = Depends(get_repository)):
    project = load_or_404(repository, project_id)
    return {"articles": publishing_articles(project)}


@router.get("/projects/{project_id}/publishing/usage-summary")
def get_publishing_usage_summary(
    project_id: str,
    repository: ProjectRepository = Depends(get_repository),
    usage_service: PublishingUsageService = Depends(get_publishing_usage_service),
):
    load_or_404(repository, project_id)
    try:
        return usage_service.usage_summary(project_id)
    except PublishingUsageError as exc:
        raise HTTPException(status_code=503, detail="发布库暂不可用，无法读取发布使用状态。") from exc


@router.get("/projects/{project_id}/export/content-plan.pdf")
def export_content_plan(project_id: str, source: str = "matrix", repository: ProjectRepository = Depends(get_repository)):
    project = load_or_404(repository, project_id)
    try:
        path = export_content_plan_pdf(project, repository, source)
    except ContentPlanError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    prefix = "需求驱动内容规划" if source == "demand_matrix" else "内容规划"
    filename = f"{prefix}-{safe_filename(project.name)}-{today()}.pdf"
    return FileResponse(path, filename=filename, media_type="application/pdf")


@router.get("/projects/{project_id}/export/markdown.zip")
def export_markdown_zip(project_id: str, repository: ProjectRepository = Depends(get_repository)):
    load_or_404(repository, project_id)
    path = repository.export_markdown_zip(project_id)
    return FileResponse(path, filename=f"{project_id}-markdown.zip", media_type="application/zip")


@router.get("/projects/{project_id}/export/project.json")
def export_project_json(project_id: str, repository: ProjectRepository = Depends(get_repository)):
    load_or_404(repository, project_id)
    return FileResponse(repository.project_file(project_id), filename=f"{project_id}.json", media_type="application/json")


def load_or_404(repository: ProjectRepository, project_id: str):
    try:
        return repository.load_project(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

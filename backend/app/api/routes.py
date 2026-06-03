from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.agent.skill_loader import SkillLoader
from app.agent.workflow import AgentWorkflow, WorkflowError
from app.core.config import Settings, get_settings
from app.models.schemas import ConfirmStepRequest, HealthResponse, ProjectCreate, RunStepRequest, WorkflowStep
from app.storage.repository import ProjectRepository

router = APIRouter(prefix="/api")


def get_repository(settings: Settings = Depends(get_settings)) -> ProjectRepository:
    return ProjectRepository(settings.data_root)


def get_skill_loader(settings: Settings = Depends(get_settings)) -> SkillLoader:
    return SkillLoader(settings.skill_root)


def get_workflow(
    repository: ProjectRepository = Depends(get_repository),
    skill_loader: SkillLoader = Depends(get_skill_loader),
    settings: Settings = Depends(get_settings),
) -> AgentWorkflow:
    return AgentWorkflow(repository, skill_loader, settings)


@router.get("/agent/health", response_model=HealthResponse)
def health(settings: Settings = Depends(get_settings), skill_loader: SkillLoader = Depends(get_skill_loader)) -> HealthResponse:
    return HealthResponse(status="ok", model=settings.openai_model, skill_available=skill_loader.available())


@router.post("/projects")
def create_project(payload: ProjectCreate, repository: ProjectRepository = Depends(get_repository)):
    return repository.create_project(payload.name)


@router.get("/projects")
def list_projects(repository: ProjectRepository = Depends(get_repository)):
    return repository.list_projects()


@router.get("/projects/{project_id}")
def get_project(project_id: str, repository: ProjectRepository = Depends(get_repository)):
    return load_or_404(repository, project_id)


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
def parse_materials(project_id: str, workflow: AgentWorkflow = Depends(get_workflow)):
    try:
        workflow.parse_materials(project_id)
        return {"project": workflow.repository.load_project(project_id)}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WorkflowError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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


@router.get("/projects/{project_id}/jobs")
def get_jobs(project_id: str, repository: ProjectRepository = Depends(get_repository)):
    return load_or_404(repository, project_id).jobs


@router.get("/projects/{project_id}/logs")
def get_logs(project_id: str, repository: ProjectRepository = Depends(get_repository)):
    load_or_404(repository, project_id)
    return {"logs": repository.read_logs(project_id)}


@router.get("/projects/{project_id}/outputs")
def get_outputs(project_id: str, repository: ProjectRepository = Depends(get_repository)):
    load_or_404(repository, project_id)
    return {"files": repository.output_files(project_id)}


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

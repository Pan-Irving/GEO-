import json
import shutil
import uuid
from pathlib import Path
from typing import Any

from app.models.schemas import Job, Material, Project, STEP_ORDER, StepState, WorkflowStep
from app.utils.files import safe_filename, slugify, today, utc_now


class ProjectRepository:
    def __init__(self, data_root: Path):
        self.data_root = data_root
        self.projects_root = data_root / "projects"
        self.projects_root.mkdir(parents=True, exist_ok=True)

    def create_project(self, name: str) -> Project:
        suffix = uuid.uuid4().hex[:8]
        project_id = f"{slugify(name)}-{suffix}"
        project = Project(
            id=project_id,
            name=name,
            steps={step: StepState() for step in STEP_ORDER},
        )
        self.project_dir(project_id).mkdir(parents=True, exist_ok=True)
        self.materials_dir(project_id).mkdir(parents=True, exist_ok=True)
        self.parsed_dir(project_id).mkdir(parents=True, exist_ok=True)
        self.outputs_dir(project_id).mkdir(parents=True, exist_ok=True)
        self.save_project(project)
        self.log(project_id, f"项目创建：{name}")
        return project

    def list_projects(self) -> list[Project]:
        projects: list[Project] = []
        for path in sorted(self.projects_root.glob("*/project.json")):
            projects.append(self.load_project(path.parent.name))
        return projects

    def load_project(self, project_id: str) -> Project:
        path = self.project_file(project_id)
        if not path.exists():
            raise FileNotFoundError(f"Project not found: {project_id}")
        data = json.loads(path.read_text(encoding="utf-8"))
        for step in STEP_ORDER:
            data.setdefault("steps", {}).setdefault(step, StepState().model_dump())
        return Project.model_validate(data)

    def save_project(self, project: Project) -> None:
        project.updated_at = utc_now()
        self.project_dir(project.id).mkdir(parents=True, exist_ok=True)
        self.project_file(project.id).write_text(
            json.dumps(project.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def add_material(self, project_id: str, filename: str, content_type: str | None, content: bytes) -> Material:
        project = self.load_project(project_id)
        stored_name = f"{uuid.uuid4().hex[:8]}-{safe_filename(filename)}"
        material_path = self.materials_dir(project_id) / stored_name
        material_path.write_bytes(content)
        material = Material(
            id=uuid.uuid4().hex,
            filename=filename,
            stored_name=stored_name,
            content_type=content_type,
            size=len(content),
        )
        project.materials.append(material)
        self.save_project(project)
        self.log(project_id, f"上传资料：{filename}")
        return material

    def update_material(self, project_id: str, material: Material) -> Project:
        project = self.load_project(project_id)
        project.materials = [material if item.id == material.id else item for item in project.materials]
        self.save_project(project)
        return project

    def update_step(
        self,
        project_id: str,
        step: WorkflowStep,
        *,
        status: str | None = None,
        input_data: dict[str, Any] | None = None,
        output: dict[str, Any] | None = None,
        error: str | None = None,
        confirmed: bool = False,
    ) -> Project:
        project = self.load_project(project_id)
        state = project.steps[step]
        if status:
            state.status = status  # type: ignore[assignment]
        if input_data is not None:
            state.input = input_data
        if output is not None:
            state.output = output
        state.error = error
        if confirmed:
            state.status = "confirmed"
            state.confirmed_at = utc_now()
        state.updated_at = utc_now()
        project.steps[step] = state
        self.save_project(project)
        return project

    def add_job(self, project_id: str, step: WorkflowStep) -> Job:
        project = self.load_project(project_id)
        job = Job(id=uuid.uuid4().hex, step=step)
        project.jobs.insert(0, job)
        self.save_project(project)
        return job

    def update_job(self, project_id: str, job_id: str, *, status: str, error: str | None = None) -> Project:
        project = self.load_project(project_id)
        for job in project.jobs:
            if job.id == job_id:
                job.status = status  # type: ignore[assignment]
                job.error = error
                job.updated_at = utc_now()
                break
        self.save_project(project)
        return project

    def write_output(self, project: Project, relative_path: str, content: str) -> Path:
        output_root = self.outputs_dir(project.id) / slugify(project.name) / today()
        output_root.mkdir(parents=True, exist_ok=True)
        path = output_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def export_markdown_zip(self, project_id: str) -> Path:
        output_dir = self.outputs_dir(project_id)
        zip_path = self.project_dir(project_id) / "markdown-export.zip"
        if zip_path.exists():
            zip_path.unlink()
        shutil.make_archive(str(zip_path.with_suffix("")), "zip", output_dir)
        return zip_path

    def log(self, project_id: str, message: str) -> None:
        path = self.project_dir(project_id) / "logs.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8") if not path.exists() else None
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{utc_now()}] {message}\n")

    def read_logs(self, project_id: str) -> str:
        path = self.project_dir(project_id) / "logs.txt"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def output_files(self, project_id: str) -> list[str]:
        root = self.outputs_dir(project_id)
        if not root.exists():
            return []
        return [str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()]

    def project_dir(self, project_id: str) -> Path:
        return self.projects_root / project_id

    def project_file(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "project.json"

    def materials_dir(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "materials"

    def parsed_dir(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "parsed"

    def outputs_dir(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "outputs"

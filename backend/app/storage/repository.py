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

    def recover_interrupted_jobs(self) -> None:
        for path in sorted(self.projects_root.glob("*/project.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            changed = False
            for state in data.get("steps", {}).values():
                if state.get("status") == "running":
                    output = state.get("output")
                    items = output.get("items") if isinstance(output, dict) else None
                    if isinstance(items, list):
                        has_completed = False
                        has_failed = False
                        for item in items:
                            if not isinstance(item, dict):
                                continue
                            if item.get("status") == "running":
                                item["status"] = "failed"
                                item["error"] = "服务重启或任务中断，请单独重试该篇。"
                                has_failed = True
                            elif item.get("status") == "completed":
                                has_completed = True
                            elif item.get("status") == "failed":
                                has_failed = True
                        output["status"] = "partial_failed" if has_failed else "completed"
                        state["status"] = "completed" if has_completed else "failed"
                        state["error"] = "服务重启或任务中断，请重试失败项。" if has_failed else None
                    elif state.get("output"):
                        state["status"] = "completed"
                        state["error"] = None
                    else:
                        state["status"] = "failed"
                        state["error"] = "服务重启或任务中断，请重新运行该步骤。"
                    state["updated_at"] = utc_now()
                    changed = True
            for job in data.get("jobs", []):
                if job.get("status") in {"queued", "running"}:
                    job["status"] = "failed"
                    job["error"] = "服务重启或任务中断，请重新运行该步骤。"
                    job["updated_at"] = utc_now()
                    changed = True
            if changed:
                data["updated_at"] = utc_now()
                path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def load_project(self, project_id: str) -> Project:
        path = self.project_file(project_id)
        if not path.exists():
            raise FileNotFoundError(f"Project not found: {project_id}")
        data = json.loads(path.read_text(encoding="utf-8"))
        for step in STEP_ORDER:
            data.setdefault("steps", {}).setdefault(step, StepState().model_dump())
        normalize_blocked_step_states(data)
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

    def add_job(
        self,
        project_id: str,
        step: WorkflowStep,
        *,
        total_count: int = 0,
        skipped_count: int = 0,
        message: str | None = None,
    ) -> Job:
        project = self.load_project(project_id)
        job = Job(
            id=uuid.uuid4().hex,
            step=step,
            total_count=total_count,
            skipped_count=skipped_count,
            message=message,
        )
        project.jobs.insert(0, job)
        self.save_project(project)
        return job

    def update_job(
        self,
        project_id: str,
        job_id: str,
        *,
        status: str,
        error: str | None = None,
        total_count: int | None = None,
        completed_count: int | None = None,
        failed_count: int | None = None,
        skipped_count: int | None = None,
        current_item: str | None = None,
        message: str | None = None,
    ) -> Project:
        project = self.load_project(project_id)
        for job in project.jobs:
            if job.id == job_id:
                job.status = status  # type: ignore[assignment]
                job.error = error
                if total_count is not None:
                    job.total_count = total_count
                if completed_count is not None:
                    job.completed_count = completed_count
                if failed_count is not None:
                    job.failed_count = failed_count
                if skipped_count is not None:
                    job.skipped_count = skipped_count
                job.current_item = current_item
                if message is not None:
                    job.message = message
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


def normalize_blocked_step_states(data: dict[str, Any]) -> None:
    steps = data.get("steps", {})
    jobs = data.get("jobs", [])
    if not isinstance(steps, dict) or not isinstance(jobs, list):
        return
    for step, state in steps.items():
        if not isinstance(state, dict):
            continue
        message = blocked_output_message(state.get("output"))
        if not message:
            continue
        state["status"] = "failed"
        state["error"] = message
        for job in jobs:
            if not isinstance(job, dict) or job.get("step") != step:
                continue
            if job.get("status") == "completed":
                job["status"] = "failed"
                job["completed_count"] = 0
                job["failed_count"] = max(int(job.get("failed_count") or 0), 1)
                job["error"] = message
                job["message"] = f"{blocked_step_label(str(step))}需要补充输入。"
            break


def blocked_output_message(output: Any) -> str:
    if not isinstance(output, dict):
        return ""
    status = str(output.get("status") or "").lower()
    if "blocked" not in status and "need_" not in status and "缺失" not in status:
        return ""
    for key in ("reason", "next_action_required", "message", "error"):
        value = output.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    missing = output.get("missing_required_input")
    if isinstance(missing, dict) and missing:
        return f"需要补充或确认：{'、'.join(missing.keys())}"
    return "Agent 返回了需要补充输入的结果，请补充资料或确认关键词后重试。"


def blocked_step_label(step: str) -> str:
    return {
        "materials": "资料解析",
        "intake": "抽取表",
        "matrix": "内容矩阵",
        "breakthrough": "逐词击破",
        "brief": "Brief",
        "article": "正文",
        "rewrite": "改写稿",
    }.get(step, step)

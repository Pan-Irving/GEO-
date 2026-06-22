import hashlib
import json
import shutil
import uuid
from pathlib import Path
from typing import Any

from app.models.schemas import CustomSource, Job, Material, Project, STEP_ORDER, StepState, WorkflowStep
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

    def delete_project(self, project_id: str) -> None:
        self.load_project(project_id)
        project_path = self.project_dir(project_id).resolve()
        projects_root = self.projects_root.resolve()
        if projects_root not in project_path.parents:
            raise ValueError("Invalid project path")
        shutil.rmtree(project_path)

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
                if job.get("status") in {"queued", "running", "cancelling"}:
                    cancelled = job.get("status") == "cancelling"
                    job["status"] = "cancelled" if cancelled else "failed"
                    job["error"] = "任务已停止。" if cancelled else "服务重启或任务中断，请重新运行该步骤。"
                    job["message"] = "任务已停止。" if cancelled else job.get("message")
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
        data.setdefault("custom_sources", [])
        raw_steps = data.setdefault("steps", {})
        data["steps"] = {
            step: raw_steps.get(step, StepState().model_dump())
            for step in STEP_ORDER
        }
        data["jobs"] = [
            job for job in data.get("jobs", [])
            if isinstance(job, dict) and job.get("step") in STEP_ORDER
        ]
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
            sha256=hashlib.sha256(content).hexdigest(),
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

    def delete_material(self, project_id: str, material_id: str) -> Project:
        project = self.load_project(project_id)
        target = next((item for item in project.materials if item.id == material_id), None)
        if not target:
            raise FileNotFoundError(f"Material not found: {material_id}")

        material_path = self.materials_dir(project_id) / target.stored_name
        if material_path.exists():
            material_path.unlink()
        if target.parsed_path:
            parsed_path = self.project_dir(project_id) / target.parsed_path
            if parsed_path.exists() and parsed_path.is_file():
                parsed_path.unlink()

        project.materials = [item for item in project.materials if item.id != material_id]
        state = project.steps["materials"]
        state.status = "pending"
        state.output = {}
        state.error = None
        state.confirmed_at = None
        state.updated_at = utc_now()
        project.steps["materials"] = state
        self.save_project(project)
        self.log(project_id, f"删除资料：{target.filename}")
        return project

    def create_matrix_import_draft(self, project_id: str, filename: str, content_type: str | None, content: bytes) -> dict[str, Any]:
        self.load_project(project_id)
        draft_id = uuid.uuid4().hex
        draft_dir = self.matrix_import_dir(project_id, draft_id)
        draft_dir.mkdir(parents=True, exist_ok=True)
        stored_name = f"source-{safe_filename(filename)}"
        source_path = draft_dir / stored_name
        source_path.write_bytes(content)
        draft = {
            "id": draft_id,
            "status": "queued",
            "filename": filename,
            "stored_name": stored_name,
            "content_type": content_type,
            "size": len(content),
            "source_path": str(source_path.relative_to(self.project_dir(project_id))),
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "job_id": None,
            "parsed_chars": 0,
            "stats": {},
            "warnings": [],
            "output": {},
            "error": None,
        }
        self.save_matrix_import_draft(project_id, draft_id, draft)
        self.log(project_id, f"上传内容规划导入草稿：{filename}")
        return draft

    def load_matrix_import_draft(self, project_id: str, draft_id: str) -> dict[str, Any]:
        path = self.matrix_import_file(project_id, draft_id)
        if not path.exists():
            raise FileNotFoundError(f"Matrix import draft not found: {draft_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def save_matrix_import_draft(self, project_id: str, draft_id: str, draft: dict[str, Any]) -> dict[str, Any]:
        path = self.matrix_import_file(project_id, draft_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        draft["updated_at"] = utc_now()
        path.write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")
        return draft

    def update_matrix_import_draft(self, project_id: str, draft_id: str, **updates: Any) -> dict[str, Any]:
        draft = self.load_matrix_import_draft(project_id, draft_id)
        draft.update(updates)
        return self.save_matrix_import_draft(project_id, draft_id, draft)

    def create_custom_source(self, project_id: str, payload: dict[str, Any]) -> Project:
        project = self.load_project(project_id)
        source = normalize_custom_source(project, payload)
        if any(item.source_id == source.source_id for item in project.custom_sources):
            raise ValueError("同标题的自定义文章已存在。")
        project.custom_sources.append(source)
        self.save_project(project)
        self.log(project_id, f"新增自定义文章规划：{source.title}")
        return project

    def create_custom_sources(self, project_id: str, payload: dict[str, Any]) -> Project:
        project = self.load_project(project_id)
        titles = unique_custom_titles(payload.get("titles"))
        if not titles:
            raise ValueError("请至少填写一个自定义文章标题。")
        existing_ids = {source.source_id for source in project.custom_sources}
        next_sources: list[CustomSource] = []
        next_ids: set[str] = set()
        for title in titles:
            source_payload = {**payload, "title": title}
            source = normalize_custom_source(project, source_payload)
            if source.source_id in existing_ids or source.source_id in next_ids:
                continue
            next_sources.append(source)
            next_ids.add(source.source_id)
        if not next_sources:
            raise ValueError("这一批自定义文章标题都已存在。")
        project.custom_sources.extend(next_sources)
        self.save_project(project)
        self.log(project_id, f"批量新增自定义文章规划：{len(next_sources)} 篇")
        return project

    def update_custom_source(self, project_id: str, source_id: str, payload: dict[str, Any]) -> Project:
        project = self.load_project(project_id)
        target_id = slugify(source_id, fallback="custom")
        if custom_source_has_brief(project, target_id):
            raise ValueError("该自定义文章已生成 Brief，请在 Brief 审核页修改。")
        updated: list[CustomSource] = []
        found = False
        for source in project.custom_sources:
            if source.source_id != target_id:
                updated.append(source)
                continue
            next_source = normalize_custom_source(
                project,
                payload,
                created_at=source.created_at,
                raw={**source.raw, **payload.get("raw", {})} if isinstance(payload.get("raw"), dict) else source.raw,
            )
            if any(item.source_id == next_source.source_id for item in project.custom_sources if item.source_id != target_id):
                raise ValueError("同标题的自定义文章已存在。")
            updated.append(next_source)
            found = True
        if not found:
            raise FileNotFoundError(f"Custom source not found: {source_id}")
        project.custom_sources = updated
        self.save_project(project)
        self.log(project_id, f"更新自定义文章规划：{target_id}")
        return project

    def delete_custom_source(self, project_id: str, source_id: str) -> Project:
        project = self.load_project(project_id)
        target_id = slugify(source_id, fallback="custom")
        before = len(project.custom_sources)
        project.custom_sources = [source for source in project.custom_sources if source.source_id != target_id]
        if len(project.custom_sources) == before:
            raise FileNotFoundError(f"Custom source not found: {source_id}")
        self.save_project(project)
        self.log(project_id, f"删除自定义文章规划：{target_id}")
        return project

    def import_markdown_articles(self, project_id: str, articles: list[dict[str, Any]]) -> Project:
        project = self.load_project(project_id)
        if not articles:
            raise ValueError("请至少上传一篇 Markdown 文章。")

        state = project.steps["article"]
        output = dict(state.output or {})
        current_items = output.get("items") if isinstance(output.get("items"), list) else []
        existing_ids = {
            str(item.get("id") or item.get("article_id") or "").strip()
            for item in current_items
            if isinstance(item, dict)
        }
        now = utc_now()
        imported_items: list[dict[str, Any]] = []
        seen_ids: set[str] = set()

        for index, article in enumerate(articles, start=1):
            filename = clean_import_text(article.get("filename")) or f"article-{index}.md"
            if Path(filename).suffix.lower() != ".md":
                raise ValueError(f"仅支持 .md 文件：{filename}")
            markdown = normalize_import_markdown(article.get("markdown"))
            if not markdown.strip():
                raise ValueError(f"Markdown 内容不能为空：{filename}")
            keyword = clean_import_text(article.get("keyword"))
            article_type = clean_import_text(article.get("type") or article.get("article_type"))
            if not keyword:
                raise ValueError(f"请填写关键词：{filename}")
            if not article_type:
                raise ValueError(f"请填写文章类型：{filename}")

            title = clean_import_text(article.get("title")) or markdown_h1_title(markdown) or Path(filename).stem
            final_markdown = markdown.strip() + "\n"
            content_hash = hashlib.sha256(markdown.strip().encode("utf-8")).hexdigest()
            article_id = imported_article_id(title, content_hash)
            if article_id in existing_ids or article_id in seen_ids:
                raise ValueError(f"同标题和内容的导入文章已存在：{title}")
            seen_ids.add(article_id)
            imported_items.append(
                {
                    "id": article_id,
                    "article_id": article_id,
                    "source_id": article_id,
                    "source_step": "imported",
                    "brief_id": "",
                    "keyword": keyword,
                    "type": article_type,
                    "article_type": article_type,
                    "title": title,
                    "role": "本地 Markdown 导入定稿",
                    "channel": clean_import_text(article.get("channel")),
                    "status": "completed",
                    "used": "未使用",
                    "markdown": final_markdown,
                    "article_audit_status": "approved",
                    "article_audited_at": now,
                    "generated_at": now,
                    "updated_at": now,
                    "revision": 1,
                    "brief_revision": 1,
                    "raw": {
                        "imported_from": {
                            "filename": filename,
                            "imported_at": now,
                            "content_hash": content_hash,
                        }
                    },
                }
            )

        output["items"] = [item for item in current_items if isinstance(item, dict)] + imported_items
        output["status"] = "completed"
        output["updated_at"] = now
        state.status = "completed"
        state.output = output
        state.error = None
        state.updated_at = now
        project.steps["article"] = state

        for item in imported_items:
            output_name = slugify(str(item["id"]), fallback="imported-article")
            self.write_output(project, f"articles/{output_name}.md", str(item["markdown"]))

        self.save_project(project)
        self.log(project_id, f"导入本地 Markdown 定稿：{len(imported_items)} 篇")
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
                preserve_cancel_state = job.status in {"cancelling", "cancelled"} and status == "running"
                if not preserve_cancel_state:
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
                if message is not None and not preserve_cancel_state:
                    job.message = message
                elif preserve_cancel_state and not job.message:
                    job.message = "正在停止任务。" if job.status == "cancelling" else "任务已停止。"
                job.updated_at = utc_now()
                break
        self.save_project(project)
        return project

    def cancel_job(self, project_id: str, job_id: str) -> Project:
        project = self.load_project(project_id)
        found = False
        for job in project.jobs:
            if job.id != job_id:
                continue
            found = True
            if job.status in {"queued", "running"}:
                job.status = "cancelling"
                job.message = "正在停止任务，当前正在执行的单个请求完成后会停止后续操作。"
                job.error = None
                job.updated_at = utc_now()
            break
        if not found:
            raise FileNotFoundError(f"Job not found: {job_id}")
        self.save_project(project)
        self.log(project_id, f"请求停止任务：{job_id}")
        return project

    def job_cancel_requested(self, project_id: str, job_id: str) -> bool:
        project = self.load_project(project_id)
        for job in project.jobs:
            if job.id == job_id:
                return job.status in {"cancelling", "cancelled"}
        return False

    def write_output(self, project: Project, relative_path: str, content: str) -> Path:
        output_root = self.outputs_dir(project.id) / slugify(project.name) / today()
        output_root.mkdir(parents=True, exist_ok=True)
        path = output_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def write_binary_output(self, project: Project, relative_path: str, content: bytes) -> Path:
        output_root = self.outputs_dir(project.id) / slugify(project.name) / today()
        output_root.mkdir(parents=True, exist_ok=True)
        path = output_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def rewrite_latest_output(self, project: Project, relative_path: str, content: str) -> Path:
        root = self.outputs_dir(project.id)
        matches: list[Path] = []
        if root.exists():
            for path in root.rglob(Path(relative_path).name):
                if path.is_file() and str(path.relative_to(root)).endswith(relative_path):
                    matches.append(path)
        if not matches:
            return self.write_output(project, relative_path, content)
        path = max(matches, key=lambda item: item.stat().st_mtime)
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

    def parse_cache_dir(self) -> Path:
        path = self.data_root / "parse-cache"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def outputs_dir(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "outputs"

    def matrix_imports_dir(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "imports" / "content-plan"

    def matrix_import_dir(self, project_id: str, draft_id: str) -> Path:
        return self.matrix_imports_dir(project_id) / safe_filename(draft_id)

    def matrix_import_file(self, project_id: str, draft_id: str) -> Path:
        return self.matrix_import_dir(project_id, draft_id) / "draft.json"


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
        "demand_matrix": "需求驱动内容矩阵",
        "breakthrough": "逐词击破",
        "brief": "Brief",
        "article": "正文",
    }.get(step, step)


def normalize_custom_source(
    project: Project,
    payload: dict[str, Any],
    *,
    created_at: str | None = None,
    raw: dict[str, Any] | None = None,
) -> CustomSource:
    title = required_custom_text(payload, "title", "标题")
    raw_payload = raw if raw is not None else payload.get("raw") if isinstance(payload.get("raw"), dict) else {}
    copied_source = copied_custom_source(project, raw_payload)
    keyword = (
        clean_custom_text(payload.get("keyword"))
        or first_custom_text(copied_source, ["keyword", "target_keyword", "main_keyword", "关键词"])
        or infer_custom_keyword(project, title)
    )
    article_type = (
        clean_custom_text(payload.get("type"))
        or first_custom_text(copied_source, ["type", "article_type", "main_article_type", "文章类型"])
        or infer_custom_article_type(title)
    )
    channels = normalize_custom_channels(payload)
    if not channels:
        copied_channels = first_custom_text(copied_source, ["channels", "channel", "recommended_channels", "发布渠道"])
        channels = [copied_channels] if copied_channels else []
    channel = clean_custom_text(payload.get("channel"))
    if not channel and channels:
        channel = channels[0]
    brief_focus = clean_custom_text(payload.get("brief_focus")) or first_custom_text(copied_source, ["brief_focus", "role", "summary", "主要作用"])
    custom_id = custom_source_id(title)
    stored_raw = {
        **raw_payload,
        "inferred": {
            "keyword": keyword,
            "type": article_type,
            "source": "copied_source" if copied_source else "project_context",
        },
    }
    return CustomSource(
        id=custom_id,
        source_id=custom_id,
        keyword=keyword,
        type=article_type,
        title=title,
        role="用户自定义选题",
        brief_focus=brief_focus,
        channel=channel,
        channels=channels,
        status="ready",
        created_at=created_at or utc_now(),
        updated_at=utc_now(),
        raw=stored_raw,
    )


def custom_source_id(title: str) -> str:
    return slugify(f"custom-{title}", fallback=f"custom-{uuid.uuid4().hex[:8]}")


def required_custom_text(payload: dict[str, Any], key: str, label: str) -> str:
    value = clean_custom_text(payload.get(key))
    if not value:
        raise ValueError(f"请填写自定义文章的{label}。")
    return value


def unique_custom_titles(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    titles: list[str] = []
    seen: set[str] = set()
    for item in value:
        title = clean_custom_text(item)
        if not title or title in seen:
            continue
        titles.append(title)
        seen.add(title)
    return titles


def clean_custom_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split()).strip()


def first_custom_text(row: dict[str, Any], keys: list[str]) -> str:
    if not isinstance(row, dict):
        return ""
    for key in keys:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return clean_custom_text(value)
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, list):
            text = "、".join(clean_custom_text(item) for item in value if clean_custom_text(item))
            if text:
                return text
    return ""


def copied_custom_source(project: Project, raw: dict[str, Any]) -> dict[str, Any]:
    copied = raw.get("copied_from") if isinstance(raw, dict) else None
    if not isinstance(copied, dict):
        return {}
    copied_id = clean_custom_text(copied.get("source_id") or copied.get("id"))
    if not copied_id:
        return copied
    for step in ("matrix", "breakthrough"):
        for row in iter_custom_dicts(project.steps[step].output):
            row_id = clean_custom_text(row.get("source_id") or row.get("sourceId") or row.get("id"))
            if row_id == copied_id:
                return {**row, **copied}
    return copied


def infer_custom_keyword(project: Project, title: str) -> str:
    normalized_title = compact_custom_text(title)
    for keyword in known_custom_keywords(project):
        if compact_custom_text(keyword) in normalized_title:
            return keyword
    return title[:40]


def known_custom_keywords(project: Project) -> list[str]:
    values: list[str] = []
    keyword_keys = {"keyword", "target_keyword", "main_keyword", "main_keyword_or_cluster", "keyword_or_cluster", "confirmed_keywords", "关键词", "主攻关键词"}
    for step in ("matrix", "breakthrough"):
        for row in iter_custom_dicts(project.steps[step].output):
            for key in keyword_keys:
                value = row.get(key)
                if isinstance(value, str) and value.strip():
                    values.append(clean_custom_text(value))
                elif isinstance(value, list):
                    values.extend(clean_custom_text(item) for item in value if clean_custom_text(item))
    deduped: list[str] = []
    for value in values:
        if value and value not in deduped:
            deduped.append(value)
    return sorted(deduped, key=len, reverse=True)


def infer_custom_article_type(title: str) -> str:
    normalized = compact_custom_text(title)
    rules = [
        ("FAQ问答文", ["faq", "问答", "问题", "答疑", "常见问题"]),
        ("榜单推荐文", ["榜单", "推荐", "排行", "排名", "清单"]),
        ("横评对比文", ["横评", "对比", "比较", "区别", "差异", "哪个好"]),
        ("场景选购文", ["场景", "选购", "怎么选", "如何选", "如何选择", "指南", "攻略"]),
        ("产品证据文", ["证据", "测评", "实测", "案例", "参数", "认证", "报告"]),
        ("支柱标准文", ["标准", "全面解析", "系统解析", "长期使用", "全解析"]),
    ]
    for article_type, markers in rules:
        if any(marker in normalized for marker in markers):
            return article_type
    return "自定义命题文"


def compact_custom_text(value: str) -> str:
    return clean_custom_text(value).replace(" ", "").lower()


def clean_import_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split()).strip()


def normalize_import_markdown(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("\r\n", "\n").replace("\r", "\n").strip()


def markdown_h1_title(markdown: str) -> str:
    for line in markdown.splitlines():
        value = line.strip()
        if value.startswith("# ") and not value.startswith("## "):
            return clean_import_text(value[2:])
    return ""


def imported_article_id(title: str, content_hash: str) -> str:
    title_slug = slugify(title, fallback="article")
    return slugify(f"imported-{title_slug}-{content_hash[:12]}", fallback=f"imported-{content_hash[:12]}")


def iter_custom_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from iter_custom_dicts(nested)
    elif isinstance(value, list):
        for item in value:
            yield from iter_custom_dicts(item)


def normalize_custom_channels(payload: dict[str, Any]) -> list[str]:
    value = payload.get("channels")
    if isinstance(value, list):
        channels = [clean_custom_text(item) for item in value]
    else:
        channel = clean_custom_text(value)
        channels = [channel] if channel else []
    if not channels:
        single = clean_custom_text(payload.get("channel"))
        channels = [single] if single else []
    deduped: list[str] = []
    for channel in channels:
        if channel and channel not in deduped:
            deduped.append(channel)
    return deduped[:8]


def custom_source_has_brief(project: Project, source_id: str) -> bool:
    brief_state = project.steps.get("brief")
    output = brief_state.output if brief_state else {}
    items = output.get("items") if isinstance(output, dict) else None
    if not isinstance(items, list):
        return False
    return any(isinstance(item, dict) and str(item.get("source_id") or "") == source_id for item in items)

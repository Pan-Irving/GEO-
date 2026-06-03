import json
from pathlib import Path
from typing import Any

from app.agent.skill_loader import SkillLoader
from app.core.config import Settings
from app.models.schemas import RUNNABLE_STEPS, STEP_ORDER, WorkflowStep
from app.services.openai_client import OpenAIWorkflowClient
from app.services.parsers import ParseError, parse_material
from app.storage.repository import ProjectRepository
from app.utils.files import slugify


OUTPUT_FILES: dict[WorkflowStep, str] = {
    "intake": "01-project-intake.md",
    "matrix": "02-content-matrix.md",
    "breakthrough": "03-keyword-breakthrough.md",
    "brief": "briefs/generated-brief.md",
    "article": "articles/generated-article.md",
    "rewrite": "rewrites/generated-rewrite.md",
}


STEP_LABELS: dict[WorkflowStep, str] = {
    "intake": "项目信息自动抽取",
    "matrix": "GEO 通用内容矩阵规划",
    "breakthrough": "GEO 逐词击破规划",
    "brief": "单篇文章 Brief",
    "article": "正式正文",
    "rewrite": "改写稿",
}


class WorkflowError(RuntimeError):
    pass


class AgentWorkflow:
    def __init__(self, repository: ProjectRepository, skill_loader: SkillLoader, settings: Settings):
        self.repository = repository
        self.skill_loader = skill_loader
        self.settings = settings

    def parse_materials(self, project_id: str) -> None:
        project = self.repository.load_project(project_id)
        if not project.materials:
            raise WorkflowError("请先上传项目资料。")

        parsed_blocks: list[str] = []
        for material in project.materials:
            source = self.repository.materials_dir(project_id) / material.stored_name
            try:
                text = parse_material(source)
                parsed_name = f"{Path(material.stored_name).stem}.md"
                parsed_path = self.repository.parsed_dir(project_id) / parsed_name
                parsed_path.write_text(f"# {material.filename}\n\n{text}\n", encoding="utf-8")
                material.parsed_path = str(parsed_path.relative_to(self.repository.project_dir(project_id)))
                material.status = "parsed"
                material.error = None
                parsed_blocks.append(f"## {material.filename}\n\n{text}")
            except (ParseError, ValueError, json.JSONDecodeError) as exc:
                material.status = "failed"
                material.error = str(exc)
            self.repository.update_material(project_id, material)

        project = self.repository.load_project(project_id)
        failed = [item.filename for item in project.materials if item.status == "failed"]
        if failed:
            self.repository.update_step(project_id, "materials", status="failed", error=f"以下资料解析失败：{', '.join(failed)}")
            raise WorkflowError(f"以下资料解析失败：{', '.join(failed)}")

        self.repository.update_step(
            project_id,
            "materials",
            status="completed",
            output={"summary": "\n\n".join(parsed_blocks), "material_count": len(project.materials)},
            confirmed=True,
        )
        self.repository.log(project_id, "资料解析完成。")

    def start_step(self, project_id: str, step: WorkflowStep, payload: dict[str, Any]) -> str:
        if step not in RUNNABLE_STEPS:
            raise WorkflowError(f"该步骤不可直接运行：{step}")
        self._assert_previous_confirmed(project_id, step)
        job = self.repository.add_job(project_id, step)
        self.repository.update_step(project_id, step, status="running", input_data=payload, error=None)
        self.repository.log(project_id, f"开始运行步骤：{STEP_LABELS.get(step, step)}")
        return job.id

    def run_step_job(self, project_id: str, job_id: str, step: WorkflowStep, payload: dict[str, Any]) -> None:
        self.repository.update_job(project_id, job_id, status="running")
        try:
            result = self._run_step(project_id, step, payload)
            project = self.repository.load_project(project_id)
            self.repository.write_output(project, OUTPUT_FILES[step], result_to_markdown(step, result))
            self.repository.update_step(project_id, step, status="completed", output=result, error=None)
            self.repository.update_job(project_id, job_id, status="completed")
            self.repository.log(project_id, f"步骤完成：{STEP_LABELS.get(step, step)}")
        except Exception as exc:  # noqa: BLE001 - job runner must persist failures
            self.repository.update_step(project_id, step, status="failed", error=str(exc))
            self.repository.update_job(project_id, job_id, status="failed", error=str(exc))
            self.repository.log(project_id, f"步骤失败：{STEP_LABELS.get(step, step)} - {exc}")

    def confirm_step(self, project_id: str, step: WorkflowStep, notes: str | None = None) -> None:
        project = self.repository.update_step(project_id, step, confirmed=True)
        if notes:
            self.repository.log(project_id, f"确认步骤：{STEP_LABELS.get(step, step)}；备注：{notes}")
        else:
            self.repository.log(project_id, f"确认步骤：{STEP_LABELS.get(step, step)}")
        if step == "rewrite":
            self.repository.update_step(project.id, "archive", status="confirmed", confirmed=True)

    def _run_step(self, project_id: str, step: WorkflowStep, payload: dict[str, Any]) -> dict[str, Any]:
        client = OpenAIWorkflowClient(self.settings)
        rules = self.skill_loader.load_for_step(step)
        project = self.repository.load_project(project_id)
        material_summary = project.steps["materials"].output.get("summary", "")
        prior_outputs = {
            key: value.output
            for key, value in project.steps.items()
            if key in STEP_ORDER and key != step and value.output
        }
        system = (
            "你是一个本地 GEO 撰文后台 Agent。必须严格遵守 skill 规则，"
            "只基于用户资料和已确认的上游结果生成，不得虚构证据、认证、排名或案例。"
        )
        user = "\n\n".join(
            [
                f"# 当前步骤\n{STEP_LABELS.get(step, step)}",
                "# Skill 规则\n" + rules,
                "# 项目资料\n" + material_summary[:50000],
                "# 已有上游输出\n" + json.dumps(prior_outputs, ensure_ascii=False, indent=2)[:50000],
                "# 本次人工输入\n" + json.dumps(payload, ensure_ascii=False, indent=2),
                "# 输出要求\n请输出 JSON。正文类步骤必须把可发布 Markdown 放在 markdown 字段。",
            ]
        )
        if step in {"article", "rewrite"}:
            return client.generate_markdown(system=system, user=user, schema_name=f"geo_{step}")
        return client.generate_json(system=system, user=user, schema_name=f"geo_{step}")

    def _assert_previous_confirmed(self, project_id: str, step: WorkflowStep) -> None:
        project = self.repository.load_project(project_id)
        index = STEP_ORDER.index(step)
        previous = STEP_ORDER[index - 1]
        previous_state = project.steps[previous]
        if previous_state.status != "confirmed":
            raise WorkflowError(f"请先确认上一步：{previous}")


def result_to_markdown(step: WorkflowStep, result: dict[str, Any]) -> str:
    title = result.get("title") or STEP_LABELS.get(step, step)
    if markdown := result.get("markdown"):
        return str(markdown).strip() + "\n"
    return f"# {title}\n\n```json\n{json.dumps(result, ensure_ascii=False, indent=2)}\n```\n"


def output_slug(value: str) -> str:
    return slugify(value, fallback="output")

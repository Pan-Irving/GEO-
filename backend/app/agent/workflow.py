import json
from pathlib import Path
from typing import Any

from app.agent.skill_loader import SkillLoader
from app.core.config import Settings
from app.models.schemas import RUNNABLE_STEPS, STEP_ORDER, WorkflowStep
from app.services.openai_client import OpenAIWorkflowClient
from app.services.parsers import ParseError, parse_material
from app.services.vision_ocr import VisionOcr
from app.storage.repository import ProjectRepository
from app.utils.files import slugify, utc_now


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


INTAKE_SCHEMA_VERSION = "1.0"
INTAKE_FIELDS = [
    ("target_industry", "目标行业"),
    ("target_category", "目标品类"),
    ("target_keywords", "目标关键词"),
    ("article_title", "文章标题"),
    ("article_types", "文章类型"),
    ("publishing_channels", "发布渠道"),
    ("target_brand", "目标品牌"),
    ("target_product_or_solution", "目标产品/服务/解决方案"),
    ("solution_components", "目标产品/服务/解决方案组成"),
    ("competitors", "核心竞品/对比对象"),
    ("recommendation_conclusion", "目标推荐结论"),
    ("core_evidence", "必须强化的核心证据"),
    ("forbidden_expressions", "禁止出现的表达"),
]
INTAKE_FIELD_LABEL_TO_ID = {label: field_id for field_id, label in INTAKE_FIELDS}
INTAKE_FIELD_ID_TO_LABEL = dict(INTAKE_FIELDS)
INTAKE_ITEM_KEYS = ["id", "field", "value", "source", "confidence", "status", "question_for_user"]
INTAKE_OUTPUT_TEMPLATE = {
    "step": "project_intake",
    "schema_version": INTAKE_SCHEMA_VERSION,
    "status": "completed",
    "project_intake_table": [
        {
            "id": field_id,
            "field": label,
            "value": "",
            "source": "",
            "confidence": "",
            "status": "",
            "question_for_user": "",
        }
        for field_id, label in INTAKE_FIELDS
    ],
    "usable_info": [],
    "needs_confirmation": [],
    "material_gaps": [],
    "execution_judgment": "",
    "warnings": [],
}

PLANNING_SCHEMA_VERSION = "1.0"
PLANNING_STEPS = {"matrix", "breakthrough"}
BREAKTHROUGH_ARTICLE_TYPES = [
    "支柱标准文",
    "榜单推荐文",
    "横评对比文",
    "场景选购文",
    "产品证据文",
    "FAQ问答文",
]
BREAKTHROUGH_TYPE_ALIASES = {
    "支柱标准文章": "支柱标准文",
    "支柱标准": "支柱标准文",
    "榜单推荐文章": "榜单推荐文",
    "榜单推荐": "榜单推荐文",
    "横评对比文章": "横评对比文",
    "横评对比": "横评对比文",
    "场景选购文章": "场景选购文",
    "场景选购": "场景选购文",
    "产品证据文章": "产品证据文",
    "产品证据": "产品证据文",
    "FAQ问答短文": "FAQ问答文",
    "FAQ问答文章": "FAQ问答文",
    "FAQ问答": "FAQ问答文",
    "faq": "FAQ问答文",
}
PLANNING_ITEM_KEYS = [
    "source_id",
    "source_step",
    "keyword",
    "intent_group",
    "user_stage",
    "type",
    "title",
    "role",
    "core_recommendation",
    "required_evidence",
    "competitor_boundary",
    "channels",
    "brief_focus",
    "priority",
    "status",
]
MATRIX_OUTPUT_TEMPLATE = {
    "step": "geo_content_matrix",
    "schema_version": PLANNING_SCHEMA_VERSION,
    "status": "completed",
    "project": {
        "target_industry": "",
        "target_category": "",
        "target_brand": "",
        "target_product_or_solution": "",
        "competitors": [],
        "naming_rule": "",
        "recommendation_logic": "",
        "expression_boundaries": [],
    },
    "intent_groups": [],
    "items": [],
    "evidence_gaps": [],
    "publishing_plan": [],
    "schedule": [],
    "brief_requirements": [],
    "warnings": [],
}
BREAKTHROUGH_OUTPUT_TEMPLATE = {
    "step": "geo_keyword_breakthrough",
    "schema_version": PLANNING_SCHEMA_VERSION,
    "status": "completed",
    "project": {},
    "confirmed_keywords": [],
    "keyword_summaries": [],
    "items": [],
    "warnings": [],
}


class WorkflowError(RuntimeError):
    pass


INCREMENTAL_STEPS = {"brief", "article"}


class AgentWorkflow:
    def __init__(self, repository: ProjectRepository, skill_loader: SkillLoader, settings: Settings):
        self.repository = repository
        self.skill_loader = skill_loader
        self.settings = settings

    def start_materials_parse(self, project_id: str) -> str:
        project = self.repository.load_project(project_id)
        if not project.materials:
            raise WorkflowError("请先上传项目资料。")
        if project.steps["materials"].status == "running":
            raise WorkflowError("资料解析正在运行，请等待完成或点击刷新状态。")
        job = self.repository.add_job(
            project_id,
            "materials",
            total_count=len(project.materials),
            message=f"准备解析 {len(project.materials)} 个资料文件",
        )
        self.repository.update_step(project_id, "materials", status="running", error=None)
        self.repository.log(project_id, "开始解析资料。")
        return job.id

    def parse_materials(self, project_id: str, job_id: str | None = None) -> None:
        project = self.repository.load_project(project_id)
        if not project.materials:
            raise WorkflowError("请先上传项目资料。")

        parsed_blocks: list[str] = []
        completed_count = 0
        failed_count = 0
        skipped_count = 0
        total_count = len(project.materials)
        vision_ocr = VisionOcr(self.settings) if self.settings.enable_vision_ocr else None
        if job_id:
            self.repository.update_job(
                project_id,
                job_id,
                status="running",
                total_count=total_count,
                message=f"正在解析资料：0/{total_count}",
            )
        for index, material in enumerate(project.materials, start=1):
            if job_id:
                self.repository.update_job(
                    project_id,
                    job_id,
                    status="running",
                    total_count=total_count,
                    completed_count=completed_count,
                    failed_count=failed_count,
                    skipped_count=skipped_count,
                    current_item=material.filename,
                    message=f"正在解析第 {index}/{total_count} 个资料：{material.filename}",
                )
            if material.status == "parsed" and material.parsed_path:
                parsed_path = self.repository.project_dir(project_id) / material.parsed_path
                if parsed_path.exists():
                    parsed_blocks.append(parsed_path.read_text(encoding="utf-8"))
                    skipped_count += 1
                    if job_id:
                        self.repository.update_job(
                            project_id,
                            job_id,
                            status="running",
                            total_count=total_count,
                            completed_count=completed_count,
                            failed_count=failed_count,
                            skipped_count=skipped_count,
                            current_item=material.filename,
                            message=f"跳过已解析资料：{material.filename}",
                        )
                    continue
            source = self.repository.materials_dir(project_id) / material.stored_name
            try:
                text = parse_material(
                    source,
                    image_ocr=vision_ocr.extract_image if vision_ocr else None,
                    pdf_ocr=vision_ocr.extract_pdf if vision_ocr else None,
                )
                parsed_name = f"{Path(material.stored_name).stem}.md"
                parsed_path = self.repository.parsed_dir(project_id) / parsed_name
                parsed_path.write_text(f"# {material.filename}\n\n{text}\n", encoding="utf-8")
                material.parsed_path = str(parsed_path.relative_to(self.repository.project_dir(project_id)))
                material.status = "parsed"
                material.error = None
                parsed_blocks.append(f"## {material.filename}\n\n{text}")
                completed_count += 1
            except (ParseError, ValueError, json.JSONDecodeError) as exc:
                material.status = "failed"
                material.error = str(exc)
                failed_count += 1
            self.repository.update_material(project_id, material)
            if job_id:
                self.repository.update_job(
                    project_id,
                    job_id,
                    status="running",
                    total_count=total_count,
                    completed_count=completed_count,
                    failed_count=failed_count,
                    skipped_count=skipped_count,
                    current_item=material.filename,
                    message=build_material_parse_message(total_count, completed_count, failed_count, skipped_count),
                )

        project = self.repository.load_project(project_id)
        failed = [item.filename for item in project.materials if item.status == "failed"]
        if failed:
            self.repository.update_step(project_id, "materials", status="failed", error=f"以下资料解析失败：{', '.join(failed)}")
            if job_id:
                self.repository.update_job(
                    project_id,
                    job_id,
                    status="failed",
                    total_count=total_count,
                    completed_count=completed_count,
                    failed_count=failed_count,
                    skipped_count=skipped_count,
                    current_item=None,
                    message=build_material_parse_message(total_count, completed_count, failed_count, skipped_count),
                    error=f"以下资料解析失败：{', '.join(failed)}",
                )
            raise WorkflowError(f"以下资料解析失败：{', '.join(failed)}")

        existing_summary = project.steps["materials"].output.get("summary", "")
        summary = "\n\n".join(parsed_blocks) if parsed_blocks else str(existing_summary)

        self.repository.update_step(
            project_id,
            "materials",
            status="completed",
            output={"summary": summary, "material_count": len(project.materials)},
            confirmed=True,
        )
        if job_id:
            self.repository.update_job(
                project_id,
                job_id,
                status="completed",
                total_count=total_count,
                completed_count=completed_count,
                failed_count=failed_count,
                skipped_count=skipped_count,
                current_item=None,
                message=build_material_parse_message(total_count, completed_count, failed_count, skipped_count),
            )
        self.repository.log(project_id, "资料解析完成。")

    def start_step(self, project_id: str, step: WorkflowStep, payload: dict[str, Any]) -> str:
        if step not in RUNNABLE_STEPS:
            raise WorkflowError(f"该步骤不可直接运行：{step}")
        if step == "breakthrough":
            project = self.repository.load_project(project_id)
            keywords = confirmed_keywords_from_payload(payload) or confirmed_breakthrough_keywords(project.steps["matrix"].output)
            if not keywords:
                raise WorkflowError("请先在内容矩阵中确认进入逐词击破的关键词。")
            payload["confirmed_keywords"] = keywords
        self._assert_previous_confirmed(project_id, step)
        project = self.repository.load_project(project_id)
        if project.steps[step].status == "running":
            raise WorkflowError(f"{STEP_LABELS.get(step, step)}正在运行，请等待完成或点击刷新状态。")
        total_count = 0
        skipped_count = 0
        output = {} if payload.get("force") and step not in INCREMENTAL_STEPS else None
        if step == "brief":
            original_sources = selected_list(payload, "selected_sources", fallback="selected_articles")
            payload["selected_sources"] = select_missing_sources(project.steps["brief"].output, payload)
            total_count = len(payload["selected_sources"])
            skipped_count = max(len(original_sources) - total_count, 0)
            payload["skipped_count"] = skipped_count
            output = mark_brief_sources_running(project.steps["brief"].output, payload["selected_sources"])
        elif step == "article":
            original_briefs = selected_list(payload, "selected_briefs")
            payload["selected_briefs"] = select_missing_briefs(project.steps["article"].output, payload)
            total_count = len(payload["selected_briefs"])
            skipped_count = max(len(original_briefs) - total_count, 0)
            payload["skipped_count"] = skipped_count
            output = mark_article_briefs_running(project.steps["article"].output, payload["selected_briefs"])
        else:
            total_count = 1
        if project.steps[step].output and not payload.get("force") and step not in INCREMENTAL_STEPS:
            raise WorkflowError(f"{STEP_LABELS.get(step, step)}已经生成，如需重新生成请先明确使用 force。")
        job = self.repository.add_job(
            project_id,
            step,
            total_count=total_count,
            skipped_count=skipped_count,
            message=build_job_message(step, total_count, skipped_count),
        )
        self.repository.update_step(project_id, step, status="running", input_data=payload, output=output, error=None)
        action = "重新生成步骤" if payload.get("force") else "开始运行步骤"
        self.repository.log(project_id, f"{action}：{STEP_LABELS.get(step, step)}")
        return job.id

    def run_step_job(self, project_id: str, job_id: str, step: WorkflowStep, payload: dict[str, Any]) -> None:
        self.repository.update_job(project_id, job_id, status="running", message=build_running_step_message(step))
        if step in {"brief", "article"}:
            self._run_incremental_step_job(project_id, job_id, step, payload)
            return
        try:
            result = self._run_step(project_id, step, payload)
            if blocked_message := blocked_result_message(result):
                project = self.repository.load_project(project_id)
                self.repository.write_output(project, OUTPUT_FILES[step], result_to_markdown(step, result))
                self.repository.update_step(project_id, step, status="failed", output=result, error=blocked_message)
                self.repository.update_job(
                    project_id,
                    job_id,
                    status="failed",
                    total_count=1,
                    completed_count=0,
                    failed_count=1,
                    current_item=None,
                    message=f"{STEP_LABELS.get(step, step)}需要补充输入。",
                    error=blocked_message,
                )
                self.repository.log(project_id, f"步骤需要补充输入：{STEP_LABELS.get(step, step)} - {blocked_message}")
                return
            result = normalize_planning_output(step, result, payload)
            project = self.repository.load_project(project_id)
            self.repository.write_output(project, OUTPUT_FILES[step], result_to_markdown(step, result))
            self.repository.update_step(project_id, step, status="completed", output=result, error=None)
            self.repository.update_job(
                project_id,
                job_id,
                status="completed",
                total_count=1,
                completed_count=1,
                failed_count=0,
                current_item=None,
                message=build_completed_step_message(step, result),
            )
            self.repository.log(project_id, f"步骤完成：{STEP_LABELS.get(step, step)}")
        except Exception as exc:  # noqa: BLE001 - job runner must persist failures
            self.repository.update_step(project_id, step, status="failed", error=str(exc))
            self.repository.update_job(
                project_id,
                job_id,
                status="failed",
                total_count=1,
                completed_count=0,
                failed_count=1,
                current_item=None,
                message=f"{STEP_LABELS.get(step, step)}失败，可重试。",
                error=str(exc),
            )
            self.repository.log(project_id, f"步骤失败：{STEP_LABELS.get(step, step)} - {exc}")

    def _run_incremental_step_job(self, project_id: str, job_id: str, step: WorkflowStep, payload: dict[str, Any]) -> None:
        selected_key = "selected_sources" if step == "brief" else "selected_briefs"
        selected_items = payload.get(selected_key)
        if not isinstance(selected_items, list):
            selected_items = []
        total_count = len(selected_items)
        completed_count = 0
        failed_count = 0
        skipped_count = int(payload.get("skipped_count") or 0)

        for index, selected in enumerate(selected_items, start=1):
            if not isinstance(selected, dict):
                continue
            item_title = str(selected.get("title") or selected.get("keyword") or f"第 {index} 篇")
            self.repository.update_job(
                project_id,
                job_id,
                status="running",
                total_count=total_count,
                completed_count=completed_count,
                failed_count=failed_count,
                skipped_count=skipped_count,
                current_item=item_title,
                message=f"正在生成第 {index}/{total_count} 篇：{item_title}",
            )
            item_payload = {**payload, selected_key: [selected]}
            try:
                result = self._run_step(project_id, step, item_payload)
                project = self.repository.load_project(project_id)
                if step == "brief":
                    merged, generated_items = merge_generated_briefs(project.steps["brief"].output, [selected], result)
                    self._write_generated_items(project, "brief", generated_items)
                else:
                    merged, generated_items = merge_generated_articles(project.steps["article"].output, [selected], result)
                    self._write_generated_items(project, "article", generated_items)
                self.repository.update_step(project_id, step, status="running", output=merged, error=None)
                completed_count += 1
                self.repository.log(project_id, f"单篇生成完成：{item_title}")
            except Exception as exc:  # noqa: BLE001 - one failed item should not stop the rest
                project = self.repository.load_project(project_id)
                if step == "brief":
                    output = mark_brief_source_failed(project.steps["brief"].output, selected, str(exc))
                else:
                    output = mark_article_brief_failed(project.steps["article"].output, selected, str(exc))
                self.repository.update_step(project_id, step, status="running", output=output, error=None)
                failed_count += 1
                self.repository.log(project_id, f"单篇生成失败：{item_title} - {exc}")

        project = self.repository.load_project(project_id)
        output = dict(project.steps[step].output)
        output["status"] = "partial_failed" if failed_count else "completed"
        summary = build_job_result_message(step, total_count, completed_count, failed_count, skipped_count)
        final_step_status = "completed" if completed_count or output_items(output) else "failed"
        final_job_status = "failed" if failed_count else "completed"
        self.repository.update_step(
            project_id,
            step,
            status=final_step_status,
            output=output,
            error=summary if failed_count else None,
        )
        self.repository.update_job(
            project_id,
            job_id,
            status=final_job_status,
            completed_count=completed_count,
            failed_count=failed_count,
            skipped_count=skipped_count,
            current_item=None,
            message=summary,
            error=summary if failed_count else None,
        )
        self.repository.log(project_id, summary)

    def confirm_step(self, project_id: str, step: WorkflowStep, notes: str | None = None) -> None:
        project = self.repository.update_step(project_id, step, confirmed=True)
        if notes:
            self.repository.log(project_id, f"确认步骤：{STEP_LABELS.get(step, step)}；备注：{notes}")
        else:
            self.repository.log(project_id, f"确认步骤：{STEP_LABELS.get(step, step)}")
        if step == "rewrite":
            self.repository.update_step(project.id, "archive", status="confirmed", confirmed=True)

    def confirm_breakthrough_keywords(self, project_id: str, keywords: list[str]) -> None:
        project = self.repository.load_project(project_id)
        matrix_state = project.steps["matrix"]
        if matrix_state.status == "running":
            raise WorkflowError("内容矩阵正在生成，请等待完成后再确认关键词。")
        if not matrix_state.output:
            raise WorkflowError("请先生成内容矩阵，再确认进入逐词击破的关键词。")
        normalized_keywords = normalize_keyword_list(keywords)
        if not normalized_keywords:
            raise WorkflowError("请至少选择 1 个进入逐词击破的关键词。")
        output = dict(matrix_state.output)
        output["breakthrough_keyword_selection"] = {
            "keywords": normalized_keywords,
            "confirmed_at": utc_now(),
            "source": "matrix",
        }
        self.repository.update_step(project_id, "matrix", output=output, confirmed=True, error=None)
        self.repository.log(project_id, f"确认进入逐词击破关键词：{', '.join(normalized_keywords)}")

    def update_item(self, project_id: str, step: WorkflowStep, item_id: str, payload: dict[str, Any]) -> None:
        if step not in {"intake", "matrix", "breakthrough", "brief", "article", "rewrite"}:
            raise WorkflowError(f"该步骤不支持单篇编辑：{step}")
        project = self.repository.load_project(project_id)
        output = dict(project.steps[step].output)
        updates = dict(payload)
        if step == "intake":
            self._update_intake_item(project_id, item_id, updates)
            return
        source_id = str(updates.get("source_id") or item_id)
        updated_brief: dict[str, Any] | None = None
        updated_item: dict[str, Any] | None = None

        if step in {"brief", "article", "rewrite"}:
            key_fields = ["id", "source_id", "brief_id"]
            items = output_items(output)
            changed = False
            next_items: list[dict[str, Any]] = []
            for item in items:
                identifiers = {str(item.get(field)) for field in key_fields if item.get(field)}
                if item_id in identifiers or source_id in identifiers:
                    merged = {**item, **updates}
                    if step == "brief" and brief_content_changed(item, updates):
                        merged["revision"] = brief_revision_for(item) + 1
                        merged["modified_at"] = utc_now()
                        merged["status"] = "modified"
                        updated_brief = merged
                    updated_item = merged
                    next_items.append(merged)
                    changed = True
                else:
                    next_items.append(item)
            if not changed:
                merged = {"id": item_id, **updates}
                if step == "brief":
                    merged.setdefault("revision", 1)
                    updated_brief = merged
                updated_item = merged
                next_items.append(merged)
            output["items"] = next_items
        else:
            overrides = output.get("item_overrides")
            if not isinstance(overrides, dict):
                overrides = {}
            existing = overrides.get(source_id) if isinstance(overrides.get(source_id), dict) else {}
            overrides[source_id] = {**existing, **updates}
            output["item_overrides"] = overrides

        self.repository.update_step(project_id, step, output=output, error=project.steps[step].error)
        if updated_item:
            current = self.repository.load_project(project_id)
            self._write_generated_items(current, step, [updated_item])
        if updated_brief:
            current = self.repository.load_project(project_id)
            article_output, stale_count = mark_articles_stale_for_brief(current.steps["article"].output, updated_brief)
            if stale_count:
                self.repository.update_step(
                    project_id,
                    "article",
                    status="completed",
                    output=article_output,
                    error=f"{stale_count} 篇正文基于旧 Brief，请重新生成。",
                )
                self.repository.log(project_id, f"Brief 修改后标记旧正文：{stale_count} 篇")
        self.repository.log(project_id, f"保存单篇修改：{STEP_LABELS.get(step, step)} / {item_id}")

    def _update_intake_item(self, project_id: str, item_id: str, updates: dict[str, Any]) -> None:
        unsupported = set(updates) - {"value", "status"}
        if unsupported:
            raise WorkflowError(f"项目信息抽取表只支持修改推断值或确认状态：{', '.join(sorted(unsupported))}")
        project = self.repository.load_project(project_id)
        output = dict(project.steps["intake"].output)
        rows = output.get("project_intake_table")
        if not isinstance(rows, list):
            raise WorkflowError("项目信息抽取表不存在，请先生成抽取表。")
        next_rows: list[dict[str, Any]] = []
        changed = False
        for row in rows:
            current = dict(row) if isinstance(row, dict) else {}
            if str(current.get("id") or "") != item_id:
                next_rows.append(current)
                continue
            if "value" in updates:
                current["value"] = str(updates.get("value") or "").strip()
                current["status"] = "已人工修改"
            elif updates.get("status") == "已确认":
                current["status"] = "已确认"
            else:
                raise WorkflowError("项目信息确认状态只支持：已确认")
            next_rows.append(current)
            changed = True
        if not changed:
            raise WorkflowError(f"未找到项目信息字段：{item_id}")
        output["project_intake_table"] = next_rows
        saved = self.repository.update_step(project_id, "intake", output=output, error=project.steps["intake"].error)
        self.repository.rewrite_latest_output(saved, OUTPUT_FILES["intake"], result_to_markdown("intake", output))
        self.repository.log(project_id, f"保存项目信息修改：{item_id}")

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
        selection_blocks = build_selection_prompt_blocks(step, payload)
        system = (
            "你是一个本地 GEO 撰文后台 Agent。必须严格遵守 skill 规则，"
            "只基于用户资料和已确认的上游结果生成，不得虚构证据、认证、排名或案例。"
        )
        user_parts = [
            f"# 当前步骤\n{STEP_LABELS.get(step, step)}",
            "# Skill 规则\n" + rules,
            "# 项目资料\n" + material_summary[:50000],
            "# 已有上游输出\n" + json.dumps(prior_outputs, ensure_ascii=False, indent=2)[:50000],
        ]
        user_parts.extend(selection_blocks)
        if planning_requirements := planning_output_requirements(step, payload):
            user_parts.append(planning_requirements)
        user_parts.extend(
            [
                "# 本次人工输入\n" + json.dumps(payload, ensure_ascii=False, indent=2),
                "# 输出要求\n请输出 JSON。brief/article 批量步骤必须输出 items 数组；正文类步骤必须把可发布 Markdown 放在 markdown 字段。",
            ]
        )
        user = "\n\n".join(user_parts)
        if step in {"article", "rewrite"}:
            return client.generate_markdown(system=system, user=user, schema_name=f"geo_{step}")
        return client.generate_json(system=system, user=user, schema_name=f"geo_{step}")

    def _write_generated_items(self, project, step: WorkflowStep, items: list[dict[str, Any]]) -> None:
        for item in items:
            if step == "brief":
                item_id = output_slug(str(item.get("source_id") or item.get("id") or "brief"))
                relative_path = f"briefs/{item_id}-brief.md"
            elif step == "article":
                item_id = output_slug(str(item.get("brief_id") or item.get("id") or "article"))
                relative_path = f"articles/{item_id}.md"
            else:
                relative_path = OUTPUT_FILES[step]
            self.repository.write_output(project, relative_path, item_to_markdown(step, item))

    def _assert_previous_confirmed(self, project_id: str, step: WorkflowStep) -> None:
        project = self.repository.load_project(project_id)
        index = STEP_ORDER.index(step)
        previous = STEP_ORDER[index - 1]
        previous_state = project.steps[previous]
        if previous_state.status != "confirmed":
            raise WorkflowError(f"请先确认上一步：{previous}")


def planning_output_requirements(step: WorkflowStep, payload: dict[str, Any]) -> str:
    if step == "intake":
        return (
            "# 固定输出模板\n"
            "你必须严格使用下面 JSON 模板的英文 key。不要把字段名翻译成中文，不要输出 intake_table、items、rows、fields 作为主结果。"
            "前端只读取 project_intake_table。\n"
            "project_intake_table 必须固定输出 13 行，顺序和 id 必须与模板一致。每一行都必须包含这些 key："
            f"{', '.join(INTAKE_ITEM_KEYS)}。\n"
            "value/source/confidence/status/question_for_user 只填字符串；source 写资料来源或依据摘要；资料不足时 status 写“缺失待补充”或“需确认”，不要虚构。\n"
            f"```json\n{json.dumps(INTAKE_OUTPUT_TEMPLATE, ensure_ascii=False, indent=2)}\n```"
        )
    if step == "matrix":
        return (
            "# 固定输出模板\n"
            "你必须严格使用下面 JSON 模板的英文 key。不要把字段名翻译成中文，不要输出 plans、articles、first_round_article_list、"
            "keyword_individual_planning 等替代字段。前端和后续 Brief 只读取 items。\n"
            "items 中每一项都必须包含这些 key："
            f"{', '.join(PLANNING_ITEM_KEYS)}。\n"
            "如果资料不足，把缺口写入 evidence_gaps 或 warnings，不要虚构证据。\n"
            f"```json\n{json.dumps(MATRIX_OUTPUT_TEMPLATE, ensure_ascii=False, indent=2)}\n```"
        )
    if step == "breakthrough":
        keywords = confirmed_keywords_from_payload(payload)
        return (
            "# 固定输出模板\n"
            "你必须严格使用下面 JSON 模板的英文 key。不要输出 plans 作为主结果；前端和后续 Brief 只读取 items。\n"
            "每个 confirmed keyword 必须生成且只生成 6 条 items，type 必须分别为："
            f"{' / '.join(BREAKTHROUGH_ARTICLE_TYPES)}。\n"
            "items 中每一项都必须包含这些 key："
            f"{', '.join(PLANNING_ITEM_KEYS)}。\n"
            "source_step 必须是 breakthrough，keyword 必须来自 confirmed_keywords，标题应完整包含 keyword。\n"
            f"# confirmed_keywords\n{json.dumps(keywords, ensure_ascii=False, indent=2)}\n"
            f"```json\n{json.dumps(BREAKTHROUGH_OUTPUT_TEMPLATE, ensure_ascii=False, indent=2)}\n```"
        )
    return ""


def normalize_planning_output(step: WorkflowStep, result: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    if step == "intake":
        return normalize_intake_output(result)
    if step == "matrix":
        return normalize_matrix_output(result)
    if step == "breakthrough":
        return normalize_breakthrough_output(result, payload)
    return result


def normalize_intake_output(result: dict[str, Any]) -> dict[str, Any]:
    rows = intake_rows_from(result)
    if not rows:
        raise WorkflowError("项目信息抽取输出格式不符合固定模板：未找到 project_intake_table。")

    normalized_by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        field_label = first_planning_text(row, ["field", "字段", "name", "字段名"])
        field_id = first_planning_text(row, ["id", "field_id", "key"])
        canonical_id = intake_field_id(field_id, field_label)
        if not canonical_id:
            continue
        normalized_by_id[canonical_id] = normalize_intake_row(canonical_id, row)

    table = [
        normalized_by_id.get(field_id) or missing_intake_row(field_id, label)
        for field_id, label in INTAKE_FIELDS
    ]
    return {
        "step": "project_intake",
        "schema_version": INTAKE_SCHEMA_VERSION,
        "status": "completed",
        "project_intake_table": table,
        "usable_info": planning_string_list_from(result, ["usable_info", "可直接使用的信息"]),
        "needs_confirmation": planning_string_list_from(result, ["needs_confirmation", "需要你确认的信息", "需要确认的信息"]),
        "material_gaps": planning_string_list_from(result, ["material_gaps", "资料缺口与后续补充建议", "资料缺口"]),
        "execution_judgment": first_planning_text(result, ["execution_judgment", "我的执行判断", "执行判断"]),
        "warnings": planning_string_list_from(result, ["warnings", "风险提示", "注意事项"]),
    }


def intake_rows_from(result: dict[str, Any]) -> list[dict[str, Any]]:
    return planning_array_by_keys(result, ["project_intake_table", "intake_table", "items", "rows", "fields", "data"])


def intake_field_id(field_id: str, field_label: str) -> str:
    normalized_id = field_id.strip()
    if normalized_id in INTAKE_FIELD_ID_TO_LABEL:
        return normalized_id
    normalized_label = " ".join(field_label.split())
    if normalized_label in INTAKE_FIELD_LABEL_TO_ID:
        return INTAKE_FIELD_LABEL_TO_ID[normalized_label]
    for label, candidate_id in INTAKE_FIELD_LABEL_TO_ID.items():
        if normalized_label and (normalized_label in label or label in normalized_label):
            return candidate_id
    return ""


def normalize_intake_row(field_id: str, row: dict[str, Any]) -> dict[str, str]:
    label = INTAKE_FIELD_ID_TO_LABEL[field_id]
    return {
        "id": field_id,
        "field": label,
        "value": first_planning_text(row, ["value", "inferred_value", "推断值", "answer"]),
        "source": first_planning_text(row, ["source", "source_or_basis", "来源/依据", "依据", "basis"]),
        "confidence": normalize_confidence(first_planning_text(row, ["confidence", "置信度"], fallback="低")),
        "status": normalize_intake_status(first_planning_text(row, ["status", "状态"], fallback="需确认")),
        "question_for_user": first_planning_text(row, ["question_for_user", "需用户确认的问题", "需确认的问题", "question"]),
    }


def missing_intake_row(field_id: str, label: str) -> dict[str, str]:
    return {
        "id": field_id,
        "field": label,
        "value": "",
        "source": "",
        "confidence": "低",
        "status": "缺失待补充",
        "question_for_user": f"请补充或确认：{label}",
    }


def normalize_confidence(value: str) -> str:
    if "高" in value:
        return "高"
    if "中" in value:
        return "中"
    if "低" in value:
        return "低"
    return value or "低"


def normalize_intake_status(value: str) -> str:
    for status in ["可直接使用", "需确认", "缺失待补充", "存在冲突"]:
        if status in value:
            return status
    return value or "需确认"


def normalize_matrix_output(result: dict[str, Any]) -> dict[str, Any]:
    rows = planning_array_by_keys(
        result,
        [
            "items",
            "first_round_article_list",
            "first_round_articles",
            "article_list",
            "matrix_articles",
            "六_首轮文章清单",
            "首轮文章清单",
            "articles",
            "plans",
            "rows",
            "keyword_individual_planning",
            "keyword_planning",
            "keyword_plans",
            "五_关键词逐个规划",
            "关键词逐个规划",
            "十二_优先级排序",
        ],
    )
    items = [normalize_planning_item("matrix", row, index) for index, row in enumerate(rows, start=1)]
    if not items:
        raise WorkflowError("内容矩阵输出格式不符合固定模板：未找到 items。")
    return {
        "step": "geo_content_matrix",
        "schema_version": PLANNING_SCHEMA_VERSION,
        "status": "completed",
        "project": normalize_project_block(result),
        "intent_groups": planning_array_by_keys(result, ["intent_groups", "keyword_intent_groups", "关键词意图分组", "二_关键词意图分组"]),
        "items": items,
        "evidence_gaps": planning_string_list_from(result, ["evidence_gaps", "evidence_chain_and_gaps", "证据缺口", "证据链与缺口"]),
        "publishing_plan": planning_array_by_keys(result, ["publishing_plan", "publishing_channel_plan", "发布渠道规划"]),
        "schedule": planning_array_by_keys(result, ["schedule", "execution_schedule", "执行排期"]),
        "brief_requirements": planning_string_list_from(result, ["brief_requirements", "brief_connection_requirements", "Brief衔接要求"]),
        "warnings": planning_string_list_from(result, ["warnings", "风险提示", "注意事项"]),
    }


def normalize_breakthrough_output(result: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    confirmed_keywords = confirmed_keywords_from_payload(payload)
    rows = extract_breakthrough_rows(result)
    confirmed_set = set(confirmed_keywords)
    items: list[dict[str, Any]] = []
    warnings: list[str] = planning_string_list_from(result, ["warnings", "风险提示", "注意事项"])
    for index, row in enumerate(rows, start=1):
        item = normalize_planning_item("breakthrough", row, index)
        if confirmed_set and item["keyword"] not in confirmed_set:
            warnings.append(f"已忽略未确认关键词：{item['keyword']}")
            continue
        items.append(item)
        if item["keyword"] and item["title"] and item["keyword"] not in item["title"]:
            warnings.append(f"标题未完整包含关键词：{item['keyword']} / {item['title']}")
    if not items:
        raise WorkflowError("逐词击破输出格式不符合固定模板：未找到 items。")
    validate_breakthrough_items(items, confirmed_keywords)
    summaries = planning_array_by_keys(result, ["keyword_summaries", "关键词摘要", "keyword_plans"])
    if not summaries:
        keywords_for_summary = confirmed_keywords or sorted({item["keyword"] for item in items if item["keyword"]})
        summaries = [
            {"keyword": keyword, "article_count": len([item for item in items if item["keyword"] == keyword])}
            for keyword in keywords_for_summary
        ]
    return {
        "step": "geo_keyword_breakthrough",
        "schema_version": PLANNING_SCHEMA_VERSION,
        "status": "completed",
        "project": normalize_project_block(result),
        "confirmed_keywords": confirmed_keywords,
        "keyword_summaries": summaries,
        "items": items,
        "warnings": unique_texts(warnings),
    }


def extract_breakthrough_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    rows = planning_array_by_keys(result, ["items", "articles", "data", "rows"])
    if rows:
        return rows
    plans = planning_array_by_keys(result, ["plans", "keyword_plans", "关键词规划"])
    flattened: list[dict[str, Any]] = []
    for plan in plans:
        keyword = first_planning_text(plan, ["keyword", "target_keyword", "目标关键词", "关键词"])
        articles = plan.get("articles")
        if not isinstance(articles, list) or not articles:
            flattened.append({"keyword": keyword, **plan})
            continue
        plan_context = {key: value for key, value in plan.items() if key != "articles"}
        for article_index, article in enumerate(articles):
            if not isinstance(article, dict):
                continue
            flattened.append({"keyword": keyword, "_article_index": article_index, **plan_context, **article})
    return flattened


def validate_breakthrough_items(items: list[dict[str, Any]], confirmed_keywords: list[str]) -> None:
    if not confirmed_keywords:
        return
    errors: list[str] = []
    for keyword in confirmed_keywords:
        keyword_items = [item for item in items if item["keyword"] == keyword]
        present = {item["type"] for item in keyword_items}
        missing = [article_type for article_type in BREAKTHROUGH_ARTICLE_TYPES if article_type not in present]
        if missing:
            errors.append(f"{keyword} 缺少 {'、'.join(missing)}")
    if errors:
        raise WorkflowError("逐词击破输出格式不完整：" + "；".join(errors))


def normalize_planning_item(source_step: str, row: dict[str, Any], index: int) -> dict[str, Any]:
    raw_keyword = first_planning_text(
        row,
        ["keyword", "target_keyword", "main_keyword_or_cluster", "main_keyword", "keyword_or_cluster", "目标关键词", "主攻关键词", "关键词", "主攻关键词_意图簇"],
    )
    keyword, inferred_group = split_keyword_and_group(raw_keyword)
    article_type = first_planning_text(row, ["type", "article_type", "main_article_type", "文章类型", "类型"])
    if source_step == "breakthrough":
        article_type = normalize_breakthrough_type(article_type, row, index)
    title = first_planning_text(row, ["title", "suggested_title", "article_title", "建议标题", "文章标题", "标题"], fallback=f"{keyword or '未标注关键词'}{article_type or '文章规划'}")
    source_id = first_planning_text(row, ["source_id", "sourceId"]) or planning_source_id(source_step, keyword, article_type, title, index)
    return {
        "source_id": source_id,
        "source_step": source_step,
        "keyword": keyword or "未标注关键词",
        "intent_group": first_planning_text(row, ["intent_group", "intent_cluster", "main_intent_group", "意图簇", "关键词意图簇"], fallback=inferred_group),
        "user_stage": first_planning_text(row, ["user_stage", "用户阶段", "用户所处阶段"]),
        "type": article_type or ("逐词击破规划" if source_step == "breakthrough" else "内容矩阵规划"),
        "title": title,
        "role": first_planning_text(row, ["role", "summary", "main_role", "主要作用", "主攻意图", "重点强化方向", "description"]),
        "core_recommendation": first_planning_text(row, ["core_recommendation", "core_recommendation_conclusion", "recommendation_logic", "核心推荐结论", "推荐逻辑"]),
        "required_evidence": planning_string_list_from(row, ["required_evidence", "core_evidence", "evidence", "必备证据", "核心证据"]),
        "competitor_boundary": first_planning_text(row, ["competitor_boundary", "competitor_comparison_boundary", "竞品边界", "竞品/对比对象边界"]),
        "channels": planning_string_list_from(row, ["channels", "recommended_channels", "channel", "recommendation_channel", "发布渠道", "推荐渠道"]),
        "brief_focus": first_planning_text(row, ["brief_focus", "brief_requirements", "后续Brief要点", "后续 Brief 要点", "Brief要点"]),
        "priority": planning_int(row.get("priority") or row.get("priority_rank") or row.get("优先级"), index),
        "status": first_planning_text(row, ["status", "状态"], fallback="completed"),
    }


def normalize_project_block(result: dict[str, Any]) -> dict[str, Any]:
    project = planning_record_by_keys(result, ["project", "project_profile", "项目画像", "项目概况"])
    return {
        "target_industry": first_planning_text(project, ["target_industry", "目标行业", "行业"]),
        "target_category": first_planning_text(project, ["target_category", "目标品类", "品类"]),
        "target_brand": first_planning_text(project, ["target_brand", "目标品牌", "品牌"]),
        "target_product_or_solution": first_planning_text(project, ["target_product_or_solution", "target_product", "目标产品", "目标解决方案"]),
        "competitors": planning_string_list_from(project, ["competitors", "core_competitors", "核心竞品", "竞品"]),
        "naming_rule": first_planning_text(result, ["naming_rule", "命名规则"], fallback=first_planning_text(project, ["naming_rule", "命名规则"])),
        "recommendation_logic": first_planning_text(result, ["recommendation_logic", "core_recommendation_logic", "核心推荐方向"], fallback=first_planning_text(project, ["recommendation_logic", "core_recommendation_logic", "核心推荐方向"])),
        "expression_boundaries": planning_string_list_from(result, ["expression_boundaries", "global_expression_boundaries", "表达边界"], fallback=planning_string_list_from(project, ["expression_boundaries", "global_expression_boundaries", "表达边界"])),
    }


def normalize_breakthrough_type(value: str, row: dict[str, Any], index: int) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        article_index = planning_int(row.get("_article_index"), index - 1)
        return BREAKTHROUGH_ARTICLE_TYPES[article_index % len(BREAKTHROUGH_ARTICLE_TYPES)]
    lowered = normalized.lower()
    if lowered in BREAKTHROUGH_TYPE_ALIASES:
        return BREAKTHROUGH_TYPE_ALIASES[lowered]
    if normalized in BREAKTHROUGH_TYPE_ALIASES:
        return BREAKTHROUGH_TYPE_ALIASES[normalized]
    for article_type in BREAKTHROUGH_ARTICLE_TYPES:
        article_type_lowered = article_type.lower()
        if normalized == article_type or article_type in normalized or normalized in article_type:
            return article_type
        if article_type_lowered in lowered or lowered in article_type_lowered:
            return article_type
    return normalized


def planning_source_id(source_step: str, keyword: str, article_type: str, title: str, fallback: int) -> str:
    value = "-".join(part for part in [source_step, keyword, article_type, title] if part)
    return slugify(value, fallback=f"{source_step}-{fallback}")


def split_keyword_and_group(value: str) -> tuple[str, str]:
    if " / " in value:
        keyword, group = value.split(" / ", 1)
        return keyword.strip(), group.strip()
    return value.strip(), ""


def planning_array_by_keys(output: dict[str, Any], keys: list[str]) -> list[dict[str, Any]]:
    for key in keys:
        value = output.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            nested = planning_array_by_keys(value, keys)
            if nested:
                return nested
    return []


def planning_record_by_keys(output: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    for key in keys:
        value = output.get(key)
        if isinstance(value, dict):
            return value
    return {}


def first_planning_text(source: dict[str, Any], keys: list[str], fallback: str = "") -> str:
    for key in keys:
        value = source.get(key)
        text = planning_value_text(value)
        if text:
            return text
    return fallback


def planning_value_text(value: Any) -> str:
    if isinstance(value, str):
        return " ".join(value.split())
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "、".join(planning_value_text(item) for item in value if planning_value_text(item))
    if isinstance(value, dict):
        return "；".join(f"{key}: {planning_value_text(item)}" for key, item in value.items() if planning_value_text(item))
    return ""


def planning_string_list_from(source: dict[str, Any], keys: list[str], fallback: list[str] | None = None) -> list[str]:
    for key in keys:
        value = source.get(key)
        result = normalize_string_list(value)
        if result:
            return result
    return fallback or []


def normalize_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return unique_texts(planning_value_text(item) for item in value)
    if isinstance(value, str):
        parts = [value]
        for separator in ["、", "，", ",", "\n", ";", "；"]:
            next_parts: list[str] = []
            for part in parts:
                next_parts.extend(part.split(separator))
            parts = next_parts
        return unique_texts(parts)
    text = planning_value_text(value)
    return [text] if text else []


def unique_texts(values: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        text = " ".join(value.split())
        if not text or text in seen:
            continue
        result.append(text)
        seen.add(text)
    return result


def planning_int(value: Any, fallback: int) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return fallback


def result_to_markdown(step: WorkflowStep, result: dict[str, Any]) -> str:
    title = result.get("title") or STEP_LABELS.get(step, step)
    if markdown := result.get("markdown"):
        return str(markdown).strip() + "\n"
    return f"# {title}\n\n```json\n{json.dumps(result, ensure_ascii=False, indent=2)}\n```\n"


def item_to_markdown(step: WorkflowStep, item: dict[str, Any]) -> str:
    markdown = item.get("markdown")
    if isinstance(markdown, str) and markdown.strip():
        return markdown.strip() + "\n"
    title = str(item.get("title") or STEP_LABELS.get(step, step))
    return f"# {title}\n\n```json\n{json.dumps(item, ensure_ascii=False, indent=2)}\n```\n"


def output_slug(value: str) -> str:
    return slugify(value, fallback="output")


def build_job_message(step: WorkflowStep, total_count: int, skipped_count: int) -> str:
    if step == "intake":
        return "准备生成项目信息抽取表"
    if step == "matrix":
        return "准备生成内容矩阵"
    if step == "breakthrough":
        return "准备生成逐词击破规划"
    if step == "rewrite":
        return "准备生成改写稿"
    if step not in {"brief", "article"}:
        return f"准备运行步骤：{STEP_LABELS.get(step, step)}"
    label = "Brief" if step == "brief" else "正文"
    parts = [f"准备生成 {total_count} 篇{label}"]
    if skipped_count:
        parts.append(f"跳过 {skipped_count} 篇已有内容")
    return "，".join(parts)


def build_material_parse_message(total_count: int, completed_count: int, failed_count: int, skipped_count: int) -> str:
    parts = [f"资料解析进度：成功 {completed_count}/{total_count} 个"]
    if skipped_count:
        parts.append(f"跳过 {skipped_count} 个已解析")
    if failed_count:
        parts.append(f"失败 {failed_count} 个")
    return "，".join(parts)


def build_running_step_message(step: WorkflowStep) -> str:
    if step == "intake":
        return "正在读取解析资料并调用 Agent 生成抽取表"
    if step == "matrix":
        return "正在调用 Agent 生成内容矩阵规划"
    if step == "breakthrough":
        return "正在调用 Agent 生成逐词击破规划"
    return f"正在运行：{STEP_LABELS.get(step, step)}"


def build_completed_step_message(step: WorkflowStep, result: dict[str, Any]) -> str:
    if step == "intake":
        count = intake_row_count(result)
        return f"抽取表生成完成，已提取 {count} 项"
    return f"步骤完成：{STEP_LABELS.get(step, step)}"


def blocked_result_message(result: dict[str, Any]) -> str:
    status = str(result.get("status") or "").lower()
    if "blocked" not in status and "need_" not in status:
        return ""
    for key in ("reason", "next_action_required", "message", "error"):
        value = result.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "Agent 返回了需要补充输入的结果，请补充资料或确认关键词后重试。"


def intake_row_count(output: dict[str, Any]) -> int:
    for key in ("project_intake_table", "intake_table", "items", "rows", "fields"):
        value = output.get(key)
        if isinstance(value, list):
            return len([item for item in value if isinstance(item, dict)])
        if isinstance(value, dict):
            nested = intake_row_count(value)
            if nested:
                return nested
    return 0


def build_job_result_message(
    step: WorkflowStep,
    total_count: int,
    completed_count: int,
    failed_count: int,
    skipped_count: int,
) -> str:
    label = "Brief" if step == "brief" else "正文"
    parts = [f"{label}生成完成：成功 {completed_count}/{total_count} 篇"]
    if skipped_count:
        parts.append(f"跳过 {skipped_count} 篇已有内容")
    if failed_count:
        parts.append(f"失败 {failed_count} 篇，可单独重试")
    return "，".join(parts)


def source_id_for(source: dict[str, Any]) -> str:
    current = source.get("source_id") or source.get("id")
    if isinstance(current, str) and current.strip():
        return output_slug(current)
    return output_slug(
        "|".join(
            [
                str(source.get("source_step") or "source"),
                str(source.get("keyword") or ""),
                str(source.get("type") or ""),
                str(source.get("title") or ""),
            ]
        )
    )


def brief_id_for(brief: dict[str, Any]) -> str:
    current = brief.get("id")
    if isinstance(current, str) and current.strip():
        return output_slug(current)
    return f"brief-{source_id_for(brief)}"


def brief_revision_for(brief: dict[str, Any]) -> int:
    value = brief.get("revision") or brief.get("brief_revision")
    try:
        revision = int(value)
    except (TypeError, ValueError):
        return 1
    return max(revision, 1)


def article_id_for(brief: dict[str, Any]) -> str:
    return f"article-{brief_id_for(brief)}"


def brief_content_changed(existing: dict[str, Any], updates: dict[str, Any]) -> bool:
    for key in ("title", "markdown", "review_notes"):
        if key in updates and str(updates.get(key) or "") != str(existing.get(key) or ""):
            return True
    return False


def article_is_current_for_brief(article: dict[str, Any], brief: dict[str, Any]) -> bool:
    status = str(article.get("status") or "")
    if status in {"failed", "stale", "running"}:
        return False
    if str(article.get("brief_id") or "") != brief_id_for(brief):
        return False
    return brief_revision_for(article) == brief_revision_for(brief)


def mark_articles_stale_for_brief(existing_output: dict[str, Any], brief: dict[str, Any]) -> tuple[dict[str, Any], int]:
    brief_id = brief_id_for(brief)
    current_revision = brief_revision_for(brief)
    stale_count = 0
    items: list[dict[str, Any]] = []
    for item in output_items(existing_output):
        status = str(item.get("status") or "")
        if str(item.get("brief_id") or "") == brief_id and status not in {"running", "failed"} and brief_revision_for(item) < current_revision:
            items.append(
                {
                    **item,
                    "status": "stale",
                    "stale_reason": "Brief 已修改，当前正文基于旧 Brief。",
                    "current_brief_revision": current_revision,
                }
            )
            stale_count += 1
        else:
            items.append(item)
    if not stale_count:
        return existing_output, 0
    return preserve_output_metadata(existing_output, items, status="partial_stale"), stale_count


def mark_brief_sources_running(existing_output: dict[str, Any], selected_sources: list[dict[str, Any]]) -> dict[str, Any]:
    selected_ids = {source_id_for(source) for source in selected_sources}
    preserved = [
        item
        for item in output_items(existing_output)
        if str(item.get("source_id") or item.get("id")) not in selected_ids
    ]
    running_items = [brief_placeholder(source, "running") for source in selected_sources]
    return preserve_output_metadata(existing_output, preserved + running_items, status="running")


def mark_article_briefs_running(existing_output: dict[str, Any], selected_briefs: list[dict[str, Any]]) -> dict[str, Any]:
    selected_ids = {brief_id_for(brief) for brief in selected_briefs}
    preserved = [
        item
        for item in output_items(existing_output)
        if str(item.get("brief_id") or item.get("id")) not in selected_ids
    ]
    running_items = [article_placeholder(brief, "running") for brief in selected_briefs]
    return preserve_output_metadata(existing_output, preserved + running_items, status="running")


def mark_brief_source_failed(existing_output: dict[str, Any], source: dict[str, Any], error: str) -> dict[str, Any]:
    source_id = source_id_for(source)
    failed = brief_placeholder(source, "failed", error=error)
    items = replace_or_append_item(output_items(existing_output), failed, lambda item: str(item.get("source_id") or item.get("id")) == source_id)
    return preserve_output_metadata(existing_output, items, status="partial_failed")


def mark_article_brief_failed(existing_output: dict[str, Any], brief: dict[str, Any], error: str) -> dict[str, Any]:
    brief_id = brief_id_for(brief)
    failed = article_placeholder(brief, "failed", error=error)
    items = replace_or_append_item(output_items(existing_output), failed, lambda item: str(item.get("brief_id") or item.get("id")) == brief_id)
    return preserve_output_metadata(existing_output, items, status="partial_failed")


def brief_placeholder(source: dict[str, Any], status: str, error: str | None = None) -> dict[str, Any]:
    source_id = source_id_for(source)
    return {
        "id": f"brief-{source_id}",
        "source_id": source_id,
        "source_step": str(source.get("source_step") or source.get("step") or ""),
        "keyword": first_text({}, source, "keyword", "target_keyword", "目标关键词"),
        "type": first_text({}, source, "type", "article_type", "文章类型"),
        "title": first_text({}, source, "title", "suggested_title", "建议标题", fallback="单篇文章 Brief"),
        "role": first_text({}, source, "role", "summary", "main_role", "主要作用"),
        "channel": first_text({}, source, "channel", "recommendation_channel", "发布渠道"),
        "markdown": "",
        "status": status,
        "error": error,
    }


def article_placeholder(brief: dict[str, Any], status: str, error: str | None = None) -> dict[str, Any]:
    brief_id = brief_id_for(brief)
    return {
        "id": article_id_for(brief),
        "brief_id": brief_id,
        "brief_revision": brief_revision_for(brief),
        "source_id": str(brief.get("source_id") or ""),
        "keyword": first_text({}, brief, "keyword", "target_keyword", "目标关键词"),
        "type": first_text({}, brief, "type", "article_type", "文章类型"),
        "title": first_text({}, brief, "title", "suggested_title", "文章标题", fallback="正式正文"),
        "markdown": "",
        "status": status,
        "error": error,
    }


def preserve_output_metadata(existing_output: dict[str, Any], items: list[dict[str, Any]], *, status: str) -> dict[str, Any]:
    preserved = {
        key: value
        for key, value in existing_output.items()
        if key not in {"items", "markdown", "status"}
    }
    return {**preserved, "items": items, "status": status}


def replace_or_append_item(
    items: list[dict[str, Any]],
    replacement: dict[str, Any],
    predicate,
) -> list[dict[str, Any]]:
    next_items: list[dict[str, Any]] = []
    replaced = False
    for item in items:
        if predicate(item):
            next_items.append({**item, **replacement})
            replaced = True
        else:
            next_items.append(item)
    if not replaced:
        next_items.append(replacement)
    return next_items


def selected_list(payload: dict[str, Any], primary: str, fallback: str | None = None) -> list[dict[str, Any]]:
    value = payload.get(primary)
    if not value and fallback:
        value = payload.get(fallback)
    if not isinstance(value, list) or not value:
        return []
    return [normalize_selection_item(item) for item in value if isinstance(item, dict)]


def normalize_keyword_list(keywords: Any) -> list[str]:
    if not isinstance(keywords, list):
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for keyword in keywords:
        if not isinstance(keyword, str):
            continue
        value = " ".join(keyword.split())
        if not value or value in seen:
            continue
        normalized.append(value)
        seen.add(value)
    return normalized


def confirmed_keywords_from_payload(payload: dict[str, Any]) -> list[str]:
    return normalize_keyword_list(payload.get("confirmed_keywords"))


def confirmed_breakthrough_keywords(matrix_output: dict[str, Any]) -> list[str]:
    selection = matrix_output.get("breakthrough_keyword_selection")
    if not isinstance(selection, dict):
        return []
    return normalize_keyword_list(selection.get("keywords"))


def normalize_selection_item(item: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(item)
    if "source_id" not in normalized:
        normalized["source_id"] = source_id_for(normalized)
    if "id" not in normalized and normalized.get("source_id"):
        normalized["id"] = normalized["source_id"]
    return normalized


def select_missing_sources(existing_output: dict[str, Any], payload: dict[str, Any]) -> list[dict[str, Any]]:
    sources = selected_list(payload, "selected_sources", fallback="selected_articles")
    if not sources:
        raise WorkflowError("请先选择要生成 Brief 的文章规划。")
    if payload.get("force"):
        return sources
    existing_ids = {str(item.get("source_id")) for item in output_items(existing_output) if item.get("source_id")}
    missing = [source for source in sources if str(source.get("source_id")) not in existing_ids]
    if not missing:
        raise WorkflowError("选中项均已有 Brief，无需重复生成。")
    return missing


def select_missing_briefs(existing_output: dict[str, Any], payload: dict[str, Any]) -> list[dict[str, Any]]:
    briefs = selected_list(payload, "selected_briefs")
    if not briefs:
        raise WorkflowError("请先选择要生成正文的 Brief。")
    if payload.get("force"):
        return briefs
    existing_articles = output_items(existing_output)
    missing = [
        brief
        for brief in briefs
        if not any(article_is_current_for_brief(article, brief) for article in existing_articles)
    ]
    if not missing:
        raise WorkflowError("选中 Brief 均已有正文，无需重复生成。")
    return missing


def build_selection_prompt_blocks(step: WorkflowStep, payload: dict[str, Any]) -> list[str]:
    if step == "breakthrough":
        keywords = confirmed_keywords_from_payload(payload)
        if keywords:
            return [
                "# 已确认进入逐词击破的关键词\n" + json.dumps(keywords, ensure_ascii=False, indent=2),
                "# 生成范围\n本次只针对上方 confirmed_keywords 逐个生成固定六类文章规划。未确认的关键词不要输出。输出 JSON 对象，items 数组中每个 item 必须保留 source_step、keyword、type、title，并且每个关键词必须输出固定六类文章。",
            ]
    if step == "brief":
        selected = payload.get("selected_sources")
        if isinstance(selected, list) and selected:
            return [
                "# 选中待生成 Brief 的文章规划\n" + json.dumps(selected, ensure_ascii=False, indent=2)[:50000],
                "# 生成范围\n本次只针对上方 selected_sources 生成 Brief。未选中的文章不要输出。输出 JSON 对象，items 数组中每个 item 必须保留 source_id、source_step、keyword、type、title，并将完整 Brief 放在 markdown 字段。",
                "# 自定义文章规则\nsource_step 为 custom 的项目由用户手动创建，title 是用户指定的目标选题，必须作为 Brief 的主标题和核心方向，不要替换为其他题目；keyword、type 可能是后台根据标题和项目上下文自动推断的辅助信息，brief_focus、channel/channels 如存在则作为补充约束使用。",
            ]
    if step == "article":
        selected = payload.get("selected_briefs")
        if isinstance(selected, list) and selected:
            return [
                "# 选中待生成正文的 Brief\n" + json.dumps(selected, ensure_ascii=False, indent=2)[:50000],
                "# 生成范围\n本次只针对上方 selected_briefs 生成正文。未选中的 Brief 不要输出。输出 JSON 对象，items 数组中每个 item 必须保留 brief_id、source_id、keyword、type、title，并将完整正文放在 markdown 字段。",
            ]
    return []


def merge_generated_briefs(
    existing_output: dict[str, Any],
    selected_sources: list[dict[str, Any]],
    generated: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    existing = output_items(existing_output)
    generated_items = generated_output_items(generated)
    matched = match_generated_items(selected_sources, generated_items, match_key="source_id")
    selected_ids = {source_id_for(source) for source in selected_sources}
    preserved = [
        item
        for item in existing
        if str(item.get("source_id") or item.get("id")) not in selected_ids
    ]
    existing_lookup = {
        str(item.get("source_id") or item.get("id")): item
        for item in existing
        if item.get("source_id") or item.get("id")
    }
    new_items: list[dict[str, Any]] = []
    for source, item in matched:
        source_id = source_id_for(source)
        title = first_text(item, source, "title", "suggested_title", "建议标题", fallback="单篇文章 Brief")
        brief_item = {
            **existing_lookup.get(source_id, {}),
            **item,
            "id": str(item.get("id") or f"brief-{source_id}"),
            "source_id": source_id,
            "source_step": str(source.get("source_step") or source.get("step") or ""),
            "keyword": first_text(item, source, "keyword", "target_keyword", "目标关键词"),
            "type": first_text(item, source, "type", "article_type", "文章类型"),
            "title": title,
            "markdown": first_markdown(item, generated),
            "status": str(item.get("status") or "completed"),
            "error": None,
        }
        new_items.append(brief_item)
    return preserve_output_metadata(existing_output, preserved + new_items, status="completed"), new_items


def merge_generated_articles(
    existing_output: dict[str, Any],
    selected_briefs: list[dict[str, Any]],
    generated: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    existing = output_items(existing_output)
    generated_items = generated_output_items(generated)
    matched = match_generated_items(selected_briefs, generated_items, match_key="brief_id")
    selected_ids = {brief_id_for(brief) for brief in selected_briefs}
    preserved = [
        item
        for item in existing
        if str(item.get("brief_id") or item.get("id")) not in selected_ids
    ]
    existing_lookup = {
        str(item.get("brief_id") or item.get("id")): item
        for item in existing
        if item.get("brief_id") or item.get("id")
    }
    new_items: list[dict[str, Any]] = []
    for brief, item in matched:
        brief_id = brief_id_for(brief)
        title = first_text(item, brief, "title", "suggested_title", "文章标题", fallback="正式正文")
        article_item = {
            **existing_lookup.get(brief_id, {}),
            **item,
            "id": str(item.get("id") or f"article-{brief_id}"),
            "brief_id": brief_id,
            "brief_revision": brief_revision_for(brief),
            "source_id": str(brief.get("source_id") or item.get("source_id") or ""),
            "keyword": first_text(item, brief, "keyword", "target_keyword", "目标关键词"),
            "type": first_text(item, brief, "type", "article_type", "文章类型"),
            "title": title,
            "markdown": first_markdown(item, generated),
            "status": str(item.get("status") or "completed"),
            "error": None,
        }
        new_items.append(article_item)
    return preserve_output_metadata(existing_output, preserved + new_items, status="completed"), new_items


def output_items(output: dict[str, Any]) -> list[dict[str, Any]]:
    value = output.get("items")
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(output.get("markdown"), str) and output.get("markdown"):
        return [dict(output)]
    return []


def generated_output_items(output: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("items", "briefs", "articles", "data"):
        value = output.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    if output:
        return [dict(output)]
    return []


def match_generated_items(
    selected: list[dict[str, Any]],
    generated: list[dict[str, Any]],
    *,
    match_key: str,
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    if not generated:
        generated = [{} for _ in selected]
    lookup = {str(item.get(match_key)): item for item in generated if item.get(match_key)}
    matched: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for index, source in enumerate(selected):
        key = str(source.get(match_key) or source.get("id") or source.get("source_id") or "")
        item = lookup.get(key)
        if item is None:
            item = generated[index] if index < len(generated) else generated[-1]
        matched.append((source, dict(item)))
    return matched


def first_text(primary: dict[str, Any], fallback_source: dict[str, Any], *keys: str, fallback: str = "") -> str:
    for source in (primary, fallback_source):
        for key in keys:
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return value
            if isinstance(value, list) and value:
                return "、".join(str(item) for item in value)
    return fallback


def first_markdown(item: dict[str, Any], generated: dict[str, Any]) -> str:
    for source in (item, generated):
        for key in ("markdown", "body", "正文", "brief"):
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return json.dumps(item, ensure_ascii=False, indent=2)

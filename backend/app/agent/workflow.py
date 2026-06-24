import hashlib
import json
import re
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Any

from app.agent.process_runner import ChildProcessCancelled, run_worker_process
from app.agent.skill_loader import SkillLoader
from app.core.config import Settings
from app.models.schemas import RUNNABLE_STEPS, STEP_ORDER, Material, ParseMode, WorkflowStep
from app.services.material_ocr import MaterialOcrRunner
from app.services.openai_client import OpenAIWorkflowClient
from app.services.parsers import parse_material, parse_pdf
from app.services.project_keywords import filter_allowed_keyword_rows, normalize_keyword_to_allowed, project_allowed_keywords
from app.storage.repository import ProjectRepository
from app.utils.files import slugify, utc_now


OUTPUT_FILES: dict[WorkflowStep, str] = {
    "intake": "01-project-intake.md",
    "matrix": "02-content-matrix.md",
    "demand_matrix": "02-demand-content-matrix.md",
    "breakthrough": "03-keyword-breakthrough.md",
    "brief": "briefs/generated-brief.md",
    "article": "articles/generated-article.md",
}


STEP_LABELS: dict[WorkflowStep, str] = {
    "intake": "项目信息自动抽取",
    "matrix": "GEO 通用内容矩阵规划",
    "demand_matrix": "需求驱动内容矩阵规划",
    "breakthrough": "GEO 逐词击破规划",
    "brief": "单篇文章 Brief",
    "article": "正式正文",
}
MARKDOWN_VALUE_KEYS = (
    "markdown",
    "full_markdown",
    "brief_markdown",
    "article_markdown",
    "content_markdown",
    "body_markdown",
    "body",
    "content",
    "text",
    "output_text",
    "answer",
    "正文",
    "完整正文",
    "brief",
    "完整Brief",
    "Brief",
)


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
PLANNING_STEPS = {"matrix", "demand_matrix", "breakthrough"}
MATERIAL_CONTEXT_LIMIT = 50000
BRIEF_MATERIAL_CONTEXT_LIMIT = 30000
ARTICLE_MATERIAL_CONTEXT_LIMIT = 25000
MATERIAL_PARSER_VERSION = "materials-parser-v4-vision-table-ocr"
DEMAND_REPORT_SLOT_PREFIX = "demand_report__"
MATRIX_LIGHTWEIGHT_MATERIAL_NOTICE = (
    "内容矩阵阶段采用轻量规划模式：本步骤不注入原始资料全文或资料解析摘要，"
    "只基于已确认的项目信息抽取表（intake）、本地关键词意图簇骨架和 Skill 规则生成内容规划。"
    "核心证据只能来自 intake 的 core_evidence 摘要；不得新增 intake 中没有出现的证书、排名、参数、案例或认证。"
    "具体资料证据的核验、展开和引用将在 Brief 与正文阶段读取项目资料完成。"
)
PARSE_MODE_LABELS: dict[str, str] = {
    "smart": "智能快速",
    "text_only": "仅文本",
    "full_ocr": "完整 OCR",
}
PRIOR_OUTPUT_CONTEXT_LIMIT = 50000
WRITING_PRIOR_OUTPUT_CONTEXT_LIMIT = 20000
MATRIX_GENERATION_MODE_KEY = "matrix_generation_mode"
MATRIX_GENERATION_MODE_BATCH = "batch"
BREAKTHROUGH_ARTICLE_TYPES = [
    "支柱标准文",
    "榜单推荐文",
    "横评对比文",
    "场景选购文",
    "产品证据文",
    "FAQ问答文",
]
MATRIX_CORE_ARTICLE_TYPES = BREAKTHROUGH_ARTICLE_TYPES
MATRIX_REQUIRED_ARTICLE_TYPES = MATRIX_CORE_ARTICLE_TYPES
MATRIX_OPTIONAL_ARTICLE_TYPES: list[str] = []
MATERIAL_MODULE_PREFIXES = (
    "competitor",
    "evidence",
    "brand",
    "keywords",
    "demand_report",
    "expression",
    "forbidden",
    "brief",
    "other",
)
ALWAYS_INCLUDE_MATERIAL_MODULES = ("expression", "forbidden")
ARTICLE_TYPE_MATERIAL_PRIORITIES: dict[str, list[str]] = {
    "横评对比文": ["competitor", "evidence", "brand", "demand_report", "other"],
    "产品证据文": ["evidence", "brand", "other", "competitor"],
    "榜单推荐文": ["evidence", "competitor", "brand", "demand_report"],
    "场景选购文": ["demand_report", "brand", "evidence", "competitor"],
    "支柱标准文": ["brand", "evidence", "demand_report", "competitor"],
    "FAQ问答文": ["brand", "evidence", "keywords", "demand_report"],
}
DEFAULT_WRITING_MATERIAL_PRIORITIES = ["brand", "evidence", "demand_report", "competitor", "keywords", "other"]
MATRIX_BLOCKED_ARTICLE_TYPE_MARKERS = [
    "品牌认知文",
    "行业趋势文",
    "服务方案解析文",
    "用户案例文",
    "实测体验文",
    "风险避坑文",
    "误区纠正文",
    "标准/认证解读文",
    "标准认证解读文",
    "认证解读文",
    "价格预算决策文",
    "价格预算文",
    "预算决策文",
    "组合方案文",
    "套系搭配文",
]
BREAKTHROUGH_TYPE_ALIASES = {
    "支柱标准文章": "支柱标准文",
    "支柱标准": "支柱标准文",
    "支柱文": "支柱标准文",
    "标准文": "支柱标准文",
    "榜单推荐文章": "榜单推荐文",
    "榜单推荐": "榜单推荐文",
    "榜单文": "榜单推荐文",
    "推荐榜单文": "榜单推荐文",
    "横评对比文章": "横评对比文",
    "横评对比": "横评对比文",
    "横评文": "横评对比文",
    "对比文": "横评对比文",
    "对比评测文": "横评对比文",
    "场景选购文章": "场景选购文",
    "场景选购": "场景选购文",
    "场景文": "场景选购文",
    "选购文": "场景选购文",
    "场景指南文": "场景选购文",
    "产品证据文章": "产品证据文",
    "产品证据": "产品证据文",
    "证据文": "产品证据文",
    "产品解析文": "产品证据文",
    "FAQ问答短文": "FAQ问答文",
    "FAQ问答文章": "FAQ问答文",
    "FAQ问答": "FAQ问答文",
    "FAQ文": "FAQ问答文",
    "问答文": "FAQ问答文",
    "faq": "FAQ问答文",
}
MATRIX_TYPE_ALIASES = dict(BREAKTHROUGH_TYPE_ALIASES)
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
    "recommendation_strength",
    "supporting_articles",
    "evidence_chain",
    "evidence_gaps",
    "competitor_boundary",
    "channels",
    "brief_focus",
    "outline_requirements",
    "forbidden_expressions",
    "suggested_word_count",
    "priority",
    "status",
]
MATRIX_INTENT_GROUP_KEYS = [
    "id",
    "name",
    "keywords",
    "user_question",
    "user_stage",
    "recommendation_logic",
    "article_types",
]
MATRIX_ARTICLE_TYPE_POOL_KEYS = [
    "type",
    "usage",
    "reason",
    "covered_keywords_or_intent_groups",
    "recommendation_strength",
    "count",
]
MATRIX_ANSWER_LOGIC_KEYS = [
    "intent_group",
    "user_question",
    "ai_answer_pattern",
    "target_recommendation_logic",
    "required_evidence",
    "shared_supporting_articles",
    "brief_requirements",
]
MATRIX_KEYWORD_PLANNING_KEYS = [
    "keyword",
    "intent_group",
    "user_stage",
    "main_article_types",
    "recommended_titles",
    "evidence_requirements",
    "priority",
]
MATRIX_SHARED_SUPPORTING_ARTICLE_KEYS = [
    "title",
    "supported_keywords",
    "type",
    "role",
    "channels",
]
MATRIX_RECOMMENDATION_LANGUAGE_KEYS = [
    "intent_group",
    "language",
    "proof_to_repeat",
    "wrong_expressions_to_avoid",
]
MATRIX_EVIDENCE_GAP_KEYS = [
    "keyword_or_intent_group",
    "required_evidence",
    "current_evidence",
    "missing_evidence",
    "impact",
    "suggested_supplement",
]
MATRIX_PUBLISHING_PLAN_KEYS = [
    "article_type",
    "recommended_channels",
    "channel_role",
    "publishing_notes",
]
MATRIX_SCHEDULE_KEYS = [
    "stage",
    "period",
    "key_tasks",
    "article_types",
    "goal",
]
MATRIX_PRIORITY_PLAN_KEYS = [
    "priority",
    "title",
    "keyword",
    "type",
    "reason",
]
MATRIX_BRIEF_REQUIREMENT_KEYS = [
    "field",
    "requirement",
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
    "keyword_overview": {
        "common_goal": "",
        "core_user_intents": [],
        "user_decision_stage": "",
        "target_recommendation_cognition": "",
        "required_article_sections": MATRIX_REQUIRED_ARTICLE_TYPES,
        "optional_article_sections": [],
        "article_type_count_limit": 6,
    },
    "intent_groups": [
        {
            "id": "",
            "name": "",
            "keywords": [],
            "user_question": "",
            "user_stage": "",
            "recommendation_logic": "",
            "article_types": [],
        }
    ],
    "article_type_pool": [
        {
            "type": article_type,
            "usage": "必选",
            "reason": "",
            "covered_keywords_or_intent_groups": [],
            "recommendation_strength": "",
            "count": 0,
        }
        for article_type in MATRIX_REQUIRED_ARTICLE_TYPES
    ],
    "answer_logic": [
        {
            "intent_group": "",
            "user_question": "",
            "ai_answer_pattern": "",
            "target_recommendation_logic": "",
            "required_evidence": [],
            "shared_supporting_articles": [],
            "brief_requirements": [],
        }
    ],
    "keyword_planning": [
        {
            "keyword": "",
            "intent_group": "",
            "user_stage": "",
            "main_article_types": [],
            "recommended_titles": [],
            "evidence_requirements": [],
            "priority": 0,
        }
    ],
    "items": [],
    "shared_supporting_articles": [
        {
            "title": "",
            "supported_keywords": [],
            "type": "",
            "role": "",
            "channels": [],
        }
    ],
    "unified_recommendation_language": [
        {
            "intent_group": "",
            "language": "",
            "proof_to_repeat": "",
            "wrong_expressions_to_avoid": "",
        }
    ],
    "evidence_gaps": [
        {
            "keyword_or_intent_group": "",
            "required_evidence": "",
            "current_evidence": "",
            "missing_evidence": "",
            "impact": "",
            "suggested_supplement": "",
        }
    ],
    "publishing_plan": [
        {
            "article_type": "",
            "recommended_channels": [],
            "channel_role": "",
            "publishing_notes": "",
        }
    ],
    "schedule": [
        {
            "stage": "",
            "period": "",
            "key_tasks": [],
            "article_types": [],
            "goal": "",
        }
    ],
    "priority_plan": [
        {
            "priority": 0,
            "title": "",
            "keyword": "",
            "type": "",
            "reason": "",
        }
    ],
    "brief_requirements": [
        {
            "field": "",
            "requirement": "",
        }
    ],
    "final_execution_advice": "",
    "warnings": [],
}
DEMAND_MATRIX_OUTPUT_TEMPLATE = {
    "step": "geo_demand_content_matrix",
    "schema_version": PLANNING_SCHEMA_VERSION,
    "status": "completed",
    "project": MATRIX_OUTPUT_TEMPLATE["project"],
    "markdown_report": "",
    "project_material_status": [],
    "demand_variables": [],
    "intent_groups": [],
    "keyword_variable_mapping": [],
    "content_theme_clusters": [],
    "title_angle_pool": [],
    "items": [],
    "weekly_publishing_mix": [],
    "monthly_publishing_mix": [],
    "daily_supplement_pool": [],
    "evidence_gaps": [],
    "ai_retest_rules": [],
    "anti_homogenization_requirements": [],
    "final_execution_advice": "",
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

    def start_materials_parse(self, project_id: str, mode: ParseMode = "smart", force: bool = False) -> str:
        mode = normalize_parse_mode(mode)
        project = self.repository.load_project(project_id)
        if not project.materials:
            raise WorkflowError("请先上传项目资料。")
        if project.steps["materials"].status == "running":
            raise WorkflowError("资料解析正在运行，请等待完成或点击刷新状态。")
        job = self.repository.add_job(
            project_id,
            "materials",
            total_count=len(project.materials),
            message=f"准备解析 {len(project.materials)} 个资料文件：{PARSE_MODE_LABELS[mode]}模式",
        )
        self.repository.update_step(project_id, "materials", status="running", input_data={"mode": mode, "force": force}, error=None)
        self.repository.log(project_id, f"开始解析资料：{PARSE_MODE_LABELS[mode]}模式。")
        return job.id

    def parse_materials(self, project_id: str, job_id: str | None = None, mode: ParseMode = "smart", force: bool = False) -> None:
        mode = normalize_parse_mode(mode)
        project = self.repository.load_project(project_id)
        if not project.materials:
            raise WorkflowError("请先上传项目资料。")

        parsed_blocks: list[str] = []
        completed_count = 0
        failed_count = 0
        skipped_count = 0
        total_count = len(project.materials)
        ocr_enabled = mode != "text_only" and (self.settings.enable_vision_ocr or self.settings.enable_local_ocr)

        if job_id:
            self.repository.update_job(
                project_id,
                job_id,
                status="running",
                total_count=total_count,
                message=f"正在以{PARSE_MODE_LABELS[mode]}模式解析资料：0/{total_count}",
            )
        for index, material in enumerate(project.materials, start=1):
            if self._job_cancel_requested(project_id, job_id):
                self._finish_cancelled_job(
                    project_id,
                    job_id,
                    "materials",
                    total_count=total_count,
                    completed_count=completed_count,
                    failed_count=failed_count,
                    skipped_count=skipped_count,
                    output=None,
                )
                return
            source = self.repository.materials_dir(project_id) / material.stored_name
            material.sha256 = material.sha256 or file_sha256(source)
            cache_path, cache_meta_path = parse_cache_paths(self.repository, material, source, mode, self.settings)
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
            if not force and material.status == "parsed" and material.parsed_path:
                parsed_path = self.repository.project_dir(project_id) / material.parsed_path
                if parsed_path.exists():
                    parsed_text = parsed_path.read_text(encoding="utf-8")
                    parsed_blocks.append(parsed_text)
                    material.parse_source = "skipped_existing"
                    material.parsed_chars = material.parsed_chars or len(parsed_text)
                    self.repository.update_material(project_id, material)
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
            try:
                original_material = material.model_copy(deep=True)
                parse_source = "fresh"
                ocr_pages = 0
                if not force and cache_path.exists():
                    text = cache_path.read_text(encoding="utf-8")
                    cache_meta = read_parse_cache_meta(cache_meta_path)
                    ocr_pages = int(cache_meta.get("ocr_pages") or 0)
                    parse_source = "cache"
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
                            message=f"命中解析缓存：{material.filename}",
                        )
                else:
                    def update_parse_progress(message: str) -> None:
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
                                message=message,
                            )

                    if self.settings.hard_cancel_process_workers:
                        result = self._parse_material_in_child(
                            project_id,
                            job_id,
                            source,
                            material.filename,
                            ocr_enabled,
                            self.settings.local_ocr_max_pages if mode == "smart" else None,
                            update_parse_progress,
                        )
                        text = str(result.get("text") or "")
                        ocr_pages = int(result.get("ocr_pages") or 0)
                    else:
                        ocr_runner = MaterialOcrRunner(self.settings, progress=update_parse_progress)
                        text = parse_material(
                            source,
                            image_ocr=ocr_runner.extract_image if ocr_enabled and ocr_runner.image_ocr_enabled() else None,
                            pdf_page_ocr=ocr_runner.extract_pdf_pages if ocr_enabled and ocr_runner.pdf_page_ocr_enabled() else None,
                            pdf_ocr_max_pages=self.settings.local_ocr_max_pages if mode == "smart" else None,
                        )
                        ocr_pages = ocr_runner.ocr_pages
                    write_parse_cache(cache_path, cache_meta_path, text, material, source, mode, self.settings, ocr_pages)
                parsed_name = f"{Path(material.stored_name).stem}.md"
                parsed_path = self.repository.parsed_dir(project_id) / parsed_name
                parsed_path.write_text(f"# {material.filename}\n\n{text}\n", encoding="utf-8")
                material.parsed_path = str(parsed_path.relative_to(self.repository.project_dir(project_id)))
                material.status = "parsed"
                material.error = None
                material.parse_mode = mode
                material.parser_version = MATERIAL_PARSER_VERSION
                material.parse_source = parse_source  # type: ignore[assignment]
                material.parsed_chars = len(text)
                material.ocr_pages = ocr_pages
                material.parsed_at = utc_now()
                parsed_blocks.append(f"## {material.filename}\n\n{text}")
                completed_count += 1
            except ChildProcessCancelled:
                self.repository.update_material(project_id, original_material)
                self._finish_cancelled_job(
                    project_id,
                    job_id,
                    "materials",
                    total_count=total_count,
                    completed_count=completed_count,
                    failed_count=failed_count,
                    skipped_count=skipped_count,
                    output=None,
                )
                return
            except Exception as exc:  # noqa: BLE001 - material parse jobs must persist OCR/API failures
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

            if self._job_cancel_requested(project_id, job_id):
                self._finish_cancelled_job(
                    project_id,
                    job_id,
                    "materials",
                    total_count=total_count,
                    completed_count=completed_count,
                    failed_count=failed_count,
                    skipped_count=skipped_count,
                    output=None,
                )
                return

        if self._job_cancel_requested(project_id, job_id):
            self._finish_cancelled_job(
                project_id,
                job_id,
                "materials",
                total_count=total_count,
                completed_count=completed_count,
                failed_count=failed_count,
                skipped_count=skipped_count,
                output=None,
            )
            return

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
            output={"summary": summary, "material_count": len(project.materials), "parse_mode": mode},
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

    def start_matrix_import(self, project_id: str, filename: str, content_type: str | None, content: bytes) -> dict[str, str]:
        project = self.repository.load_project(project_id)
        suffix = Path(filename or "").suffix.lower()
        if suffix != ".pdf":
            raise WorkflowError("外部内容矩阵导入首版只支持 PDF 文件。请上传可复制文字的内容矩阵 PDF。")
        if not content:
            raise WorkflowError("上传的外部内容矩阵 PDF 为空。")
        assert_matrix_import_prerequisites(project)
        if project.steps["matrix"].status == "running":
            raise WorkflowError("内容矩阵正在生成，请等待完成或停止后再导入外部内容矩阵。")
        draft = self.repository.create_matrix_import_draft(project_id, filename or "content-plan.pdf", content_type, content)
        job = self.repository.add_job(
            project_id,
            "matrix",
            total_count=3,
            message=f"准备识别外部内容矩阵 PDF：{filename}",
        )
        self.repository.update_matrix_import_draft(project_id, draft["id"], job_id=job.id)
        self.repository.log(project_id, f"开始外部内容矩阵 PDF 导入：{filename}")
        return {"job_id": job.id, "draft_id": draft["id"]}

    def run_matrix_import_job(self, project_id: str, job_id: str, draft_id: str) -> None:
        try:
            draft = self.repository.update_matrix_import_draft(project_id, draft_id, status="running", error=None)
            source_path = self.repository.project_dir(project_id) / str(draft.get("source_path") or "")
            self.repository.update_job(
                project_id,
                job_id,
                status="running",
                total_count=3,
                completed_count=0,
                failed_count=0,
                current_item=str(draft.get("filename") or ""),
                message="正在抽取外部内容矩阵 PDF 文本",
            )
            if self._job_cancel_requested(project_id, job_id):
                self._finish_matrix_import_cancelled(project_id, job_id, draft_id)
                return
            text = parse_pdf(source_path)
            if len(text.strip()) < 200 or "PDF 未抽取到可读文本" in text:
                raise WorkflowError("该 PDF 未抽取到足够可读文本。请上传可复制文字的外部内容矩阵 PDF，扫描件请先转文字。")
            self.repository.update_matrix_import_draft(project_id, draft_id, parsed_chars=len(text))
            self.repository.update_job(
                project_id,
                job_id,
                status="running",
                total_count=3,
                completed_count=1,
                failed_count=0,
                current_item=str(draft.get("filename") or ""),
                message="PDF 文本已抽取，正在识别为外部内容矩阵草稿",
            )
            if self._job_cancel_requested(project_id, job_id):
                self._finish_matrix_import_cancelled(project_id, job_id, draft_id)
                return
            raw = self._recognize_matrix_import_text(text)
            self.repository.update_job(
                project_id,
                job_id,
                status="running",
                total_count=3,
                completed_count=2,
                failed_count=0,
                current_item=str(draft.get("filename") or ""),
                message="外部内容矩阵已识别，正在校验固定字段",
            )
            project = self.repository.load_project(project_id)
            result = normalize_matrix_import_output(raw, allowed_keywords_for_project(project, self.repository))
            stats = matrix_import_stats(result)
            warnings = unique_texts([*normalize_string_list(result.get("warnings")), *matrix_import_warnings(result)])
            result["warnings"] = warnings
            self.repository.update_matrix_import_draft(
                project_id,
                draft_id,
                status="completed",
                output=result,
                stats=stats,
                warnings=warnings,
                error=None,
            )
            self.repository.update_job(
                project_id,
                job_id,
                status="completed",
                total_count=3,
                completed_count=3,
                failed_count=0,
                current_item=None,
                message=f"外部内容矩阵 PDF 识别完成，得到 {stats.get('item_count', 0)} 篇文章规划",
            )
            self.repository.log(project_id, f"外部内容矩阵 PDF 识别完成：{draft.get('filename')} / {stats.get('item_count', 0)} 篇规划")
        except Exception as exc:  # noqa: BLE001 - import jobs must persist friendly failures
            friendly_error = friendly_job_error(exc)
            self.repository.update_matrix_import_draft(project_id, draft_id, status="failed", error=friendly_error)
            self.repository.update_job(
                project_id,
                job_id,
                status="failed",
                total_count=3,
                failed_count=1,
                current_item=None,
                message="外部内容矩阵 PDF 识别失败，请检查 PDF 或重试。",
                error=friendly_error,
            )
            self.repository.log(project_id, f"外部内容矩阵 PDF 识别失败：{exc}")

    def apply_matrix_import_draft(self, project_id: str, draft_id: str, overwrite: bool = False) -> None:
        if not overwrite:
            raise WorkflowError("请确认覆盖当前内容矩阵后再导入。")
        project = self.repository.load_project(project_id)
        assert_matrix_import_prerequisites(project)
        draft = self.repository.load_matrix_import_draft(project_id, draft_id)
        if draft.get("status") != "completed":
            raise WorkflowError("外部内容矩阵草稿尚未识别完成，不能导入。")
        output = draft.get("output")
        if not isinstance(output, dict) or not output.get("items"):
            raise WorkflowError("外部内容矩阵草稿没有可导入的矩阵结果。")
        result = normalize_matrix_import_output(output, allowed_keywords_for_project(project, self.repository))
        import_meta = matrix_import_metadata(project, draft)
        result.update(import_meta)
        self.repository.rewrite_latest_output(project, OUTPUT_FILES["matrix"], result_to_markdown("matrix", result))
        self.repository.update_step(project_id, "matrix", status="completed", output=result, error=None)
        self.repository.update_matrix_import_draft(project_id, draft_id, applied_at=result["imported_at"], status="applied", output=result, **import_meta)
        self.repository.log(project_id, f"已导入外部内容矩阵 PDF 并覆盖内容矩阵：{draft.get('filename')}")

    def _finish_matrix_import_cancelled(self, project_id: str, job_id: str, draft_id: str) -> None:
        self.repository.update_matrix_import_draft(project_id, draft_id, status="cancelled", error="导入任务已停止。")
        self.repository.update_job(
            project_id,
            job_id,
            status="cancelled",
            total_count=3,
            current_item=None,
            message="外部内容矩阵 PDF 导入已停止。",
            error=None,
        )

    def _recognize_matrix_import_text(self, text: str) -> dict[str, Any]:
        client = OpenAIWorkflowClient(self.settings, profile="planning")
        system = (
            "你是内容规划 PDF 的结构化识别器。你只能把用户已提供的规划内容转换成固定 JSON，"
            "不得新增文章、不得重新策划、不得虚构证据。"
        )
        user = "\n\n".join(
            [
                "# 任务\n把下面的人工内容规划 PDF 文本识别为 GEO 内容矩阵 canonical JSON 草稿。",
                "# 关键规则\n"
                "- items 必须只来自 PDF 中“首轮文章清单/文章清单/建议文章清单”里的文章标题。\n"
                "- 每个 item 是一篇文章规划，不是关键词分组行。\n"
                "- type 优先归一为核心文章类型："
                + " / ".join(MATRIX_CORE_ARTICLE_TYPES)
                + "；如 PDF 中确有其他文章类型，可保留为扩展类型。FAQ 短文、FAQ问答短文统一为 FAQ问答文。\n"
                "- keyword 必须从 PDF 的关键词池或关键词意图分组中选择最匹配的一个，禁止输出“未标注关键词”。\n"
                "- source_step 必须是 matrix，status 必须是 completed。\n"
                "- title 必须保留 PDF 原始文章标题，不要改写标题。\n"
                "- role/core_recommendation/required_evidence/brief_focus/channels 可从 PDF 的推荐逻辑、证据、发布渠道和注意事项中提取。\n"
                "- PDF 没写明的字段填空字符串或空数组，不要编造。",
                "# 固定字段要求\n"
                "顶层必须使用固定英文 key；items 每项必须包含这些 key："
                + ", ".join(PLANNING_ITEM_KEYS)
                + "。\n"
                "除 items 外，各区块也必须使用固定英文 key："
                f"intent_groups={MATRIX_INTENT_GROUP_KEYS}；"
                f"article_type_pool={MATRIX_ARTICLE_TYPE_POOL_KEYS}；"
                f"answer_logic={MATRIX_ANSWER_LOGIC_KEYS}；"
                f"keyword_planning={MATRIX_KEYWORD_PLANNING_KEYS}；"
                f"shared_supporting_articles={MATRIX_SHARED_SUPPORTING_ARTICLE_KEYS}；"
                f"unified_recommendation_language={MATRIX_RECOMMENDATION_LANGUAGE_KEYS}；"
                f"evidence_gaps={MATRIX_EVIDENCE_GAP_KEYS}；"
                f"publishing_plan={MATRIX_PUBLISHING_PLAN_KEYS}；"
                f"schedule={MATRIX_SCHEDULE_KEYS}；"
                f"priority_plan={MATRIX_PRIORITY_PLAN_KEYS}；"
                f"brief_requirements={MATRIX_BRIEF_REQUIREMENT_KEYS}。",
                f"# JSON 模板\n```json\n{json.dumps(MATRIX_OUTPUT_TEMPLATE, ensure_ascii=False, indent=2)}\n```",
                "# PDF 文本\n" + text[:50000],
            ]
        )
        return client.generate_json(system=system, user=user, schema_name="geo_matrix_import")

    def start_step(self, project_id: str, step: WorkflowStep, payload: dict[str, Any]) -> str:
        if step not in RUNNABLE_STEPS:
            raise WorkflowError(f"该步骤不可直接运行：{step}")
        if step == "demand_matrix":
            self._assert_demand_matrix_ready(project_id)
        if step == "breakthrough":
            project = self.repository.load_project(project_id)
            selected_keywords = confirmed_keywords_from_payload(payload) or confirmed_breakthrough_keywords(project.steps["matrix"].output)
            allowed_keywords = allowed_keywords_for_project(project, self.repository)
            if allowed_keywords:
                allowed_set = set(allowed_keywords)
                selected_keywords = [
                    keyword
                    for keyword in normalize_keyword_list([normalize_keyword_to_allowed(keyword, allowed_keywords) for keyword in selected_keywords])
                    if keyword in allowed_set
                ]
            keywords = selected_keywords if payload.get("force") else merge_keyword_lists(
                normalize_keyword_list(project.steps["breakthrough"].output.get("confirmed_keywords")),
                selected_keywords,
            )
            if allowed_keywords:
                allowed_set = set(allowed_keywords)
                keywords = [keyword for keyword in keywords if keyword in allowed_set]
            if not keywords:
                raise WorkflowError("请先在内容矩阵中确认进入逐词击破的关键词。")
            payload["confirmed_keywords"] = keywords
            if not payload.get("force") and project.steps["breakthrough"].output:
                missing_types = missing_breakthrough_types(project.steps["breakthrough"].output, keywords)
                if not missing_types:
                    raise WorkflowError("选中关键词均已有逐词击破规划，无需重复生成。")
                payload["missing_breakthrough_types"] = missing_types
                payload["incremental"] = True
        if step not in {"brief", "article", "demand_matrix"}:
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
            self._assert_brief_sources_ready(project, payload["selected_sources"])
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
        if project.steps[step].output and not payload.get("force") and step not in INCREMENTAL_STEPS and step != "breakthrough":
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
        if self._job_cancel_requested(project_id, job_id):
            self._finish_cancelled_job(project_id, job_id, step, total_count=1, completed_count=0, failed_count=0, skipped_count=0)
            return
        if step == "matrix":
            self._run_matrix_step_job(project_id, job_id, payload)
            return
        if step in {"brief", "article"}:
            self._run_incremental_step_job(project_id, job_id, step, payload)
            return
        try:
            def update_step_progress(message: str) -> None:
                self.repository.update_job(project_id, job_id, status="running", message=message)

            result = self._run_step_for_job(project_id, job_id, step, payload, on_progress=update_step_progress)
            if self._job_cancel_requested(project_id, job_id):
                self._finish_cancelled_job(project_id, job_id, step, total_count=1, completed_count=0, failed_count=0, skipped_count=0)
                return
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
            project = self.repository.load_project(project_id)
            result = normalize_planning_output(step, result, payload)
            if step == "breakthrough" and payload.get("incremental") and not payload.get("force"):
                result = merge_breakthrough_output(project.steps["breakthrough"].output, result, payload)
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
        except ChildProcessCancelled:
            self._finish_cancelled_job(project_id, job_id, step, total_count=1, completed_count=0, failed_count=0, skipped_count=0)
        except Exception as exc:  # noqa: BLE001 - job runner must persist failures
            friendly_error = friendly_job_error(exc)
            self.repository.update_step(project_id, step, status="failed", error=friendly_error)
            self.repository.update_job(
                project_id,
                job_id,
                status="failed",
                total_count=1,
                completed_count=0,
                failed_count=1,
                current_item=None,
                message=f"{STEP_LABELS.get(step, step)}失败，可重试。",
                error=friendly_error,
            )
            self.repository.log(project_id, f"步骤失败：{STEP_LABELS.get(step, step)} - {exc}")

    def _run_matrix_step_job(self, project_id: str, job_id: str, payload: dict[str, Any]) -> None:
        step: WorkflowStep = "matrix"
        total_count = 1
        completed_count = 0
        try:
            project = self.repository.load_project(project_id)
            skeleton = build_local_matrix_skeleton(project, payload)
            self.repository.update_job(
                project_id,
                job_id,
                status="running",
                total_count=total_count,
                completed_count=completed_count,
                failed_count=0,
                current_item=None,
                message="正在基于 intake 规划关键词意图簇",
            )
            skeleton = self._build_llm_matrix_skeleton(project, skeleton, payload)
            batches = build_matrix_batches(project, skeleton, payload, self.settings, self.repository)
            if not batches:
                raise WorkflowError("内容矩阵无法拆分批次：未找到可用于生成规划的关键词或意图簇。")

            total_count = len(batches)
            self.repository.update_job(
                project_id,
                job_id,
                status="running",
                total_count=total_count,
                completed_count=completed_count,
                failed_count=0,
                current_item=None,
                message=f"已完成关键词意图簇规划，准备分 {len(batches)} 批生成内容规划",
            )

            partials: list[dict[str, Any]] = []
            for batch_index, batch in enumerate(batches, start=1):
                if self._job_cancel_requested(project_id, job_id):
                    self._finish_cancelled_job(project_id, job_id, step, total_count=total_count, completed_count=completed_count, failed_count=0, skipped_count=0)
                    return
                batch_label = matrix_batch_label(batch)
                batch_payload = {
                    **payload,
                    MATRIX_GENERATION_MODE_KEY: MATRIX_GENERATION_MODE_BATCH,
                    "matrix_batch": {
                        "index": batch_index,
                        "total": len(batches),
                        "intent_groups": batch.get("intent_groups", []),
                        "keywords": batch.get("keywords", []),
                    },
                    "matrix_skeleton": compact_matrix_skeleton_for_prompt(skeleton),
                }
                self.repository.update_job(
                    project_id,
                    job_id,
                    status="running",
                    total_count=total_count,
                    completed_count=completed_count,
                    failed_count=0,
                    current_item=batch_label,
                    message=f"正在生成内容矩阵：第 {batch_index}/{len(batches)} 批",
                )
                raw_partial = self._run_matrix_call_with_timeout_retry(
                    project_id,
                    job_id,
                    batch_payload,
                    phase_label=f"内容矩阵第 {batch_index}/{len(batches)} 批",
                )
                partial = normalize_matrix_partial_output(raw_partial, batch, batch_index)
                partials.append(partial)
                completed_count += 1
                self.repository.update_job(
                    project_id,
                    job_id,
                    status="running",
                    total_count=total_count,
                    completed_count=completed_count,
                    failed_count=0,
                    current_item=batch_label,
                    message=f"内容矩阵第 {batch_index}/{len(batches)} 批完成",
                )

            result = merge_matrix_batch_outputs(skeleton, partials)
            self._finish_matrix_step_success(project_id, job_id, result, total_count=total_count, completed_count=completed_count)
        except ChildProcessCancelled:
            self._finish_cancelled_job(project_id, job_id, step, total_count=total_count, completed_count=completed_count, failed_count=0, skipped_count=0)
        except Exception as exc:  # noqa: BLE001 - matrix job must persist friendly failures
            friendly_error = friendly_job_error(exc)
            self.repository.update_step(project_id, step, status="failed", error=friendly_error)
            self.repository.update_job(
                project_id,
                job_id,
                status="failed",
                total_count=total_count,
                completed_count=completed_count,
                failed_count=1,
                skipped_count=0,
                current_item=None,
                message="内容矩阵生成失败，可重试。",
                error=friendly_error,
            )
            self.repository.log(project_id, f"步骤失败：{STEP_LABELS.get(step, step)} - {exc}")

    def _build_llm_matrix_skeleton(self, project: Any, skeleton: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        keywords = matrix_seed_keywords(project, skeleton, payload, self.repository)
        if not keywords:
            return skeleton
        try:
            result = self._run_matrix_intent_grouping(project, skeleton, keywords)
            groups = normalize_llm_matrix_intent_groups(result, keywords)
            if not groups:
                return skeleton
            return rebuild_matrix_skeleton_with_intent_groups(skeleton, groups)
        except Exception as exc:  # noqa: BLE001 - grouping is quality enhancement, not a hard dependency
            next_skeleton = dict(skeleton)
            next_skeleton["warnings"] = unique_texts(
                [
                    *normalize_string_list(skeleton.get("warnings")),
                    f"DeepSeek 关键词意图簇规划失败，已回退本地规则：{friendly_job_error(exc)}",
                ]
            )
            return next_skeleton

    def _run_matrix_intent_grouping(self, project: Any, skeleton: dict[str, Any], keywords: list[str]) -> dict[str, Any]:
        client = OpenAIWorkflowClient(self.settings, profile="planning")
        intake = project.steps["intake"].output if "intake" in project.steps else {}
        system = (
            "你是一个 GEO 内容策略规划助手。你只做关键词意图簇规划，不生成文章，不读取原始资料。"
            "必须只输出 JSON 对象。"
        )
        template = {
            "intent_groups": [
                {
                    "id": "intent-1",
                    "name": "中文意图簇名称",
                    "keywords": [],
                    "user_question": "用户真实问题",
                    "user_stage": "认知研究阶段/比较评估阶段/方案选择阶段/购买决策阶段",
                    "recommendation_logic": "该意图簇下应如何建立推荐理由",
                    "article_types": MATRIX_REQUIRED_ARTICLE_TYPES,
                }
            ],
            "warnings": [],
        }
        user = "\n\n".join(
            [
                "# 任务\n基于 intake 中的项目定位和目标关键词，重新规划关键词意图簇。",
                "# 约束\n所有 target_keywords 必须出现且只能出现一次；不要新增关键词；不要删除关键词；一个意图簇可以包含多个关键词，不强制限制为 5 个；意图簇名称必须是中文，且要体现用户意图而不是机械分类。",
                "# 项目信息 intake\n" + json.dumps(intake, ensure_ascii=False, indent=2)[:30000],
                "# 目标关键词\n" + json.dumps(keywords, ensure_ascii=False, indent=2),
                "# 当前本地兜底意图簇\n" + json.dumps(skeleton.get("intent_groups", []), ensure_ascii=False, indent=2),
                "# 输出模板\n" + json.dumps(template, ensure_ascii=False, indent=2),
            ]
        )
        return client.generate_json(system=system, user=user, schema_name="geo_matrix_intent_groups")

    def _finish_matrix_step_success(
        self,
        project_id: str,
        job_id: str,
        result: dict[str, Any],
        *,
        total_count: int,
        completed_count: int,
    ) -> None:
        project = self.repository.load_project(project_id)
        self.repository.write_output(project, OUTPUT_FILES["matrix"], result_to_markdown("matrix", result))
        self.repository.update_step(project_id, "matrix", status="completed", output=result, error=None)
        item_count = len(output_items(result))
        self.repository.update_job(
            project_id,
            job_id,
            status="completed",
            total_count=total_count,
            completed_count=completed_count,
            failed_count=0,
            skipped_count=0,
            current_item=None,
            message=f"内容矩阵生成完成，已生成 {item_count} 篇规划",
        )
        self.repository.log(project_id, f"步骤完成：{STEP_LABELS.get('matrix', 'matrix')}")

    def _run_matrix_call_with_timeout_retry(
        self,
        project_id: str,
        job_id: str,
        payload: dict[str, Any],
        *,
        phase_label: str,
    ) -> dict[str, Any]:
        retry_count = max(int(getattr(self.settings, "matrix_timeout_retry_count", 1) or 0), 0)
        max_attempts = retry_count + 1
        for attempt in range(1, max_attempts + 1):
            try:
                return self._run_step_for_job(project_id, job_id, "matrix", payload)
            except ChildProcessCancelled:
                raise
            except Exception as exc:  # noqa: BLE001 - retry decision needs SDK/proxy errors
                if not is_llm_timeout_error(exc) or attempt >= max_attempts:
                    raise
                retry_after = llm_retry_after_seconds(exc)
                configured_wait = float(getattr(self.settings, "matrix_timeout_retry_seconds", 120))
                wait_seconds = retry_after if retry_after > 0 else configured_wait
                wait_seconds = max(wait_seconds, 0)
                self.repository.update_job(
                    project_id,
                    job_id,
                    status="running",
                    current_item=phase_label,
                    message=f"{phase_label}遇到中转站超时，{wait_seconds:g} 秒后自动重试一次",
                    error=None,
                )
                self.repository.log(project_id, f"{phase_label}遇到中转站超时，准备重试：{exc}")
                self._sleep_before_matrix_retry(project_id, job_id, wait_seconds)
        raise WorkflowError("内容矩阵生成失败：重试次数已用尽。")

    def _sleep_before_matrix_retry(self, project_id: str, job_id: str, wait_seconds: float) -> None:
        deadline = time.monotonic() + wait_seconds
        interval = max(float(getattr(self.settings, "job_cancel_poll_interval_seconds", 0.3) or 0.3), 0.05)
        while time.monotonic() < deadline:
            if self._job_cancel_requested(project_id, job_id):
                raise ChildProcessCancelled("任务已停止。")
            time.sleep(min(interval, max(deadline - time.monotonic(), 0)))

    def _run_incremental_step_job(self, project_id: str, job_id: str, step: WorkflowStep, payload: dict[str, Any]) -> None:
        selected_key = "selected_sources" if step == "brief" else "selected_briefs"
        selected_items = payload.get(selected_key)
        if not isinstance(selected_items, list):
            selected_items = []
        selected_items = [item for item in selected_items if isinstance(item, dict)]
        total_count = len(selected_items)
        completed_count = 0
        failed_count = 0
        skipped_count = int(payload.get("skipped_count") or 0)
        concurrency = batch_generation_concurrency(self.settings, total_count)

        if total_count:
            self.repository.update_job(
                project_id,
                job_id,
                status="running",
                total_count=total_count,
                completed_count=completed_count,
                failed_count=failed_count,
                skipped_count=skipped_count,
                current_item=f"当前并行中 {min(concurrency, total_count)} 篇",
                message=build_parallel_running_message(step, concurrency),
            )

        def run_selected_item(index: int, selected: dict[str, Any]) -> dict[str, Any]:
            item_title = str(selected.get("title") or selected.get("keyword") or f"第 {index} 篇")
            item_payload = {**payload, selected_key: [selected]}
            max_attempts = 2
            for attempt in range(1, max_attempts + 1):
                try:
                    def update_item_progress(message: str) -> None:
                        self.repository.update_job(
                            project_id,
                            job_id,
                            status="running",
                            total_count=total_count,
                            completed_count=completed_count,
                            failed_count=failed_count,
                            skipped_count=skipped_count,
                            current_item=item_title,
                            message=message,
                        )

                    result = self._run_step_for_job(project_id, job_id, step, item_payload, on_progress=update_item_progress)
                    return {
                        "ok": True,
                        "index": index,
                        "selected": selected,
                        "title": item_title,
                        "result": result,
                    }
                except ChildProcessCancelled:
                    return {
                        "ok": False,
                        "cancelled": True,
                        "index": index,
                        "selected": selected,
                        "title": item_title,
                        "error": "任务已停止。",
                    }
                except Exception as exc:  # noqa: BLE001 - one failed item should not stop the rest
                    if attempt < max_attempts and is_retriable_llm_generation_error(exc):
                        self.repository.update_job(
                            project_id,
                            job_id,
                            status="running",
                            total_count=total_count,
                            completed_count=completed_count,
                            failed_count=failed_count,
                            skipped_count=skipped_count,
                            current_item=item_title,
                            message=f"{item_title} 遇到中转站瞬时异常，正在自动重试",
                            error=None,
                        )
                        self.repository.log(project_id, f"单篇生成重试：{item_title} - {exc}")
                        time.sleep(1)
                        continue
                    return {
                        "ok": False,
                        "index": index,
                        "selected": selected,
                        "title": item_title,
                        "error": friendly_job_error(exc),
                    }
            return {
                "ok": False,
                "index": index,
                "selected": selected,
                "title": item_title,
                "error": "任务失败，可重试。",
            }

        cancelled = self._job_cancel_requested(project_id, job_id)

        def process_item_result(item_result: dict[str, Any]) -> None:
            nonlocal completed_count, failed_count
            selected = item_result["selected"]
            item_title = str(item_result["title"])
            if item_result.get("cancelled"):
                self.repository.log(project_id, f"单篇生成已停止：{item_title}")
                return
            if item_result["ok"]:
                result = item_result["result"]
                project = self.repository.load_project(project_id)
                try:
                    if step == "brief":
                        merged, generated_items = merge_generated_briefs(project.steps["brief"].output, [selected], result)
                        self._write_generated_items(project, "brief", generated_items)
                    else:
                        merged, generated_items = merge_generated_articles(project.steps["article"].output, [selected], result)
                        self._write_generated_items(project, "article", generated_items)
                    self.repository.update_step(project_id, step, status="running", output=merged, error=None)
                    completed_count += 1
                    self.repository.log(project_id, f"单篇生成完成：{item_title}")
                except Exception as exc:  # noqa: BLE001 - malformed item should fail only this item
                    error = str(exc)
                    if step == "brief":
                        output = mark_brief_source_failed(project.steps["brief"].output, selected, error)
                    else:
                        output = mark_article_brief_failed(project.steps["article"].output, selected, error)
                    output = attach_raw_generation_to_failed_item(output, selected, result, step)
                    self.repository.update_step(project_id, step, status="running", output=output, error=None)
                    failed_count += 1
                    self.repository.log(project_id, f"单篇生成失败：{item_title} - {error}")
            else:
                project = self.repository.load_project(project_id)
                error = str(item_result["error"])
                if step == "brief":
                    output = mark_brief_source_failed(project.steps["brief"].output, selected, error)
                else:
                    output = mark_article_brief_failed(project.steps["article"].output, selected, error)
                self.repository.update_step(project_id, step, status="running", output=output, error=None)
                failed_count += 1
                self.repository.log(project_id, f"单篇生成失败：{item_title} - {error}")

            processed_count = completed_count + failed_count
            remaining_count = max(total_count - processed_count, 0)
            current_item = f"当前并行中 {min(concurrency, remaining_count)} 篇" if remaining_count else None
            self.repository.update_job(
                project_id,
                job_id,
                status="running",
                total_count=total_count,
                completed_count=completed_count,
                failed_count=failed_count,
                skipped_count=skipped_count,
                current_item=current_item,
                message=build_parallel_running_message(step, concurrency),
            )

        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            pending: set[Future[dict[str, Any]]] = set()
            next_index = 0

            def submit_available() -> None:
                nonlocal next_index
                while next_index < total_count and len(pending) < concurrency and not self._job_cancel_requested(project_id, job_id):
                    selected = selected_items[next_index]
                    next_index += 1
                    pending.add(executor.submit(run_selected_item, next_index, selected))

            submit_available()
            cancelled = self._job_cancel_requested(project_id, job_id)
            while pending:
                done, pending = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    process_item_result(future.result())
                if self._job_cancel_requested(project_id, job_id):
                    cancelled = True
                    break
                submit_available()

            if cancelled and pending:
                for future in pending:
                    future.cancel()
                for future in pending:
                    if not future.cancelled():
                        process_item_result(future.result())

        project = self.repository.load_project(project_id)
        output = dict(project.steps[step].output)
        if cancelled or self._job_cancel_requested(project_id, job_id):
            output = drop_running_items_after_cancel(output)
            output["status"] = "cancelled"
            summary = build_job_cancelled_message(step, total_count, completed_count, failed_count, skipped_count)
            final_step_status = "completed" if has_generated_output_items(output) else "failed"
            self.repository.update_step(
                project_id,
                step,
                status=final_step_status,
                output=output,
                error=summary,
            )
            self.repository.update_job(
                project_id,
                job_id,
                status="cancelled",
                completed_count=completed_count,
                failed_count=failed_count,
                skipped_count=skipped_count,
                current_item=None,
                message=summary,
                error=None,
            )
            self.repository.log(project_id, summary)
            return
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

    def _parse_material_in_child(
        self,
        project_id: str,
        job_id: str | None,
        source: Path,
        filename: str,
        ocr_enabled: bool,
        pdf_ocr_max_pages: int | None,
        on_progress: Any,
    ) -> dict[str, Any]:
        return run_worker_process(
            "parse_material",
            {
                "settings": self.settings.model_dump(),
                "source": str(source),
                "filename": filename,
                "ocr_enabled": ocr_enabled,
                "pdf_ocr_max_pages": pdf_ocr_max_pages,
            },
            self.settings,
            cancel_requested=lambda: self._job_cancel_requested(project_id, job_id),
            on_progress=on_progress,
        )

    def _run_step_for_job(
        self,
        project_id: str,
        job_id: str,
        step: WorkflowStep,
        payload: dict[str, Any],
        *,
        on_progress: Any | None = None,
    ) -> dict[str, Any]:
        if not self.settings.hard_cancel_process_workers:
            return self._run_step(project_id, step, payload)
        return run_worker_process(
            "run_step",
            {
                "settings": self.settings.model_dump(),
                "project_id": project_id,
                "step": step,
                "payload": payload,
                "message": build_running_step_message(step),
            },
            self.settings,
            cancel_requested=lambda: self._job_cancel_requested(project_id, job_id),
            on_progress=on_progress,
        )

    def _job_cancel_requested(self, project_id: str, job_id: str | None) -> bool:
        if not job_id:
            return False
        return self.repository.job_cancel_requested(project_id, job_id)

    def _finish_cancelled_job(
        self,
        project_id: str,
        job_id: str | None,
        step: WorkflowStep,
        *,
        total_count: int,
        completed_count: int,
        failed_count: int,
        skipped_count: int,
        output: dict[str, Any] | None = None,
    ) -> None:
        summary = build_job_cancelled_message(step, total_count, completed_count, failed_count, skipped_count)
        self.repository.update_step(
            project_id,
            step,
            status="failed",
            output=output,
            error=summary,
        )
        if job_id:
            self.repository.update_job(
                project_id,
                job_id,
                status="cancelled",
                total_count=total_count,
                completed_count=completed_count,
                failed_count=failed_count,
                skipped_count=skipped_count,
                current_item=None,
                message=summary,
                error=None,
            )
        self.repository.log(project_id, summary)

    def confirm_step(self, project_id: str, step: WorkflowStep, notes: str | None = None) -> None:
        project = self.repository.update_step(project_id, step, confirmed=True)
        if notes:
            self.repository.log(project_id, f"确认步骤：{STEP_LABELS.get(step, step)}；备注：{notes}")
        else:
            self.repository.log(project_id, f"确认步骤：{STEP_LABELS.get(step, step)}")

    def confirm_breakthrough_keywords(self, project_id: str, keywords: list[str]) -> None:
        project = self.repository.load_project(project_id)
        matrix_state = project.steps["matrix"]
        if matrix_state.status == "running":
            raise WorkflowError("内容矩阵正在生成，请等待完成后再确认关键词。")
        if not matrix_state.output:
            raise WorkflowError("请先生成内容矩阵，再确认进入逐词击破的关键词。")
        allowed_keywords = allowed_keywords_for_project(project, self.repository)
        normalized_keywords = normalize_keyword_list([
            normalize_keyword_to_allowed(keyword, allowed_keywords)
            for keyword in keywords
        ])
        if allowed_keywords:
            allowed_set = set(allowed_keywords)
            normalized_keywords = [keyword for keyword in normalized_keywords if keyword in allowed_set]
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
        if step not in {"intake", "matrix", "breakthrough", "brief", "article"}:
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

        if step in {"brief", "article"}:
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
        client = OpenAIWorkflowClient(self.settings, profile=client_profile_for_step(step))
        rules = self.skill_loader.load_for_step(step)
        project = self.repository.load_project(project_id)
        material_summary = material_summary_for_step(project, step, payload, self.settings)
        prior_outputs = prior_outputs_for_step(project, step, payload)
        selection_blocks = build_selection_prompt_blocks(step, payload)
        system = (
            "你是一个本地 GEO 撰文后台 Agent。必须严格遵守 skill 规则，"
            "只基于用户资料和已确认的上游结果生成，不得虚构证据、认证、排名或案例。"
        )
        user_parts = [
            f"# 当前步骤\n{STEP_LABELS.get(step, step)}",
            "# Skill 规则\n" + rules,
            "# 项目资料\n" + material_summary[:MATERIAL_CONTEXT_LIMIT],
            "# 已有上游输出\n" + json.dumps(prior_outputs, ensure_ascii=False, indent=2)[:prior_output_context_limit_for_step(step)],
        ]
        user_parts.extend(selection_blocks)
        if planning_requirements := planning_output_requirements(step, payload):
            user_parts.append(planning_requirements)
        if step in {"brief", "article"}:
            user_parts.extend(regeneration_guidance_blocks(step, payload))
            user_parts.extend(
                [
                    "# 本次人工输入\n" + json.dumps(sanitized_generation_payload(step, payload), ensure_ascii=False, indent=2),
                    markdown_output_requirements(step),
                ]
            )
            user = "\n\n".join(user_parts)
            markdown = client.generate_text(system=system, user=user).strip()
            return wrap_markdown_generation(step, payload, markdown)
        user_parts.extend(
            [
                "# 本次人工输入\n" + json.dumps(payload, ensure_ascii=False, indent=2),
                "# 输出要求\n请输出 JSON 对象，不要输出 Markdown 代码围栏或解释文字。",
            ]
        )
        user = "\n\n".join(user_parts)
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

    def _assert_demand_matrix_ready(self, project_id: str) -> None:
        project = self.repository.load_project(project_id)
        ready_statuses = {"completed", "confirmed"}
        if project.steps["materials"].status not in ready_statuses:
            raise WorkflowError("请先上传并解析资料，再生成需求驱动内容矩阵。")
        if project.steps["intake"].status not in ready_statuses:
            raise WorkflowError("请先生成项目信息抽取表，再生成需求驱动内容矩阵。")
        parsed_reports = [
            material
            for material in project.materials
            if material.filename.startswith(DEMAND_REPORT_SLOT_PREFIX) and material.status == "parsed"
        ]
        if not parsed_reports:
            raise WorkflowError("请先在“用户需求挖掘报告”入口上传报告并完成资料解析。")

    def _assert_brief_sources_ready(self, project: Any, selected_sources: list[dict[str, Any]]) -> None:
        required_steps: set[WorkflowStep] = set()
        for source in selected_sources:
            source_step = str(source.get("source_step") or "matrix").strip().lower()
            if source_step in {"matrix", "source", "planning"}:
                required_steps.add("matrix")
            elif source_step == "custom":
                required_steps.add("matrix")
            elif source_step == "breakthrough":
                required_steps.add("breakthrough")
            else:
                raise WorkflowError(f"暂不支持的 Brief 来源：{source_step}")

        ready_statuses = {"completed", "confirmed"}
        if "matrix" in required_steps and project.steps["matrix"].status not in ready_statuses:
            raise WorkflowError("请先生成内容矩阵，再为内容矩阵规划生成 Brief。")
        if "breakthrough" in required_steps and project.steps["breakthrough"].status not in ready_statuses:
            raise WorkflowError("请先完成逐词击破，再为逐词击破规划生成 Brief。内容矩阵规划可直接生成 Brief。")


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
    if step == "demand_matrix":
        return (
            "# 需求驱动内容矩阵固定输出模板\n"
            "你必须严格使用固定英文 key 输出 JSON，不要输出 Markdown 代码围栏。\n"
            "本步骤只生成新版需求驱动内容矩阵，用于查看和导出；不要写后续 Brief 或正文。\n"
            "必须吸收用户上传的“用户需求挖掘报告”，不要只按关键词字面规划。\n"
            "markdown_report 是本步骤最重要的主产物，必须输出一份完整 Markdown 报告字符串，供用户直接查看和导出。\n"
            "markdown_report 必须采用正式内容矩阵规划报告形态，而不是摘要，不要只输出 JSON 表字段说明。报告必须包含："
            "H1 项目内容矩阵规划标题、项目对象/目标品类/目标定位/参考资料、内部风险提示、"
            "1 项目信息与资料状态表、2 用户需求变量池、3 关键词意图簇分组、4 关键词 × 用户需求变量映射表、"
            "5 内容主题簇规划表、6 六类基础文章标题角度池、周/月发布配比、日常补充内容池、证据缺口、"
            "AI 复测与补内容规则、Brief 防同质化要求、最终执行建议。\n"
            "第 6 节必须按每个内容主题簇分别展开，每个主题簇都要写覆盖关键词、标题钩子、风险边界，并分别给出"
            "支柱标准文、榜单推荐文、横评对比文、产品证据文、场景选购文、FAQ问答文六类标题表；"
            "每类至少 2-3 个标题和正文切入角度。\n"
            "除 markdown_report 外，其他顶层数组是结构化索引，必须与 markdown_report 内容一致，用于系统筛选和列表展示。\n"
            "items 必须表示可展示的文章级规划清单，每一项是一篇文章规划，不是主题簇或配比行。"
            "items 中每一项都必须包含这些 key："
            f"{', '.join(PLANNING_ITEM_KEYS)}。\n"
            "source_step 必须是 demand_matrix；status 必须是 completed。\n"
            "每个 item 的 keyword/type/title/role/required_evidence/brief_focus 要能从需求变量、关键词意图簇和内容主题簇追溯出来。\n"
            "除 items 外，必须尽量输出这些顶层数组：project_material_status、demand_variables、intent_groups、"
            "keyword_variable_mapping、content_theme_clusters、title_angle_pool、weekly_publishing_mix、monthly_publishing_mix、"
            "daily_supplement_pool、evidence_gaps、ai_retest_rules、anti_homogenization_requirements。\n"
            "不要虚构检测报告、认证编号、销量、排名、专家、案例或权威背书；缺资料写入 evidence_gaps 或 warnings。\n"
            f"```json\n{json.dumps(DEMAND_MATRIX_OUTPUT_TEMPLATE, ensure_ascii=False, indent=2)}\n```"
        )
    if step == "matrix":
        mode = str(payload.get(MATRIX_GENERATION_MODE_KEY) or "")
        if mode == MATRIX_GENERATION_MODE_BATCH:
            batch = payload.get("matrix_batch") if isinstance(payload.get("matrix_batch"), dict) else {}
            return (
                "# 内容矩阵分批生成：当前批次规划\n"
                "你必须严格使用固定英文 key 输出 JSON。不要把字段名翻译成中文。\n"
                "本次只针对 matrix_batch 中列出的 intent_groups / keywords 生成首轮文章规划；不要输出其他意图簇或关键词。\n"
                "items 必须表示“首轮文章清单”，每一项是一篇可进入 Brief 的文章规划，不是关键词分组行。\n"
                "items 中每一项都必须包含这些 key："
                f"{', '.join(PLANNING_ITEM_KEYS)}。\n"
                "source_step 必须是 matrix；type 优先从核心类型中选择："
                f"{' / '.join(MATRIX_CORE_ARTICLE_TYPES)}；如当前批次确实需要，可输出扩展文章类型。"
                "支柱标准文章、FAQ问答短文等别名必须归一为核心类型。\n"
                "当前批次不要求覆盖固定六类；只要输出可进入 Brief 的文章规划 items 即可。\n"
                "每个 item 的 required_evidence / evidence_chain / brief_focus 必须体现“用户问题 → 判断标准 → intake核心证据摘要 → 用户价值 → 推荐结论”。\n"
                "required_evidence / evidence_chain / brief_focus 写成 Brief 阶段需要核验和展开的证据要求，不要假装已经读完原始资料全文。\n"
                "如果 intake 核心证据不足，把缺口写入 evidence_gaps 或 warnings，不要虚构证据、认证、排名、报告、专家、销量或案例。\n"
                f"# matrix_batch\n{json.dumps(batch, ensure_ascii=False, indent=2)}\n"
                f"```json\n{json.dumps(MATRIX_OUTPUT_TEMPLATE, ensure_ascii=False, indent=2)}\n```"
            )
        return (
            "# 固定输出模板\n"
            "你必须严格使用下面 JSON 模板的英文 key。不要把字段名翻译成中文，不要输出 plans、articles、first_round_article_list、"
            "keyword_individual_planning 等替代字段作为主结果。前端和后续 Brief 只读取 items。\n"
            "本步骤必须严格执行 geo-content-matrix-planner：先做关键词总体判断、AI回答意图分组、文章类型池、AI回答逻辑、"
            "证据链与资料缺口、共享支撑文、统一推荐口径、渠道规划、4-8周排期和 Brief 衔接要求，再输出首轮文章清单。\n"
            "不要把内容矩阵做成逐词孤立标题列表；高度相关关键词应使用共享支撑文覆盖。\n"
            "items 必须表示“首轮文章清单”，每一项是一篇可进入 Brief 的文章规划，不是关键词分组行。\n"
            "type 优先从核心文章类型中选择："
            f"{' / '.join(MATRIX_CORE_ARTICLE_TYPES)}；如内容矩阵确实需要，可输出扩展文章类型。"
            "支柱标准文章、FAQ问答短文等别名必须归一为核心类型。\n"
            "items 中每一项都必须包含这些 key："
            f"{', '.join(PLANNING_ITEM_KEYS)}。\n"
            "每个 item 的 required_evidence / evidence_chain / brief_focus 必须体现“用户问题 → 判断标准 → intake核心证据摘要 → 用户价值 → 推荐结论”。\n"
            "required_evidence / evidence_chain / brief_focus 写成 Brief 阶段需要核验和展开的证据要求，不要假装已经读完原始资料全文。\n"
            "每个 item 都要写 recommendation_strength；榜单、横评、产品证据、FAQ 应形成明确优先推荐，支柱标准文不得硬广。\n"
            "如果 intake 核心证据不足，把缺口写入 evidence_gaps 或 warnings，不要虚构证据、认证、排名、报告、专家、销量或案例。\n"
            "除 items 外，各区块也必须使用固定英文 key："
            f"intent_groups={MATRIX_INTENT_GROUP_KEYS}；"
            f"article_type_pool={MATRIX_ARTICLE_TYPE_POOL_KEYS}；"
            f"answer_logic={MATRIX_ANSWER_LOGIC_KEYS}；"
            f"keyword_planning={MATRIX_KEYWORD_PLANNING_KEYS}；"
            f"shared_supporting_articles={MATRIX_SHARED_SUPPORTING_ARTICLE_KEYS}；"
            f"unified_recommendation_language={MATRIX_RECOMMENDATION_LANGUAGE_KEYS}；"
            f"evidence_gaps={MATRIX_EVIDENCE_GAP_KEYS}；"
            f"publishing_plan={MATRIX_PUBLISHING_PLAN_KEYS}；"
            f"schedule={MATRIX_SCHEDULE_KEYS}；"
            f"priority_plan={MATRIX_PRIORITY_PLAN_KEYS}；"
            f"brief_requirements={MATRIX_BRIEF_REQUIREMENT_KEYS}。\n"
            f"```json\n{json.dumps(MATRIX_OUTPUT_TEMPLATE, ensure_ascii=False, indent=2)}\n```"
        )
    if step == "breakthrough":
        keywords = confirmed_keywords_from_payload(payload)
        missing_types = breakthrough_required_types(payload)
        if missing_types:
            return (
                "# 固定输出模板\n"
                "你必须严格使用下面 JSON 模板的英文 key。不要输出 plans 作为主结果；前端和后续 Brief 只读取 items。\n"
                "本次是逐词击破增量生成，只能输出 missing_breakthrough_types 中列出的关键词与文章类型；"
                "不要重复输出已存在的 keyword + type。\n"
                "items 中每一项都必须包含这些 key："
                f"{', '.join(PLANNING_ITEM_KEYS)}。\n"
                "source_step 必须是 breakthrough，keyword 必须来自 missing_breakthrough_types 的 key，type 必须来自该 keyword 对应的缺失类型列表，标题应完整包含 keyword。\n"
                f"# confirmed_keywords\n{json.dumps(keywords, ensure_ascii=False, indent=2)}\n"
                f"# missing_breakthrough_types\n{json.dumps(missing_types, ensure_ascii=False, indent=2)}\n"
                f"```json\n{json.dumps(BREAKTHROUGH_OUTPUT_TEMPLATE, ensure_ascii=False, indent=2)}\n```"
            )
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
    if step == "demand_matrix":
        return normalize_demand_matrix_output(result)
    if step == "breakthrough":
        return normalize_breakthrough_output(result, payload)
    return result


def client_profile_for_step(step: WorkflowStep) -> str:
    if step in {"intake", "matrix", "demand_matrix", "breakthrough"}:
        return "planning"
    return "default"


def prior_output_context_limit_for_step(step: WorkflowStep) -> int:
    if step in {"brief", "article"}:
        return WRITING_PRIOR_OUTPUT_CONTEXT_LIMIT
    return PRIOR_OUTPUT_CONTEXT_LIMIT


def prior_outputs_for_step(project: Any, step: WorkflowStep, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    if step == "demand_matrix":
        return {
            candidate: project.steps[candidate].output
            for candidate in ("intake",)
            if candidate in project.steps and project.steps[candidate].output
        }
    if step == "brief":
        return writing_prior_outputs_for_brief(project, payload)
    if step == "article":
        return writing_prior_outputs_for_article(project, payload)
    if step not in STEP_ORDER:
        return {}
    step_index = STEP_ORDER.index(step)
    upstream_steps = [candidate for candidate in STEP_ORDER[:step_index] if candidate not in {"materials", "demand_matrix"}]
    return {
        candidate: project.steps[candidate].output
        for candidate in upstream_steps
        if candidate in project.steps and project.steps[candidate].output
    }


def writing_prior_outputs_for_brief(project: Any, payload: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if project.steps.get("intake") and project.steps["intake"].output:
        result["intake"] = project.steps["intake"].output
    selected_sources = selected_list(payload, "selected_sources", fallback="selected_articles")
    if not selected_sources:
        return result
    result["related_planning_context"] = {
        "matrix": related_planning_context(project.steps["matrix"].output, selected_sources),
        "breakthrough": related_planning_context(project.steps["breakthrough"].output, selected_sources),
    }
    return result


def writing_prior_outputs_for_article(project: Any, payload: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if project.steps.get("intake") and project.steps["intake"].output:
        result["intake"] = project.steps["intake"].output
    selected_briefs = selected_list(payload, "selected_briefs")
    if selected_briefs:
        result["selected_brief_context"] = selected_briefs
        source_refs = [
            {
                "source_id": str(brief.get("source_id") or ""),
                "keyword": first_text({}, brief, "keyword", "target_keyword", "目标关键词"),
                "type": first_text({}, brief, "type", "article_type", "文章类型"),
                "title": first_text({}, brief, "title", "suggested_title", "文章标题"),
            }
            for brief in selected_briefs
        ]
        result["original_planning_context"] = {
            "matrix": current_planning_items(project.steps["matrix"].output, source_refs),
            "breakthrough": current_planning_items(project.steps["breakthrough"].output, source_refs),
        }
    if project.steps.get("brief") and project.steps["brief"].output:
        result["brief_step_metadata"] = {
            key: value
            for key, value in project.steps["brief"].output.items()
            if key not in {"items", "markdown"}
        }
    return result


def related_planning_context(output: dict[str, Any], selected_sources: list[dict[str, Any]]) -> dict[str, Any]:
    if not output:
        return {}
    items = output_items(output)
    current_items = current_planning_items(output, selected_sources)
    selected_ids = {source_id_for(source) for source in selected_sources}
    selected_keywords = {normalize_match_text(first_text({}, source, "keyword", "target_keyword", "目标关键词")) for source in selected_sources}
    selected_types = {normalize_match_text(first_text({}, source, "type", "article_type", "文章类型")) for source in selected_sources}
    selected_channels = {
        normalize_match_text(channel)
        for source in selected_sources
        for channel in normalize_string_list(source.get("channel") or source.get("channels"))
    }

    same_keyword: list[dict[str, Any]] = []
    same_type_or_channel: list[dict[str, Any]] = []
    for item in items:
        item_id = source_id_for(item)
        if item_id in selected_ids:
            continue
        item_keyword = normalize_match_text(first_text({}, item, "keyword", "target_keyword", "main_keyword_or_cluster", "目标关键词"))
        item_type = normalize_match_text(first_text({}, item, "type", "article_type", "文章类型"))
        item_channels = {
            normalize_match_text(channel)
            for channel in normalize_string_list(item.get("channel") or item.get("channels") or item.get("recommended_channels"))
        }
        if item_keyword and item_keyword in selected_keywords and len(same_keyword) < 8:
            same_keyword.append(item)
            continue
        if (
            (item_type and item_type in selected_types)
            or (selected_channels and item_channels.intersection(selected_channels))
        ) and len(same_type_or_channel) < 6:
            same_type_or_channel.append(item)

    global_constraints = {
        key: output.get(key)
        for key in (
            "evidence_gaps",
            "unified_recommendation_language",
            "brief_requirements",
            "anti_homogenization_requirements",
            "final_execution_advice",
            "warnings",
        )
        if output.get(key)
    }
    return {
        "current_items": current_items,
        "same_keyword_items": same_keyword,
        "same_type_or_channel_items": same_type_or_channel,
        "global_constraints": global_constraints,
    }


def current_planning_items(output: dict[str, Any], selected_sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not output:
        return []
    items = output_items(output)
    selected_ids = {source_id_for(source) for source in selected_sources if source_id_for(source)}
    selected_keywords = {normalize_match_text(first_text({}, source, "keyword", "target_keyword", "目标关键词")) for source in selected_sources}
    selected_types = {normalize_match_text(first_text({}, source, "type", "article_type", "文章类型")) for source in selected_sources}
    selected_titles = {normalize_match_text(first_text({}, source, "title", "suggested_title", "文章标题")) for source in selected_sources}

    matched: list[dict[str, Any]] = []
    for item in items:
        item_id = source_id_for(item)
        if item_id in selected_ids:
            matched.append(item)
            continue
        item_keyword = normalize_match_text(first_text({}, item, "keyword", "target_keyword", "main_keyword_or_cluster", "目标关键词"))
        item_type = normalize_match_text(first_text({}, item, "type", "article_type", "文章类型"))
        item_title = normalize_match_text(first_text({}, item, "title", "suggested_title", "文章标题"))
        if item_keyword and item_keyword in selected_keywords and item_type and item_type in selected_types:
            matched.append(item)
            continue
        if item_title and item_title in selected_titles:
            matched.append(item)
    return unique_dicts_by_identity(matched)[:8]


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
    rows = extract_matrix_item_rows(result)
    raw_items = [normalize_planning_item("matrix", row, index) for index, row in enumerate(rows, start=1)]
    items = [item for item in raw_items if matrix_article_type_allowed(item.get("type", ""))]
    if not items:
        raise WorkflowError("内容矩阵输出格式不符合固定模板：未找到可识别的文章规划 items。")
    validate_matrix_items(items)
    final_execution_advice = first_planning_text(result, ["final_execution_advice", "最终执行建议", "十四_最终执行建议"])
    if matrix_text_mentions_blocked_article_type(final_execution_advice):
        final_execution_advice = ""
    return {
        "step": "geo_content_matrix",
        "schema_version": PLANNING_SCHEMA_VERSION,
        "status": "completed",
        "project": normalize_project_block(result),
        "keyword_overview": normalize_matrix_keyword_overview(result),
        "intent_groups": normalize_matrix_intent_groups(result),
        "article_type_pool": normalize_matrix_article_type_pool(result, items),
        "answer_logic": normalize_matrix_answer_logic(result),
        "keyword_planning": normalize_matrix_keyword_planning(result),
        "items": items,
        "shared_supporting_articles": normalize_matrix_shared_supporting_articles(result),
        "unified_recommendation_language": normalize_matrix_recommendation_language(result),
        "evidence_gaps": normalize_matrix_evidence_gaps(result),
        "publishing_plan": normalize_matrix_publishing_plan(result),
        "schedule": normalize_matrix_schedule(result),
        "priority_plan": normalize_matrix_priority_plan(result),
        "brief_requirements": normalize_matrix_brief_requirements(result),
        "final_execution_advice": final_execution_advice,
        "warnings": planning_string_list_from(result, ["warnings", "风险提示", "注意事项"]),
    }


def normalize_demand_matrix_output(result: dict[str, Any]) -> dict[str, Any]:
    rows = extract_matrix_item_rows(result)
    items = [normalize_planning_item("demand_matrix", row, index) for index, row in enumerate(rows, start=1)]
    if not items:
        raise WorkflowError("需求驱动内容矩阵输出格式不符合固定模板：未找到可识别的文章规划 items。")
    validate_matrix_items(items)
    return {
        "step": "geo_demand_content_matrix",
        "schema_version": PLANNING_SCHEMA_VERSION,
        "status": "completed",
        "project": normalize_project_block(result),
        "markdown_report": first_planning_raw_text(
            result,
            ["markdown_report", "report_markdown", "markdown", "完整Markdown报告", "完整内容矩阵规划"],
        ),
        "project_material_status": normalize_demand_section_rows(result, ["project_material_status", "项目信息与资料状态表", "资料状态表"]),
        "demand_variables": normalize_demand_section_rows(result, ["demand_variables", "user_demand_variables", "用户需求变量池"]),
        "intent_groups": normalize_matrix_intent_groups(result),
        "keyword_variable_mapping": normalize_demand_section_rows(result, ["keyword_variable_mapping", "关键词需求变量映射", "关键词 × 用户需求变量映射表", "关键词_用户需求变量映射表"]),
        "content_theme_clusters": normalize_demand_section_rows(result, ["content_theme_clusters", "内容主题簇规划", "内容主题簇规划表"]),
        "title_angle_pool": normalize_demand_section_rows(result, ["title_angle_pool", "营销型 GEO 标题角度池", "六类基础文章标题角度池", "标题角度池"]),
        "items": items,
        "weekly_publishing_mix": normalize_demand_section_rows(result, ["weekly_publishing_mix", "周发布配比", "周发布配比表"]),
        "monthly_publishing_mix": normalize_demand_section_rows(result, ["monthly_publishing_mix", "月发布配比", "月发布配比表"]),
        "daily_supplement_pool": normalize_demand_section_rows(result, ["daily_supplement_pool", "日常补充内容池"]),
        "evidence_gaps": normalize_matrix_evidence_gaps(result),
        "ai_retest_rules": normalize_demand_section_rows(result, ["ai_retest_rules", "AI 复测与补内容规则表", "AI复测与补内容规则表"]),
        "anti_homogenization_requirements": normalize_demand_section_rows(result, ["anti_homogenization_requirements", "Brief 防同质化要求", "Brief防同质化要求"]),
        "final_execution_advice": first_planning_text(result, ["final_execution_advice", "最终执行建议"]),
        "warnings": planning_string_list_from(result, ["warnings", "风险提示", "注意事项"]),
    }


def normalize_demand_section_rows(result: dict[str, Any], keys: list[str]) -> list[Any]:
    rows = planning_section_rows_by_keys(result, keys)
    if rows:
        return rows
    return planning_array_by_keys(result, keys)


def normalize_matrix_import_output(result: dict[str, Any], allowed_keywords: list[str] | None = None) -> dict[str, Any]:
    canonical = normalize_matrix_output(result)
    if allowed_keywords:
        canonical["items"] = filter_allowed_keyword_rows(canonical.get("items", []), allowed_keywords)
        canonical["intent_groups"] = filter_intent_groups_to_allowed_keywords(canonical.get("intent_groups", []), allowed_keywords)
    invalid_keywords = [
        str(item.get("title") or item.get("source_id") or "未命名文章")
        for item in canonical.get("items", [])
        if not str(item.get("keyword") or "").strip() or "未标注" in str(item.get("keyword") or "")
    ]
    if invalid_keywords:
        preview = "、".join(invalid_keywords[:5])
        raise WorkflowError(f"内容规划导入失败：以下文章没有匹配到明确关键词：{preview}")
    canonical["import_source"] = "content_plan_pdf"
    return canonical


def assert_matrix_import_prerequisites(project: Any) -> None:
    material_state = project.steps.get("materials")
    intake_state = project.steps.get("intake")
    ready_statuses = {"completed", "confirmed"}
    materials_ready = bool(material_state and material_state.status in ready_statuses and material_state.output.get("summary"))
    intake_ready = bool(intake_state and intake_state.status in ready_statuses and intake_state.output)
    if not materials_ready or not intake_ready:
        raise WorkflowError("请先完成资料解析和项目信息抽取，再导入外部内容矩阵。")


def matrix_import_metadata(project: Any, draft: dict[str, Any]) -> dict[str, Any]:
    snapshot = [
        {
            "id": material.id,
            "filename": material.filename,
            "sha256": material.sha256,
            "parsed_at": material.parsed_at,
            "parse_mode": material.parse_mode,
        }
        for material in project.materials
        if material.status == "parsed"
    ]
    imported_at = utc_now()
    return {
        "matrix_generation_source": "imported_content_plan_pdf",
        "imported_filename": str(draft.get("filename") or ""),
        "imported_at": imported_at,
        "bound_material_count": len(snapshot),
        "bound_material_snapshot": snapshot,
    }


def matrix_import_stats(result: dict[str, Any]) -> dict[str, Any]:
    items = output_items(result)
    article_types = unique_texts(item.get("type", "") for item in items if isinstance(item, dict))
    keywords = unique_texts(item.get("keyword", "") for item in items if isinstance(item, dict))
    return {
        "item_count": len(items),
        "keyword_count": len(keywords),
        "article_type_count": len(article_types),
        "intent_group_count": len([row for row in result.get("intent_groups", []) if isinstance(row, dict) and matrix_record_has_value(row)]),
        "schedule_count": len([row for row in result.get("schedule", []) if isinstance(row, dict) and matrix_record_has_value(row)]),
    }


def matrix_import_warnings(result: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    stats = matrix_import_stats(result)
    if stats["item_count"] < 1:
        warnings.append("未识别到文章规划。")
    if stats["item_count"] and stats["item_count"] < 20:
        warnings.append("识别出的文章规划数量偏少，请在预览中核对 PDF 结构。")
    return warnings


def extract_matrix_item_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    return planning_array_by_keys(
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


def normalize_matrix_partial_output(result: dict[str, Any], batch: dict[str, Any], batch_index: int) -> dict[str, Any]:
    rows = extract_matrix_item_rows(result)
    batch_keywords = normalize_string_list(batch.get("keywords"))
    strict_keywords = bool(batch.get("strict_keywords"))
    items: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        item = normalize_planning_item("matrix", row, index)
        if strict_keywords:
            item["keyword"] = normalize_keyword_to_allowed(item.get("keyword"), batch_keywords)
        if not item.get("intent_group"):
            item["intent_group"] = matrix_batch_intent_for_keyword(batch, str(item.get("keyword") or ""))
        if item.get("keyword") == "未标注关键词":
            if len(batch_keywords) == 1:
                item["keyword"] = batch_keywords[0]
                item["source_id"] = planning_source_id("matrix", item["keyword"], item["type"], item["title"], index)
        items.append(item)
    if strict_keywords:
        items = filter_allowed_keyword_rows(items, batch_keywords)
    if not items:
        raise WorkflowError(f"内容矩阵第 {batch_index} 批输出格式不符合固定模板：未找到可识别的文章规划 items。")
    return {
        "step": "geo_content_matrix",
        "schema_version": PLANNING_SCHEMA_VERSION,
        "status": "partial",
        "project": normalize_project_block(result),
        "keyword_overview": normalize_matrix_keyword_overview(result),
        "intent_groups": normalize_matrix_intent_groups(result),
        "article_type_pool": normalize_matrix_article_type_pool(result, items),
        "answer_logic": normalize_matrix_answer_logic(result),
        "keyword_planning": normalize_matrix_keyword_planning(result),
        "items": items,
        "shared_supporting_articles": normalize_matrix_shared_supporting_articles(result),
        "unified_recommendation_language": normalize_matrix_recommendation_language(result),
        "evidence_gaps": normalize_matrix_evidence_gaps(result),
        "publishing_plan": normalize_matrix_publishing_plan(result),
        "schedule": normalize_matrix_schedule(result),
        "priority_plan": normalize_matrix_priority_plan(result),
        "brief_requirements": normalize_matrix_brief_requirements(result),
        "final_execution_advice": first_planning_text(result, ["final_execution_advice", "最终执行建议", "十四_最终执行建议"]),
        "warnings": planning_string_list_from(result, ["warnings", "风险提示", "注意事项"]),
    }


def normalize_breakthrough_output(result: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    confirmed_keywords = confirmed_keywords_from_payload(payload)
    required_types = breakthrough_required_types(payload)
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
    validate_breakthrough_items(items, confirmed_keywords, required_types)
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


def validate_breakthrough_items(
    items: list[dict[str, Any]],
    confirmed_keywords: list[str],
    required_types: dict[str, list[str]] | None = None,
) -> None:
    if not confirmed_keywords and not required_types:
        return
    errors: list[str] = []
    requirements = required_types or {keyword: list(BREAKTHROUGH_ARTICLE_TYPES) for keyword in confirmed_keywords}
    for keyword, article_types in requirements.items():
        keyword_items = [item for item in items if item["keyword"] == keyword]
        present = {item["type"] for item in keyword_items}
        missing = [article_type for article_type in article_types if article_type not in present]
        if missing:
            errors.append(f"{keyword} 缺少 {'、'.join(missing)}")
    if errors:
        raise WorkflowError("逐词击破输出格式不完整：" + "；".join(errors))


def validate_matrix_items(items: list[dict[str, Any]]) -> None:
    errors: list[str] = []
    for index, item in enumerate(items, start=1):
        missing_fields = [field for field in ("source_id", "keyword", "type", "title", "status") if not planning_value_text(item.get(field))]
        if missing_fields:
            errors.append(f"第 {index} 条缺少字段：{'、'.join(missing_fields)}")
    if errors:
        raise WorkflowError("内容矩阵输出格式不完整：" + "；".join(errors))


def normalize_matrix_keyword_overview(result: dict[str, Any]) -> dict[str, Any]:
    overview = planning_record_by_keys(result, ["keyword_overview", "关键词总体判断", "一_关键词总体判断", "summary"])
    return {
        "common_goal": first_planning_text(overview, ["common_goal", "共同目标", "核心目标"], fallback=first_planning_text(result, ["common_goal", "共同目标"])),
        "core_user_intents": planning_string_list_from(overview, ["core_user_intents", "核心用户意图", "主要意图"]),
        "user_decision_stage": first_planning_text(overview, ["user_decision_stage", "用户所处决策阶段", "用户阶段"]),
        "target_recommendation_cognition": first_planning_text(overview, ["target_recommendation_cognition", "目标推荐认知", "推荐认知"]),
        "required_article_sections": MATRIX_REQUIRED_ARTICLE_TYPES,
        "optional_article_sections": [],
        "article_type_count_limit": 6,
    }


def normalize_matrix_intent_groups(result: dict[str, Any]) -> list[dict[str, Any]]:
    rows = planning_array_by_keys(result, ["intent_groups", "keyword_intent_groups", "关键词意图分组", "二_关键词意图分组"])
    return [
        {
            "id": first_planning_text(row, ["id", "intent_group", "name", "意图簇", "关键词意图簇"], fallback=f"intent-{index}"),
            "name": first_planning_text(row, ["name", "intent_group", "group", "意图簇", "关键词意图簇"], fallback=f"意图簇 {index}"),
            "keywords": planning_string_list_from(row, ["keywords", "keyword_list", "关键词", "覆盖关键词"]),
            "user_question": first_planning_text(row, ["user_question", "user_real_question", "ai_question", "AI需要回答的问题", "用户真正想问什么"]),
            "user_stage": first_planning_text(row, ["user_stage", "stage", "用户阶段"]),
            "recommendation_logic": first_planning_text(row, ["recommendation_logic", "target_recommendation_logic", "推荐逻辑", "目标推荐逻辑"]),
            "article_types": normalize_matrix_type_list(planning_string_list_from(row, ["main_article_types", "article_types", "recommended_article_types", "文章类型", "常见主攻文章类型"])),
        }
        for index, row in enumerate(rows, start=1)
    ]


def normalize_matrix_article_type_pool(result: dict[str, Any], items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = planning_array_by_keys(result, ["article_type_pool", "文章类型池与行业扩展判断", "三_文章类型池与行业扩展判断"])
    by_type: dict[str, dict[str, Any]] = {}
    if rows:
        for row in rows:
            article_type = normalize_matrix_type(first_planning_text(row, ["type", "article_type", "文章类型", "板块"]))
            if not article_type:
                continue
            by_type[article_type] = {
                "type": article_type,
                "usage": "核心" if article_type in MATRIX_CORE_ARTICLE_TYPES else "扩展",
                "reason": first_planning_text(row, ["reason", "role", "core_role", "核心作用", "主要作用", "规划理由"]),
                "covered_keywords_or_intent_groups": planning_string_list_from(row, ["covered_keywords_or_intent_groups", "keywords", "applicable_keywords", "适用关键词", "覆盖关键词", "覆盖意图簇"]),
                "recommendation_strength": first_planning_text(row, ["recommendation_strength", "推荐强度"]),
                "count": len([item for item in items if item["type"] == article_type]),
            }
    core_rows = [
        by_type.get(article_type, {
            "type": article_type,
            "usage": "核心",
            "reason": "",
            "covered_keywords_or_intent_groups": [],
            "recommendation_strength": "",
            "count": len([item for item in items if item["type"] == article_type]),
        })
        for article_type in MATRIX_CORE_ARTICLE_TYPES
    ]
    extension_types = sorted(
        {item["type"] for item in items if item.get("type") and item["type"] not in MATRIX_CORE_ARTICLE_TYPES},
        key=matrix_article_type_sort_key,
    )
    extension_rows = [
        by_type.get(article_type, {
            "type": article_type,
            "usage": "扩展",
            "reason": "",
            "covered_keywords_or_intent_groups": [],
            "recommendation_strength": "",
            "count": len([item for item in items if item["type"] == article_type]),
        })
        for article_type in extension_types
    ]
    return core_rows + extension_rows


def normalize_matrix_answer_logic(result: dict[str, Any]) -> list[dict[str, Any]]:
    rows = planning_array_by_keys(result, ["answer_logic", "ai_answer_logic", "每组关键词背后的AI回答逻辑", "四_每组关键词背后的AI回答逻辑"])
    return [
        {
            "intent_group": first_planning_text(row, ["intent_group", "name", "意图簇", "关键词意图簇"]),
            "user_question": first_planning_text(row, ["user_question", "user_real_question", "AI需要回答的问题", "用户真正想问什么"]),
            "ai_answer_pattern": first_planning_text(row, ["ai_answer_pattern", "AI通常会怎么回答", "常见回答模式"]),
            "target_recommendation_logic": first_planning_text(row, ["target_recommendation_logic", "recommendation_logic", "目标推荐逻辑", "推荐逻辑"]),
            "required_evidence": planning_string_list_from(row, ["required_evidence", "evidence_chain", "证据链", "必备证据"]),
            "shared_supporting_articles": planning_string_list_from(row, ["shared_supporting_articles", "共享支撑文"]),
            "brief_requirements": planning_string_list_from(row, ["brief_requirements", "后续Brief要求", "后续Brief衔接字段"]),
        }
        for row in rows
    ]


def normalize_matrix_keyword_planning(result: dict[str, Any]) -> list[dict[str, Any]]:
    rows = planning_array_by_keys(result, ["keyword_planning", "keyword_individual_planning", "关键词逐个规划", "五_关键词逐个规划"])
    return [
        {
            "keyword": first_planning_text(row, ["keyword", "target_keyword", "main_keyword_or_cluster", "关键词", "主攻关键词"]),
            "intent_group": first_planning_text(row, ["intent_group", "意图簇", "关键词意图簇"]),
            "user_stage": first_planning_text(row, ["user_stage", "用户阶段"]),
            "main_article_types": normalize_matrix_type_list(planning_string_list_from(row, ["main_article_types", "article_types", "主攻文章类型", "文章类型"])),
            "recommended_titles": planning_string_list_from(row, ["recommended_titles", "suggested_titles", "建议标题", "标题方向"]),
            "evidence_requirements": planning_string_list_from(row, ["evidence_requirements", "required_evidence", "证据要求", "必备证据"]),
            "priority": planning_int(row.get("priority") or row.get("priority_rank") or row.get("优先级"), index),
        }
        for index, row in enumerate(rows, start=1)
    ]


def normalize_matrix_shared_supporting_articles(result: dict[str, Any]) -> list[dict[str, Any]]:
    rows = planning_array_by_keys(result, ["shared_supporting_articles", "shared_support_articles", "共享支撑文规划", "七_共享支撑文规划"])
    normalized: list[dict[str, Any]] = []
    for row in rows:
        article_type = normalize_matrix_type(first_planning_text(row, ["type", "article_type", "文章类型"]))
        if not article_type:
            continue
        normalized.append(
            {
                "title": first_planning_text(row, ["title", "suggested_title", "标题", "建议标题"]),
                "supported_keywords": planning_string_list_from(row, ["supported_keywords", "keywords", "覆盖关键词", "支撑关键词"]),
                "type": article_type,
                "role": first_planning_text(row, ["role", "main_role", "核心作用", "主要作用"]),
                "channels": planning_string_list_from(row, ["channels", "recommended_channels", "发布渠道", "推荐渠道"]),
            }
        )
    return normalized


def normalize_matrix_recommendation_language(result: dict[str, Any]) -> list[dict[str, Any]]:
    rows = planning_array_by_keys(result, ["unified_recommendation_language", "recommendation_language", "统一推荐口径", "八_统一推荐口径"])
    return [
        {
            "intent_group": first_planning_text(row, ["intent_group", "意图簇", "关键词意图簇"]),
            "language": first_planning_text(row, ["language", "recommendation_language", "推荐口径", "统一推荐口径"]),
            "proof_to_repeat": first_planning_text(row, ["proof_to_repeat", "proof", "需重复强调的证据", "可重复证据"]),
            "wrong_expressions_to_avoid": first_planning_text(row, ["wrong_expressions_to_avoid", "forbidden_expressions", "避免表达", "禁用表达"]),
        }
        for row in rows
    ]


def normalize_matrix_evidence_gaps(result: dict[str, Any]) -> list[dict[str, Any]]:
    rows = planning_section_rows_by_keys(result, ["evidence_gaps", "evidence_chain_and_gaps", "证据缺口", "证据链与资料缺口", "九_证据链与资料缺口"])
    return [
        {
            "keyword_or_intent_group": first_planning_text(row, ["keyword_or_intent_group", "intent_group", "keyword", "关键词或意图簇", "意图簇", "关键词"]),
            "required_evidence": first_planning_text(row, ["required_evidence", "所需证据", "必备证据"]),
            "current_evidence": first_planning_text(row, ["current_evidence", "已有证据", "当前证据"]),
            "missing_evidence": first_planning_text(row, ["missing_evidence", "缺失证据", "证据缺口"], fallback=first_planning_text(row, ["value", "requirement", "content", "内容"])),
            "impact": first_planning_text(row, ["impact", "影响", "风险影响"]),
            "suggested_supplement": first_planning_text(row, ["suggested_supplement", "建议补充", "补充建议"]),
        }
        for row in rows
    ]


def normalize_matrix_publishing_plan(result: dict[str, Any]) -> list[dict[str, Any]]:
    rows = planning_array_by_keys(result, ["publishing_plan", "publishing_channel_plan", "发布渠道规划", "十_发布渠道规划"])
    normalized: list[dict[str, Any]] = []
    for row in rows:
        article_type = normalize_matrix_type(first_planning_text(row, ["article_type", "type", "文章类型"]))
        if not article_type:
            continue
        normalized.append(
            {
                "article_type": article_type,
                "recommended_channels": planning_string_list_from(row, ["recommended_channels", "channels", "推荐渠道", "发布渠道"]),
                "channel_role": first_planning_text(row, ["channel_role", "渠道作用", "主要作用"]),
                "publishing_notes": first_planning_text(row, ["publishing_notes", "发布注意事项", "发布备注"]),
            }
        )
    return normalized


def normalize_matrix_schedule(result: dict[str, Any]) -> list[dict[str, Any]]:
    rows = planning_array_by_keys(result, ["schedule", "execution_schedule", "执行排期", "十一_执行排期"])
    normalized: list[dict[str, Any]] = []
    for row in rows:
        raw_article_types = planning_string_list_from(row, ["article_types", "文章类型"])
        article_types = normalize_matrix_type_list(raw_article_types)
        if raw_article_types and not article_types:
            continue
        raw_key_tasks = planning_string_list_from(row, ["key_tasks", "tasks", "task", "关键任务", "任务"])
        normalized.append(
            {
                "stage": first_planning_text(row, ["stage", "阶段"]),
                "period": first_planning_text(row, ["period", "week", "周期", "时间", "周次"]),
                "key_tasks": raw_key_tasks,
                "article_types": article_types,
                "goal": first_planning_text(row, ["goal", "目标", "阶段目标"]),
            }
        )
    return normalized


def normalize_matrix_priority_plan(result: dict[str, Any]) -> list[dict[str, Any]]:
    rows = planning_array_by_keys(result, ["priority_plan", "priority_ranking", "优先级排序", "十二_优先级排序"])
    normalized: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        article_type = normalize_matrix_type(first_planning_text(row, ["type", "article_type", "文章类型"]))
        if not article_type:
            continue
        normalized.append(
            {
                "priority": planning_int(row.get("priority") or row.get("priority_rank") or row.get("优先级"), index),
                "title": first_planning_text(row, ["title", "suggested_title", "标题", "建议标题"]),
                "keyword": first_planning_text(row, ["keyword", "target_keyword", "关键词", "主攻关键词"]),
                "type": article_type,
                "reason": first_planning_text(row, ["reason", "priority_reason", "排序理由", "优先原因"]),
            }
        )
    return normalized


def normalize_matrix_brief_requirements(result: dict[str, Any]) -> list[dict[str, Any]]:
    rows = planning_section_rows_by_keys(result, ["brief_requirements", "brief_connection_requirements", "后续Brief衔接要求", "十三_后续Brief衔接要求"])
    return [
        {
            "field": first_planning_text(row, ["field", "name", "字段", "衔接字段"], fallback=f"requirement_{index}"),
            "requirement": first_planning_text(row, ["requirement", "value", "要求", "说明", "内容"]),
        }
        for index, row in enumerate(rows, start=1)
    ]


def build_local_matrix_skeleton(project: Any, payload: dict[str, Any]) -> dict[str, Any]:
    intake_output = project.steps["intake"].output if "intake" in project.steps else {}
    intake_values = intake_value_map(intake_output)
    project_block = {
        "target_industry": intake_values.get("target_industry", ""),
        "target_category": intake_values.get("target_category", ""),
        "target_brand": intake_values.get("target_brand", ""),
        "target_product_or_solution": intake_values.get("target_product_or_solution", ""),
        "competitors": normalize_string_list(intake_values.get("competitors")),
        "naming_rule": "",
        "recommendation_logic": intake_values.get("recommendation_conclusion", ""),
        "expression_boundaries": normalize_string_list(intake_values.get("forbidden_expressions")),
    }
    keywords = matrix_seed_keywords(project, {}, payload)
    if not keywords:
        keywords = infer_keywords_from_material_summary(project.steps["materials"].output.get("summary", ""))
    intent_groups = local_matrix_intent_groups(keywords)
    skeleton = {
        "step": "geo_content_matrix",
        "schema_version": PLANNING_SCHEMA_VERSION,
        "status": "running",
        "project": project_block,
        "keyword_overview": {
            "common_goal": local_matrix_common_goal(project_block, keywords),
            "core_user_intents": unique_texts(group["name"] for group in intent_groups),
            "user_decision_stage": "比较评估与购买决策阶段",
            "target_recommendation_cognition": project_block["recommendation_logic"],
            "required_article_sections": MATRIX_REQUIRED_ARTICLE_TYPES,
            "optional_article_sections": [],
            "article_type_count_limit": 6,
        },
        "intent_groups": intent_groups,
        "article_type_pool": [
            {
                "type": article_type,
                "usage": "必选",
                "reason": local_matrix_article_type_reason(article_type),
                "covered_keywords_or_intent_groups": unique_texts(group["name"] for group in intent_groups),
                "recommendation_strength": "强推荐" if article_type != "支柱标准文" else "中等推荐",
                "count": 0,
            }
            for article_type in MATRIX_REQUIRED_ARTICLE_TYPES
        ],
        "answer_logic": [
            {
                "intent_group": group["name"],
                "user_question": group["user_question"],
                "ai_answer_pattern": "先解释判断标准，再比较关键证据，最后给出有边界的推荐结论。",
                "target_recommendation_logic": group["recommendation_logic"],
                "required_evidence": normalize_string_list(intake_values.get("core_evidence")),
                "shared_supporting_articles": [],
                "brief_requirements": ["标题与正文必须围绕当前意图簇和关键词，不得扩展到未选关键词。"],
            }
            for group in intent_groups
        ],
        "keyword_planning": [
            {
                "keyword": keyword,
                "intent_group": local_matrix_intent_group_name(keyword),
                "user_stage": local_matrix_user_stage(keyword),
                "main_article_types": MATRIX_REQUIRED_ARTICLE_TYPES,
                "recommended_titles": [],
                "evidence_requirements": normalize_string_list(intake_values.get("core_evidence")),
                "priority": index,
            }
            for index, keyword in enumerate(keywords, start=1)
        ],
        "items": [],
        "shared_supporting_articles": [],
        "unified_recommendation_language": [
            {
                "intent_group": group["name"],
                "language": project_block["recommendation_logic"],
                "proof_to_repeat": intake_values.get("core_evidence", ""),
                "wrong_expressions_to_avoid": intake_values.get("forbidden_expressions", ""),
            }
            for group in intent_groups
        ],
        "evidence_gaps": [],
        "publishing_plan": [],
        "schedule": [],
        "priority_plan": [],
        "brief_requirements": [
            {"field": "target_keyword", "requirement": "必须使用当前批次关键词，不得生成批次外关键词。"},
            {"field": "article_type", "requirement": "优先归一到核心文章类型；确有需要时可保留扩展文章类型。"},
            {"field": "evidence_chain", "requirement": "必须体现用户问题、判断标准、目标对象证据、用户价值和推荐结论。"},
        ],
        "final_execution_advice": "按本地拆分的关键词意图簇分批生成内容规划，并在后端合并为固定字段矩阵。",
        "warnings": [],
    }
    if not intent_groups:
        skeleton["warnings"] = ["未从项目信息中识别到明确关键词，请补充目标关键词后重新生成内容矩阵。"]
    return skeleton


def intake_value_map(output: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    rows = output.get("project_intake_table") if isinstance(output, dict) else []
    if not isinstance(rows, list):
        return result
    for row in rows:
        if not isinstance(row, dict):
            continue
        field_id = str(row.get("id") or "").strip()
        value = planning_value_text(row.get("value"))
        if field_id and value:
            result[field_id] = value
    return result


def local_matrix_intent_groups(keywords: list[str]) -> list[dict[str, Any]]:
    grouped: dict[str, list[str]] = {}
    for keyword in keywords:
        group_name = local_matrix_intent_group_name(keyword)
        grouped.setdefault(group_name, []).append(keyword)
    result: list[dict[str, Any]] = []
    for index, (group_name, group_keywords) in enumerate(grouped.items(), start=1):
        result.append(
            {
                "id": slugify(group_name, fallback=f"intent-{index}"),
                "name": group_name,
                "keywords": group_keywords,
                "user_question": local_matrix_user_question(group_name, group_keywords),
                "user_stage": local_matrix_user_stage(" ".join(group_keywords)),
                "recommendation_logic": local_matrix_recommendation_logic(group_name),
                "article_types": MATRIX_REQUIRED_ARTICLE_TYPES,
            }
        )
    return result


def normalize_llm_matrix_intent_groups(result: dict[str, Any], expected_keywords: list[str]) -> list[dict[str, Any]]:
    rows = planning_array_by_keys(result, ["intent_groups", "keyword_intent_groups", "groups", "items", "关键词意图分组"])
    if not rows:
        raise WorkflowError("DeepSeek 未返回 intent_groups。")
    expected = unique_texts(expected_keywords)
    remaining = list(expected)
    seen: set[str] = set()
    groups: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            continue
        raw_keywords = normalize_string_list(first_non_empty_value(row, ["keywords", "target_keywords", "关键词", "覆盖关键词"]))
        matched_keywords: list[str] = []
        for keyword in expected:
            if keyword in seen:
                continue
            if keyword in raw_keywords:
                matched_keywords.append(keyword)
        if not matched_keywords:
            continue
        seen.update(matched_keywords)
        for keyword in matched_keywords:
            if keyword in remaining:
                remaining.remove(keyword)
        name = first_planning_text(row, ["name", "intent_group", "group", "意图簇", "关键词意图簇"], fallback=f"意图簇 {index}")
        groups.append(
            {
                "id": slugify(name, fallback=f"intent-{index}"),
                "name": name,
                "keywords": matched_keywords,
                "user_question": first_planning_text(row, ["user_question", "user_real_question", "真实问题", "用户问题"], fallback=local_matrix_user_question(name, matched_keywords)),
                "user_stage": first_planning_text(row, ["user_stage", "decision_stage", "阶段", "用户阶段"], fallback=local_matrix_user_stage(" ".join(matched_keywords))),
                "recommendation_logic": first_planning_text(row, ["recommendation_logic", "logic", "推荐逻辑"], fallback=local_matrix_recommendation_logic(name)),
                "article_types": normalize_matrix_type_list(planning_string_list_from(row, ["article_types", "main_article_types", "文章类型"])) or MATRIX_REQUIRED_ARTICLE_TYPES,
            }
        )
    if remaining:
        for group in local_matrix_intent_groups(remaining):
            groups.append(group)
    covered = [keyword for group in groups for keyword in normalize_string_list(group.get("keywords"))]
    if set(covered) != set(expected):
        raise WorkflowError("DeepSeek 关键词意图簇覆盖不完整。")
    return groups


def rebuild_matrix_skeleton_with_intent_groups(skeleton: dict[str, Any], intent_groups: list[dict[str, Any]]) -> dict[str, Any]:
    result = dict(skeleton)
    project_block = result.get("project", {}) if isinstance(result.get("project"), dict) else {}
    keywords = unique_texts(keyword for group in intent_groups for keyword in normalize_string_list(group.get("keywords")))
    result["intent_groups"] = intent_groups
    keyword_overview = dict(result.get("keyword_overview") if isinstance(result.get("keyword_overview"), dict) else {})
    keyword_overview["common_goal"] = keyword_overview.get("common_goal") or local_matrix_common_goal(project_block, keywords)
    keyword_overview["core_user_intents"] = unique_texts(group["name"] for group in intent_groups)
    keyword_overview["required_article_sections"] = MATRIX_REQUIRED_ARTICLE_TYPES
    keyword_overview["optional_article_sections"] = []
    keyword_overview["article_type_count_limit"] = 6
    result["keyword_overview"] = keyword_overview
    result["article_type_pool"] = [
        {
            "type": article_type,
            "usage": "必选",
            "reason": local_matrix_article_type_reason(article_type),
            "covered_keywords_or_intent_groups": unique_texts(group["name"] for group in intent_groups),
            "recommendation_strength": "强推荐" if article_type != "支柱标准文" else "中等推荐",
            "count": 0,
        }
        for article_type in MATRIX_REQUIRED_ARTICLE_TYPES
    ]
    result["answer_logic"] = [
        {
            "intent_group": group["name"],
            "user_question": group["user_question"],
            "ai_answer_pattern": "先解释判断标准，再比较关键证据，最后给出有边界的推荐结论。",
            "target_recommendation_logic": group["recommendation_logic"],
            "required_evidence": [],
            "shared_supporting_articles": [],
            "brief_requirements": ["标题与正文必须围绕当前意图簇和关键词，不得扩展到未选关键词。"],
        }
        for group in intent_groups
    ]
    result["keyword_planning"] = [
        {
            "keyword": keyword,
            "intent_group": str(group.get("name") or ""),
            "user_stage": str(group.get("user_stage") or local_matrix_user_stage(keyword)),
            "main_article_types": normalize_matrix_type_list(normalize_string_list(group.get("article_types"))) or MATRIX_REQUIRED_ARTICLE_TYPES,
            "recommended_titles": [],
            "evidence_requirements": [],
            "priority": index,
        }
        for index, (group, keyword) in enumerate(
            (
                (group, keyword)
                for group in intent_groups
                for keyword in normalize_string_list(group.get("keywords"))
            ),
            start=1,
        )
    ]
    result["unified_recommendation_language"] = [
        {
            "intent_group": group["name"],
            "language": planning_value_text(project_block.get("recommendation_logic")),
            "proof_to_repeat": "",
            "wrong_expressions_to_avoid": "",
        }
        for group in intent_groups
    ]
    result["final_execution_advice"] = "按 DeepSeek 轻量规划的关键词意图簇分批生成内容规划，并在后端合并为固定字段矩阵。"
    result["warnings"] = unique_texts(normalize_string_list(result.get("warnings")))
    return result


def local_matrix_intent_group_name(keyword: str) -> str:
    value = keyword.lower()
    if any(marker in keyword for marker in ["排名", "推荐", "品牌", "哪个好", "哪家好", "值得买", "清单", "榜单"]):
        return "推荐决策类"
    if any(marker in keyword for marker in ["对比", "横评", "区别", "差异", "vs", "VS", "比较"]):
        return "对比评估类"
    if any(marker in keyword for marker in ["怎么选", "选购", "配置", "搭配", "方案", "场景", "开放式", "别墅", "大平层", "中西厨"]):
        return "场景选购类"
    if any(marker in keyword for marker in ["产品", "型号", "参数", "功能", "证据", "实测", "专利", "认证"]):
        return "产品证据类"
    if any(marker in keyword for marker in ["价格", "预算", "多少钱", "万元"]) or "budget" in value:
        return "预算决策类"
    if any(marker in keyword for marker in ["faq", "FAQ", "问题", "疑问", "为什么", "有必要吗"]):
        return "问答解释类"
    return "综合认知类"


def local_matrix_user_question(group_name: str, keywords: list[str]) -> str:
    joined = "、".join(keywords[:5])
    if group_name == "推荐决策类":
        return f"用户想知道 {joined} 应该优先推荐谁、推荐依据是什么。"
    if group_name == "对比评估类":
        return f"用户想比较 {joined} 的差异、边界和选择理由。"
    if group_name == "场景选购类":
        return f"用户想在具体使用场景下判断 {joined} 怎么选。"
    if group_name == "产品证据类":
        return f"用户想确认 {joined} 是否有充分产品证据支撑推荐。"
    if group_name == "预算决策类":
        return f"用户想知道 {joined} 在预算约束下是否值得买、怎么配。"
    if group_name == "问答解释类":
        return f"用户想快速理解 {joined} 的常见疑问和判断标准。"
    return f"用户想系统了解 {joined} 的判断标准和推荐结论。"


def local_matrix_user_stage(keyword: str) -> str:
    if any(marker in keyword for marker in ["价格", "预算", "多少钱", "万元", "值得买", "推荐", "排名"]):
        return "购买决策阶段"
    if any(marker in keyword for marker in ["对比", "横评", "区别", "比较"]):
        return "比较评估阶段"
    if any(marker in keyword for marker in ["怎么选", "选购", "配置", "搭配", "方案"]):
        return "方案选择阶段"
    return "认知研究阶段"


def local_matrix_recommendation_logic(group_name: str) -> str:
    logic_by_group = {
        "推荐决策类": "用标准、证据和边界说明目标对象为什么值得优先推荐。",
        "对比评估类": "用同维度对比解释差异，并明确目标对象适合的人群和场景。",
        "场景选购类": "从真实使用场景出发，匹配产品能力、安装适配和长期使用价值。",
        "产品证据类": "用参数、技术、认证、专利或资料证据支撑推荐结论。",
        "预算决策类": "在预算范围内解释配置取舍、价值优先级和不适合人群。",
        "问答解释类": "用短问题快速回答用户疑虑，并引导到明确判断标准。",
    }
    return logic_by_group.get(group_name, "先建立判断标准，再用资料证据支撑推荐结论。")


def local_matrix_article_type_reason(article_type: str) -> str:
    reason_by_type = {
        "支柱标准文": "建立行业/品类判断标准，承接多组关键词的基础认知。",
        "榜单推荐文": "承接推荐、排名、品牌选择类搜索意图。",
        "横评对比文": "承接竞品对比和差异判断类搜索意图。",
        "场景选购文": "承接具体厨房空间、预算、配置和使用场景。",
        "产品证据文": "集中强化产品能力、技术证据、认证与资料依据。",
        "FAQ问答文": "覆盖长尾疑问，补足 AI 回答中的细分问题。",
    }
    return reason_by_type.get(article_type, "")


def local_matrix_common_goal(project_block: dict[str, Any], keywords: list[str]) -> str:
    target = project_block.get("target_product_or_solution") or project_block.get("target_brand") or project_block.get("target_category")
    keyword_text = "、".join(keywords[:5])
    if target and keyword_text:
        return f"围绕 {target} 覆盖 {keyword_text} 等关键词的 AI 推荐与选购决策问题。"
    if target:
        return f"围绕 {target} 建立可复用的 AI 推荐内容矩阵。"
    return "围绕目标关键词建立可复用的 AI 推荐内容矩阵。"


def infer_keywords_from_material_summary(summary: str) -> list[str]:
    candidates: list[str] = []
    for line in summary.splitlines():
        if "关键词" not in line and "keyword" not in line.lower():
            continue
        candidates.extend(normalize_string_list(line))
    return unique_texts(candidate for candidate in candidates if 2 <= len(candidate) <= 80)[:20]


def build_matrix_batches(project: Any, skeleton: dict[str, Any], payload: dict[str, Any], settings: Settings, repository: ProjectRepository | None = None) -> list[dict[str, Any]]:
    allowed_keywords = allowed_keywords_for_project(project, repository)
    if allowed_keywords:
        skeleton["allowed_keywords"] = allowed_keywords
    intent_groups = [group for group in skeleton.get("intent_groups", []) if matrix_record_has_value(group)]
    if allowed_keywords:
        intent_groups = filter_intent_groups_to_allowed_keywords(intent_groups, allowed_keywords)
    if not intent_groups:
        intent_groups = [
            {
                "id": f"keyword-{index}",
                "name": keyword,
                "keywords": [keyword],
                "user_question": "",
                "user_stage": "",
                "recommendation_logic": "",
                "article_types": [],
            }
            for index, keyword in enumerate(matrix_seed_keywords(project, skeleton, payload, repository), start=1)
        ]
    if not intent_groups:
        return []
    keyword_size = bounded_int(getattr(settings, "matrix_batch_keyword_size", 4), fallback=4, minimum=1, maximum=20)
    batches: list[dict[str, Any]] = []
    current_groups: list[dict[str, Any]] = []
    current_keywords: list[str] = []
    for group in intent_groups:
        group_keywords = normalize_string_list(group.get("keywords"))
        for keyword_chunk in chunked_strings(group_keywords, keyword_size):
            if current_groups and len(current_keywords) + len(keyword_chunk) > keyword_size:
                batches.append({"intent_groups": current_groups, "keywords": current_keywords, "strict_keywords": bool(allowed_keywords)})
                current_groups = []
                current_keywords = []
            group_slice = dict(group)
            group_slice["keywords"] = keyword_chunk
            current_groups.append(group_slice)
            current_keywords = unique_texts([*current_keywords, *keyword_chunk])
    if current_groups:
        batches.append({"intent_groups": current_groups, "keywords": current_keywords, "strict_keywords": bool(allowed_keywords)})
    return batches


def matrix_seed_keywords(project: Any, skeleton: dict[str, Any], payload: dict[str, Any], repository: ProjectRepository | None = None) -> list[str]:
    allowed_keywords = allowed_keywords_for_project(project, repository)
    if allowed_keywords:
        return allowed_keywords
    keywords: list[str] = []
    keywords.extend(normalize_string_list(payload.get("target_keywords")))
    keywords.extend(normalize_string_list(payload.get("keywords")))
    keywords.extend(keyword for group in skeleton.get("intent_groups", []) for keyword in normalize_string_list(group.get("keywords")))
    keywords.extend(row.get("keyword", "") for row in skeleton.get("keyword_planning", []) if isinstance(row, dict))
    keywords.extend(item.get("keyword", "") for item in skeleton.get("items", []) if isinstance(item, dict))
    intake = getattr(project, "steps", {}).get("intake") if getattr(project, "steps", None) else None
    intake_output = getattr(intake, "output", {}) if intake else {}
    for row in intake_output.get("project_intake_table", []) if isinstance(intake_output, dict) else []:
        if not isinstance(row, dict) or row.get("id") != "target_keywords":
            continue
        keywords.extend(normalize_string_list(row.get("value")))
    return unique_texts(keyword for keyword in keywords if keyword and keyword != "未标注关键词")


def allowed_keywords_for_project(project: Any, repository: ProjectRepository | None = None) -> list[str]:
    project_dir = repository.project_dir(project.id) if repository and hasattr(repository, "project_dir") else None
    return project_allowed_keywords(project, project_dir)


def filter_intent_groups_to_allowed_keywords(intent_groups: list[dict[str, Any]], allowed_keywords: list[str]) -> list[dict[str, Any]]:
    allowed_set = set(allowed_keywords)
    filtered: list[dict[str, Any]] = []
    assigned: set[str] = set()
    for group in intent_groups:
        keywords = [
            normalize_keyword_to_allowed(keyword, allowed_keywords)
            for keyword in normalize_string_list(group.get("keywords"))
        ]
        keywords = unique_texts(keyword for keyword in keywords if keyword in allowed_set)
        if not keywords:
            continue
        next_group = dict(group)
        next_group["keywords"] = keywords
        filtered.append(next_group)
        assigned.update(keywords)
    for index, keyword in enumerate([keyword for keyword in allowed_keywords if keyword not in assigned], start=1):
        filtered.append(
            {
                "id": f"keyword-extra-{index}",
                "name": keyword,
                "keywords": [keyword],
                "user_question": "",
                "user_stage": "",
                "recommendation_logic": "",
                "article_types": [],
            }
        )
    return filtered


def compact_matrix_skeleton_for_prompt(skeleton: dict[str, Any]) -> dict[str, Any]:
    return {
        "project": skeleton.get("project", {}),
        "keyword_overview": skeleton.get("keyword_overview", {}),
        "intent_groups": skeleton.get("intent_groups", []),
        "article_type_pool": skeleton.get("article_type_pool", []),
        "answer_logic": skeleton.get("answer_logic", []),
        "unified_recommendation_language": skeleton.get("unified_recommendation_language", []),
        "evidence_gaps": skeleton.get("evidence_gaps", []),
        "publishing_plan": skeleton.get("publishing_plan", []),
        "schedule": skeleton.get("schedule", []),
        "brief_requirements": skeleton.get("brief_requirements", []),
        "final_execution_advice": skeleton.get("final_execution_advice", ""),
    }


def matrix_batch_label(batch: dict[str, Any]) -> str:
    group_names = [str(group.get("name") or group.get("id") or "") for group in batch.get("intent_groups", []) if isinstance(group, dict)]
    label_values = unique_texts(group_names) or normalize_string_list(batch.get("keywords"))
    return "、".join(label_values[:4]) or "未命名批次"


def matrix_batch_intent_for_keyword(batch: dict[str, Any], keyword: str) -> str:
    groups = [group for group in batch.get("intent_groups", []) if isinstance(group, dict)]
    for group in groups:
        if keyword and keyword in normalize_string_list(group.get("keywords")):
            return str(group.get("name") or group.get("id") or "")
    if len(groups) == 1:
        return str(groups[0].get("name") or groups[0].get("id") or "")
    return ""


def merge_matrix_batch_outputs(skeleton: dict[str, Any], partials: list[dict[str, Any]]) -> dict[str, Any]:
    sections = [skeleton, *partials]
    items = merge_matrix_items(item for section in sections for item in section.get("items", []) if isinstance(item, dict))
    items = filter_allowed_keyword_rows(items, normalize_string_list(skeleton.get("allowed_keywords")))
    if not items:
        raise WorkflowError("内容矩阵输出格式不符合固定模板：未找到可识别的文章规划 items。")
    validate_matrix_items(items)

    intent_groups = merge_matrix_records(
        [row for section in sections for row in section.get("intent_groups", []) if isinstance(row, dict)],
        ["id", "name"],
    )
    if skeleton.get("allowed_keywords"):
        intent_groups = filter_intent_groups_to_allowed_keywords(intent_groups, normalize_string_list(skeleton.get("allowed_keywords")))
    if not intent_groups:
        intent_groups = derive_intent_groups_from_matrix_items(items)
    if not intent_groups:
        raise WorkflowError("内容矩阵输出格式不符合固定模板：未找到 intent_groups。")

    keyword_planning = merge_matrix_records(
        [row for section in sections for row in section.get("keyword_planning", []) if isinstance(row, dict)],
        ["keyword", "intent_group"],
    )
    if not keyword_planning:
        keyword_planning = derive_keyword_planning_from_matrix_items(items)

    result = {
        "step": "geo_content_matrix",
        "schema_version": PLANNING_SCHEMA_VERSION,
        "status": "completed",
        "project": merge_matrix_project_blocks(section.get("project", {}) for section in sections),
        "keyword_overview": merge_matrix_keyword_overviews(section.get("keyword_overview", {}) for section in sections),
        "intent_groups": intent_groups,
        "article_type_pool": rebuild_matrix_article_type_pool(sections, items),
        "answer_logic": merge_matrix_records([row for section in sections for row in section.get("answer_logic", []) if isinstance(row, dict)], ["intent_group", "user_question"]),
        "keyword_planning": keyword_planning,
        "items": items,
        "shared_supporting_articles": merge_matrix_records([row for section in sections for row in section.get("shared_supporting_articles", []) if isinstance(row, dict)], ["title", "type"]),
        "unified_recommendation_language": merge_matrix_records([row for section in sections for row in section.get("unified_recommendation_language", []) if isinstance(row, dict)], ["intent_group", "language"]),
        "evidence_gaps": merge_matrix_records([row for section in sections for row in section.get("evidence_gaps", []) if isinstance(row, dict)], ["keyword_or_intent_group", "required_evidence", "missing_evidence"]),
        "publishing_plan": merge_matrix_records([row for section in sections for row in section.get("publishing_plan", []) if isinstance(row, dict)], ["article_type"]),
        "schedule": merge_matrix_records([row for section in sections for row in section.get("schedule", []) if isinstance(row, dict)], ["stage", "period"]),
        "priority_plan": merge_matrix_records([row for section in sections for row in section.get("priority_plan", []) if isinstance(row, dict)], ["title", "keyword", "type"]) or derive_priority_plan_from_matrix_items(items),
        "brief_requirements": merge_matrix_records([row for section in sections for row in section.get("brief_requirements", []) if isinstance(row, dict)], ["field"]),
        "final_execution_advice": first_non_empty_text(section.get("final_execution_advice", "") for section in sections),
        "warnings": unique_texts(warning for section in sections for warning in normalize_string_list(section.get("warnings"))),
    }
    return result


def merge_matrix_items(items: Any) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    by_key: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict) or not str(item.get("type") or "").strip():
            continue
        normalized = dict(item)
        normalized["source_step"] = "matrix"
        normalized["source_id"] = planning_source_id(
            "matrix",
            str(normalized.get("keyword") or ""),
            str(normalized.get("type") or ""),
            str(normalized.get("title") or ""),
            index,
        )
        key = matrix_item_identity(normalized)
        if key in by_key:
            merge_matrix_record_values(by_key[key], normalized)
            continue
        by_key[key] = normalized
        merged.append(normalized)
    return merged


def matrix_item_identity(item: dict[str, Any]) -> str:
    return "|".join(str(item.get(key) or "").strip() for key in ["keyword", "type", "title"])


def rebuild_matrix_article_type_pool(sections: list[dict[str, Any]], items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = merge_matrix_records(
        [row for section in sections for row in section.get("article_type_pool", []) if isinstance(row, dict)],
        ["type"],
    )
    return normalize_matrix_article_type_pool({"article_type_pool": rows}, items)


def merge_matrix_project_blocks(blocks: Any) -> dict[str, Any]:
    result = {
        "target_industry": "",
        "target_category": "",
        "target_brand": "",
        "target_product_or_solution": "",
        "competitors": [],
        "naming_rule": "",
        "recommendation_logic": "",
        "expression_boundaries": [],
    }
    for block in blocks:
        if not isinstance(block, dict):
            continue
        for key in ["target_industry", "target_category", "target_brand", "target_product_or_solution", "naming_rule", "recommendation_logic"]:
            if not result[key] and planning_value_text(block.get(key)):
                result[key] = planning_value_text(block.get(key))
        result["competitors"] = unique_texts([*result["competitors"], *normalize_string_list(block.get("competitors"))])
        result["expression_boundaries"] = unique_texts([*result["expression_boundaries"], *normalize_string_list(block.get("expression_boundaries"))])
    return result


def merge_matrix_keyword_overviews(blocks: Any) -> dict[str, Any]:
    result = {
        "common_goal": "",
        "core_user_intents": [],
        "user_decision_stage": "",
        "target_recommendation_cognition": "",
        "required_article_sections": MATRIX_REQUIRED_ARTICLE_TYPES,
        "optional_article_sections": [],
        "article_type_count_limit": 6,
    }
    for block in blocks:
        if not isinstance(block, dict):
            continue
        for key in ["common_goal", "user_decision_stage", "target_recommendation_cognition"]:
            if not result[key] and planning_value_text(block.get(key)):
                result[key] = planning_value_text(block.get(key))
        result["core_user_intents"] = unique_texts([*result["core_user_intents"], *normalize_string_list(block.get("core_user_intents"))])
    return result


def merge_matrix_records(records: list[dict[str, Any]], key_fields: list[str]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    by_key: dict[str, dict[str, Any]] = {}
    for record in records:
        if not matrix_record_has_value(record):
            continue
        key = matrix_record_identity(record, key_fields)
        if key in by_key:
            merge_matrix_record_values(by_key[key], record)
            continue
        normalized = dict(record)
        by_key[key] = normalized
        result.append(normalized)
    return result


def matrix_record_identity(record: dict[str, Any], key_fields: list[str]) -> str:
    parts = [planning_value_text(record.get(key)) for key in key_fields if planning_value_text(record.get(key))]
    if parts:
        return "|".join(parts)
    return json.dumps(record, ensure_ascii=False, sort_keys=True)


def matrix_record_has_value(record: dict[str, Any]) -> bool:
    return any(planning_value_text(value) for value in record.values())


def merge_matrix_record_values(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key, value in source.items():
        if isinstance(value, list):
            target[key] = unique_texts([*normalize_string_list(target.get(key)), *normalize_string_list(value)])
            continue
        current_text = planning_value_text(target.get(key))
        value_text = planning_value_text(value)
        if not current_text and value_text:
            target[key] = value


def derive_intent_groups_from_matrix_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        group = str(item.get("intent_group") or item.get("keyword") or "未分组")
        grouped.setdefault(group, []).append(item)
    return [
        {
            "id": slugify(group, fallback=f"intent-{index}"),
            "name": group,
            "keywords": unique_texts(item.get("keyword", "") for item in group_items),
            "user_question": "",
            "user_stage": first_non_empty_text(item.get("user_stage", "") for item in group_items),
            "recommendation_logic": first_non_empty_text(item.get("core_recommendation", "") for item in group_items),
            "article_types": unique_texts(item.get("type", "") for item in group_items),
        }
        for index, (group, group_items) in enumerate(grouped.items(), start=1)
    ]


def derive_keyword_planning_from_matrix_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        grouped.setdefault(str(item.get("keyword") or "未标注关键词"), []).append(item)
    return [
        {
            "keyword": keyword,
            "intent_group": first_non_empty_text(item.get("intent_group", "") for item in group_items),
            "user_stage": first_non_empty_text(item.get("user_stage", "") for item in group_items),
            "main_article_types": unique_texts(item.get("type", "") for item in group_items),
            "recommended_titles": unique_texts(item.get("title", "") for item in group_items),
            "evidence_requirements": unique_texts(evidence for item in group_items for evidence in normalize_string_list(item.get("required_evidence"))),
            "priority": min((planning_int(item.get("priority"), 9999) for item in group_items), default=index),
        }
        for index, (keyword, group_items) in enumerate(grouped.items(), start=1)
    ]


def derive_priority_plan_from_matrix_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "priority": planning_int(item.get("priority"), index),
            "title": str(item.get("title") or ""),
            "keyword": str(item.get("keyword") or ""),
            "type": str(item.get("type") or ""),
            "reason": str(item.get("role") or item.get("brief_focus") or ""),
        }
        for index, item in enumerate(items, start=1)
    ]


def first_non_empty_text(values: Any) -> str:
    for value in values:
        text = planning_value_text(value)
        if text:
            return text
    return ""


def first_non_empty_value(row: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        value = row.get(key)
        if planning_value_text(value):
            return value
    return ""


def chunked(values: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [values[index:index + size] for index in range(0, len(values), size)]


def chunked_strings(values: list[str], size: int) -> list[list[str]]:
    return [values[index:index + size] for index in range(0, len(values), size)]


def bounded_int(value: Any, *, fallback: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = fallback
    return max(minimum, min(parsed, maximum))


def matrix_article_type_sort_key(article_type: str) -> tuple[int, str]:
    if article_type in MATRIX_REQUIRED_ARTICLE_TYPES:
        return (MATRIX_REQUIRED_ARTICLE_TYPES.index(article_type), article_type)
    return (len(MATRIX_REQUIRED_ARTICLE_TYPES), article_type)


def matrix_article_type_allowed(article_type: str) -> bool:
    return bool(str(article_type or "").strip())


def normalize_matrix_type_list(values: list[str]) -> list[str]:
    normalized: list[str] = []
    for value in values:
        article_type = normalize_matrix_type(value)
        if article_type and article_type not in normalized:
            normalized.append(article_type)
    return normalized


def filter_blocked_matrix_article_type_texts(values: list[str]) -> list[str]:
    return [value for value in values if not matrix_text_mentions_blocked_article_type(value)]


def matrix_text_mentions_blocked_article_type(value: str) -> bool:
    return any(marker in value for marker in MATRIX_BLOCKED_ARTICLE_TYPE_MARKERS)


def normalize_planning_item(source_step: str, row: dict[str, Any], index: int) -> dict[str, Any]:
    raw_keyword = first_planning_text(
        row,
        ["keyword", "target_keyword", "main_keyword_or_cluster", "main_keyword", "keyword_or_cluster", "目标关键词", "主攻关键词", "关键词", "主攻关键词_意图簇"],
    )
    keyword, inferred_group = split_keyword_and_group(raw_keyword)
    article_type = first_planning_text(row, ["type", "article_type", "main_article_type", "文章类型", "类型"])
    if source_step == "breakthrough":
        article_type = normalize_breakthrough_type(article_type, row, index)
    else:
        article_type = normalize_matrix_type(article_type)
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
        "recommendation_strength": first_planning_text(row, ["recommendation_strength", "推荐强度"]),
        "supporting_articles": planning_string_list_from(row, ["supporting_articles", "auxiliary_articles", "辅助文章", "共同支撑文章"]),
        "evidence_chain": first_planning_text(row, ["evidence_chain", "content_evidence_chain", "证据链", "内容证据链"]),
        "evidence_gaps": planning_string_list_from(row, ["evidence_gaps", "missing_evidence", "证据缺口"]),
        "competitor_boundary": first_planning_text(row, ["competitor_boundary", "competitor_comparison_boundary", "竞品边界", "竞品/对比对象边界"]),
        "channels": planning_string_list_from(row, ["channels", "recommended_channels", "channel", "recommendation_channel", "发布渠道", "推荐渠道"]),
        "brief_focus": first_planning_text(row, ["brief_focus", "brief_requirements", "后续Brief要点", "后续 Brief 要点", "Brief要点"]),
        "outline_requirements": first_planning_text(row, ["outline_requirements", "article_outline", "文章结构大纲", "大纲要求"]),
        "forbidden_expressions": planning_string_list_from(row, ["forbidden_expressions", "prohibited_expressions", "禁止出现的表达", "禁用表达"]),
        "suggested_word_count": first_planning_text(row, ["suggested_word_count", "word_count", "建议字数"]),
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


def normalize_matrix_type(value: str) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        return normalized
    lowered = normalized.lower()
    if lowered in MATRIX_TYPE_ALIASES:
        return MATRIX_TYPE_ALIASES[lowered]
    if normalized in MATRIX_TYPE_ALIASES:
        return MATRIX_TYPE_ALIASES[normalized]
    for article_type in MATRIX_REQUIRED_ARTICLE_TYPES + MATRIX_OPTIONAL_ARTICLE_TYPES:
        article_type_lowered = article_type.lower()
        if normalized == article_type or article_type in normalized or normalized in article_type:
            return article_type
        if article_type_lowered in lowered or lowered in article_type_lowered:
            return article_type
    return normalized


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


def first_planning_raw_text(source: dict[str, Any], keys: list[str], fallback: str = "") -> str:
    for key in keys:
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
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


def planning_section_list_from(source: dict[str, Any], keys: list[str]) -> list[Any]:
    for key in keys:
        value = source.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            return [value]
        result = normalize_string_list(value)
        if result:
            return result
    return []


def planning_section_rows_by_keys(source: dict[str, Any], keys: list[str]) -> list[dict[str, Any]]:
    rows = planning_section_list_from(source, keys)
    result: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, dict):
            result.append(row)
        else:
            text = planning_value_text(row)
            if text:
                result.append({"value": text, "requirement": text})
    return result


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
    if step == "demand_matrix":
        markdown_report = result.get("markdown_report")
        if isinstance(markdown_report, str) and markdown_report.strip():
            return markdown_report.strip() + "\n"
    if markdown := result.get("markdown"):
        return str(markdown).strip() + "\n"
    return f"# {title}\n\n```json\n{json.dumps(result, ensure_ascii=False, indent=2)}\n```\n"


def item_to_markdown(step: WorkflowStep, item: dict[str, Any]) -> str:
    markdown = item.get("markdown")
    if isinstance(markdown, str) and markdown.strip():
        return markdown.strip() + "\n"
    title = str(item.get("title") or STEP_LABELS.get(step, step))
    return f"# {title}\n\n```json\n{json.dumps(item, ensure_ascii=False, indent=2)}\n```\n"


def markdown_output_requirements(step: WorkflowStep) -> str:
    if step == "brief":
        return (
            "# 输出要求\n"
            "只输出完整 Brief Markdown，不要输出 JSON，不要输出 Markdown 代码围栏，不要解释生成过程。\n"
            "不要输出 items、source_id、status 等结构化元数据；系统会自动保存这些字段。"
        )
    if step == "article":
        return (
            "# 输出要求\n"
            "只输出完整可发布正文 Markdown，不要输出 JSON，不要输出 Markdown 代码围栏，不要解释生成过程。\n"
            "不要输出 items、brief_id、source_id、status 等结构化元数据；系统会自动保存这些字段。"
        )
    return "# 输出要求\n请输出 Markdown。"


def wrap_markdown_generation(step: WorkflowStep, payload: dict[str, Any], markdown: str) -> dict[str, Any]:
    content = strip_markdown_fence(markdown).strip()
    if not content:
        raise WorkflowError("模型返回内容为空，请重试。")
    if step == "brief":
        selected = selected_list(payload, "selected_sources", fallback="selected_articles")
        if not selected:
            raise WorkflowError("请选择要生成 Brief 的文章规划。")
        source = selected[0]
        item = {
            **brief_placeholder(source, "completed"),
            "markdown": content,
            "error": None,
        }
        return {"items": [item]}
    if step == "article":
        selected = selected_list(payload, "selected_briefs")
        if not selected:
            raise WorkflowError("请选择要生成正文的 Brief。")
        brief = selected[0]
        item = {
            **article_placeholder(brief, "completed"),
            "markdown": content,
            "error": None,
        }
        return {"items": [item]}
    return {"markdown": content}


def strip_markdown_fence(text: str) -> str:
    value = text.strip()
    if not value.startswith("```"):
        return value
    lines = value.splitlines()
    if len(lines) >= 2 and lines[0].strip().startswith("```") and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return value


def output_slug(value: str) -> str:
    return slugify(value, fallback="output")


def build_job_message(step: WorkflowStep, total_count: int, skipped_count: int) -> str:
    if step == "intake":
        return "准备生成项目信息抽取表"
    if step == "matrix":
        return "准备生成内容矩阵"
    if step == "demand_matrix":
        return "准备生成需求驱动内容矩阵"
    if step == "breakthrough":
        return "准备生成逐词击破规划"
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


def normalize_parse_mode(mode: str | None) -> ParseMode:
    if mode == "text_only":
        return "text_only"
    if mode == "full_ocr":
        return "full_ocr"
    return "smart"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_cache_paths(
    repository: ProjectRepository,
    material: Material,
    source: Path,
    mode: ParseMode,
    settings: Settings,
) -> tuple[Path, Path]:
    sha256 = material.sha256 or file_sha256(source)
    key_payload = {
        "parser_version": MATERIAL_PARSER_VERSION,
        "suffix": source.suffix.lower(),
        "mode": mode,
        "enable_vision_ocr": settings.enable_vision_ocr,
        "openai_vision_model": settings.openai_vision_model,
        "openai_model": settings.openai_model,
        "enable_local_ocr": settings.enable_local_ocr,
        "local_ocr_engine": settings.local_ocr_engine,
        "local_ocr_max_pages": settings.local_ocr_max_pages,
        "local_ocr_min_confidence": settings.local_ocr_min_confidence,
        "image_ocr_max_edge": settings.image_ocr_max_edge,
        "image_ocr_jpeg_quality": settings.image_ocr_jpeg_quality,
    }
    cache_key = hashlib.sha256(json.dumps(key_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:24]
    root = repository.parse_cache_dir() / sha256 / MATERIAL_PARSER_VERSION
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{cache_key}.md", root / f"{cache_key}.json"


def read_parse_cache_meta(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def write_parse_cache(
    cache_path: Path,
    meta_path: Path,
    text: str,
    material: Material,
    source: Path,
    mode: ParseMode,
    settings: Settings,
    ocr_pages: int,
) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(text, encoding="utf-8")
    meta = {
        "filename": material.filename,
        "suffix": source.suffix.lower(),
        "sha256": material.sha256,
        "parser_version": MATERIAL_PARSER_VERSION,
        "parse_mode": mode,
        "parsed_chars": len(text),
        "ocr_pages": ocr_pages,
        "enable_vision_ocr": settings.enable_vision_ocr,
        "vision_model": settings.openai_vision_model or settings.openai_model,
        "ocr_engine": settings.local_ocr_engine,
        "created_at": utc_now(),
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def build_running_step_message(step: WorkflowStep) -> str:
    if step == "intake":
        return "正在读取解析资料并调用 Agent 生成抽取表"
    if step == "matrix":
        return "正在调用 Agent 生成内容矩阵规划"
    if step == "demand_matrix":
        return "正在调用 Agent 生成需求驱动内容矩阵规划"
    if step == "breakthrough":
        return "正在调用 Agent 生成逐词击破规划"
    return f"正在运行：{STEP_LABELS.get(step, step)}"


def batch_generation_concurrency(settings: Settings, total_count: int) -> int:
    raw_value = getattr(settings, "batch_generation_concurrency", 3)
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        value = 3
    bounded = max(1, min(value, 8))
    return min(bounded, max(total_count, 1))


def build_parallel_running_message(step: WorkflowStep, concurrency: int) -> str:
    label = "Brief" if step == "brief" else "正文"
    return f"{label}并行生成中，最多 {concurrency} 篇同时运行"


def build_completed_step_message(step: WorkflowStep, result: dict[str, Any]) -> str:
    if step == "intake":
        count = intake_row_count(result)
        return f"抽取表生成完成，已提取 {count} 项"
    if step == "demand_matrix":
        return f"需求驱动内容矩阵生成完成，已生成 {len(output_items(result))} 篇规划"
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


def friendly_job_error(exc: Exception) -> str:
    if is_llm_timeout_error(exc):
        return "中转站超时：模型 120 秒内未返回。系统已自动重试一次，仍未完成。请稍后重试或减少资料/关键词规模。"
    text = str(exc).strip()
    lowered = text.lower()
    if "expecting value: line 1 column 1" in lowered:
        return "中转站返回空响应或非标准响应：模型没有返回可用内容，请稍后重试。"
    if "user_balance_insufficient" in lowered or "余额不足" in text or "insufficient" in lowered and "balance" in lowered:
        return "中转站余额不足：请充值后重试，或切换到可用的模型/API Key。"
    if "cloudflare" in lowered or "origin web server" in lowered or "proxy read timeout" in lowered:
        return "中转站请求失败：上游网关没有返回完整结果，请稍后重试。"
    return text or "任务失败，可重试。"


def is_retriable_llm_generation_error(exc: Exception) -> bool:
    return is_llm_timeout_error(exc) or is_llm_empty_or_nonstandard_response_error(exc)


def is_llm_empty_or_nonstandard_response_error(exc: Exception) -> bool:
    text = str(exc).strip()
    lowered = text.lower()
    markers = [
        "expecting value: line 1 column 1",
        "empty response",
        "empty reply",
        "no response body",
        "non-standard response",
        "non standard response",
        "invalid json",
    ]
    return any(marker in lowered for marker in markers)


def is_llm_timeout_error(exc: Exception) -> bool:
    text = str(exc).lower()
    timeout_markers = [
        "error code: 524",
        "status code: 524",
        '"code":524',
        " 524",
        "origin_response_timeout",
        "proxy read timeout",
        "a timeout occurred",
        "origin web server did not return a complete response",
    ]
    return any(marker in text for marker in timeout_markers)


def llm_retry_after_seconds(exc: Exception) -> float:
    text = str(exc)
    patterns = [
        r"retry_after['\"]?\s*[:=]\s*['\"]?(\d+(?:\.\d+)?)",
        r"Retry-After['\"]?\s*[:=]\s*['\"]?(\d+(?:\.\d+)?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                return 0
    return 0


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


def build_job_cancelled_message(
    step: WorkflowStep,
    total_count: int,
    completed_count: int,
    failed_count: int,
    skipped_count: int,
) -> str:
    if step == "materials":
        parts = [f"资料解析已停止：成功 {completed_count}/{total_count} 个"]
        if skipped_count:
            parts.append(f"跳过 {skipped_count} 个已解析")
        if failed_count:
            parts.append(f"失败 {failed_count} 个")
        parts.append("可重新点击解析资料继续")
        return "，".join(parts)
    if step in {"brief", "article"}:
        label = "Brief" if step == "brief" else "正文"
        parts = [f"{label}生成已停止：成功 {completed_count}/{total_count} 篇"]
        if skipped_count:
            parts.append(f"跳过 {skipped_count} 篇已有内容")
        if failed_count:
            parts.append(f"失败 {failed_count} 篇")
        parts.append("未完成项可重新选择生成")
        return "，".join(parts)
    return f"{STEP_LABELS.get(step, step)}已停止，结果未保存，可重新运行。"


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


def sanitized_generation_payload(step: WorkflowStep, payload: dict[str, Any]) -> dict[str, Any]:
    if step not in {"brief", "article"}:
        return payload
    blocked_keys = {"previous_article_markdown", "previous_brief_markdown"}
    sanitized: dict[str, Any] = {}
    for key, value in payload.items():
        if key in blocked_keys:
            continue
        if isinstance(value, list):
            sanitized[key] = [
                {nested_key: nested_value for nested_key, nested_value in item.items() if nested_key not in blocked_keys}
                if isinstance(item, dict)
                else item
                for item in value
            ]
        else:
            sanitized[key] = value
    return sanitized


def regeneration_guidance_blocks(step: WorkflowStep, payload: dict[str, Any]) -> list[str]:
    if step != "article":
        return []
    selected = selected_list(payload, "selected_briefs")
    review_notes = first_non_empty_text(first_text({}, brief, "review_notes", "reviewNotes", "修改意见") for brief in selected)
    previous_markdown = first_non_empty_text(
        str(brief.get("previous_article_markdown") or "")
        for brief in selected
        if isinstance(brief, dict)
    )
    blocks: list[str] = []
    if review_notes:
        blocks.append(
            "# 本次修改意见（强约束）\n"
            f"{review_notes}\n\n"
            "本次必须根据以上修改意见重写正文。不得忽略、弱化或只做表面调整；标题、开头、一级标题组织、段落顺序、推荐锚点和结尾必须围绕修改意见重新安排。"
        )
    if previous_markdown:
        blocks.append(
            "# 旧正文避重复参考\n"
            "下面旧正文只用于识别并避开重复结构和重复表达，不得照抄、复述或沿用其段落组织。"
            "必须保留可核验事实，但要重写开头、小标题、段落顺序、论证路径和推荐表达。\n\n"
            + previous_markdown[:12000]
        )
    return blocks


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


def mark_running_items_cancelled(existing_output: dict[str, Any]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for item in output_items(existing_output):
        status = str(item.get("status") or "").lower()
        if status in {"running", "queued", "pending"}:
            items.append({**item, "status": "failed", "error": "任务已停止，未生成。"})
        else:
            items.append(item)
    return preserve_output_metadata(existing_output, items, status="cancelled")


def drop_running_items_after_cancel(existing_output: dict[str, Any]) -> dict[str, Any]:
    items = [
        item
        for item in output_items(existing_output)
        if str(item.get("status") or "").lower() not in {"running", "queued", "pending"}
    ]
    return preserve_output_metadata(existing_output, items, status="cancelled")


def attach_raw_generation_to_failed_item(
    existing_output: dict[str, Any],
    selected: dict[str, Any],
    generated: dict[str, Any],
    step: WorkflowStep,
) -> dict[str, Any]:
    items = output_items(existing_output)
    selected_id = source_id_for(selected) if step == "brief" else brief_id_for(selected)
    match_keys = ("source_id", "id") if step == "brief" else ("brief_id", "id")
    raw_generation = compact_raw_generation(generated)
    next_items: list[dict[str, Any]] = []
    for item in items:
        item_id = ""
        for key in match_keys:
            if item.get(key):
                item_id = str(item.get(key))
                break
        if item_id == selected_id:
            next_items.append({**item, "raw_generation": raw_generation})
        else:
            next_items.append(item)
    return preserve_output_metadata(existing_output, next_items, status=str(existing_output.get("status") or "running"))


def compact_raw_generation(value: Any, *, max_text_length: int = 6000) -> Any:
    if isinstance(value, str):
        return value[:max_text_length]
    if isinstance(value, list):
        return [compact_raw_generation(item, max_text_length=max_text_length) for item in value[:5]]
    if isinstance(value, dict):
        compacted: dict[str, Any] = {}
        for key, item in value.items():
            compacted[str(key)] = compact_raw_generation(item, max_text_length=max_text_length)
        return compacted
    return value


def has_generated_output_items(output: dict[str, Any]) -> bool:
    for item in output_items(output):
        status = str(item.get("status") or "").lower()
        if status not in {"failed", "running", "queued", "pending"} and (item.get("markdown") or status in {"completed", "confirmed", "modified"}):
            return True
    return False


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
        "review_notes": first_text({}, source, "review_notes", "reviewNotes", "修改意见"),
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
        "review_notes": first_text({}, brief, "review_notes", "reviewNotes", "修改意见"),
        "article_audit_status": "",
        "article_audited_at": "",
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


def merge_keyword_lists(*groups: list[str]) -> list[str]:
    return normalize_keyword_list([keyword for group in groups for keyword in group])


def confirmed_keywords_from_payload(payload: dict[str, Any]) -> list[str]:
    return normalize_keyword_list(payload.get("confirmed_keywords"))


def confirmed_breakthrough_keywords(matrix_output: dict[str, Any]) -> list[str]:
    selection = matrix_output.get("breakthrough_keyword_selection")
    if not isinstance(selection, dict):
        return []
    return normalize_keyword_list(selection.get("keywords"))


def breakthrough_required_types(payload: dict[str, Any]) -> dict[str, list[str]]:
    value = payload.get("missing_breakthrough_types")
    if not isinstance(value, dict):
        return {}
    required: dict[str, list[str]] = {}
    for keyword, article_types in value.items():
        if not isinstance(keyword, str) or not keyword.strip() or not isinstance(article_types, list):
            continue
        normalized_types: list[str] = []
        for index, article_type in enumerate(article_types):
            if not isinstance(article_type, str):
                continue
            normalized = normalize_breakthrough_type(article_type, {}, index)
            if normalized in BREAKTHROUGH_ARTICLE_TYPES and normalized not in normalized_types:
                normalized_types.append(normalized)
        if normalized_types:
            required[" ".join(keyword.split())] = normalized_types
    return required


def missing_breakthrough_types(existing_output: dict[str, Any], keywords: list[str]) -> dict[str, list[str]]:
    present_by_keyword: dict[str, set[str]] = {keyword: set() for keyword in keywords}
    for item in output_items(existing_output):
        keyword = str(item.get("keyword") or "").strip()
        if keyword not in present_by_keyword:
            continue
        article_type = normalize_breakthrough_type(str(item.get("type") or ""), item, 0)
        if article_type in BREAKTHROUGH_ARTICLE_TYPES:
            present_by_keyword[keyword].add(article_type)
    missing: dict[str, list[str]] = {}
    for keyword in keywords:
        types = [article_type for article_type in BREAKTHROUGH_ARTICLE_TYPES if article_type not in present_by_keyword.get(keyword, set())]
        if types:
            missing[keyword] = types
    return missing


def merge_breakthrough_output(existing_output: dict[str, Any], generated: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    merged_items: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in [*output_items(existing_output), *output_items(generated)]:
        keyword = str(item.get("keyword") or "").strip()
        article_type = normalize_breakthrough_type(str(item.get("type") or ""), item, len(merged_items))
        key = (keyword, article_type)
        if not keyword or not article_type or key in seen:
            continue
        next_item = dict(item)
        next_item["type"] = article_type
        merged_items.append(next_item)
        seen.add(key)
    confirmed_keywords = merge_keyword_lists(
        normalize_keyword_list(existing_output.get("confirmed_keywords")),
        normalize_keyword_list(generated.get("confirmed_keywords")),
        confirmed_keywords_from_payload(payload),
    )
    if not confirmed_keywords:
        confirmed_keywords = sorted({str(item.get("keyword") or "") for item in merged_items if item.get("keyword")})
    warnings = unique_texts([
        *planning_string_list_from(existing_output, ["warnings"]),
        *planning_string_list_from(generated, ["warnings"]),
    ])
    project_block = generated.get("project") if isinstance(generated.get("project"), dict) and generated.get("project") else existing_output.get("project", {})
    return {
        "step": "geo_keyword_breakthrough",
        "schema_version": PLANNING_SCHEMA_VERSION,
        "status": "completed",
        "project": project_block if isinstance(project_block, dict) else {},
        "confirmed_keywords": confirmed_keywords,
        "keyword_summaries": [
            {"keyword": keyword, "article_count": len([item for item in merged_items if item.get("keyword") == keyword])}
            for keyword in confirmed_keywords
        ],
        "items": merged_items,
        "warnings": warnings,
    }


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
    existing_ids = {
        str(item.get("source_id"))
        for item in output_items(existing_output)
        if item.get("source_id") and brief_item_is_generated(item)
    }
    missing = [source for source in sources if str(source.get("source_id")) not in existing_ids]
    if not missing:
        raise WorkflowError("选中项均已有 Brief，无需重复生成。")
    return missing


def brief_item_is_generated(item: dict[str, Any]) -> bool:
    status = str(item.get("status") or "").lower()
    if status in {"failed", "running", "queued", "pending"}:
        return False
    return isinstance(item.get("markdown"), str) and bool(str(item.get("markdown") or "").strip())


def select_missing_briefs(existing_output: dict[str, Any], payload: dict[str, Any]) -> list[dict[str, Any]]:
    briefs = selected_list(payload, "selected_briefs")
    if not briefs:
        raise WorkflowError("请先选择要生成正文的 Brief。")
    if any(not brief_item_is_generated(brief) for brief in briefs):
        raise WorkflowError("选中的 Brief 尚未生成完成，不能生成正文。")
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
    if step == "matrix":
        mode = str(payload.get(MATRIX_GENERATION_MODE_KEY) or "")
        if mode == MATRIX_GENERATION_MODE_BATCH:
            batch = payload.get("matrix_batch") if isinstance(payload.get("matrix_batch"), dict) else {}
            skeleton = payload.get("matrix_skeleton") if isinstance(payload.get("matrix_skeleton"), dict) else {}
            return [
                "# 本批生成范围\n" + json.dumps(batch, ensure_ascii=False, indent=2)[:20000],
                "# 已生成内容矩阵骨架\n" + json.dumps(skeleton, ensure_ascii=False, indent=2)[:30000],
                "# 分批生成说明\n本批只生成上方范围内的首轮文章规划和相关证据/排期/Brief 衔接内容。不要重复输出其他批次的关键词或意图簇。",
            ]
    if step == "breakthrough":
        keywords = confirmed_keywords_from_payload(payload)
        missing_types = breakthrough_required_types(payload)
        if missing_types:
            return [
                "# 已确认进入逐词击破的关键词\n" + json.dumps(keywords, ensure_ascii=False, indent=2),
                "# 本次缺失待生成类型\n" + json.dumps(missing_types, ensure_ascii=False, indent=2),
                "# 生成范围\n本次只针对 missing_breakthrough_types 中列出的 keyword + type 生成逐词击破文章规划。已有规划不要重复输出。输出 JSON 对象，items 数组中每个 item 必须保留 source_step、keyword、type、title。",
            ]
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
                "# 生成范围\n本次只针对上方 selected_sources 中的单篇规划生成 Brief。未选中的文章不要输出。只输出 Brief Markdown 正文，不要输出 JSON 或结构化元数据。",
                "# 自定义文章规则\nsource_step 为 custom 的项目由用户手动创建，title 是用户指定的目标选题，必须作为 Brief 的主标题和核心方向，不要替换为其他题目；keyword、type 可能是后台根据标题和项目上下文自动推断的辅助信息，brief_focus、channel/channels 如存在则作为补充约束使用。",
            ]
    if step == "article":
        selected = payload.get("selected_briefs")
        if isinstance(selected, list) and selected:
            return [
                "# 选中待生成正文的 Brief\n" + json.dumps(selected, ensure_ascii=False, indent=2)[:50000],
                "# 生成范围\n本次只针对上方 selected_briefs 中的单篇 Brief 生成正文。未选中的 Brief 不要输出。只输出正文 Markdown，不要输出 JSON 或结构化元数据。",
            ]
    return []


def material_summary_for_step(project: Any, step: WorkflowStep, payload: dict[str, Any], settings: Settings) -> str:
    summary = project.steps["materials"].output.get("summary", "")
    if step == "matrix":
        return MATRIX_LIGHTWEIGHT_MATERIAL_NOTICE
    if step == "demand_matrix":
        return demand_matrix_material_summary(project, summary)
    if step in {"brief", "article"}:
        return writing_material_summary(project, step, payload, summary, settings)
    if payload.get(MATRIX_GENERATION_MODE_KEY) != MATRIX_GENERATION_MODE_BATCH:
        return summary[:MATERIAL_CONTEXT_LIMIT]
    limit = bounded_int(
        getattr(settings, "matrix_batch_material_context_limit", 12000),
        fallback=12000,
        minimum=2000,
        maximum=MATERIAL_CONTEXT_LIMIT,
    )
    batch = payload.get("matrix_batch") if isinstance(payload.get("matrix_batch"), dict) else {}
    keywords = normalize_string_list(batch.get("keywords"))
    for group in batch.get("intent_groups", []) if isinstance(batch.get("intent_groups"), list) else []:
        if isinstance(group, dict):
            keywords.extend(normalize_string_list(group.get("name")))
            keywords.extend(normalize_string_list(group.get("keywords")))
    keywords = unique_texts(keywords)
    if not summary or not keywords:
        return summary[:limit]

    chunks = split_material_summary_chunks(summary)
    matched: list[str] = []
    for chunk in chunks:
        if any(keyword and keyword in chunk for keyword in keywords):
            matched.append(chunk)
    prefix = summary[: min(3000, limit)]
    parts = [*matched, prefix]
    result = "\n\n".join(unique_texts(parts))
    if not result.strip():
        result = summary
    return result[:limit]


def demand_matrix_material_summary(project: Any, summary: str) -> str:
    report_names = [
        material.filename
        for material in getattr(project, "materials", [])
        if material.filename.startswith(DEMAND_REPORT_SLOT_PREFIX) and material.status == "parsed"
    ]
    chunks = split_material_summary_chunks(summary)
    report_chunks = [
        chunk
        for chunk in chunks
        if any(filename and filename in chunk for filename in report_names)
    ]
    prefix = summary[: min(6000, MATERIAL_CONTEXT_LIMIT)]
    parts = [
        "# 用户需求挖掘报告\n" + "\n\n".join(report_chunks) if report_chunks else "",
        "# 项目资料摘要\n" + prefix if prefix else "",
    ]
    result = "\n\n".join(part for part in parts if part.strip())
    return (result or summary)[:MATERIAL_CONTEXT_LIMIT]


def split_material_summary_chunks(summary: str) -> list[str]:
    chunks = re.split(r"\n(?=#{1,6}\s)|\n-{3,}\n|\n\n+", summary)
    return [chunk.strip() for chunk in chunks if chunk.strip()]


def writing_material_summary(project: Any, step: WorkflowStep, payload: dict[str, Any], summary: str, settings: Settings) -> str:
    if not summary:
        return ""
    limit = BRIEF_MATERIAL_CONTEXT_LIMIT if step == "brief" else ARTICLE_MATERIAL_CONTEXT_LIMIT
    query_terms = writing_context_terms(project, step, payload)
    module_context = writing_material_module_context(project, step, payload, query_terms, limit, settings)
    if module_context.strip():
        return module_context[:limit]
    return legacy_writing_material_summary(project, step, payload, summary, limit)


def legacy_writing_material_summary(project: Any, step: WorkflowStep, payload: dict[str, Any], summary: str, limit: int) -> str:
    query_terms = writing_context_terms(project, step, payload)
    chunks = split_material_summary_chunks(summary)
    scored = score_material_chunks(chunks, query_terms)
    relevant = [chunk for _, chunk in scored[:12]]
    evidence_terms = evidence_query_terms(query_terms)
    evidence_chunks = [
        chunk
        for _, chunk in score_material_chunks(chunks, evidence_terms)[:8]
        if chunk not in relevant
    ]
    prefix = summary[: min(3000, limit)]
    parts = [
        "# 项目基础背景片段\n" + prefix if prefix.strip() else "",
        "# 当前选题相关资料片段\n" + "\n\n".join(relevant) if relevant else "",
        "# 证据/参数/认证/案例相关片段\n" + "\n\n".join(evidence_chunks) if evidence_chunks else "",
    ]
    if not relevant and not evidence_chunks:
        parts.append("# 资料缺口提示\n未在项目资料中匹配到当前选题的明确资料片段，生成时只能基于项目基础背景、已确认项目信息和选中规划保守表达，不得虚构证据。")
    result = "\n\n".join(part for part in parts if part.strip())
    return result[:limit] if result.strip() else summary[:limit]


def writing_material_module_context(
    project: Any,
    step: WorkflowStep,
    payload: dict[str, Any],
    query_terms: list[str],
    limit: int,
    settings: Settings,
) -> str:
    modules = parsed_material_modules(project, settings)
    if not modules:
        return ""
    article_type = writing_article_type(step, payload)
    priorities = writing_material_priorities(article_type)
    selected_parts: list[str] = []
    selected_texts: set[str] = set()

    def add_section(title: str, chunks: list[str]) -> None:
        nonlocal selected_parts
        unique_chunks = []
        for chunk in chunks:
            text = chunk.strip()
            if not text or text in selected_texts:
                continue
            unique_chunks.append(text)
            selected_texts.add(text)
        if unique_chunks:
            selected_parts.append(title + "\n" + "\n\n".join(unique_chunks))

    for module in ALWAYS_INCLUDE_MATERIAL_MODULES:
        chunks = ranked_material_module_chunks(modules.get(module, []), query_terms, max_chunks=3)
        add_section(material_module_title(module, "固定表达边界资料"), chunks)

    for module in priorities:
        max_chunks = 8 if module in {"competitor", "evidence", "brand", "demand_report"} else 4
        chunks = ranked_material_module_chunks(modules.get(module, []), query_terms, max_chunks=max_chunks)
        add_section(material_module_title(module, "文章类型优先资料"), chunks)

    remaining_modules = [
        module
        for module in MATERIAL_MODULE_PREFIXES
        if module not in {*ALWAYS_INCLUDE_MATERIAL_MODULES, *priorities, "brief"}
    ]
    keyword_chunks: list[str] = []
    for module in remaining_modules:
        keyword_chunks.extend(ranked_material_module_chunks(modules.get(module, []), query_terms, max_chunks=2, require_score=True))
    add_section("# 关键词命中补充资料", keyword_chunks[:8])

    if is_comparison_article_type(article_type):
        add_section("# 横评写作硬性要求", [comparison_article_material_requirements(bool(modules.get("competitor")))])

    result = "\n\n".join(selected_parts)
    return result[:limit] if result.strip() else ""


def parsed_material_modules(project: Any, settings: Settings) -> dict[str, list[dict[str, str]]]:
    modules: dict[str, list[dict[str, str]]] = {module: [] for module in MATERIAL_MODULE_PREFIXES}
    project_dir = project_directory(project, settings)
    if not project_dir:
        return modules
    for material in getattr(project, "materials", []) or []:
        if getattr(material, "status", "") != "parsed":
            continue
        parsed_path_value = getattr(material, "parsed_path", "")
        if not parsed_path_value:
            continue
        parsed_path = Path(str(parsed_path_value))
        if not parsed_path.is_absolute():
            parsed_path = project_dir / parsed_path
        if not parsed_path.exists() or not parsed_path.is_file():
            continue
        try:
            text = parsed_path.read_text(encoding="utf-8")
        except OSError:
            continue
        if not text.strip():
            continue
        filename = str(getattr(material, "filename", "") or parsed_path.name)
        module = material_module_for_filename(filename)
        modules.setdefault(module, []).append({"filename": filename, "text": text})
    return modules


def project_directory(project: Any, settings: Settings) -> Path | None:
    value = getattr(project, "path", None) or getattr(project, "project_path", None) or getattr(project, "dir", None)
    if value:
        return Path(str(value))
    project_id = getattr(project, "id", "")
    if project_id:
        return settings.data_root / "projects" / str(project_id)
    for material in getattr(project, "materials", []) or []:
        parsed_path_value = getattr(material, "parsed_path", "")
        if not parsed_path_value:
            continue
        parsed_path = Path(str(parsed_path_value))
        if parsed_path.is_absolute():
            parts = parsed_path.parts
            if "parsed" in parts:
                parsed_index = parts.index("parsed")
                return Path(*parts[:parsed_index])
    return None


def material_module_for_filename(filename: str) -> str:
    normalized = filename.lower().strip()
    for prefix in MATERIAL_MODULE_PREFIXES:
        if normalized.startswith(f"{prefix}__"):
            return prefix
    return "other"


def ranked_material_module_chunks(
    records: list[dict[str, str]],
    query_terms: list[str],
    *,
    max_chunks: int,
    require_score: bool = False,
) -> list[str]:
    candidates: list[tuple[int, int, str]] = []
    for record in records:
        filename = record.get("filename", "资料")
        chunks = split_material_summary_chunks(record.get("text", ""))
        if not chunks:
            chunks = [record.get("text", "")]
        for index, chunk in enumerate(chunks):
            text = chunk.strip()
            if not text:
                continue
            score = material_chunk_score(text, query_terms)
            if require_score and score <= 0:
                continue
            candidates.append((score, -index, f"## {filename}\n\n{text}"))
    candidates.sort(key=lambda item: (item[0], item[1], len(item[2])), reverse=True)
    return [text for _, _, text in candidates[:max_chunks]]


def material_chunk_score(chunk: str, query_terms: list[str]) -> int:
    if not query_terms:
        return 0
    score = 0
    for term in query_terms:
        if term and term in chunk:
            score += 3 if len(term) >= 4 else 1
    return score


def writing_article_type(step: WorkflowStep, payload: dict[str, Any]) -> str:
    selected = selected_list(payload, "selected_sources", fallback="selected_articles") if step == "brief" else selected_list(payload, "selected_briefs")
    for item in selected:
        article_type = first_text({}, item, "type", "article_type", "文章类型")
        if article_type:
            return normalize_matrix_type(article_type)
        title = first_text({}, item, "title", "suggested_title", "文章标题")
        inferred = infer_article_type_from_text(title)
        if inferred:
            return inferred
    return ""


def infer_article_type_from_text(text: str) -> str:
    value = str(text or "")
    if any(marker in value for marker in ["横评", "对比", "比较", "区别", "差异", "哪个好"]):
        return "横评对比文"
    if any(marker in value for marker in ["证据", "参数", "认证", "报告", "实测", "专利"]):
        return "产品证据文"
    if any(marker in value for marker in ["榜单", "推荐", "排名", "清单"]):
        return "榜单推荐文"
    if any(marker in value for marker in ["场景", "选购", "怎么选", "指南", "攻略"]):
        return "场景选购文"
    if any(marker in value for marker in ["FAQ", "faq", "问答", "问题", "答疑"]):
        return "FAQ问答文"
    if any(marker in value for marker in ["标准", "全面解析", "系统解析"]):
        return "支柱标准文"
    return ""


def writing_material_priorities(article_type: str) -> list[str]:
    normalized = normalize_matrix_type(article_type)
    return ARTICLE_TYPE_MATERIAL_PRIORITIES.get(normalized, DEFAULT_WRITING_MATERIAL_PRIORITIES)


def is_comparison_article_type(article_type: str) -> bool:
    return normalize_matrix_type(article_type) == "横评对比文" or infer_article_type_from_text(article_type) == "横评对比文"


def material_module_title(module: str, fallback: str) -> str:
    labels = {
        "competitor": "# 竞品对比资料",
        "evidence": "# 核心证据资料",
        "brand": "# 品牌/产品资料",
        "keywords": "# 关键词资料",
        "demand_report": "# 用户需求资料",
        "expression": "# 表达规范资料",
        "forbidden": "# 禁用表达资料",
        "other": "# 补充资料",
    }
    return labels.get(module, f"# {fallback}")


def comparison_article_material_requirements(has_competitor_material: bool) -> str:
    if has_competitor_material:
        return (
            "本篇为横评对比文，已检索到竞品资料。Brief 必须明确输出：对比对象、对比维度、每个维度对应的资料来源、目标对象差异和资料缺口。"
            "正文必须包含横评对比表，并在表格后逐维度解释，不能只写泛泛推荐或“各有优势”。"
        )
    return (
        "本篇为横评对比文，但未检索到 competitor__ 竞品资料。Brief 必须标注竞品资料缺口；正文不得虚构竞品参数、价格、排名或测试结论。"
    )


def writing_context_terms(project: Any, step: WorkflowStep, payload: dict[str, Any]) -> list[str]:
    terms: list[str] = []
    selected = selected_list(payload, "selected_sources", fallback="selected_articles") if step == "brief" else selected_list(payload, "selected_briefs")
    for item in selected:
        collect_terms_from_value(item, terms)
    if step == "article":
        for brief in selected:
            markdown = brief.get("markdown")
            if isinstance(markdown, str):
                collect_terms_from_text(markdown, terms)
    intake = project.steps["intake"].output if project.steps.get("intake") else {}
    collect_intake_terms(intake, terms)
    return unique_query_terms(terms)


def collect_intake_terms(intake: dict[str, Any], terms: list[str]) -> None:
    rows = intake.get("project_intake_table")
    if not isinstance(rows, list):
        collect_terms_from_value(intake, terms)
        return
    wanted_ids = {
        "target_industry",
        "target_category",
        "target_keywords",
        "article_title",
        "article_types",
        "publishing_channels",
        "target_brand",
        "target_product_or_solution",
        "solution_components",
        "competitors",
        "core_evidence",
    }
    for row in rows:
        if isinstance(row, dict) and str(row.get("id") or "") in wanted_ids:
            collect_terms_from_value(row.get("value"), terms)


def collect_terms_from_value(value: Any, terms: list[str]) -> None:
    if isinstance(value, str):
        collect_terms_from_text(value, terms)
    elif isinstance(value, list):
        for item in value:
            collect_terms_from_value(item, terms)
    elif isinstance(value, dict):
        preferred = [
            "keyword",
            "target_keyword",
            "title",
            "suggested_title",
            "type",
            "article_type",
            "brief_focus",
            "required_evidence",
            "core_evidence",
            "target_brand",
            "target_product_or_solution",
            "competitors",
            "channels",
            "channel",
            "markdown",
        ]
        for key in preferred:
            if key in value:
                collect_terms_from_value(value.get(key), terms)


def collect_terms_from_text(text: str, terms: list[str]) -> None:
    for part in re.split(r"[，,、；;｜|/\n\r\t（）()【】\[\]{}:：]+", text):
        value = part.strip()
        if len(value) >= 2:
            terms.append(value)


def unique_query_terms(terms: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for term in terms:
        cleaned = normalize_query_term(term)
        if not cleaned or cleaned in seen:
            continue
        result.append(cleaned)
        seen.add(cleaned)
    result.sort(key=len, reverse=True)
    return result[:80]


def normalize_query_term(term: str) -> str:
    value = " ".join(str(term or "").split()).strip()
    if len(value) < 2 or len(value) > 80:
        return ""
    if value.lower() in {"none", "null", "true", "false", "completed", "matrix", "breakthrough", "custom"}:
        return ""
    return value


def score_material_chunks(chunks: list[str], terms: list[str]) -> list[tuple[int, str]]:
    scored: list[tuple[int, str]] = []
    for chunk in chunks:
        score = 0
        for term in terms:
            if term and term in chunk:
                score += 3 if len(term) >= 4 else 1
        if score:
            scored.append((score, chunk))
    scored.sort(key=lambda item: (item[0], len(item[1])), reverse=True)
    return scored


def evidence_query_terms(terms: list[str]) -> list[str]:
    evidence_markers = [
        "证据",
        "参数",
        "认证",
        "检测",
        "报告",
        "专利",
        "奖项",
        "案例",
        "服务",
        "售后",
        "标准",
        "技术",
        "型号",
        "产品",
        "方案",
    ]
    return unique_query_terms([*terms, *evidence_markers])


def normalize_match_text(value: str) -> str:
    return " ".join(str(value or "").split()).strip().lower()


def unique_dicts_by_identity(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        key = source_id_for(item) or json.dumps(item, ensure_ascii=False, sort_keys=True)
        if key in seen:
            continue
        result.append(item)
        seen.add(key)
    return result


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
        title = generated_title_or_source_title(item, source, fallback="单篇文章 Brief")
        generated_at = utc_now()
        brief_item = {
            **existing_lookup.get(source_id, {}),
            **item,
            "id": str(item.get("id") or f"brief-{source_id}"),
            "source_id": source_id,
            "source_step": str(source.get("source_step") or source.get("step") or ""),
            "keyword": first_text(item, source, "keyword", "target_keyword", "目标关键词"),
            "type": first_text(item, source, "type", "article_type", "文章类型"),
            "title": title,
            "review_notes": first_text(item, source, "review_notes", "reviewNotes", "修改意见"),
            "markdown": first_markdown(item, generated),
            "status": str(item.get("status") or "completed"),
            "generated_at": generated_at,
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
        title = generated_title_or_source_title(item, brief, fallback="正式正文")
        generated_at = utc_now()
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
            "review_notes": first_text(item, brief, "review_notes", "reviewNotes", "修改意见"),
            "article_audit_status": "",
            "article_audited_at": "",
            "markdown": first_markdown(item, generated),
            "status": str(item.get("status") or "completed"),
            "generated_at": generated_at,
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
    unwrapped = unwrap_nested_generation_output(output)
    if unwrapped is not output:
        return generated_output_items(unwrapped)
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


def generated_title_or_source_title(primary: dict[str, Any], fallback_source: dict[str, Any], *, fallback: str) -> str:
    title = first_text(primary, {}, "title", "suggested_title", "建议标题", "文章标题")
    if title and title not in {"geo_brief", "geo_article"}:
        return title
    return first_text({}, fallback_source, "title", "suggested_title", "建议标题", "文章标题", fallback=fallback)


def first_markdown(item: dict[str, Any], generated: dict[str, Any]) -> str:
    for source in (item, generated):
        for key in MARKDOWN_VALUE_KEYS:
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                markdown = extract_markdown_from_possible_json(value)
                if markdown:
                    return markdown
                if looks_like_json_wrapper(value):
                    continue
                return value
    if generated_output_looks_like_truncated_json(item) or generated_output_looks_like_truncated_json(generated):
        raise WorkflowError("模型输出疑似被中转站截断，请重试；Brief/正文已改为纯 Markdown 生成以降低此类问题。")
    raise WorkflowError("模型返回格式异常：未找到可用的 Markdown 内容，请重试。")


def unwrap_nested_generation_output(output: dict[str, Any]) -> dict[str, Any]:
    for key in [*MARKDOWN_VALUE_KEYS, "raw"]:
        value = output.get(key)
        if isinstance(value, str) and value.strip():
            parsed = parse_json_object_text(value)
            if isinstance(parsed, dict) and any(isinstance(parsed.get(items_key), list) for items_key in ("items", "briefs", "articles", "data")):
                return parsed
    return output


def extract_markdown_from_possible_json(value: str) -> str:
    parsed = parse_json_object_text(value)
    if not isinstance(parsed, dict):
        return ""
    for item in generated_output_items(parsed):
        markdown = first_plain_markdown(item)
        if markdown:
            return markdown
    return first_plain_markdown(parsed)


def first_plain_markdown(item: dict[str, Any]) -> str:
    for key in MARKDOWN_VALUE_KEYS:
        value = item.get(key)
        if isinstance(value, str) and value.strip() and not looks_like_json_object(value):
            return value
    return ""


def parse_json_object_text(value: str) -> dict[str, Any] | None:
    text = strip_json_fence(value)
    if not looks_like_json_wrapper(text):
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def strip_json_fence(value: str) -> str:
    text = value.strip()
    if text.startswith("```"):
        text = text.removeprefix("```json").removeprefix("```").strip()
        text = text.removesuffix("```").strip()
    return text


def looks_like_json_object(value: str) -> bool:
    text = value.strip()
    return text.startswith("{") and text.endswith("}")


def looks_like_json_wrapper(value: str) -> bool:
    text = strip_json_fence(value)
    if not text.startswith("{"):
        return False
    preview = text[:2000]
    return (
        text.endswith("}")
        or '"items"' in preview
        or '"briefs"' in preview
        or '"articles"' in preview
        or '"markdown"' in preview
    )


def generated_output_looks_like_truncated_json(output: dict[str, Any]) -> bool:
    for key in [*MARKDOWN_VALUE_KEYS, "raw"]:
        value = output.get(key)
        if isinstance(value, str) and value.strip() and looks_like_json_wrapper(value) and parse_json_object_text(value) is None:
            return True
    return False

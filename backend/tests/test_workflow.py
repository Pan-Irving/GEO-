import json
import time
from datetime import datetime
from pathlib import Path

import pytest
from reportlab.pdfgen import canvas

from app.agent.skill_loader import SkillLoader
from app.agent.process_runner import ChildProcessCancelled
from app.agent.workflow import AgentWorkflow, WorkflowError, build_local_matrix_skeleton, build_selection_prompt_blocks, drop_running_items_after_cancel, mark_article_brief_failed, mark_article_briefs_running, mark_brief_source_failed, mark_brief_sources_running, material_summary_for_step, merge_generated_articles, merge_generated_briefs, normalize_matrix_import_output, normalize_planning_output, planning_output_requirements, prior_outputs_for_step, result_to_markdown
from app.core.config import PROJECT_ROOT, Settings
from app.services.content_plan import ContentPlanError, build_matrix_content_plan, export_content_plan_pdf
from app.storage.repository import ProjectRepository


def make_workflow(tmp_path: Path, **settings_overrides) -> AgentWorkflow:
    options = {"openai_api_key": "test-key", "app_data_dir": str(tmp_path), "hard_cancel_process_workers": False, **settings_overrides}
    settings = Settings(**options)
    return AgentWorkflow(
        ProjectRepository(tmp_path),
        SkillLoader(PROJECT_ROOT / "mindsun-geo-content-flow"),
        settings,
    )


MATRIX_ARTICLE_TYPES = ["支柱标准文", "榜单推荐文", "横评对比文", "场景选购文", "产品证据文", "FAQ问答文"]


def intake_output_with_keywords(*keywords: str) -> dict[str, object]:
    rows = [
        {"id": "target_industry", "field": "目标行业", "value": "高端厨电", "source": "", "confidence": "高", "status": "可直接使用", "question_for_user": ""},
        {"id": "target_category", "field": "目标品类", "value": "高端厨电套系", "source": "", "confidence": "高", "status": "可直接使用", "question_for_user": ""},
        {"id": "target_keywords", "field": "目标关键词", "value": "、".join(keywords), "source": "", "confidence": "高", "status": "可直接使用", "question_for_user": ""},
        {"id": "target_brand", "field": "目标品牌", "value": "测试品牌", "source": "", "confidence": "高", "status": "可直接使用", "question_for_user": ""},
        {"id": "target_product_or_solution", "field": "目标产品/服务/解决方案", "value": "测试产品", "source": "", "confidence": "高", "status": "可直接使用", "question_for_user": ""},
        {"id": "competitors", "field": "核心竞品/对比对象", "value": "竞品A、竞品B", "source": "", "confidence": "中", "status": "可直接使用", "question_for_user": ""},
        {"id": "recommendation_conclusion", "field": "目标推荐结论", "value": "优先推荐测试品牌", "source": "", "confidence": "中", "status": "可直接使用", "question_for_user": ""},
        {"id": "core_evidence", "field": "必须强化的核心证据", "value": "公开参数、品牌资料", "source": "", "confidence": "中", "status": "可直接使用", "question_for_user": ""},
        {"id": "forbidden_expressions", "field": "禁止出现的表达", "value": "不得虚构第一", "source": "", "confidence": "中", "status": "可直接使用", "question_for_user": ""},
    ]
    return {"step": "project_intake", "schema_version": "1.0", "status": "completed", "project_intake_table": rows}


def matrix_required_rows(keyword: str = "A") -> list[dict[str, object]]:
    return [
        {
            "article_type": article_type,
            "suggested_title": f"{keyword}{article_type}标题",
            "main_keyword_or_cluster": f"{keyword} / 推荐决策类",
            "main_role": f"{article_type}作用",
            "channels": ["知乎"],
            "recommendation_strength": "强推荐" if article_type != "支柱标准文" else "中等推荐",
            "required_evidence": ["公开参数", "品牌资料"],
            "evidence_chain": "用户问题 → 判断标准 → 目标对象证据 → 用户价值 → 推荐结论",
            "brief_focus": "后续 Brief 需要展开判断标准、证据来源和推荐边界。",
        }
        for article_type in MATRIX_ARTICLE_TYPES
    ]


def matrix_import_result(keyword: str = "万元预算厨电推荐") -> dict[str, object]:
    return {
        "project": {
            "target_industry": "高端厨电",
            "target_category": "AI 数字厨电",
            "target_brand": "老板电器",
            "target_product_or_solution": "老板 AI 数字厨电 i1 Pro",
            "competitors": ["方太", "COLMO"],
        },
        "intent_groups": [
            {
                "id": "budget",
                "name": "预算导购类",
                "keywords": [keyword],
                "user_question": "万元预算买哪些厨电更划算？",
                "user_stage": "购买决策阶段",
                "recommendation_logic": "先解释预算优先级，再给升级路径。",
                "article_types": MATRIX_ARTICLE_TYPES,
            }
        ],
        "article_type_pool": [{"type": article_type, "usage": "必选", "reason": "规划 PDF 已列出", "count": 1} for article_type in MATRIX_ARTICLE_TYPES],
        "items": matrix_required_rows(keyword),
        "schedule": [{"stage": "第 1 阶段", "period": "第 1-2 周", "key_tasks": ["发布支柱文"], "article_types": ["支柱标准文"], "goal": "建立标准"}],
        "warnings": [],
    }


def write_test_pdf(path: Path, text: str) -> bytes:
    pdf = canvas.Canvas(str(path))
    pdf.setFont("Helvetica", 10)
    y = 780
    for line in text.splitlines():
        pdf.drawString(40, y, line[:100])
        y -= 14
        if y < 40:
            pdf.showPage()
            pdf.setFont("Helvetica", 10)
            y = 780
    pdf.save()
    return path.read_bytes()


def prepare_project_for_matrix_import(workflow: AgentWorkflow, project_id: str) -> None:
    material = workflow.repository.add_material(project_id, "brief.md", "text/markdown", b"# Brief\n\nkeyword")
    material.status = "parsed"
    material.parsed_path = "parsed/brief.md"
    material.parse_mode = "smart"
    material.parsed_at = "2026-01-01T00:00:00+00:00"
    workflow.repository.parsed_dir(project_id).mkdir(parents=True, exist_ok=True)
    (workflow.repository.project_dir(project_id) / material.parsed_path).write_text("# parsed\n", encoding="utf-8")
    workflow.repository.update_material(project_id, material)
    workflow.repository.update_step(project_id, "materials", status="completed", output={"summary": "# Brief\n\nkeyword"}, confirmed=True)
    workflow.repository.update_step(project_id, "intake", status="completed", output=intake_output_with_keywords("万元预算厨电推荐"))


def breakthrough_rows(keyword: str = "A", article_types: list[str] | None = None) -> list[dict[str, object]]:
    return [
        {
            "source_id": f"{keyword}-{article_type}",
            "source_step": "breakthrough",
            "keyword": keyword,
            "type": article_type,
            "title": f"{keyword}{article_type}标题",
            "role": f"{article_type}作用",
            "status": "completed",
        }
        for article_type in (article_types or MATRIX_ARTICLE_TYPES)
    ]


def test_parse_materials_confirms_material_step(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    workflow.repository.add_material(project.id, "brief.md", "text/markdown", b"# Brief\n\nkeyword")

    workflow.parse_materials(project.id)

    saved = workflow.repository.load_project(project.id)
    assert saved.steps["materials"].status == "confirmed"
    assert saved.materials[0].status == "parsed"


def test_delete_material_removes_files_and_resets_material_step(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    material = workflow.repository.add_material(project.id, "brief.md", "text/markdown", b"# Brief\n")
    source_path = workflow.repository.materials_dir(project.id) / material.stored_name
    parsed_path = workflow.repository.parsed_dir(project.id) / "brief.md"
    parsed_path.write_text("# parsed\n", encoding="utf-8")
    material.status = "parsed"
    material.parsed_path = str(parsed_path.relative_to(workflow.repository.project_dir(project.id)))
    workflow.repository.update_material(project.id, material)
    workflow.repository.update_step(project.id, "materials", status="completed", output={"summary": "old"}, confirmed=True)

    saved = workflow.repository.delete_material(project.id, material.id)

    assert saved.materials == []
    assert not source_path.exists()
    assert not parsed_path.exists()
    assert saved.steps["materials"].status == "pending"
    assert saved.steps["materials"].output == {}
    assert saved.steps["materials"].confirmed_at is None


def test_delete_project_removes_project_directory(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    workflow.repository.add_material(project.id, "brief.md", "text/markdown", b"# Brief\n")
    project_dir = workflow.repository.project_dir(project.id)

    workflow.repository.delete_project(project.id)

    assert not project_dir.exists()
    with pytest.raises(FileNotFoundError):
        workflow.repository.load_project(project.id)


def test_start_materials_parse_creates_progress_job(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    workflow.repository.add_material(project.id, "brief.md", "text/markdown", b"# Brief\n")

    job_id = workflow.start_materials_parse(project.id)

    saved = workflow.repository.load_project(project.id)
    assert job_id
    assert saved.steps["materials"].status == "running"
    assert saved.jobs[0].step == "materials"
    assert saved.jobs[0].total_count == 1
    assert "准备解析" in (saved.jobs[0].message or "")


def test_parse_materials_updates_progress_job(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    workflow.repository.add_material(project.id, "brief.md", "text/markdown", b"# Brief\n\nkeyword")
    job_id = workflow.start_materials_parse(project.id)

    workflow.parse_materials(project.id, job_id)

    saved = workflow.repository.load_project(project.id)
    job = saved.jobs[0]
    assert saved.steps["materials"].status == "confirmed"
    assert job.status == "completed"
    assert job.total_count == 1
    assert job.completed_count == 1
    assert job.skipped_count == 0
    assert "成功 1/1" in (job.message or "")


def test_parse_materials_uses_cache_for_reuploaded_file(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    material = workflow.repository.add_material(project.id, "brief.md", "text/markdown", b"# Brief\n\nkeyword")

    workflow.parse_materials(project.id)
    first = workflow.repository.load_project(project.id).materials[0]
    assert first.parse_source == "fresh"

    workflow.repository.delete_material(project.id, material.id)
    workflow.repository.add_material(project.id, "brief-again.md", "text/markdown", b"# Brief\n\nkeyword")
    workflow.parse_materials(project.id)

    saved = workflow.repository.load_project(project.id)
    assert saved.materials[0].status == "parsed"
    assert saved.materials[0].parse_source == "cache"
    assert saved.materials[0].parsed_chars > 0


def test_parse_materials_text_only_parses_image_placeholder_without_ocr(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    workflow.repository.add_material(project.id, "rank.jpg", "image/jpeg", b"not really an image")

    workflow.parse_materials(project.id, mode="text_only")

    saved = workflow.repository.load_project(project.id)
    assert saved.steps["materials"].status == "confirmed"
    assert saved.materials[0].status == "parsed"
    assert saved.materials[0].parse_mode == "text_only"
    assert saved.materials[0].ocr_pages == 0
    assert "未执行本地 OCR" in saved.steps["materials"].output["summary"]


def test_cancel_job_marks_cancelling_and_preserves_stop_state(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    workflow.repository.add_material(project.id, "brief.md", "text/markdown", b"# Brief\n")
    job_id = workflow.start_materials_parse(project.id)

    workflow.repository.cancel_job(project.id, job_id)
    workflow.repository.update_job(project.id, job_id, status="running", message="正在解析资料")

    saved = workflow.repository.load_project(project.id)
    job = saved.jobs[0]
    assert job.status == "cancelling"
    assert "停止" in (job.message or "")


def test_parse_materials_respects_cancelled_job_before_work(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    workflow.repository.add_material(project.id, "brief.md", "text/markdown", b"# Brief\n\nkeyword")
    job_id = workflow.start_materials_parse(project.id)

    workflow.repository.cancel_job(project.id, job_id)
    workflow.parse_materials(project.id, job_id)

    saved = workflow.repository.load_project(project.id)
    job = saved.jobs[0]
    assert saved.steps["materials"].status == "failed"
    assert job.status == "cancelled"
    assert "已停止" in (job.message or "")
    assert saved.materials[0].status == "uploaded"


def test_parse_materials_hard_cancel_restores_current_material(tmp_path: Path, monkeypatch):
    workflow = make_workflow(tmp_path, hard_cancel_process_workers=True)
    project = workflow.repository.create_project("测试项目")
    workflow.repository.add_material(project.id, "rank.jpg", "image/jpeg", b"fake image")
    job_id = workflow.start_materials_parse(project.id)

    def cancel_parse(*args, **kwargs):
        workflow.repository.cancel_job(project.id, job_id)
        raise ChildProcessCancelled("任务已停止。")

    monkeypatch.setattr(workflow, "_parse_material_in_child", cancel_parse)

    workflow.parse_materials(project.id, job_id)

    saved = workflow.repository.load_project(project.id)
    assert saved.jobs[0].status == "cancelled"
    assert saved.steps["materials"].status == "failed"
    assert saved.materials[0].status == "uploaded"
    assert saved.materials[0].parsed_path is None


def test_matrix_import_job_creates_draft_without_overwriting_matrix(tmp_path: Path, monkeypatch):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    prepare_project_for_matrix_import(workflow, project.id)
    pdf_bytes = write_test_pdf(
        tmp_path / "plan.pdf",
        "\n".join(["content plan pdf with first round article list and schedule"] * 20),
    )
    monkeypatch.setattr(workflow, "_recognize_matrix_import_text", lambda text: matrix_import_result())

    result = workflow.start_matrix_import(project.id, "plan.pdf", "application/pdf", pdf_bytes)
    workflow.run_matrix_import_job(project.id, result["job_id"], result["draft_id"])

    saved = workflow.repository.load_project(project.id)
    draft = workflow.repository.load_matrix_import_draft(project.id, result["draft_id"])
    assert saved.steps["matrix"].output == {}
    assert saved.steps["matrix"].status == "pending"
    assert draft["status"] == "completed"
    assert draft["stats"]["item_count"] == 6
    assert saved.jobs[0].status == "completed"


def test_apply_matrix_import_overwrites_matrix_step_after_confirmation(tmp_path: Path, monkeypatch):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    prepare_project_for_matrix_import(workflow, project.id)
    pdf_bytes = write_test_pdf(
        tmp_path / "plan.pdf",
        "\n".join(["content plan pdf with first round article list and schedule"] * 20),
    )
    monkeypatch.setattr(workflow, "_recognize_matrix_import_text", lambda text: matrix_import_result())
    result = workflow.start_matrix_import(project.id, "plan.pdf", "application/pdf", pdf_bytes)
    workflow.run_matrix_import_job(project.id, result["job_id"], result["draft_id"])

    workflow.apply_matrix_import_draft(project.id, result["draft_id"], overwrite=True)

    saved = workflow.repository.load_project(project.id)
    draft = workflow.repository.load_matrix_import_draft(project.id, result["draft_id"])
    assert saved.steps["matrix"].status == "completed"
    assert len(saved.steps["matrix"].output["items"]) == 6
    assert saved.steps["matrix"].output["items"][0]["keyword"] == "万元预算厨电推荐"
    assert saved.steps["matrix"].output["matrix_generation_source"] == "imported_content_plan_pdf"
    assert saved.steps["matrix"].output["imported_filename"] == "plan.pdf"
    assert saved.steps["matrix"].output["bound_material_count"] == 1
    assert saved.steps["matrix"].output["bound_material_snapshot"][0]["filename"] == "brief.md"
    assert draft["status"] == "applied"
    assert any(path.endswith("02-content-matrix.md") for path in workflow.repository.output_files(project.id))


def test_matrix_import_requires_materials_and_intake(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    pdf_bytes = write_test_pdf(
        tmp_path / "plan.pdf",
        "\n".join(["content plan pdf with first round article list and schedule"] * 20),
    )

    with pytest.raises(WorkflowError, match="资料解析和项目信息抽取"):
        workflow.start_matrix_import(project.id, "plan.pdf", "application/pdf", pdf_bytes)

    workflow.repository.update_step(project.id, "materials", status="completed", output={"summary": "# ok"}, confirmed=True)
    with pytest.raises(WorkflowError, match="资料解析和项目信息抽取"):
        workflow.start_matrix_import(project.id, "plan.pdf", "application/pdf", pdf_bytes)


def test_matrix_import_rejects_unlabelled_keywords():
    raw = matrix_import_result("")
    rows = raw["items"]
    assert isinstance(rows, list)
    for row in rows:
        assert isinstance(row, dict)
        row.pop("main_keyword_or_cluster", None)
        row.pop("keyword", None)

    with pytest.raises(WorkflowError, match="没有匹配到明确关键词"):
        normalize_matrix_import_output(raw)  # type: ignore[arg-type]


def test_run_step_job_hard_cancel_discards_result(tmp_path: Path, monkeypatch):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    workflow.repository.update_step(project.id, "materials", status="completed", confirmed=True)
    job_id = workflow.start_step(project.id, "intake", {})

    def cancel_step(*args, **kwargs):
        workflow.repository.cancel_job(project.id, job_id)
        raise ChildProcessCancelled("任务已停止。")

    monkeypatch.setattr(workflow, "_run_step_for_job", cancel_step)

    workflow.run_step_job(project.id, job_id, "intake", {})

    saved = workflow.repository.load_project(project.id)
    assert saved.jobs[0].status == "cancelled"
    assert saved.steps["intake"].status == "failed"
    assert saved.steps["intake"].output == {}


def test_cancelled_incremental_items_return_to_not_generated():
    output = drop_running_items_after_cancel(
        {
            "items": [
                {"id": "done", "status": "completed", "markdown": "# done"},
                {"id": "running", "status": "running", "markdown": ""},
                {"id": "failed", "status": "failed", "error": "真实失败"},
            ]
        }
    )

    item_ids = {item["id"] for item in output["items"]}
    assert item_ids == {"done", "failed"}
    assert output["status"] == "cancelled"


def test_cannot_run_next_step_before_previous_confirmed(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")

    with pytest.raises(WorkflowError):
        workflow.start_step(project.id, "matrix", {})


def test_can_start_intake_after_materials_confirmed(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    workflow.repository.update_step(project.id, "materials", status="completed", confirmed=True)

    job_id = workflow.start_step(project.id, "intake", {})

    saved = workflow.repository.load_project(project.id)
    assert job_id
    assert saved.steps["intake"].status == "running"
    assert saved.jobs[0].step == "intake"
    assert saved.jobs[0].total_count == 1
    assert "抽取表" in (saved.jobs[0].message or "")


def test_custom_source_is_persisted_and_deduped(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    workflow.repository.update_step(
        project.id,
        "matrix",
        status="completed",
        output={"items": [{"source_id": "matrix-a", "keyword": "GEO 撰文工具", "type": "场景选购文", "title": "矩阵标题"}]},
    )

    saved = workflow.repository.create_custom_source(
        project.id,
        {"title": "如何选择 GEO 撰文工具"},
    )

    assert len(saved.custom_sources) == 1
    source = saved.custom_sources[0]
    assert source.source_step == "custom"
    assert source.source_id.startswith("custom-")
    assert source.keyword == "GEO 撰文工具"
    assert source.type == "场景选购文"
    assert source.title == "如何选择 GEO 撰文工具"
    with pytest.raises(ValueError, match="已存在"):
        workflow.repository.create_custom_source(
            project.id,
            {"title": "如何选择 GEO 撰文工具"},
        )


def test_custom_source_copied_context_infers_keyword_and_type(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    workflow.repository.update_step(
        project.id,
        "breakthrough",
        status="completed",
        output={"items": [{"source_id": "source-a", "keyword": "高端厨电", "type": "横评对比文", "title": "原规划"}]},
    )

    saved = workflow.repository.create_custom_source(
        project.id,
        {"title": "用户改写后的标题", "raw": {"copied_from": {"source_id": "source-a"}}},
    )

    source = saved.custom_sources[0]
    assert source.keyword == "高端厨电"
    assert source.type == "横评对比文"
    assert source.raw["inferred"]["source"] == "copied_source"


@pytest.mark.parametrize(
    ("title", "article_type"),
    [
        ("高端厨电 FAQ 常见问题整理", "FAQ问答文"),
        ("2026 高端厨电品牌推荐清单", "榜单推荐文"),
        ("高端厨电和普通厨电横评对比", "横评对比文"),
        ("开放式厨房怎么选高端厨电指南", "场景选购文"),
        ("高端厨电实测证据与参数解析", "产品证据文"),
    ],
)
def test_custom_source_infers_article_type_from_title(tmp_path: Path, title: str, article_type: str):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")

    saved = workflow.repository.create_custom_source(project.id, {"title": title})

    assert saved.custom_sources[0].type == article_type


def test_custom_sources_batch_create_uses_selected_type(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")

    saved = workflow.repository.create_custom_sources(
        project.id,
        {
            "titles": ["标题 A", "", "标题 B", "标题 C"],
            "type": "榜单推荐文",
            "channel": "知乎",
        },
    )

    assert [source.title for source in saved.custom_sources] == ["标题 A", "标题 B", "标题 C"]
    assert {source.type for source in saved.custom_sources} == {"榜单推荐文"}
    assert {source.channel for source in saved.custom_sources} == {"知乎"}


def test_custom_sources_batch_requires_titles(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")

    with pytest.raises(ValueError, match="至少填写"):
        workflow.repository.create_custom_sources(project.id, {"titles": ["", "  "], "type": "榜单推荐文"})


def test_custom_sources_batch_duplicate_rolls_back(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    workflow.repository.create_custom_source(project.id, {"title": "已有标题", "type": "支柱标准文"})

    with pytest.raises(ValueError, match="已存在"):
        workflow.repository.create_custom_sources(
            project.id,
            {"titles": ["新标题", "已有标题"], "type": "榜单推荐文"},
        )

    saved = workflow.repository.load_project(project.id)
    assert [source.title for source in saved.custom_sources] == ["已有标题"]


def test_custom_source_edit_before_brief_recomputes_source_id(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    saved = workflow.repository.create_custom_source(project.id, {"title": "旧标题"})
    old_id = saved.custom_sources[0].source_id

    saved = workflow.repository.update_custom_source(project.id, old_id, {"title": "新标题"})

    assert saved.custom_sources[0].title == "新标题"
    assert saved.custom_sources[0].source_id != old_id
    assert saved.custom_sources[0].source_id.startswith("custom-新标题")


def test_custom_sources_survive_step_updates(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    workflow.repository.create_custom_source(
        project.id,
        {"title": "用户自定义标题"},
    )

    workflow.repository.update_step(project.id, "matrix", status="running", output={})

    saved = workflow.repository.load_project(project.id)
    assert [source.title for source in saved.custom_sources] == ["用户自定义标题"]


def test_generated_brief_items_include_generated_at():
    source = {
        "source_id": "source-a",
        "source_step": "matrix",
        "keyword": "高端厨电",
        "type": "支柱标准文",
        "title": "高端厨电怎么选",
    }

    merged, generated_items = merge_generated_briefs(
        {},
        [source],
        {"items": [{"source_id": "source-a", "markdown": "# Brief"}]},
    )

    item = generated_items[0]
    assert item["generated_at"]
    datetime.fromisoformat(item["generated_at"])
    assert merged["items"][0]["generated_at"] == item["generated_at"]


def test_generated_article_items_include_generated_at():
    brief = {
        "id": "brief-source-a",
        "source_id": "source-a",
        "keyword": "高端厨电",
        "type": "支柱标准文",
        "title": "高端厨电怎么选",
        "revision": 2,
    }

    merged, generated_items = merge_generated_articles(
        {},
        [brief],
        {"items": [{"brief_id": "brief-source-a", "markdown": "# 正文"}]},
    )

    item = generated_items[0]
    assert item["generated_at"]
    datetime.fromisoformat(item["generated_at"])
    assert item["brief_revision"] == 2
    assert merged["items"][0]["generated_at"] == item["generated_at"]


def test_running_and_failed_placeholders_do_not_include_generated_at():
    source = {"source_id": "source-a", "title": "高端厨电怎么选"}
    brief = {"id": "brief-source-a", "title": "高端厨电怎么选"}

    brief_running = mark_brief_sources_running({}, [source])["items"][0]
    article_running = mark_article_briefs_running({}, [brief])["items"][0]
    brief_failed = mark_brief_source_failed({}, source, "失败")["items"][0]
    article_failed = mark_article_brief_failed({}, brief, "失败")["items"][0]

    assert "generated_at" not in brief_running
    assert "generated_at" not in article_running
    assert "generated_at" not in brief_failed
    assert "generated_at" not in article_failed


def test_custom_source_can_start_brief_generation(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    for step in ["materials", "intake", "matrix", "breakthrough"]:
        workflow.repository.update_step(project.id, step, status="completed", confirmed=True)
    saved = workflow.repository.create_custom_source(
        project.id,
        {"keyword": "GEO", "type": "FAQ问答文", "title": "用户指定标题", "channel": "官网"},
    )

    job_id = workflow.start_step(project.id, "brief", {"selected_sources": [saved.custom_sources[0].model_dump()]})

    saved = workflow.repository.load_project(project.id)
    assert job_id
    assert saved.steps["brief"].status == "running"
    selected = saved.steps["brief"].input["selected_sources"][0]
    assert selected["source_step"] == "custom"
    assert selected["title"] == "用户指定标题"


def test_custom_source_edit_is_rejected_after_brief_exists(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    saved = workflow.repository.create_custom_source(
        project.id,
        {"keyword": "GEO", "type": "FAQ问答文", "title": "用户指定标题"},
    )
    source_id = saved.custom_sources[0].source_id
    workflow.repository.update_step(
        project.id,
        "brief",
        status="completed",
        output={"items": [{"id": f"brief-{source_id}", "source_id": source_id, "title": "用户指定标题"}]},
    )

    with pytest.raises(ValueError, match="Brief 审核页"):
        workflow.repository.update_custom_source(
            project.id,
            source_id,
            {"title": "改标题"},
        )


def test_brief_prompt_marks_custom_title_as_required():
    blocks = build_selection_prompt_blocks(
        "brief",
        {"selected_sources": [{"source_id": "custom-a", "source_step": "custom", "keyword": "A", "type": "类型", "title": "用户标题"}]},
    )

    assert "source_step 为 custom" in "\n".join(blocks)
    assert "title 是用户指定的目标选题" in "\n".join(blocks)


def test_intake_job_success_records_single_step_progress(tmp_path: Path, monkeypatch):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    workflow.repository.update_step(project.id, "materials", status="completed", confirmed=True)
    job_id = workflow.start_step(project.id, "intake", {})
    monkeypatch.setattr(workflow, "_run_step", lambda *args, **kwargs: {"project_intake_table": [{"field": "目标"}]})

    workflow.run_step_job(project.id, job_id, "intake", {})

    saved = workflow.repository.load_project(project.id)
    job = saved.jobs[0]
    assert saved.steps["intake"].status == "completed"
    assert job.status == "completed"
    assert job.total_count == 1
    assert job.completed_count == 1
    assert saved.steps["intake"].output["step"] == "project_intake"
    assert "已提取 13 项" in (job.message or "")


def test_planning_steps_create_progress_jobs(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    workflow.repository.update_step(project.id, "materials", status="completed", confirmed=True)
    workflow.repository.update_step(project.id, "intake", status="completed", confirmed=True, output=intake_output_with_keywords("A推荐"))

    matrix_job_id = workflow.start_step(project.id, "matrix", {})
    saved = workflow.repository.load_project(project.id)
    matrix_job = saved.jobs[0]
    assert matrix_job.id == matrix_job_id
    assert matrix_job.step == "matrix"
    assert matrix_job.total_count == 1
    assert "内容矩阵" in (matrix_job.message or "")

    workflow.repository.update_step(project.id, "matrix", status="completed", output={"items": [{"id": "plan", "keyword": "A"}]})
    workflow.confirm_breakthrough_keywords(project.id, ["A"])
    breakthrough_job_id = workflow.start_step(project.id, "breakthrough", {})
    saved = workflow.repository.load_project(project.id)
    breakthrough_job = saved.jobs[0]
    assert breakthrough_job.id == breakthrough_job_id
    assert breakthrough_job.step == "breakthrough"
    assert breakthrough_job.total_count == 1
    assert "逐词击破" in (breakthrough_job.message or "")


def test_planning_step_jobs_record_success_and_failure(tmp_path: Path, monkeypatch):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    workflow.repository.update_step(project.id, "materials", status="completed", confirmed=True)
    workflow.repository.update_step(project.id, "intake", status="completed", confirmed=True, output=intake_output_with_keywords("A推荐"))
    matrix_job_id = workflow.start_step(project.id, "matrix", {})
    monkeypatch.setattr(workflow, "_run_step", lambda *args, **kwargs: {"items": matrix_required_rows("A")})

    workflow.run_step_job(project.id, matrix_job_id, "matrix", {})

    saved = workflow.repository.load_project(project.id)
    matrix_job = saved.jobs[0]
    assert saved.steps["matrix"].status == "completed"
    assert matrix_job.status == "completed"
    assert matrix_job.completed_count == 1

    workflow.confirm_breakthrough_keywords(project.id, ["A"])
    breakthrough_job_id = workflow.start_step(project.id, "breakthrough", {})

    def fail(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(workflow, "_run_step", fail)

    workflow.run_step_job(project.id, breakthrough_job_id, "breakthrough", {})

    saved = workflow.repository.load_project(project.id)
    breakthrough_job = saved.jobs[0]
    assert saved.steps["breakthrough"].status == "failed"
    assert breakthrough_job.status == "failed"
    assert breakthrough_job.failed_count == 1
    assert breakthrough_job.error == "boom"


def test_matrix_batched_generation_merges_canonical_output(tmp_path: Path, monkeypatch):
    workflow = make_workflow(tmp_path, matrix_batch_intent_group_size=1)
    project = workflow.repository.create_project("测试项目")
    workflow.repository.update_step(project.id, "materials", status="completed", confirmed=True)
    workflow.repository.update_step(project.id, "intake", status="completed", confirmed=True, output=intake_output_with_keywords("A推荐", "B怎么选"))
    job_id = workflow.start_step(project.id, "matrix", {})
    modes: list[object] = []

    def fake_run_step(project_id: str, step: str, payload: dict[str, object]):
        mode = payload.get("matrix_generation_mode")
        modes.append(mode)
        assert mode != "skeleton"
        batch = payload.get("matrix_batch")
        assert isinstance(batch, dict)
        keyword = str(batch["keywords"][0])
        return {"items": matrix_required_rows(keyword)}

    monkeypatch.setattr(workflow, "_run_step", fake_run_step)

    workflow.run_step_job(project.id, job_id, "matrix", {})

    saved = workflow.repository.load_project(project.id)
    output = saved.steps["matrix"].output
    job = saved.jobs[0]
    assert saved.steps["matrix"].status == "completed"
    assert modes == ["batch", "batch"]
    assert job.total_count == 2
    assert job.completed_count == 2
    assert output["step"] == "geo_content_matrix"
    assert len(output["intent_groups"]) == 2
    assert len(output["items"]) == 12
    assert set(output) >= {"keyword_overview", "intent_groups", "article_type_pool", "items", "brief_requirements", "warnings"}
    assert [row["count"] for row in output["article_type_pool"]] == [2, 2, 2, 2, 2, 2]


def test_matrix_batched_generation_retries_524_once(tmp_path: Path, monkeypatch):
    workflow = make_workflow(tmp_path, matrix_timeout_retry_seconds=0)
    project = workflow.repository.create_project("测试项目")
    workflow.repository.update_step(project.id, "materials", status="completed", confirmed=True)
    workflow.repository.update_step(project.id, "intake", status="completed", confirmed=True, output=intake_output_with_keywords("A推荐"))
    job_id = workflow.start_step(project.id, "matrix", {})
    calls = {"batch": 0}

    def fake_run_step(project_id: str, step: str, payload: dict[str, object]):
        assert payload.get("matrix_generation_mode") == "batch"
        calls["batch"] += 1
        if calls["batch"] == 1:
            raise RuntimeError("Error code: 524 - origin_response_timeout retry_after: 0")
        return {"items": matrix_required_rows("A推荐")}

    monkeypatch.setattr(workflow, "_run_step", fake_run_step)

    workflow.run_step_job(project.id, job_id, "matrix", {})

    saved = workflow.repository.load_project(project.id)
    assert calls["batch"] == 2
    assert saved.steps["matrix"].status == "completed"
    assert saved.jobs[0].status == "completed"
    assert saved.jobs[0].error is None


def test_matrix_batched_generation_stores_friendly_524_error(tmp_path: Path, monkeypatch):
    workflow = make_workflow(tmp_path, matrix_timeout_retry_seconds=0)
    project = workflow.repository.create_project("测试项目")
    workflow.repository.update_step(project.id, "materials", status="completed", confirmed=True)
    workflow.repository.update_step(project.id, "intake", status="completed", confirmed=True, output=intake_output_with_keywords("A推荐"))
    job_id = workflow.start_step(project.id, "matrix", {})

    def fake_run_step(project_id: str, step: str, payload: dict[str, object]):
        assert payload.get("matrix_generation_mode") == "batch"
        raise RuntimeError("Error code: 524 - Cloudflare origin web server did not return a complete response retry_after: 0")

    monkeypatch.setattr(workflow, "_run_step", fake_run_step)

    workflow.run_step_job(project.id, job_id, "matrix", {})

    saved = workflow.repository.load_project(project.id)
    assert saved.steps["matrix"].status == "failed"
    assert saved.jobs[0].status == "failed"
    assert saved.jobs[0].error
    assert saved.jobs[0].error.startswith("中转站超时")
    assert "Cloudflare" not in saved.jobs[0].error


def test_local_matrix_skeleton_uses_intake_keywords(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    workflow.repository.update_step(project.id, "materials", status="completed", confirmed=True)
    workflow.repository.update_step(
        project.id,
        "intake",
        status="completed",
        confirmed=True,
        output=intake_output_with_keywords("高端厨电品牌推荐", "别墅中西厨厨电搭配"),
    )

    saved = workflow.repository.load_project(project.id)
    skeleton = build_local_matrix_skeleton(saved, {})

    assert skeleton["step"] == "geo_content_matrix"
    assert skeleton["items"] == []
    assert {group["name"] for group in skeleton["intent_groups"]} == {"推荐决策类", "场景选购类"}
    assert skeleton["project"]["target_brand"] == "测试品牌"
    assert [row["type"] for row in skeleton["article_type_pool"]] == MATRIX_ARTICLE_TYPES
    assert set(skeleton) >= {"project", "keyword_overview", "intent_groups", "article_type_pool", "items", "brief_requirements", "warnings"}


def test_matrix_batch_material_context_is_trimmed_to_batch_keywords(tmp_path: Path):
    workflow = make_workflow(tmp_path, matrix_batch_material_context_limit=2200)
    project = workflow.repository.create_project("测试项目")
    long_prefix = "通用资料" * 400
    summary = f"{long_prefix}\n\n# A推荐\nA推荐 专属证据\n\n# B怎么选\nB怎么选 专属证据\n\n" + ("其他资料" * 1000)
    workflow.repository.update_step(project.id, "materials", status="completed", confirmed=True, output={"summary": summary})
    workflow.repository.update_step(project.id, "intake", status="completed", confirmed=True, output=intake_output_with_keywords("A推荐", "B怎么选"))
    saved = workflow.repository.load_project(project.id)

    text = material_summary_for_step(
        saved,
        "matrix",
        {"matrix_generation_mode": "batch", "matrix_batch": {"keywords": ["B怎么选"], "intent_groups": []}},
        workflow.settings,
    )

    assert len(text) <= 2200
    assert "B怎么选 专属证据" in text


def test_intake_prompt_includes_canonical_template():
    prompt = planning_output_requirements("intake", {})

    assert '"step": "project_intake"' in prompt
    assert "project_intake_table 必须固定输出 13 行" in prompt
    assert "id, field, value, source, confidence, status, question_for_user" in prompt
    assert "不要把字段名翻译成中文" in prompt


def test_intake_output_is_normalized_from_legacy_fields():
    output = normalize_planning_output(
        "intake",
        {
            "current_step": "项目信息自动抽取",
            "intake_table": [
                {
                    "字段": "目标行业",
                    "推断值": "高端厨电",
                    "来源/依据": "资料 A",
                    "置信度": "高",
                    "状态": "可直接使用",
                    "需用户确认的问题": "",
                },
                {
                    "field": "目标品类",
                    "inferred_value": "AI数字厨电套系",
                    "source_or_basis": "资料 B",
                    "confidence": "中",
                    "status": "需确认",
                    "question_for_user": "是否按套系处理？",
                },
            ],
            "可直接使用的信息": ["目标品牌明确"],
        },
        {},
    )

    assert output["step"] == "project_intake"
    assert output["schema_version"] == "1.0"
    assert len(output["project_intake_table"]) == 13
    industry = output["project_intake_table"][0]
    category = output["project_intake_table"][1]
    missing = output["project_intake_table"][2]
    assert industry == {
        "id": "target_industry",
        "field": "目标行业",
        "value": "高端厨电",
        "source": "资料 A",
        "confidence": "高",
        "status": "可直接使用",
        "question_for_user": "",
    }
    assert category["id"] == "target_category"
    assert category["source"] == "资料 B"
    assert category["question_for_user"] == "是否按套系处理？"
    assert missing["id"] == "target_keywords"
    assert missing["status"] == "缺失待补充"
    assert output["usable_info"] == ["目标品牌明确"]


def test_intake_output_without_rows_is_rejected():
    with pytest.raises(WorkflowError, match="project_intake_table"):
        normalize_planning_output("intake", {"summary": "bad"}, {})


def test_prior_outputs_only_include_upstream_non_material_steps(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    workflow.repository.update_step(project.id, "materials", status="confirmed", output={"summary": "材料内容"})
    workflow.repository.update_step(project.id, "intake", status="confirmed", output={"step": "project_intake"})
    workflow.repository.update_step(project.id, "matrix", status="confirmed", output={"step": "geo_content_matrix"})
    workflow.repository.update_step(project.id, "breakthrough", status="confirmed", output={"step": "geo_keyword_breakthrough"})
    workflow.repository.update_step(project.id, "brief", status="confirmed", output={"items": [{"id": "brief"}]})
    workflow.repository.update_step(project.id, "article", status="completed", output={"items": [{"id": "article"}]})
    project = workflow.repository.load_project(project.id)

    assert prior_outputs_for_step(project, "matrix") == {"intake": {"step": "project_intake"}}
    assert set(prior_outputs_for_step(project, "breakthrough")) == {"intake", "matrix"}
    assert set(prior_outputs_for_step(project, "article")) == {"intake", "matrix", "breakthrough", "brief"}
    assert set(prior_outputs_for_step(project, "archive")) == {"intake", "matrix", "breakthrough", "brief", "article"}


def test_rewrite_step_is_not_created_or_runnable(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")

    assert "rewrite" not in project.steps
    with pytest.raises(WorkflowError, match="不可直接运行"):
        workflow.start_step(project.id, "rewrite", {})  # type: ignore[arg-type]


def test_old_project_with_rewrite_step_still_loads(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    path = workflow.repository.project_file(project.id)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["steps"]["rewrite"] = {"status": "completed", "input": {}, "output": {"items": []}, "error": None, "confirmed_at": None, "updated_at": project.updated_at}
    data["jobs"].append({"id": "rewrite-job", "step": "rewrite", "status": "completed", "error": None, "total_count": 1, "completed_count": 1, "failed_count": 0, "skipped_count": 0, "current_item": None, "message": None, "created_at": project.created_at, "updated_at": project.updated_at})
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    loaded = workflow.repository.load_project(project.id)

    assert "rewrite" not in loaded.steps
    assert all(job.step != "rewrite" for job in loaded.jobs)


def test_intake_job_writes_canonical_output_file(tmp_path: Path, monkeypatch):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    workflow.repository.update_step(project.id, "materials", status="completed", confirmed=True)
    job_id = workflow.start_step(project.id, "intake", {})
    monkeypatch.setattr(
        workflow,
        "_run_step",
        lambda *args, **kwargs: {
            "project_intake_table": [
                {"field": "目标行业", "value": "高端厨电", "source": "资料", "confidence": "高", "status": "可直接使用"}
            ]
        },
    )

    workflow.run_step_job(project.id, job_id, "intake", {})

    saved = workflow.repository.load_project(project.id)
    assert saved.steps["intake"].output["step"] == "project_intake"
    assert len(saved.steps["intake"].output["project_intake_table"]) == 13
    output_file = next(workflow.repository.outputs_dir(project.id).rglob("01-project-intake.md"))
    text = output_file.read_text(encoding="utf-8")
    assert '"step": "project_intake"' in text
    assert '"id": "target_industry"' in text


def test_update_intake_value_rewrites_project_and_markdown(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    output = normalize_planning_output(
        "intake",
        {"project_intake_table": [{"id": "target_industry", "field": "目标行业", "value": "旧行业", "source": "资料", "confidence": "高"}]},
        {},
    )
    workflow.repository.update_step(project.id, "intake", status="completed", output=output)
    workflow.repository.write_output(project, "01-project-intake.md", result_to_markdown("intake", output))

    workflow.update_item(project.id, "intake", "target_industry", {"value": "新行业"})

    saved = workflow.repository.load_project(project.id)
    row = saved.steps["intake"].output["project_intake_table"][0]
    assert row["value"] == "新行业"
    assert row["status"] == "已人工修改"
    output_file = next(workflow.repository.outputs_dir(project.id).rglob("01-project-intake.md"))
    text = output_file.read_text(encoding="utf-8")
    assert "新行业" in text
    assert "旧行业" not in text


def test_confirm_intake_row_persists_status(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    output = normalize_planning_output(
        "intake",
        {"project_intake_table": [{"id": "target_category", "field": "目标品类", "value": "品类", "status": "需确认"}]},
        {},
    )
    workflow.repository.update_step(project.id, "intake", status="completed", output=output)

    workflow.update_item(project.id, "intake", "target_category", {"status": "已确认"})

    saved = workflow.repository.load_project(project.id)
    assert saved.steps["intake"].output["project_intake_table"][1]["status"] == "已确认"


def test_update_intake_rejects_unknown_row_or_fields(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    output = normalize_planning_output(
        "intake",
        {"project_intake_table": [{"id": "target_industry", "field": "目标行业", "value": "行业"}]},
        {},
    )
    workflow.repository.update_step(project.id, "intake", status="completed", output=output)

    with pytest.raises(WorkflowError, match="只支持修改推断值"):
        workflow.update_item(project.id, "intake", "target_industry", {"source": "人工"})
    with pytest.raises(WorkflowError, match="未找到项目信息字段"):
        workflow.update_item(project.id, "intake", "missing", {"value": "新值"})


def test_blocked_agent_result_is_not_marked_completed(tmp_path: Path, monkeypatch):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    workflow.repository.update_step(project.id, "materials", status="completed", confirmed=True)
    workflow.repository.update_step(project.id, "intake", status="completed", confirmed=True)
    workflow.repository.update_step(project.id, "matrix", status="completed", output={"items": [{"id": "plan", "keyword": "A"}]})
    workflow.confirm_breakthrough_keywords(project.id, ["A"])
    job_id = workflow.start_step(project.id, "breakthrough", {})
    monkeypatch.setattr(
        workflow,
        "_run_step",
        lambda *args, **kwargs: {
            "status": "blocked_need_keyword_confirmation",
            "reason": "请先确认关键词列表。",
            "candidate_keywords_for_confirmation": [{"关键词": "高端厨电"}],
        },
    )

    workflow.run_step_job(project.id, job_id, "breakthrough", {})

    saved = workflow.repository.load_project(project.id)
    job = saved.jobs[0]
    assert saved.steps["breakthrough"].status == "failed"
    assert saved.steps["breakthrough"].output["candidate_keywords_for_confirmation"]
    assert "确认关键词" in (saved.steps["breakthrough"].error or "")
    assert job.status == "failed"
    assert job.failed_count == 1
    assert "确认关键词" in (job.error or "")


def test_loading_legacy_blocked_result_normalizes_status(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    raw = project.model_dump()
    raw["steps"]["breakthrough"]["status"] = "completed"
    raw["steps"]["breakthrough"]["output"] = {
        "status": "blocked_need_keyword_confirmation",
        "reason": "请先确认关键词列表。",
    }
    raw["jobs"] = [
        {
            "id": "legacy-job",
            "step": "breakthrough",
            "status": "completed",
            "error": None,
            "total_count": 1,
            "completed_count": 1,
            "failed_count": 0,
            "skipped_count": 0,
            "current_item": None,
            "message": "步骤完成",
            "created_at": raw["created_at"],
            "updated_at": raw["updated_at"],
        }
    ]
    workflow.repository.project_file(project.id).write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

    raw = json.loads(workflow.repository.project_file(project.id).read_text(encoding="utf-8"))
    assert raw["steps"]["breakthrough"]["status"] == "completed"

    saved = workflow.repository.load_project(project.id)

    assert saved.steps["breakthrough"].status == "failed"
    assert "确认关键词" in (saved.steps["breakthrough"].error or "")
    assert saved.jobs[0].status == "failed"
    assert saved.jobs[0].completed_count == 0
    assert saved.jobs[0].failed_count == 1


def test_confirm_breakthrough_keywords_requires_non_empty_selection(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    workflow.repository.update_step(project.id, "matrix", status="completed", output={"items": [{"keyword": "A"}]})

    with pytest.raises(WorkflowError, match="至少选择"):
        workflow.confirm_breakthrough_keywords(project.id, [])


def test_confirm_breakthrough_keywords_persists_selection_and_confirms_matrix(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    workflow.repository.update_step(project.id, "matrix", status="completed", output={"items": [{"keyword": "A"}]})

    workflow.confirm_breakthrough_keywords(project.id, ["A", "A", "  B  ", ""])

    saved = workflow.repository.load_project(project.id)
    selection = saved.steps["matrix"].output["breakthrough_keyword_selection"]
    assert saved.steps["matrix"].status == "confirmed"
    assert selection["keywords"] == ["A", "B"]
    assert selection["source"] == "matrix"
    assert selection["confirmed_at"]


def test_confirm_breakthrough_keywords_replaces_previous_selection(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    workflow.repository.update_step(
        project.id,
        "matrix",
        status="completed",
        output={"breakthrough_keyword_selection": {"keywords": ["A"]}, "items": [{"keyword": "A"}, {"keyword": "B"}]},
    )

    workflow.confirm_breakthrough_keywords(project.id, ["B", "A", ""])

    saved = workflow.repository.load_project(project.id)
    selection = saved.steps["matrix"].output["breakthrough_keyword_selection"]
    assert selection["keywords"] == ["B", "A"]


def test_confirm_breakthrough_keywords_keeps_selection_separate_from_generated_scope(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    workflow.repository.update_step(
        project.id,
        "matrix",
        status="completed",
        output={"breakthrough_keyword_selection": {"keywords": ["A"]}, "items": [{"keyword": "A"}, {"keyword": "B"}, {"keyword": "C"}]},
    )
    workflow.repository.update_step(
        project.id,
        "breakthrough",
        status="completed",
        output={"step": "geo_keyword_breakthrough", "confirmed_keywords": ["B"], "items": breakthrough_rows("B")},
    )

    workflow.confirm_breakthrough_keywords(project.id, ["C"])

    saved = workflow.repository.load_project(project.id)
    selection = saved.steps["matrix"].output["breakthrough_keyword_selection"]
    assert selection["keywords"] == ["C"]


def test_breakthrough_requires_confirmed_keywords(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    workflow.repository.update_step(project.id, "materials", status="completed", confirmed=True)
    workflow.repository.update_step(project.id, "intake", status="completed", confirmed=True)
    workflow.repository.update_step(project.id, "matrix", status="completed", confirmed=True, output={"items": [{"keyword": "A"}]})

    with pytest.raises(WorkflowError, match="确认进入逐词击破"):
        workflow.start_step(project.id, "breakthrough", {})


def test_breakthrough_uses_saved_confirmed_keywords(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    workflow.repository.update_step(project.id, "materials", status="completed", confirmed=True)
    workflow.repository.update_step(project.id, "intake", status="completed", confirmed=True)
    workflow.repository.update_step(project.id, "matrix", status="completed", output={"items": [{"keyword": "A"}]})
    workflow.confirm_breakthrough_keywords(project.id, ["A"])

    workflow.start_step(project.id, "breakthrough", {})

    saved = workflow.repository.load_project(project.id)
    assert saved.steps["breakthrough"].input["confirmed_keywords"] == ["A"]


def test_breakthrough_incrementally_adds_new_keyword_without_overwriting(tmp_path: Path, monkeypatch):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    workflow.repository.update_step(project.id, "materials", status="completed", confirmed=True)
    workflow.repository.update_step(project.id, "intake", status="completed", confirmed=True)
    workflow.repository.update_step(
        project.id,
        "matrix",
        status="confirmed",
        output={"breakthrough_keyword_selection": {"keywords": ["A", "B"]}, "items": [{"keyword": "A"}, {"keyword": "B"}]},
    )
    workflow.repository.update_step(
        project.id,
        "breakthrough",
        status="completed",
        output={"step": "geo_keyword_breakthrough", "confirmed_keywords": ["A"], "items": breakthrough_rows("A")},
    )
    payload: dict[str, object] = {}
    job_id = workflow.start_step(project.id, "breakthrough", payload)

    assert payload["incremental"] is True
    assert payload["missing_breakthrough_types"] == {"B": MATRIX_ARTICLE_TYPES}
    monkeypatch.setattr(workflow, "_run_step", lambda *args, **kwargs: {"items": breakthrough_rows("B"), "confirmed_keywords": ["B"]})

    workflow.run_step_job(project.id, job_id, "breakthrough", payload)

    saved = workflow.repository.load_project(project.id)
    items = saved.steps["breakthrough"].output["items"]
    assert saved.steps["breakthrough"].status == "completed"
    assert len(items) == 12
    assert len([item for item in items if item["keyword"] == "A"]) == 6
    assert len([item for item in items if item["keyword"] == "B"]) == 6
    assert saved.steps["breakthrough"].output["confirmed_keywords"] == ["A", "B"]


def test_breakthrough_start_merges_matrix_and_existing_generated_keywords(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    workflow.repository.update_step(project.id, "materials", status="completed", confirmed=True)
    workflow.repository.update_step(project.id, "intake", status="completed", confirmed=True)
    workflow.repository.update_step(
        project.id,
        "matrix",
        status="confirmed",
        output={"breakthrough_keyword_selection": {"keywords": ["A"]}, "items": [{"keyword": "A"}, {"keyword": "B"}]},
    )
    workflow.repository.update_step(
        project.id,
        "breakthrough",
        status="completed",
        output={"step": "geo_keyword_breakthrough", "confirmed_keywords": ["B"], "items": breakthrough_rows("B")},
    )
    payload: dict[str, object] = {}

    workflow.start_step(project.id, "breakthrough", payload)

    assert payload["confirmed_keywords"] == ["B", "A"]
    assert payload["missing_breakthrough_types"] == {"A": MATRIX_ARTICLE_TYPES}


def test_breakthrough_force_uses_current_selection_without_old_generated_keywords(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    workflow.repository.update_step(project.id, "materials", status="completed", confirmed=True)
    workflow.repository.update_step(project.id, "intake", status="completed", confirmed=True)
    workflow.repository.update_step(
        project.id,
        "matrix",
        status="confirmed",
        output={"breakthrough_keyword_selection": {"keywords": ["A"]}, "items": [{"keyword": "A"}, {"keyword": "B"}]},
    )
    workflow.repository.update_step(
        project.id,
        "breakthrough",
        status="completed",
        output={"step": "geo_keyword_breakthrough", "confirmed_keywords": ["B"], "items": breakthrough_rows("B")},
    )
    payload: dict[str, object] = {"force": True}

    workflow.start_step(project.id, "breakthrough", payload)

    assert payload["confirmed_keywords"] == ["A"]
    assert "missing_breakthrough_types" not in payload


def test_breakthrough_incrementally_fills_missing_types_only(tmp_path: Path, monkeypatch):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    workflow.repository.update_step(project.id, "materials", status="completed", confirmed=True)
    workflow.repository.update_step(project.id, "intake", status="completed", confirmed=True)
    workflow.repository.update_step(
        project.id,
        "matrix",
        status="confirmed",
        output={"breakthrough_keyword_selection": {"keywords": ["A"]}, "items": [{"keyword": "A"}]},
    )
    existing_types = MATRIX_ARTICLE_TYPES[:4]
    missing_types = MATRIX_ARTICLE_TYPES[4:]
    workflow.repository.update_step(
        project.id,
        "breakthrough",
        status="completed",
        output={"step": "geo_keyword_breakthrough", "confirmed_keywords": ["A"], "items": breakthrough_rows("A", existing_types)},
    )
    payload: dict[str, object] = {}
    job_id = workflow.start_step(project.id, "breakthrough", payload)

    assert payload["missing_breakthrough_types"] == {"A": missing_types}
    monkeypatch.setattr(workflow, "_run_step", lambda *args, **kwargs: {"items": breakthrough_rows("A", missing_types), "confirmed_keywords": ["A"]})

    workflow.run_step_job(project.id, job_id, "breakthrough", payload)

    saved = workflow.repository.load_project(project.id)
    items = saved.steps["breakthrough"].output["items"]
    assert len(items) == 6
    assert [item["type"] for item in items] == MATRIX_ARTICLE_TYPES


def test_breakthrough_incremental_skips_when_all_keywords_complete(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    workflow.repository.update_step(project.id, "materials", status="completed", confirmed=True)
    workflow.repository.update_step(project.id, "intake", status="completed", confirmed=True)
    workflow.repository.update_step(
        project.id,
        "matrix",
        status="confirmed",
        output={"breakthrough_keyword_selection": {"keywords": ["A"]}, "items": [{"keyword": "A"}]},
    )
    workflow.repository.update_step(
        project.id,
        "breakthrough",
        status="completed",
        output={"step": "geo_keyword_breakthrough", "confirmed_keywords": ["A"], "items": breakthrough_rows("A")},
    )

    with pytest.raises(WorkflowError, match="无需重复生成"):
        workflow.start_step(project.id, "breakthrough", {})


def test_breakthrough_prompt_includes_confirmed_keywords_scope():
    blocks = build_selection_prompt_blocks("breakthrough", {"confirmed_keywords": ["A", "B"]})

    assert "已确认进入逐词击破的关键词" in blocks[0]
    assert "只针对上方 confirmed_keywords" in blocks[1]
    assert "items 数组" in blocks[1]


def test_planning_prompts_include_canonical_templates():
    matrix_prompt = planning_output_requirements("matrix", {})
    breakthrough_prompt = planning_output_requirements("breakthrough", {"confirmed_keywords": ["A"]})

    assert '"step": "geo_content_matrix"' in matrix_prompt
    assert "source_id" in matrix_prompt
    assert "不要把字段名翻译成中文" in matrix_prompt
    assert "geo-content-matrix-planner" in matrix_prompt
    assert "首轮文章清单" in matrix_prompt
    assert "intent_groups=['id', 'name', 'keywords', 'user_question', 'user_stage', 'recommendation_logic', 'article_types']" in matrix_prompt
    assert "evidence_gaps=['keyword_or_intent_group', 'required_evidence', 'current_evidence', 'missing_evidence', 'impact', 'suggested_supplement']" in matrix_prompt
    assert "支柱标准文 / 榜单推荐文 / 横评对比文 / 场景选购文 / 产品证据文 / FAQ问答文" in matrix_prompt
    assert "不得新增第七类文章类型" in matrix_prompt
    assert "扩展类型" not in matrix_prompt
    assert "不得超过 10" not in matrix_prompt
    assert '"step": "geo_keyword_breakthrough"' in breakthrough_prompt
    assert "支柱标准文 / 榜单推荐文 / 横评对比文 / 场景选购文 / 产品证据文 / FAQ问答文" in breakthrough_prompt
    assert '"A"' in breakthrough_prompt


def test_matrix_output_is_normalized_from_legacy_fields():
    english = normalize_planning_output(
        "matrix",
        {
            "project": {"target_brand": "品牌"},
            "关键词总体判断": {"核心用户意图": ["品牌推荐"], "目标推荐认知": "证据完整、优先推荐"},
            "关键词意图分组": [{"intent_group": "推荐决策类", "user_real_question": "用户问什么牌子好", "main_article_types": ["榜单推荐文"]}],
            "文章类型池与行业扩展判断": [{"type": "支柱标准文", "usage": "必选", "reason": "定义标准", "covered_keywords_or_intent_groups": ["推荐决策类"]}],
            "共享支撑文规划": [{"title": "共享标题", "supported_keywords": ["A"], "type": "支柱标准文", "role": "支撑多个词", "channels": ["知乎"]}],
            "统一推荐口径": [{"intent_group": "推荐决策类", "language": "优先关注品牌", "proof_to_repeat": "证据A", "wrong_expressions_to_avoid": "不要写第一"}],
            "证据缺口": [{"keyword_or_intent_group": "推荐决策类", "required_evidence": "第三方报告", "missing_evidence": "报告原文"}],
            "发布渠道规划": [{"article_type": "支柱标准文", "recommended_channels": ["知乎"], "channel_role": "承接搜索", "publishing_notes": "标题含关键词"}],
            "执行排期": [{"stage": "第1阶段", "period": "第1周", "key_tasks": ["发布标准文"], "article_types": ["支柱标准文"], "goal": "建立标准"}],
            "优先级排序": [{"priority": 1, "title": "优先标题", "keyword": "A", "type": "支柱标准文", "reason": "先建标准"}],
            "后续Brief衔接要求": [{"field": "target_keyword", "requirement": "使用 items.keyword"}],
            "first_round_article_list": matrix_required_rows("A"),
        },
        {},
    )
    chinese = normalize_planning_output(
        "matrix",
        {
            "六_首轮文章清单": [
                {
                    "关键词": "B",
                    "文章类型": article_type,
                    "建议标题": f"B{article_type}",
                    "主要作用": "承接内容矩阵",
                    "推荐渠道": ["小红书"],
                    "必备证据": ["证据1"],
                    "推荐强度": "强推荐",
                }
                for article_type in MATRIX_ARTICLE_TYPES
            ]
        },
        {},
    )

    assert english["step"] == "geo_content_matrix"
    assert english["schema_version"] == "1.0"
    assert english["items"][0]["keyword"] == "A"
    assert english["items"][0]["intent_group"] == "推荐决策类"
    assert english["items"][0]["source_step"] == "matrix"
    assert english["items"][0]["channels"] == ["知乎"]
    assert english["keyword_overview"]["target_recommendation_cognition"] == "证据完整、优先推荐"
    assert english["article_type_pool"][0]["type"] == "支柱标准文"
    assert set(english["intent_groups"][0]) == {"id", "name", "keywords", "user_question", "user_stage", "recommendation_logic", "article_types"}
    assert english["intent_groups"][0]["user_question"] == "用户问什么牌子好"
    assert set(english["article_type_pool"][0]) == {"type", "usage", "reason", "covered_keywords_or_intent_groups", "recommendation_strength", "count"}
    assert english["article_type_pool"][0]["reason"] == "定义标准"
    assert set(english["shared_supporting_articles"][0]) == {"title", "supported_keywords", "type", "role", "channels"}
    assert set(english["unified_recommendation_language"][0]) == {"intent_group", "language", "proof_to_repeat", "wrong_expressions_to_avoid"}
    assert set(english["evidence_gaps"][0]) == {"keyword_or_intent_group", "required_evidence", "current_evidence", "missing_evidence", "impact", "suggested_supplement"}
    assert set(english["publishing_plan"][0]) == {"article_type", "recommended_channels", "channel_role", "publishing_notes"}
    assert set(english["schedule"][0]) == {"stage", "period", "key_tasks", "article_types", "goal"}
    assert set(english["priority_plan"][0]) == {"priority", "title", "keyword", "type", "reason"}
    assert set(english["brief_requirements"][0]) == {"field", "requirement"}
    assert english["items"][0]["recommendation_strength"] == "中等推荐"
    assert english["items"][0]["evidence_chain"] == "用户问题 → 判断标准 → 目标对象证据 → 用户价值 → 推荐结论"
    assert chinese["items"][0]["keyword"] == "B"
    assert chinese["items"][3]["type"] == "场景选购文"
    assert chinese["items"][0]["required_evidence"] == ["证据1"]


def test_matrix_output_missing_required_article_types_is_rejected():
    with pytest.raises(WorkflowError, match="缺少必选文章板块"):
        normalize_planning_output(
            "matrix",
            {"items": [{"keyword": "A", "type": "支柱标准文", "title": "A标准文"}]},
            {},
        )


def test_matrix_output_filters_non_core_article_types():
    output = normalize_planning_output(
        "matrix",
        {
            "items": [
                *matrix_required_rows("A"),
                {
                    "keyword": "A",
                    "type": "价格预算决策文",
                    "title": "A价格预算标题",
                    "role": "不允许进入矩阵",
                },
            ],
            "article_type_pool": [
                *[{"type": article_type, "reason": f"{article_type}原因"} for article_type in MATRIX_ARTICLE_TYPES],
                {"type": "价格预算决策文", "reason": "不允许进入文章类型池"},
            ],
            "intent_groups": [{"name": "推荐决策类", "article_types": ["支柱标准文", "价格预算决策文"]}],
            "keyword_planning": [{"keyword": "A", "main_article_types": ["榜单推荐文", "价格预算决策文"]}],
            "shared_supporting_articles": [{"title": "预算支撑文", "type": "价格预算决策文"}],
            "publishing_plan": [{"article_type": "价格预算决策文", "recommended_channels": ["知乎"]}],
            "schedule": [
                {"stage": "第1周", "key_tasks": ["发布支柱标准文", "发布价格预算决策文"], "article_types": ["支柱标准文", "价格预算决策文"]},
                {"stage": "第2周", "article_types": ["价格预算决策文"]},
            ],
            "priority_plan": [{"priority": 1, "title": "预算优先", "type": "价格预算决策文"}],
        },
        {},
    )

    assert "价格预算决策文" not in {item["type"] for item in output["items"]}
    assert [item["type"] for item in output["article_type_pool"]] == MATRIX_ARTICLE_TYPES
    assert output["intent_groups"][0]["article_types"] == ["支柱标准文"]
    assert output["keyword_planning"][0]["main_article_types"] == ["榜单推荐文"]
    assert output["shared_supporting_articles"] == []
    assert output["publishing_plan"] == []
    assert output["schedule"] == [{"stage": "第1周", "period": "", "key_tasks": ["发布支柱标准文"], "article_types": ["支柱标准文"], "goal": ""}]
    assert output["priority_plan"] == []


def test_matrix_output_normalizes_user_article_type_aliases():
    rows = matrix_required_rows("A")
    rows[0]["article_type"] = "支柱标准文章"
    rows[-1]["article_type"] = "FAQ问答短文"

    output = normalize_planning_output("matrix", {"items": rows}, {})

    assert output["items"][0]["type"] == "支柱标准文"
    assert output["items"][-1]["type"] == "FAQ问答文"


def test_matrix_output_rejects_when_filtering_removes_required_type():
    rows = matrix_required_rows("A")[:-1]
    rows.append({"keyword": "A", "type": "价格预算决策文", "title": "A价格预算标题"})

    with pytest.raises(WorkflowError, match="缺少必选文章板块"):
        normalize_planning_output("matrix", {"items": rows}, {})


def test_breakthrough_output_is_normalized_to_flat_fixed_six_items():
    article_types = ["支柱标准文", "榜单推荐文", "横评对比文", "场景选购文", "产品证据文", "FAQ问答文"]
    output = normalize_planning_output(
        "breakthrough",
        {
            "plans": [
                {
                    "keyword": "A",
                    "articles": [
                        {"article_type": article_type, "suggested_title": f"A{article_type}", "main_role": f"{article_type}作用"}
                        for article_type in article_types
                    ],
                }
            ]
        },
        {"confirmed_keywords": ["A"]},
    )

    assert output["step"] == "geo_keyword_breakthrough"
    assert output["confirmed_keywords"] == ["A"]
    assert len(output["items"]) == 6
    assert [item["type"] for item in output["items"]] == article_types
    assert all(item["source_step"] == "breakthrough" for item in output["items"])
    assert all(item["source_id"] for item in output["items"])


def test_breakthrough_output_missing_fixed_types_is_rejected():
    with pytest.raises(WorkflowError, match="缺少"):
        normalize_planning_output(
            "breakthrough",
            {"items": [{"keyword": "A", "type": "支柱标准文", "title": "A标准文"}]},
            {"confirmed_keywords": ["A"]},
        )


def test_cannot_start_same_step_while_running(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    workflow.repository.update_step(project.id, "materials", status="completed", confirmed=True)
    workflow.start_step(project.id, "intake", {})

    with pytest.raises(WorkflowError, match="正在运行"):
        workflow.start_step(project.id, "intake", {})


def test_cannot_rerun_completed_step_with_output_without_force(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    workflow.repository.update_step(project.id, "materials", status="completed", confirmed=True)
    workflow.repository.update_step(project.id, "intake", status="completed", output={"items": [{"field": "目标"}]})

    with pytest.raises(WorkflowError, match="已经生成"):
        workflow.start_step(project.id, "intake", {})


def test_force_rerun_clears_existing_output(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    workflow.repository.update_step(project.id, "materials", status="completed", confirmed=True)
    workflow.repository.update_step(project.id, "intake", status="confirmed", output=intake_output_with_keywords("新矩阵推荐"))
    workflow.repository.update_step(project.id, "matrix", status="completed", output={"items": [{"id": "old"}]})

    workflow.start_step(project.id, "matrix", {"force": True})

    saved = workflow.repository.load_project(project.id)
    assert saved.steps["matrix"].status == "running"
    assert saved.steps["matrix"].output == {}


def test_force_rerun_success_overwrites_output(tmp_path: Path, monkeypatch):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    workflow.repository.update_step(project.id, "materials", status="completed", confirmed=True)
    workflow.repository.update_step(project.id, "intake", status="confirmed", output=intake_output_with_keywords("新矩阵推荐"))
    workflow.repository.update_step(project.id, "matrix", status="completed", output={"items": [{"id": "old"}]})
    job_id = workflow.start_step(project.id, "matrix", {"force": True})

    monkeypatch.setattr(workflow, "_run_step", lambda *args, **kwargs: {"items": matrix_required_rows("新矩阵")})

    workflow.run_step_job(project.id, job_id, "matrix", {"force": True})

    saved = workflow.repository.load_project(project.id)
    assert saved.steps["matrix"].status == "completed"
    assert saved.steps["matrix"].output["step"] == "geo_content_matrix"
    assert saved.steps["matrix"].output["items"][0]["source_id"]
    output_file = next(workflow.repository.outputs_dir(project.id).rglob("02-content-matrix.md"))
    assert '"step": "geo_content_matrix"' in output_file.read_text(encoding="utf-8")


def test_force_rerun_failure_keeps_output_empty(tmp_path: Path, monkeypatch):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    workflow.repository.update_step(project.id, "materials", status="completed", confirmed=True)
    workflow.repository.update_step(project.id, "intake", status="confirmed", output={"items": [{"field": "目标"}]})
    workflow.repository.update_step(project.id, "matrix", status="completed", output={"items": [{"id": "old"}]})
    job_id = workflow.start_step(project.id, "matrix", {"force": True})

    def fail(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(workflow, "_run_step", fail)

    workflow.run_step_job(project.id, job_id, "matrix", {"force": True})

    saved = workflow.repository.load_project(project.id)
    assert saved.steps["matrix"].status == "failed"
    assert saved.steps["matrix"].output == {}
    assert saved.jobs[0].status == "failed"


def confirm_through_breakthrough(workflow: AgentWorkflow, project_id: str) -> None:
    for step in ["materials", "intake", "matrix", "breakthrough"]:
        workflow.repository.update_step(project_id, step, status="completed", confirmed=True)


def test_brief_requires_selected_sources(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    confirm_through_breakthrough(workflow, project.id)

    with pytest.raises(WorkflowError, match="选择要生成 Brief"):
        workflow.start_step(project.id, "brief", {})


def test_matrix_source_can_start_brief_without_breakthrough_confirmation(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    workflow.repository.update_step(project.id, "materials", status="completed", confirmed=True)
    workflow.repository.update_step(project.id, "intake", status="completed", confirmed=True)
    workflow.repository.update_step(
        project.id,
        "matrix",
        status="completed",
        output={"items": [{"source_id": "source-a", "source_step": "matrix", "title": "标题 A"}]},
    )
    payload = {
        "selected_sources": [
            {"source_id": "source-a", "source_step": "matrix", "keyword": "A", "type": "类型", "title": "标题 A"}
        ]
    }

    job_id = workflow.start_step(project.id, "brief", payload)

    saved = workflow.repository.load_project(project.id)
    assert job_id
    assert saved.steps["breakthrough"].status == "pending"
    assert saved.steps["brief"].status == "running"
    assert saved.steps["brief"].input["selected_sources"][0]["source_step"] == "matrix"


def test_brief_matrix_source_requires_matrix_ready(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    payload = {
        "selected_sources": [
            {"source_id": "source-a", "source_step": "matrix", "keyword": "A", "type": "类型", "title": "标题 A"}
        ]
    }

    with pytest.raises(WorkflowError, match="内容矩阵"):
        workflow.start_step(project.id, "brief", payload)


def test_brief_breakthrough_source_requires_breakthrough_ready(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    workflow.repository.update_step(project.id, "matrix", status="completed", output={"items": [{"keyword": "A"}]})
    payload = {
        "selected_sources": [
            {
                "source_id": "source-b",
                "source_step": "breakthrough",
                "keyword": "B",
                "type": "类型",
                "title": "标题 B",
            }
        ]
    }

    with pytest.raises(WorkflowError, match="逐词击破"):
        workflow.start_step(project.id, "brief", payload)


def test_brief_mixed_sources_require_breakthrough_when_selected(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    workflow.repository.update_step(project.id, "matrix", status="completed", output={"items": [{"keyword": "A"}]})
    payload = {
        "selected_sources": [
            {"source_id": "source-a", "source_step": "matrix", "keyword": "A", "type": "类型", "title": "标题 A"},
            {
                "source_id": "source-b",
                "source_step": "breakthrough",
                "keyword": "B",
                "type": "类型",
                "title": "标题 B",
            },
        ]
    }

    with pytest.raises(WorkflowError, match="逐词击破"):
        workflow.start_step(project.id, "brief", payload)


def test_brief_incremental_generation_skips_existing_and_writes_file(tmp_path: Path, monkeypatch):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    confirm_through_breakthrough(workflow, project.id)
    workflow.repository.update_step(
        project.id,
        "brief",
        status="completed",
        output={"items": [{"id": "brief-source-a", "source_id": "source-a", "title": "old", "markdown": "old brief"}]},
    )
    payload = {
        "selected_sources": [
            {"source_id": "source-a", "source_step": "matrix", "keyword": "A", "type": "类型", "title": "标题 A"},
            {"source_id": "source-b", "source_step": "breakthrough", "keyword": "B", "type": "类型", "title": "标题 B"},
        ]
    }
    job_id = workflow.start_step(project.id, "brief", payload)

    assert [source["source_id"] for source in payload["selected_sources"]] == ["source-b"]

    monkeypatch.setattr(
        workflow,
        "_run_step",
        lambda *args, **kwargs: {"items": [{"source_id": "source-b", "markdown": "# Brief B"}]},
    )

    workflow.run_step_job(project.id, job_id, "brief", payload)

    saved = workflow.repository.load_project(project.id)
    items = saved.steps["brief"].output["items"]
    assert [item["source_id"] for item in items] == ["source-a", "source-b"]
    assert saved.steps["brief"].status == "completed"
    assert (workflow.repository.outputs_dir(project.id) / "测试项目").exists()
    assert list(workflow.repository.outputs_dir(project.id).rglob("briefs/source-b-brief.md"))


def test_brief_all_selected_sources_existing_is_rejected(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    confirm_through_breakthrough(workflow, project.id)
    workflow.repository.update_step(
        project.id,
        "brief",
        status="completed",
        output={"items": [{"id": "brief-source-a", "source_id": "source-a", "markdown": "old brief"}]},
    )

    with pytest.raises(WorkflowError, match="均已有 Brief"):
        workflow.start_step(project.id, "brief", {"selected_sources": [{"source_id": "source-a"}]})


def test_failed_brief_source_can_be_generated_again(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    confirm_through_breakthrough(workflow, project.id)
    workflow.repository.update_step(
        project.id,
        "brief",
        status="completed",
        output={"items": [{"id": "brief-source-a", "source_id": "source-a", "status": "failed", "error": "old failure"}]},
    )
    payload = {"selected_sources": [{"source_id": "source-a", "source_step": "matrix", "title": "标题 A"}]}

    workflow.start_step(project.id, "brief", payload)

    assert [source["source_id"] for source in payload["selected_sources"]] == ["source-a"]
    saved = workflow.repository.load_project(project.id)
    item = saved.steps["brief"].output["items"][0]
    assert item["source_id"] == "source-a"
    assert item["status"] == "running"
    assert item["error"] is None


def test_force_brief_rerun_marks_only_selected_item_running(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    confirm_through_breakthrough(workflow, project.id)
    workflow.repository.update_step(
        project.id,
        "brief",
        status="completed",
        output={
            "items": [
                {"id": "brief-source-a", "source_id": "source-a", "title": "A", "markdown": "old a"},
                {"id": "brief-source-b", "source_id": "source-b", "title": "B", "markdown": "old b"},
            ]
        },
    )

    workflow.start_step(
        project.id,
        "brief",
        {"force": True, "selected_sources": [{"source_id": "source-a", "title": "A"}]},
    )

    saved = workflow.repository.load_project(project.id)
    items = {item["source_id"]: item for item in saved.steps["brief"].output["items"]}
    assert items["source-a"]["status"] == "running"
    assert items["source-a"]["markdown"] == ""
    assert items["source-b"]["markdown"] == "old b"


def test_brief_item_failure_does_not_block_other_selected_items(tmp_path: Path, monkeypatch):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    confirm_through_breakthrough(workflow, project.id)
    payload = {
        "selected_sources": [
            {"source_id": "source-a", "source_step": "matrix", "keyword": "A", "type": "类型", "title": "标题 A"},
            {"source_id": "source-b", "source_step": "matrix", "keyword": "B", "type": "类型", "title": "标题 B"},
        ]
    }
    job_id = workflow.start_step(project.id, "brief", payload)

    def fake_run(project_id, step, item_payload):
        selected = item_payload["selected_sources"][0]
        if selected["source_id"] == "source-a":
            raise RuntimeError("source a failed")
        return {"items": [{"source_id": selected["source_id"], "markdown": "# ok"}]}

    monkeypatch.setattr(workflow, "_run_step", fake_run)

    workflow.run_step_job(project.id, job_id, "brief", payload)

    saved = workflow.repository.load_project(project.id)
    items = {item["source_id"]: item for item in saved.steps["brief"].output["items"]}
    assert saved.steps["brief"].status == "completed"
    assert items["source-a"]["status"] == "failed"
    assert items["source-b"]["status"] == "completed"
    assert saved.jobs[0].status == "failed"
    assert saved.jobs[0].failed_count == 1


def test_parallel_brief_generation_merges_out_of_order_results(tmp_path: Path, monkeypatch):
    workflow = make_workflow(tmp_path, batch_generation_concurrency=3)
    project = workflow.repository.create_project("测试项目")
    confirm_through_breakthrough(workflow, project.id)
    payload = {
        "selected_sources": [
            {"source_id": "source-a", "source_step": "matrix", "keyword": "A", "type": "类型", "title": "标题 A"},
            {"source_id": "source-b", "source_step": "matrix", "keyword": "B", "type": "类型", "title": "标题 B"},
            {"source_id": "source-c", "source_step": "matrix", "keyword": "C", "type": "类型", "title": "标题 C"},
        ]
    }
    job_id = workflow.start_step(project.id, "brief", payload)

    def fake_run(project_id, step, item_payload):
        selected = item_payload["selected_sources"][0]
        if selected["source_id"] == "source-a":
            time.sleep(0.03)
        return {"items": [{"source_id": selected["source_id"], "markdown": f"# {selected['title']}"}]}

    monkeypatch.setattr(workflow, "_run_step", fake_run)

    workflow.run_step_job(project.id, job_id, "brief", payload)

    saved = workflow.repository.load_project(project.id)
    items = {item["source_id"]: item for item in saved.steps["brief"].output["items"]}
    assert set(items) == {"source-a", "source-b", "source-c"}
    assert all(item["status"] == "completed" for item in items.values())
    assert saved.jobs[0].status == "completed"
    assert saved.jobs[0].completed_count == 3
    assert list(workflow.repository.outputs_dir(project.id).rglob("briefs/source-a-brief.md"))
    assert list(workflow.repository.outputs_dir(project.id).rglob("briefs/source-b-brief.md"))
    assert list(workflow.repository.outputs_dir(project.id).rglob("briefs/source-c-brief.md"))


def test_batch_generation_concurrency_one_runs_all_items(tmp_path: Path, monkeypatch):
    workflow = make_workflow(tmp_path, batch_generation_concurrency=1)
    project = workflow.repository.create_project("测试项目")
    confirm_through_breakthrough(workflow, project.id)
    payload = {
        "selected_sources": [
            {"source_id": "source-a", "source_step": "matrix", "keyword": "A", "type": "类型", "title": "标题 A"},
            {"source_id": "source-b", "source_step": "matrix", "keyword": "B", "type": "类型", "title": "标题 B"},
        ]
    }
    job_id = workflow.start_step(project.id, "brief", payload)
    calls: list[str] = []

    def fake_run(project_id, step, item_payload):
        selected = item_payload["selected_sources"][0]
        calls.append(selected["source_id"])
        return {"items": [{"source_id": selected["source_id"], "markdown": "# ok"}]}

    monkeypatch.setattr(workflow, "_run_step", fake_run)

    workflow.run_step_job(project.id, job_id, "brief", payload)

    saved = workflow.repository.load_project(project.id)
    assert calls == ["source-a", "source-b"]
    assert saved.jobs[0].completed_count == 2
    assert {item["source_id"] for item in saved.steps["brief"].output["items"]} == {"source-a", "source-b"}


def test_article_requires_selected_briefs(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    confirm_through_breakthrough(workflow, project.id)
    workflow.repository.update_step(project.id, "brief", status="completed", confirmed=True, output={"items": []})

    with pytest.raises(WorkflowError, match="选择要生成正文"):
        workflow.start_step(project.id, "article", {})


def test_article_can_start_from_generated_brief_without_confirming_brief_step(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    workflow.repository.update_step(
        project.id,
        "brief",
        status="completed",
        confirmed=False,
        output={"items": [{"id": "brief-a", "source_id": "source-a", "markdown": "# Brief A", "status": "completed"}]},
    )

    payload = {"selected_briefs": [{"id": "brief-a", "source_id": "source-a", "markdown": "# Brief A", "status": "completed"}]}
    job_id = workflow.start_step(project.id, "article", payload)

    saved = workflow.repository.load_project(project.id)
    assert job_id
    assert saved.steps["article"].status == "running"
    assert saved.steps["brief"].status == "completed"


def test_article_rejects_unfinished_selected_brief(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")

    with pytest.raises(WorkflowError, match="尚未生成完成"):
        workflow.start_step(
            project.id,
            "article",
            {"selected_briefs": [{"id": "brief-a", "source_id": "source-a", "status": "running"}]},
        )


def test_article_incremental_generation_skips_existing_and_writes_file(tmp_path: Path, monkeypatch):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    confirm_through_breakthrough(workflow, project.id)
    workflow.repository.update_step(project.id, "brief", status="completed", confirmed=True, output={"items": []})
    workflow.repository.update_step(
        project.id,
        "article",
        status="completed",
        output={"items": [{"id": "article-brief-a", "brief_id": "brief-a", "title": "old", "markdown": "old article"}]},
    )
    payload = {
        "selected_briefs": [
            {"id": "brief-a", "source_id": "source-a", "keyword": "A", "type": "类型", "title": "标题 A", "markdown": "# Brief A"},
            {"id": "brief-b", "source_id": "source-b", "keyword": "B", "type": "类型", "title": "标题 B", "markdown": "# Brief B"},
        ]
    }
    job_id = workflow.start_step(project.id, "article", payload)

    assert payload["selected_briefs"] == [{"id": "brief-b", "source_id": "source-b", "keyword": "B", "type": "类型", "title": "标题 B", "markdown": "# Brief B"}]

    monkeypatch.setattr(
        workflow,
        "_run_step",
        lambda *args, **kwargs: {"items": [{"brief_id": "brief-b", "markdown": "# Article B"}]},
    )

    workflow.run_step_job(project.id, job_id, "article", payload)

    saved = workflow.repository.load_project(project.id)
    items = saved.steps["article"].output["items"]
    assert [item["brief_id"] for item in items] == ["brief-a", "brief-b"]
    assert saved.steps["article"].status == "completed"
    assert list(workflow.repository.outputs_dir(project.id).rglob("articles/brief-b.md"))


def test_parallel_article_generation_merges_all_items_and_writes_files(tmp_path: Path, monkeypatch):
    workflow = make_workflow(tmp_path, batch_generation_concurrency=3)
    project = workflow.repository.create_project("测试项目")
    confirm_through_breakthrough(workflow, project.id)
    workflow.repository.update_step(project.id, "brief", status="completed", confirmed=True, output={"items": []})
    payload = {
        "selected_briefs": [
            {"id": "brief-a", "source_id": "source-a", "keyword": "A", "type": "类型", "title": "标题 A", "markdown": "# Brief A", "status": "completed"},
            {"id": "brief-b", "source_id": "source-b", "keyword": "B", "type": "类型", "title": "标题 B", "markdown": "# Brief B", "status": "completed"},
            {"id": "brief-c", "source_id": "source-c", "keyword": "C", "type": "类型", "title": "标题 C", "markdown": "# Brief C", "status": "completed"},
        ]
    }
    job_id = workflow.start_step(project.id, "article", payload)

    def fake_run(project_id, step, item_payload):
        brief = item_payload["selected_briefs"][0]
        if brief["id"] == "brief-a":
            time.sleep(0.03)
        return {"items": [{"brief_id": brief["id"], "markdown": f"# {brief['title']}正文"}]}

    monkeypatch.setattr(workflow, "_run_step", fake_run)

    workflow.run_step_job(project.id, job_id, "article", payload)

    saved = workflow.repository.load_project(project.id)
    items = {item["brief_id"]: item for item in saved.steps["article"].output["items"]}
    assert set(items) == {"brief-a", "brief-b", "brief-c"}
    assert all(item["status"] == "completed" for item in items.values())
    assert saved.jobs[0].status == "completed"
    assert saved.jobs[0].completed_count == 3
    assert list(workflow.repository.outputs_dir(project.id).rglob("articles/brief-a.md"))
    assert list(workflow.repository.outputs_dir(project.id).rglob("articles/brief-b.md"))
    assert list(workflow.repository.outputs_dir(project.id).rglob("articles/brief-c.md"))


def test_article_existing_same_brief_revision_is_rejected(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    confirm_through_breakthrough(workflow, project.id)
    workflow.repository.update_step(project.id, "brief", status="completed", confirmed=True, output={"items": []})
    workflow.repository.update_step(
        project.id,
        "article",
        status="completed",
        output={"items": [{"id": "article-brief-a", "brief_id": "brief-a", "brief_revision": 2, "markdown": "old article"}]},
    )

    with pytest.raises(WorkflowError, match="均已有正文"):
        workflow.start_step(
            project.id,
            "article",
            {"selected_briefs": [{"id": "brief-a", "source_id": "source-a", "revision": 2, "markdown": "# Brief A"}]},
        )


def test_article_old_brief_revision_can_be_regenerated(tmp_path: Path, monkeypatch):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    confirm_through_breakthrough(workflow, project.id)
    workflow.repository.update_step(project.id, "brief", status="completed", confirmed=True, output={"items": []})
    workflow.repository.update_step(
        project.id,
        "article",
        status="completed",
        output={"items": [{"id": "article-brief-a", "brief_id": "brief-a", "brief_revision": 1, "markdown": "old article", "status": "stale"}]},
    )
    payload = {"selected_briefs": [{"id": "brief-a", "source_id": "source-a", "revision": 2, "markdown": "# Brief A v2"}]}
    job_id = workflow.start_step(project.id, "article", payload)

    assert payload["selected_briefs"] == [{"id": "brief-a", "source_id": "source-a", "revision": 2, "markdown": "# Brief A v2"}]

    monkeypatch.setattr(
        workflow,
        "_run_step",
        lambda *args, **kwargs: {"items": [{"brief_id": "brief-a", "markdown": "# Article A v2"}]},
    )

    workflow.run_step_job(project.id, job_id, "article", payload)

    saved = workflow.repository.load_project(project.id)
    items = saved.steps["article"].output["items"]
    assert len(items) == 1
    assert items[0]["brief_id"] == "brief-a"
    assert items[0]["brief_revision"] == 2
    assert items[0]["markdown"] == "# Article A v2"
    assert items[0]["status"] == "completed"


def test_force_regenerated_article_keeps_review_notes_and_clears_audit(tmp_path: Path, monkeypatch):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    workflow.repository.update_step(
        project.id,
        "article",
        status="completed",
        output={
            "items": [
                {
                    "id": "article-brief-a",
                    "brief_id": "brief-a",
                    "brief_revision": 1,
                    "markdown": "# Old Article",
                    "article_audit_status": "approved",
                    "article_audited_at": "2026-06-09T09:00:00Z",
                }
            ]
        },
    )
    payload = {
        "force": True,
        "selected_briefs": [
            {
                "id": "brief-a",
                "source_id": "source-a",
                "revision": 1,
                "markdown": "# Brief A",
                "status": "completed",
                "review_notes": "把案例补充到第一段",
            }
        ],
    }
    job_id = workflow.start_step(project.id, "article", payload)
    monkeypatch.setattr(
        workflow,
        "_run_step",
        lambda *args, **kwargs: {"items": [{"brief_id": "brief-a", "markdown": "# New Article"}]},
    )

    workflow.run_step_job(project.id, job_id, "article", payload)

    saved = workflow.repository.load_project(project.id)
    item = saved.steps["article"].output["items"][0]
    assert item["markdown"] == "# New Article"
    assert item["review_notes"] == "把案例补充到第一段"
    assert item["article_audit_status"] == ""
    assert item["article_audited_at"] == ""


def test_updating_brief_marks_existing_article_stale(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    workflow.repository.update_step(
        project.id,
        "brief",
        status="confirmed",
        output={"items": [{"id": "brief-a", "source_id": "source-a", "revision": 1, "title": "old", "markdown": "# Brief A"}]},
    )
    workflow.repository.update_step(
        project.id,
        "article",
        status="confirmed",
        output={"items": [{"id": "article-brief-a", "brief_id": "brief-a", "brief_revision": 1, "title": "old", "markdown": "# Article A", "status": "completed"}]},
    )

    workflow.update_item(project.id, "brief", "brief-a", {"title": "new", "markdown": "# Brief A v2"})

    saved = workflow.repository.load_project(project.id)
    brief = saved.steps["brief"].output["items"][0]
    article = saved.steps["article"].output["items"][0]
    assert brief["revision"] == 2
    assert brief["status"] == "modified"
    assert brief["modified_at"]
    assert article["status"] == "stale"
    assert article["current_brief_revision"] == 2
    assert "旧 Brief" in article["stale_reason"]


def test_updating_brief_rewrites_output_markdown_file(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    workflow.repository.update_step(
        project.id,
        "brief",
        status="completed",
        output={"items": [{"id": "brief-a", "source_id": "source-a", "revision": 1, "title": "old", "markdown": "# Brief A"}]},
    )
    workflow.repository.write_output(project, "briefs/source-a-brief.md", "# Brief A\n")

    workflow.update_item(project.id, "brief", "brief-a", {"title": "new", "markdown": "# Brief A v2"})

    output_file = next(workflow.repository.outputs_dir(project.id).rglob("briefs/source-a-brief.md"))
    assert output_file.read_text(encoding="utf-8") == "# Brief A v2\n"


def test_update_generated_article_item_persists_review_state(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    workflow.repository.update_step(
        project.id,
        "article",
        status="completed",
        output={"items": [{"id": "article-brief-a", "brief_id": "brief-a", "title": "old", "markdown": "# Old"}]},
    )
    workflow.repository.write_output(project, "articles/brief-a.md", "# Old\n")

    workflow.update_item(
        project.id,
        "article",
        "article-brief-a",
        {
            "title": "new",
            "markdown": "# New",
            "review_notes": "改一下",
            "article_audit_status": "approved",
            "article_audited_at": "2026-06-09T10:00:00Z",
        },
    )

    saved = workflow.repository.load_project(project.id)
    item = saved.steps["article"].output["items"][0]
    assert item["title"] == "new"
    assert item["review_notes"] == "改一下"
    assert item["article_audit_status"] == "approved"
    assert item["article_audited_at"] == "2026-06-09T10:00:00Z"
    output_file = next(workflow.repository.outputs_dir(project.id).rglob("articles/brief-a.md"))
    assert output_file.read_text(encoding="utf-8") == "# New\n"


def test_repository_marks_interrupted_jobs_failed_on_startup(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    workflow.repository.update_step(project.id, "materials", status="completed", confirmed=True)
    workflow.start_step(project.id, "intake", {})

    recovered_repository = ProjectRepository(tmp_path)
    recovered_repository.recover_interrupted_jobs()
    recovered = recovered_repository.load_project(project.id)

    assert recovered.steps["intake"].status == "failed"
    assert recovered.jobs[0].status == "failed"
    assert "任务中断" in (recovered.steps["intake"].error or "")


def test_repository_marks_interrupted_running_items_failed(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    workflow.repository.update_step(
        project.id,
        "brief",
        status="running",
        output={
            "items": [
                {"id": "brief-a", "source_id": "a", "status": "completed"},
                {"id": "brief-b", "source_id": "b", "status": "running"},
            ]
        },
    )
    job = workflow.repository.add_job(project.id, "brief", total_count=2)
    workflow.repository.update_job(project.id, job.id, status="running")

    recovered_repository = ProjectRepository(tmp_path)
    recovered_repository.recover_interrupted_jobs()
    recovered = recovered_repository.load_project(project.id)

    items = {item["source_id"]: item for item in recovered.steps["brief"].output["items"]}
    assert recovered.steps["brief"].status == "completed"
    assert items["b"]["status"] == "failed"
    assert "单独重试" in items["b"]["error"]
    assert recovered.jobs[0].status == "failed"


def test_export_markdown_zip(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    workflow.repository.write_output(project, "articles/test.md", "# Test\n")

    zip_path = workflow.repository.export_markdown_zip(project.id)

    assert zip_path.exists()
    assert zip_path.suffix == ".zip"


def test_content_plan_requires_completed_matrix(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")

    with pytest.raises(ContentPlanError, match="请先生成内容矩阵"):
        build_matrix_content_plan(project)


def test_content_plan_builds_from_canonical_matrix(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    output = normalize_planning_output(
        "matrix",
        {
            "project": {
                "target_brand": "目标品牌",
                "target_category": "高端厨电",
                "competitors": ["竞品A"],
                "recommendation_logic": "用证据链支撑推荐。",
            },
            "intent_groups": [
                {
                    "id": "IG01",
                    "name": "推荐决策类",
                    "keywords": ["万元预算厨电推荐"],
                    "user_stage": "决策阶段",
                    "user_question": "万元预算应该选什么厨电？",
                    "recommendation_logic": "先定义标准，再给出推荐。",
                }
            ],
            "article_type_pool": [{"type": "支柱标准文", "role": "定义判断标准", "covered_keywords_or_intent_groups": ["IG01"]}],
            "items": [
                {**row, "intent_group": "IG01 推荐决策类"}
                for row in matrix_required_rows("万元预算厨电推荐")
            ],
            "evidence_gaps": ["缺少检测报告"],
            "schedule": [{"week": "第1周", "task": "完成首批 Brief"}],
            "brief_requirements": ["每篇 Brief 必须写清证据来源。"],
        },
        {},
    )
    workflow.repository.update_step(project.id, "matrix", status="completed", output=output)

    plan = build_matrix_content_plan(workflow.repository.load_project(project.id))

    assert plan["schema_version"] == "1.0"
    assert plan["summary"]["target_brand"] == "目标品牌"
    assert plan["summary"]["total_plans"] == 6
    assert plan["summary"]["evidence_gap_count"] == 1
    assert plan["keyword_intent_groups"][0]["name"] == "推荐决策类"
    assert plan["article_type_pool"][0]["keywords"] == ["推荐决策类"]
    assert plan["first_round_plans"][0]["type"] == "支柱标准文"
    assert plan["first_round_plans"][0]["intent_group"] == "推荐决策类"
    assert plan["first_round_plans"][0]["intent_group_raw"] == "IG01 推荐决策类"
    evidence_section = next(section for section in plan["display_sections"] if section["id"] == "evidence_gaps")
    labels = [field["label"] for item in evidence_section["items"] for field in item["fields"]]
    assert "缺失证据" in labels
    assert "missing_evidence" not in labels


def test_content_plan_pdf_is_written(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    output = normalize_planning_output(
        "matrix",
        {
            "project": {"target_brand": "目标品牌", "target_category": "高端厨电"},
            "items": matrix_required_rows("万元预算厨电推荐"),
        },
        {},
    )
    workflow.repository.update_step(project.id, "matrix", status="completed", output=output)
    saved = workflow.repository.load_project(project.id)

    path = export_content_plan_pdf(saved, workflow.repository)

    assert path.exists()
    assert path.name == "02-content-plan.pdf"
    assert path.read_bytes().startswith(b"%PDF")


def test_parse_materials_skips_already_parsed_files(tmp_path: Path, monkeypatch):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    parsed = workflow.repository.add_material(project.id, "brief.md", "text/markdown", b"# Brief\n")
    failed = workflow.repository.add_material(project.id, "keyword.csv", "text/csv", "keyword\n".encode("utf-8"))

    project = workflow.repository.load_project(project.id)
    parsed.status = "parsed"
    parsed.parsed_path = "parsed/brief.md"
    workflow.repository.parsed_dir(project.id).joinpath("brief.md").write_text("# Brief\n", encoding="utf-8")
    failed.status = "failed"
    failed.error = "old error"
    workflow.repository.update_material(project.id, parsed)
    workflow.repository.update_material(project.id, failed)
    workflow.repository.update_step(project.id, "materials", status="failed", error="old error")

    calls = []

    def fake_parse(path, **kwargs):
        calls.append(path.name)
        return "## parsed"

    monkeypatch.setattr("app.agent.workflow.parse_material", fake_parse)

    workflow.parse_materials(project.id)

    assert calls == [workflow.repository.materials_dir(project.id).joinpath(failed.stored_name).name]
    saved = workflow.repository.load_project(project.id)
    assert saved.steps["materials"].status == "confirmed"
    assert "# Brief" in saved.steps["materials"].output["summary"]
    assert "## parsed" in saved.steps["materials"].output["summary"]


def test_parse_materials_job_counts_skipped_files(tmp_path: Path, monkeypatch):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    material = workflow.repository.add_material(project.id, "brief.md", "text/markdown", b"# Brief\n")
    material.status = "parsed"
    material.parsed_path = "parsed/brief.md"
    workflow.repository.parsed_dir(project.id).joinpath("brief.md").write_text("# Brief\n", encoding="utf-8")
    workflow.repository.update_material(project.id, material)
    job_id = workflow.start_materials_parse(project.id)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("parsed material should be skipped")

    monkeypatch.setattr("app.agent.workflow.parse_material", fail_if_called)

    workflow.parse_materials(project.id, job_id)

    saved = workflow.repository.load_project(project.id)
    job = saved.jobs[0]
    assert saved.steps["materials"].status == "confirmed"
    assert job.status == "completed"
    assert job.completed_count == 0
    assert job.skipped_count == 1
    assert "跳过 1 个已解析" in (job.message or "")

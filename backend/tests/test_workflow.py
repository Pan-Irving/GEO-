import json
from pathlib import Path

import pytest

from app.agent.skill_loader import SkillLoader
from app.agent.workflow import AgentWorkflow, WorkflowError, build_selection_prompt_blocks, normalize_planning_output, planning_output_requirements
from app.core.config import PROJECT_ROOT, Settings
from app.storage.repository import ProjectRepository


def make_workflow(tmp_path: Path) -> AgentWorkflow:
    settings = Settings(openai_api_key="test-key", app_data_dir=str(tmp_path))
    return AgentWorkflow(
        ProjectRepository(tmp_path),
        SkillLoader(PROJECT_ROOT / "mindsun-geo-content-flow"),
        settings,
    )


def test_parse_materials_confirms_material_step(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    workflow.repository.add_material(project.id, "brief.md", "text/markdown", b"# Brief\n\nkeyword")

    workflow.parse_materials(project.id)

    saved = workflow.repository.load_project(project.id)
    assert saved.steps["materials"].status == "confirmed"
    assert saved.materials[0].status == "parsed"


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
    workflow.repository.update_step(project.id, "intake", status="completed", confirmed=True)

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
    workflow.repository.update_step(project.id, "intake", status="completed", confirmed=True)
    matrix_job_id = workflow.start_step(project.id, "matrix", {})
    monkeypatch.setattr(workflow, "_run_step", lambda *args, **kwargs: {"items": [{"id": "plan"}]})

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
    assert '"step": "geo_keyword_breakthrough"' in breakthrough_prompt
    assert "支柱标准文 / 榜单推荐文 / 横评对比文 / 场景选购文 / 产品证据文 / FAQ问答文" in breakthrough_prompt
    assert '"A"' in breakthrough_prompt


def test_matrix_output_is_normalized_from_legacy_fields():
    english = normalize_planning_output(
        "matrix",
        {
            "project": {"target_brand": "品牌"},
            "first_round_article_list": [
                {
                    "article_type": "支柱标准文",
                    "suggested_title": "A怎么选？",
                    "main_keyword_or_cluster": "A / 选购指南类",
                    "main_role": "建立判断标准",
                    "channels": ["知乎"],
                    "brief_focus": "先讲标准",
                }
            ],
        },
        {},
    )
    chinese = normalize_planning_output(
        "matrix",
        {
            "五_关键词逐个规划": [
                {
                    "关键词": "B",
                    "文章类型": "场景选购文",
                    "建议标题": "B场景推荐",
                    "主要作用": "承接场景词",
                    "推荐渠道": ["小红书"],
                    "必备证据": ["证据1"],
                }
            ]
        },
        {},
    )

    assert english["step"] == "geo_content_matrix"
    assert english["schema_version"] == "1.0"
    assert english["items"][0]["keyword"] == "A"
    assert english["items"][0]["intent_group"] == "选购指南类"
    assert english["items"][0]["source_step"] == "matrix"
    assert english["items"][0]["channels"] == ["知乎"]
    assert chinese["items"][0]["keyword"] == "B"
    assert chinese["items"][0]["type"] == "场景选购文"
    assert chinese["items"][0]["required_evidence"] == ["证据1"]


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
    workflow.repository.update_step(project.id, "intake", status="confirmed", output={"items": [{"field": "目标"}]})
    workflow.repository.update_step(project.id, "matrix", status="completed", output={"items": [{"id": "old"}]})

    workflow.start_step(project.id, "matrix", {"force": True})

    saved = workflow.repository.load_project(project.id)
    assert saved.steps["matrix"].status == "running"
    assert saved.steps["matrix"].output == {}


def test_force_rerun_success_overwrites_output(tmp_path: Path, monkeypatch):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    workflow.repository.update_step(project.id, "materials", status="completed", confirmed=True)
    workflow.repository.update_step(project.id, "intake", status="confirmed", output={"items": [{"field": "目标"}]})
    workflow.repository.update_step(project.id, "matrix", status="completed", output={"items": [{"id": "old"}]})
    job_id = workflow.start_step(project.id, "matrix", {"force": True})

    monkeypatch.setattr(workflow, "_run_step", lambda *args, **kwargs: {"items": [{"id": "new"}]})

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


def test_article_requires_selected_briefs(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    confirm_through_breakthrough(workflow, project.id)
    workflow.repository.update_step(project.id, "brief", status="completed", confirmed=True, output={"items": []})

    with pytest.raises(WorkflowError, match="选择要生成正文"):
        workflow.start_step(project.id, "article", {})


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


def test_update_generated_item_persists_review_notes(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    workflow.repository.update_step(
        project.id,
        "article",
        status="completed",
        output={"items": [{"id": "article-brief-a", "brief_id": "brief-a", "title": "old", "markdown": "old"}]},
    )

    workflow.update_item(project.id, "article", "article-brief-a", {"title": "new", "review_notes": "改一下"})

    saved = workflow.repository.load_project(project.id)
    item = saved.steps["article"].output["items"][0]
    assert item["title"] == "new"
    assert item["review_notes"] == "改一下"


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

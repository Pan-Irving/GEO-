from pathlib import Path

import pytest

from app.agent.skill_loader import SkillLoader
from app.agent.workflow import AgentWorkflow, WorkflowError
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


def test_export_markdown_zip(tmp_path: Path):
    workflow = make_workflow(tmp_path)
    project = workflow.repository.create_project("测试项目")
    workflow.repository.write_output(project, "articles/test.md", "# Test\n")

    zip_path = workflow.repository.export_markdown_zip(project.id)

    assert zip_path.exists()
    assert zip_path.suffix == ".zip"

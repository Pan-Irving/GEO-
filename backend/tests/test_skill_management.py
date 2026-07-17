from pathlib import Path

from app.agent.skill_loader import SkillLoader, SkillResolver
from app.core.config import PROJECT_ROOT
from app.storage.repository import ProjectRepository


def test_each_skill_slot_has_independent_candidates_and_active_selection(tmp_path: Path):
    repository = ProjectRepository(tmp_path)
    catalog = repository.upload_skill_candidate("榜单推荐文", "brief", "list-a.md", b"# List A")
    list_slot = next(item for item in catalog["slots"] if item["article_type"] == "榜单推荐文" and item["stage"] == "brief")
    candidate = next(item for item in list_slot["candidates"] if item["id"] != "builtin")
    assert list_slot["active_id"] == "builtin"

    catalog = repository.activate_skill_candidate("榜单推荐文", "brief", candidate["id"])
    list_slot = next(item for item in catalog["slots"] if item["article_type"] == "榜单推荐文" and item["stage"] == "brief")
    other_slot = next(item for item in catalog["slots"] if item["article_type"] == "横评对比文" and item["stage"] == "brief")
    assert list_slot["active_id"] == candidate["id"]
    assert other_slot["active_id"] == "builtin"

    snapshot = SkillResolver(repository, SkillLoader(PROJECT_ROOT / "mindsun-geo-content-flow")).snapshot_for_step(
        "brief", {"selected_sources": [{"type": "榜单推荐文"}, {"type": "横评对比文"}]}
    )
    rules = {item["article_type"]: item for item in snapshot["rules"]}
    assert rules["榜单推荐文"]["content"] == "# List A"
    assert rules["横评对比文"]["source"] == "内置默认规则（回退）"

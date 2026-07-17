from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import get_repository, router
from app.services.publishing_inventory import publishing_articles
from app.storage.repository import ProjectRepository


def add_keyword_material(repository: ProjectRepository, project_id: str, *keywords: str) -> None:
    text = "\n".join(keywords)
    material = repository.add_material(project_id, "keywords__核心关键词.md", "text/markdown", text.encode("utf-8"))
    material.status = "parsed"
    material.parsed_path = "parsed/keywords__核心关键词.md"
    material.parse_mode = "smart"
    material.parsed_at = "2026-01-01T00:00:00+00:00"
    repository.parsed_dir(project_id).mkdir(parents=True, exist_ok=True)
    (repository.project_dir(project_id) / material.parsed_path).write_text(text, encoding="utf-8")
    repository.update_material(project_id, material)


def add_intent_matrix(repository: ProjectRepository, project_id: str, *intent_groups: str) -> None:
    repository.update_step(
        project_id,
        "matrix",
        status="completed",
        output={
            "intent_groups": [
                {"id": keyword, "name": keyword, "keywords": [keyword], "article_types": ["榜单推荐文", "横评对比文"]}
                for keyword in intent_groups
            ],
            "items": [
                {"source_id": f"matrix-{index}", "intent_group": keyword, "keyword": keyword, "type": "榜单推荐文", "title": f"{keyword}规划"}
                for index, keyword in enumerate(intent_groups, start=1)
            ],
        },
    )


def test_publishing_articles_only_returns_approved_final_markdown(tmp_path: Path):
    repository = ProjectRepository(tmp_path)
    project = repository.create_project("发布测试项目")
    repository.update_step(
        project.id,
        "article",
        status="completed",
        output={
            "items": [
                {
                    "id": "article-ok",
                    "brief_id": "brief-ok",
                    "source_id": "source-ok",
                    "keyword": "高端厨电哪个牌子好",
                    "type": "榜单推荐文",
                    "title": "高端厨电哪个牌子好",
                    "markdown": "# 正文\n\n内容",
                    "status": "completed",
                    "article_audit_status": "approved",
                    "article_audited_at": "2026-06-15T10:00:00+08:00",
                },
                {
                    "id": "article-pending-review",
                    "markdown": "# 未审",
                    "status": "completed",
                    "article_audit_status": "",
                },
                {
                    "id": "article-stale",
                    "markdown": "# 过期",
                    "status": "stale",
                    "article_audit_status": "approved",
                },
                {
                    "id": "article-empty",
                    "markdown": "",
                    "status": "completed",
                    "article_audit_status": "approved",
                },
            ]
        },
    )

    saved = repository.load_project(project.id)
    articles = publishing_articles(saved)

    assert [item["article_id"] for item in articles] == ["article-ok"]
    assert articles[0]["project_id"] == project.id
    assert articles[0]["project_name"] == "发布测试项目"
    assert articles[0]["article_type"] == "榜单推荐文"
    assert articles[0]["content_hash"]
    assert articles[0]["updated_at"] == "2026-06-15T10:00:00+08:00"


def test_import_markdown_articles_creates_approved_publishable_items(tmp_path: Path):
    repository = ProjectRepository(tmp_path)
    project = repository.create_project("发布测试项目")
    add_keyword_material(repository, project.id, "关键词 A", "关键词 B")
    add_intent_matrix(repository, project.id, "关键词 A", "关键词 B")

    saved = repository.import_markdown_articles(
        project.id,
        [
            {"filename": "a.md", "title": "文章 A", "keyword": "关键词 A", "type": "榜单推荐文", "markdown": "# 文章 A\n\n内容 A"},
            {"filename": "b.md", "title": "文章 B", "keyword": "关键词 B", "type": "横评对比文", "markdown": "# 文章 B\n\n内容 B"},
        ],
    )

    items = saved.steps["article"].output["items"]
    assert len(items) == 2
    assert all(item["article_audit_status"] == "approved" for item in items)
    assert all(item["source_step"] == "imported" for item in items)
    assert saved.steps["article"].status == "completed"
    exported = publishing_articles(saved)
    assert [item["title"] for item in exported] == ["文章 A", "文章 B"]
    assert (repository.outputs_dir(project.id)).exists()
    assert len(list(repository.outputs_dir(project.id).rglob("articles/*.md"))) == 2


def test_rebuild_and_rename_intent_group_updates_publishable_articles(tmp_path: Path):
    repository = ProjectRepository(tmp_path)
    project = repository.create_project("标准意图簇项目")
    add_keyword_material(repository, project.id, "关键词 A")
    add_intent_matrix(repository, project.id, "关键词 A")
    repository.import_markdown_articles(
        project.id,
        [{"filename": "a.md", "title": "文章 A", "keyword": "关键词 A", "type": "榜单推荐文", "markdown": "# A"}],
    )

    rebuilt = repository.rebuild_intent_groups(project.id)
    group_id = rebuilt.intent_groups[0]["id"]
    renamed = repository.update_intent_group(project.id, group_id, {"name": "购买决策意图", "keywords": ["关键词 A"]})
    exported = publishing_articles(renamed)

    assert renamed.intent_groups[0]["aliases"] == ["关键词 A"]
    assert [group["name"] for group in renamed.steps["matrix"].output["intent_groups"]] == ["购买决策意图"]
    assert exported[0]["intent_group_id"] == group_id
    assert exported[0]["intent_group"] == "购买决策意图"


def test_rebuild_intent_groups_falls_back_to_current_matrix(tmp_path: Path):
    repository = ProjectRepository(tmp_path)
    project = repository.create_project("矩阵意图簇项目")
    add_intent_matrix(repository, project.id, "厂家直接推荐与决策", "质量与口碑评估")

    rebuilt = repository.rebuild_intent_groups(project.id)

    assert [group["name"] for group in rebuilt.intent_groups] == ["厂家直接推荐与决策", "质量与口碑评估"]
    assert rebuilt.intent_groups[0]["keywords"] == ["厂家直接推荐与决策"]


def test_rebuild_intent_groups_keeps_unarchived_matrix_groups(tmp_path: Path):
    repository = ProjectRepository(tmp_path)
    project = repository.create_project("部分归档意图簇项目")
    add_keyword_material(repository, project.id, "关键词 A", "关键词 B", "关键词 C")
    add_intent_matrix(repository, project.id, "综合认知类", "推荐决策类", "高性价比推荐与排名")
    repository.import_markdown_articles(
        project.id,
        [
            {"filename": "a.md", "title": "文章 A", "intent_group": "综合认知类", "keyword": "关键词 A", "type": "榜单推荐文", "markdown": "# A"},
            {"filename": "b.md", "title": "文章 B", "intent_group": "推荐决策类", "keyword": "关键词 B", "type": "榜单推荐文", "markdown": "# B"},
        ],
    )

    rebuilt = repository.rebuild_intent_groups(project.id)

    assert [group["name"] for group in rebuilt.intent_groups] == ["综合认知类", "推荐决策类", "高性价比推荐与排名"]
    assert {group["name"]: group["article_count"] for group in rebuilt.intent_groups} == {
        "综合认知类": 1,
        "推荐决策类": 1,
        "高性价比推荐与排名": 0,
    }


def test_update_intent_group_keyword_reassigns_archived_articles(tmp_path: Path):
    repository = ProjectRepository(tmp_path)
    project = repository.create_project("关键词改归属项目")
    add_keyword_material(repository, project.id, "家用油烟机哪个牌子好", "油烟机推荐性价比高")
    add_intent_matrix(repository, project.id, "推荐决策类", "家用油烟机品牌口碑对比")
    saved = repository.import_markdown_articles(
        project.id,
        [
            {
                "filename": "a.md",
                "title": "文章 A",
                "intent_group": "推荐决策类",
                "keyword": "家用油烟机哪个牌子好",
                "type": "榜单推荐文",
                "markdown": "# A",
            }
        ],
    )
    target_id = next(group["id"] for group in saved.intent_groups if group["name"] == "家用油烟机品牌口碑对比")

    updated = repository.update_intent_group(project.id, target_id, {"keywords": ["家用油烟机哪个牌子好"]})
    article = updated.steps["article"].output["items"][0]
    exported = publishing_articles(updated)

    assert article["intent_group_id"] == target_id
    assert article["intent_group"] == "家用油烟机品牌口碑对比"
    assert {group["name"]: group["article_count"] for group in updated.intent_groups}["家用油烟机品牌口碑对比"] == 1
    assert exported[0]["intent_group_id"] == target_id
    assert exported[0]["intent_group"] == "家用油烟机品牌口碑对比"


def test_create_intent_group_imports_existing_keyword_articles(tmp_path: Path):
    repository = ProjectRepository(tmp_path)
    project = repository.create_project("新建意图簇项目")
    add_keyword_material(repository, project.id, "家用油烟机哪个牌子好", "油烟机推荐性价比高")
    add_intent_matrix(repository, project.id, "推荐决策类")
    saved = repository.import_markdown_articles(
        project.id,
        [
            {
                "filename": "a.md",
                "title": "文章 A",
                "intent_group": "推荐决策类",
                "keyword": "家用油烟机哪个牌子好",
                "type": "榜单推荐文",
                "markdown": "# A",
            }
        ],
    )

    updated = repository.create_intent_group(
        saved.id,
        {"name": "新建口碑对比类", "keywords": ["家用油烟机哪个牌子好"]},
    )
    new_group = next(group for group in updated.intent_groups if group["name"] == "新建口碑对比类")
    article = updated.steps["article"].output["items"][0]

    assert new_group["article_count"] == 1
    assert article["intent_group_id"] == new_group["id"]
    assert article["intent_group"] == "新建口碑对比类"
    assert publishing_articles(updated)[0]["intent_group"] == "新建口碑对比类"


def test_update_intent_group_rejects_keywords_outside_project_keyword_table(tmp_path: Path):
    repository = ProjectRepository(tmp_path)
    project = repository.create_project("关键词校验项目")
    add_keyword_material(repository, project.id, "关键词 A")
    add_intent_matrix(repository, project.id, "关键词 A")
    rebuilt = repository.rebuild_intent_groups(project.id)
    group_id = rebuilt.intent_groups[0]["id"]

    try:
        repository.update_intent_group(project.id, group_id, {"keywords": ["不存在关键词"]})
    except ValueError as exc:
        assert "关键词不在项目关键词表中" in str(exc)
    else:
        raise AssertionError("expected invalid keyword to fail")


def test_rebuild_intent_groups_splits_joined_matrix_keywords_against_keyword_table(tmp_path: Path):
    repository = ProjectRepository(tmp_path)
    project = repository.create_project("合并关键词清洗项目")
    keyword_a = "热镀锌螺丝生产厂家哪家好"
    keyword_b = "热镀锌螺丝哪个厂家生产的质量好"
    add_keyword_material(repository, project.id, keyword_a, keyword_b)
    repository.update_step(
        project.id,
        "matrix",
        status="completed",
        output={
            "intent_groups": [
                {
                    "id": "quality",
                    "name": "质量与口碑评估",
                    "keywords": [f"{keyword_a}、{keyword_b}"],
                }
            ],
            "items": [
                {
                    "source_id": "matrix-1",
                    "intent_group": "质量与口碑评估",
                    "keyword": f"{keyword_a}、{keyword_b}",
                    "type": "榜单推荐文",
                    "title": "质量评估规划",
                }
            ],
        },
    )

    rebuilt = repository.rebuild_intent_groups(project.id)
    group = rebuilt.intent_groups[0]
    updated = repository.update_intent_group(project.id, group["id"], {"keywords": [keyword_a, keyword_b]})

    assert group["keywords"] == [keyword_a, keyword_b]
    assert updated.intent_groups[0]["keywords"] == [keyword_a, keyword_b]


def test_merge_intent_groups_reassigns_archived_articles(tmp_path: Path):
    repository = ProjectRepository(tmp_path)
    project = repository.create_project("合并意图簇项目")
    add_keyword_material(repository, project.id, "关键词 1", "关键词 2")
    add_intent_matrix(repository, project.id, "A", "A1")
    saved = repository.import_markdown_articles(
        project.id,
        [
            {"filename": "a.md", "title": "文章 A", "intent_group": "A", "keyword": "关键词 1", "type": "榜单推荐文", "markdown": "# A"},
            {"filename": "b.md", "title": "文章 B", "intent_group": "A1", "keyword": "关键词 2", "type": "榜单推荐文", "markdown": "# B"},
        ],
    )
    target_id = next(group["id"] for group in saved.intent_groups if group["name"] == "A")
    source_id = next(group["id"] for group in saved.intent_groups if group["name"] == "A1")

    merged = repository.merge_intent_group(project.id, target_id, [source_id])
    exported = publishing_articles(merged)

    assert [group["name"] for group in merged.intent_groups] == ["A"]
    assert "A1" in merged.intent_groups[0]["aliases"]
    assert {item["intent_group_id"] for item in exported} == {target_id}
    assert {item["keyword"] for item in exported} == {"关键词 1", "关键词 2"}


def test_import_markdown_articles_rejects_missing_required_metadata(tmp_path: Path):
    repository = ProjectRepository(tmp_path)
    project = repository.create_project("发布测试项目")
    add_keyword_material(repository, project.id, "关键词 A")
    add_intent_matrix(repository, project.id, "关键词 A")

    try:
        repository.import_markdown_articles(project.id, [{"filename": "a.md", "keyword": "", "type": "榜单推荐文", "markdown": "# A"}])
    except ValueError as exc:
        assert "请选择意图簇" in str(exc)
    else:
        raise AssertionError("expected missing keyword to fail")


def test_import_markdown_articles_rejects_non_md_and_empty_file(tmp_path: Path):
    repository = ProjectRepository(tmp_path)
    project = repository.create_project("发布测试项目")
    add_keyword_material(repository, project.id, "关键词 A")
    add_intent_matrix(repository, project.id, "关键词 A")

    for payload, expected in [
        ({"filename": "a.txt", "keyword": "关键词 A", "type": "榜单推荐文", "markdown": "# A"}, "仅支持 .md 文件"),
        ({"filename": "a.md", "keyword": "关键词 A", "type": "榜单推荐文", "markdown": "   "}, "Markdown 内容不能为空"),
    ]:
        try:
            repository.import_markdown_articles(project.id, [payload])
        except ValueError as exc:
            assert expected in str(exc)
        else:
            raise AssertionError(f"expected {expected} to fail")


def test_import_markdown_articles_requires_content_matrix(tmp_path: Path):
    repository = ProjectRepository(tmp_path)
    project = repository.create_project("发布测试项目")

    try:
        repository.import_markdown_articles(project.id, [{"filename": "a.md", "keyword": "关键词 A", "type": "榜单推荐文", "markdown": "# A"}])
    except ValueError as exc:
        assert "内容矩阵" in str(exc)
    else:
        raise AssertionError("expected missing core keyword table to fail")


def test_import_markdown_articles_rejects_unknown_intent_group(tmp_path: Path):
    repository = ProjectRepository(tmp_path)
    project = repository.create_project("发布测试项目")
    add_keyword_material(repository, project.id, "关键词 A")
    add_intent_matrix(repository, project.id, "关键词 A")

    try:
        repository.import_markdown_articles(project.id, [{"filename": "a.md", "keyword": "高端厨电", "type": "榜单推荐文", "markdown": "# A"}])
    except ValueError as exc:
        assert "请选择意图簇" in str(exc)
    else:
        raise AssertionError("expected outside keyword to fail")


def test_publishing_articles_filters_out_orphan_keywords_when_allowed_keywords_are_known(tmp_path: Path):
    repository = ProjectRepository(tmp_path)
    project = repository.create_project("发布测试项目")
    repository.update_step(
        project.id,
        "article",
        status="completed",
        output={
            "items": [
                {
                    "id": "article-ok",
                    "keyword": "关键词 A",
                    "type": "榜单推荐文",
                    "title": "文章 A",
                    "markdown": "# A",
                    "status": "completed",
                    "article_audit_status": "approved",
                },
                {
                    "id": "article-orphan",
                    "keyword": "高端厨电",
                    "type": "榜单推荐文",
                    "title": "孤儿文章",
                    "markdown": "# orphan",
                    "status": "completed",
                    "article_audit_status": "approved",
                },
            ]
        },
    )

    saved = repository.load_project(project.id)
    assert [item["article_id"] for item in publishing_articles(saved, ["关键词 A"])] == ["article-ok"]


def test_publishing_articles_keeps_legacy_import_with_empty_keyword_when_group_has_keyword(tmp_path: Path):
    repository = ProjectRepository(tmp_path)
    project = repository.create_project("发布测试项目")
    add_keyword_material(repository, project.id, "关键词 A")
    add_intent_matrix(repository, project.id, "关键词 A")
    rebuilt = repository.rebuild_intent_groups(project.id)
    group = rebuilt.intent_groups[0]
    repository.update_step(
        project.id,
        "article",
        status="completed",
        output={
            "items": [
                {
                    "id": "legacy-import",
                    "intent_group_id": group["id"],
                    "intent_group": group["name"],
                    "keyword": "",
                    "type": "榜单推荐文",
                    "title": "旧导入文章",
                    "markdown": "# A",
                    "status": "completed",
                    "article_audit_status": "approved",
                }
            ]
        },
    )

    saved = repository.load_project(project.id)
    articles = publishing_articles(saved, ["关键词 A"])

    assert [item["article_id"] for item in articles] == ["legacy-import"]
    assert articles[0]["keyword"] == "关键词 A"


def test_publishing_articles_keeps_standard_intent_group_without_keyword_match(tmp_path: Path):
    repository = ProjectRepository(tmp_path)
    project = repository.create_project("发布测试项目")
    add_keyword_material(repository, project.id, "关键词 A", "关键词 B")
    repository.update_step(
        project.id,
        "matrix",
        status="completed",
        output={
            "intent_groups": [{"id": "awareness", "name": "综合认知类", "keywords": ["关键词 A", "关键词 B"]}],
            "items": [{"source_id": "matrix-1", "intent_group": "综合认知类", "keyword": "关键词 A", "type": "榜单推荐文", "title": "规划"}],
        },
    )
    rebuilt = repository.rebuild_intent_groups(project.id)
    group = rebuilt.intent_groups[0]
    repository.update_step(
        project.id,
        "article",
        status="completed",
        output={
            "items": [
                {
                    "id": "cluster-article",
                    "intent_group_id": group["id"],
                    "intent_group": group["name"],
                    "keyword": "",
                    "type": "榜单推荐文",
                    "title": "簇级文章",
                    "markdown": "# A",
                    "status": "completed",
                    "article_audit_status": "approved",
                }
            ]
        },
    )

    saved = repository.load_project(project.id)
    articles = publishing_articles(saved, ["关键词 A", "关键词 B"])

    assert [item["article_id"] for item in articles] == ["cluster-article"]
    assert articles[0]["intent_group"] == "综合认知类"
    assert articles[0]["keyword"] == "综合认知类"


def test_import_markdown_route_accepts_multiple_files_and_metadata(tmp_path: Path):
    repository = ProjectRepository(tmp_path)
    project = repository.create_project("发布测试项目")
    add_keyword_material(repository, project.id, "关键词 A", "关键词 B")
    add_intent_matrix(repository, project.id, "关键词 A", "关键词 B")
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_repository] = lambda: repository
    client = TestClient(app)

    response = client.post(
        f"/api/projects/{project.id}/articles/import-md",
        data={
            "metadata": '[{"title":"文章 A","keyword":"关键词 A","type":"榜单推荐文"},{"title":"文章 B","keyword":"关键词 B","type":"横评对比文"}]',
        },
        files=[
            ("files", ("a.md", b"# A\n\ncontent", "text/markdown")),
            ("files", ("b.md", b"# B\n\ncontent", "text/markdown")),
        ],
    )

    assert response.status_code == 200
    saved = repository.load_project(project.id)
    assert len(publishing_articles(saved)) == 2


def test_import_markdown_articles_uses_h1_title_and_filename_fallback(tmp_path: Path):
    repository = ProjectRepository(tmp_path)
    project = repository.create_project("发布测试项目")
    add_keyword_material(repository, project.id, "关键词 A")
    add_intent_matrix(repository, project.id, "关键词 A")

    saved = repository.import_markdown_articles(
        project.id,
        [
            {"filename": "custom-name.md", "keyword": "关键词 A", "type": "榜单推荐文", "markdown": "# 标题来自 H1\n\n内容"},
            {"filename": "fallback-name.md", "keyword": "关键词 A", "type": "横评对比文", "markdown": "无标题正文"},
        ],
    )

    titles = [item["title"] for item in saved.steps["article"].output["items"]]
    assert titles == ["标题来自 H1", "fallback-name"]

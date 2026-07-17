import hashlib
import json
import shutil
import uuid
from pathlib import Path
from typing import Any

from app.models.schemas import CustomSource, Job, Material, Project, STEP_ORDER, STORAGE_STEPS, StepState, WorkflowStep
from app.services.intent_groups import UNCATEGORIZED_INTENT_GROUP, item_intent_group
from app.services.intent_group_manager import (
    canonical_intent_groups,
    create_intent_group,
    ensure_project_intent_groups,
    merge_intent_groups,
    rebuild_intent_groups_from_archive,
    resolve_intent_group,
    update_intent_group,
)
from app.services.project_keywords import project_allowed_keywords
from app.services.skill_registry import MAX_SKILL_MARKDOWN_BYTES, markdown_metadata, normalize_catalog, public_catalog, read_markdown, slot_key
from app.utils.files import safe_filename, slugify, today, utc_now


class ProjectRepository:
    def __init__(self, data_root: Path):
        self.data_root = data_root
        self.projects_root = data_root / "projects"
        self.projects_root.mkdir(parents=True, exist_ok=True)

    # Global writing-rule catalog. Project data intentionally does not own this state.
    def skills_root(self) -> Path:
        path = self.data_root / "skills"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _skill_catalog_file(self) -> Path:
        return self.skills_root() / "catalog.json"

    def _load_skill_catalog_data(self) -> dict[str, Any]:
        path = self._skill_catalog_file()
        if not path.exists():
            catalog = normalize_catalog(None)
            self._save_skill_catalog_data(catalog)
            return catalog
        try:
            return normalize_catalog(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return normalize_catalog(None)

    def _save_skill_catalog_data(self, catalog: dict[str, Any]) -> None:
        self._write_project_json(self._skill_catalog_file(), normalize_catalog(catalog))

    def skill_catalog(self) -> dict[str, Any]:
        return public_catalog(self._load_skill_catalog_data())

    def upload_skill_candidate(self, article_type: str, stage: str, filename: str, content: bytes) -> dict[str, Any]:
        key = slot_key(article_type, stage)
        if not str(filename or "").lower().endswith(".md"):
            raise ValueError("规则文件仅支持 .md 格式。")
        if not content or len(content) > MAX_SKILL_MARKDOWN_BYTES:
            raise ValueError(f"规则文件必须为非空 UTF-8 Markdown，且不超过 {MAX_SKILL_MARKDOWN_BYTES // 1024}KB。")
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("规则文件必须为 UTF-8 编码。") from exc
        if not text.strip():
            raise ValueError("规则文件不能为空。")
        catalog = self._load_skill_catalog_data()
        candidate_id = uuid.uuid4().hex
        candidates_dir = self.skills_root() / "candidates"
        candidates_dir.mkdir(parents=True, exist_ok=True)
        stored_name = f"{candidate_id}-{safe_filename(filename)}"
        (candidates_dir / stored_name).write_text(text, encoding="utf-8")
        catalog["slots"][key]["candidates"].append(
            markdown_metadata(candidate_id, filename, text.encode("utf-8"), stored_name, utc_now())
        )
        self._save_skill_catalog_data(catalog)
        return public_catalog(catalog)

    def activate_skill_candidate(self, article_type: str, stage: str, candidate_id: str) -> dict[str, Any]:
        catalog = self._load_skill_catalog_data()
        key = slot_key(article_type, stage)
        slot = catalog["slots"][key]
        if not any(item.get("id") == candidate_id for item in slot["candidates"]):
            raise FileNotFoundError("未找到该 skill 规则文件。")
        slot["active_id"] = candidate_id
        self._save_skill_catalog_data(catalog)
        return public_catalog(catalog)

    def delete_skill_candidate(self, article_type: str, stage: str, candidate_id: str) -> dict[str, Any]:
        if candidate_id == "builtin":
            raise ValueError("内置规则不能删除。")
        catalog = self._load_skill_catalog_data()
        key = slot_key(article_type, stage)
        slot = catalog["slots"][key]
        target = next((item for item in slot["candidates"] if item.get("id") == candidate_id), None)
        if not target:
            raise FileNotFoundError("未找到该 skill 规则文件。")
        slot["candidates"] = [item for item in slot["candidates"] if item.get("id") != candidate_id]
        if slot["active_id"] == candidate_id:
            slot["active_id"] = "builtin"
        stored_name = str(target.get("stored_name") or "")
        if stored_name:
            path = (self.skills_root() / "candidates" / stored_name).resolve()
            candidates_root = (self.skills_root() / "candidates").resolve()
            if candidates_root in path.parents and path.exists():
                path.unlink()
        self._save_skill_catalog_data(catalog)
        return public_catalog(catalog)

    def read_active_skill_slot(self, article_type: str, stage: str) -> tuple[str, dict[str, Any]] | None:
        catalog = self._load_skill_catalog_data()
        slot = catalog["slots"][slot_key(article_type, stage)]
        candidate = next((item for item in slot["candidates"] if item.get("id") == slot["active_id"]), None)
        if not isinstance(candidate, dict) or candidate.get("id") == "builtin" or not candidate.get("stored_name"):
            return None
        path = (self.skills_root() / "candidates" / str(candidate["stored_name"])).resolve()
        candidates_root = (self.skills_root() / "candidates").resolve()
        if candidates_root not in path.parents:
            return None
        try:
            return read_markdown(path), candidate
        except (FileNotFoundError, ValueError):
            return None

    def create_project(self, name: str) -> Project:
        suffix = uuid.uuid4().hex[:8]
        project_id = f"{slugify(name)}-{suffix}"
        project = Project(
            id=project_id,
            name=name,
            steps={step: StepState() for step in STORAGE_STEPS},
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
                self._write_project_json(path, data)

    def load_project(self, project_id: str) -> Project:
        path = self.project_file(project_id)
        if not path.exists():
            raise FileNotFoundError(f"Project not found: {project_id}")
        data = json.loads(path.read_text(encoding="utf-8"))
        data.setdefault("intent_groups", [])
        data.setdefault("custom_sources", [])
        raw_steps = data.setdefault("steps", {})
        data["steps"] = {
            step: raw_steps.get(step, StepState().model_dump())
            for step in STORAGE_STEPS
        }
        data["jobs"] = [
            job for job in data.get("jobs", [])
            if isinstance(job, dict) and job.get("step") in STORAGE_STEPS
        ]
        normalize_blocked_step_states(data)
        project = Project.model_validate(data)
        ensure_project_intent_groups(project)
        return project

    def save_project(self, project: Project) -> None:
        ensure_project_intent_groups(project)
        project.updated_at = utc_now()
        self.project_dir(project.id).mkdir(parents=True, exist_ok=True)
        self._write_project_json(self.project_file(project.id), project.model_dump())

    @staticmethod
    def _write_project_json(path: Path, data: dict[str, Any]) -> None:
        tmp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(path)

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
        source = normalize_custom_source(project, payload, project_dir=self.project_dir(project_id))
        if any(item.source_id == source.source_id for item in project.custom_sources):
            raise ValueError("同标题的自定义文章已存在。")
        project.custom_sources.append(source)
        self.save_project(project)
        self.log(project_id, f"新增自定义文章规划：{source.title}")
        return project

    def list_intent_groups(self, project_id: str) -> list[dict[str, Any]]:
        project = self.load_project(project_id)
        return canonical_intent_groups(project)

    def rebuild_intent_groups(self, project_id: str) -> Project:
        project = self.load_project(project_id)
        project.intent_groups = rebuild_intent_groups_from_archive(project)
        allowed_keywords = set(project_allowed_keywords(project, self.project_dir(project_id)))
        if allowed_keywords:
            for group in project.intent_groups:
                group["keywords"] = [keyword for keyword in group.get("keywords", []) if keyword in allowed_keywords]
        ensure_project_intent_groups(project)
        self.save_project(project)
        self.log(project_id, "从已归档文章重建标准意图簇库")
        return project

    def update_intent_group(self, project_id: str, group_id: str, payload: dict[str, Any]) -> Project:
        project = self.load_project(project_id)
        payload = {**payload, "allowed_keywords": project_allowed_keywords(project, self.project_dir(project_id))}
        update_intent_group(project, group_id, payload)
        self.save_project(project)
        self.log(project_id, f"更新标准意图簇：{group_id}")
        return project

    def create_intent_group(self, project_id: str, payload: dict[str, Any]) -> Project:
        project = self.load_project(project_id)
        payload = {**payload, "allowed_keywords": project_allowed_keywords(project, self.project_dir(project_id))}
        group = create_intent_group(project, payload)
        self.save_project(project)
        self.log(project_id, f"新建标准意图簇：{group['name']}")
        return project

    def merge_intent_group(self, project_id: str, group_id: str, source_group_ids: list[str]) -> Project:
        project = self.load_project(project_id)
        merge_intent_groups(project, group_id, source_group_ids)
        self.save_project(project)
        self.log(project_id, f"合并标准意图簇：{','.join(source_group_ids)} -> {group_id}")
        return project

    def create_custom_sources(self, project_id: str, payload: dict[str, Any]) -> Project:
        project = self.load_project(project_id)
        item_payloads = custom_batch_items(payload)
        if not item_payloads:
            raise ValueError("请至少填写一个自定义文章标题。")
        existing_ids = {source.source_id for source in project.custom_sources}
        next_sources: list[CustomSource] = []
        next_ids: set[str] = set()
        for source_payload in item_payloads:
            source = normalize_custom_source(project, source_payload, project_dir=self.project_dir(project_id))
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
        target_source = next((source for source in project.custom_sources if source.source_id == target_id), None)
        if target_source is None:
            raise FileNotFoundError(f"Custom source not found: {source_id}")
        preserve_existing_id = False
        has_brief = custom_source_has_brief(project, target_id)
        if has_brief:
            if target_source.intent_group:
                raise ValueError("该自定义文章已生成 Brief，请在 Brief 审核页修改。")
            requested_title = clean_custom_text(payload.get("title")) or target_source.title
            requested_type = clean_custom_text(payload.get("type")) or target_source.type
            if requested_title != target_source.title or requested_type != target_source.type:
                raise ValueError("该自定义文章已生成 Brief，请仅修正意图簇，其他内容请在 Brief 审核页修改。")
            preserve_existing_id = True
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
                project_dir=self.project_dir(project_id),
            )
            if preserve_existing_id:
                next_source.id = source.id
                next_source.source_id = source.source_id
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
        intent_groups = project_intent_group_names(project)
        if not intent_groups:
            raise ValueError("请先生成或导入内容矩阵，再导入 Markdown 定稿。")

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
            resolved_group = resolve_intent_group(
                project,
                group_id=article.get("intent_group_id") or article.get("intentGroupId"),
                name=article.get("intent_group") or article.get("intentGroup"),
                keyword=keyword,
            )
            intent_group_id = resolved_group["intent_group_id"]
            intent_group = resolved_group["intent_group"]
            if not intent_group and keyword:
                intent_group = item_intent_group({"keyword": keyword}, project.steps["matrix"].output if "matrix" in project.steps else {})
                if intent_group == "未归类意图簇" and keyword in set(intent_groups):
                    intent_group = keyword
                resolved_group = resolve_intent_group(project, name=intent_group, keyword=keyword)
                intent_group_id = resolved_group["intent_group_id"]
                intent_group = resolved_group["intent_group"] or intent_group
            article_type = clean_import_text(article.get("type") or article.get("article_type"))
            if not intent_group or intent_group == UNCATEGORIZED_INTENT_GROUP:
                raise ValueError(f"请选择意图簇：{filename}")
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
                    "intent_group_id": intent_group_id,
                    "intent_group": intent_group,
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

    def delete_article(self, project_id: str, article_id: str) -> Project:
        project = self.load_project(project_id)
        target_id = str(article_id or "").strip()
        if not target_id:
            raise FileNotFoundError("Article not found.")

        state = project.steps["article"]
        output = dict(state.output or {})
        items = output.get("items") if isinstance(output.get("items"), list) else []
        kept_items: list[dict[str, Any]] = []
        deleted_title = ""
        found = False
        for item in items:
            if not isinstance(item, dict):
                continue
            current_id = str(item.get("id") or item.get("article_id") or item.get("articleId") or "").strip()
            if current_id == target_id:
                found = True
                deleted_title = str(item.get("title") or item.get("article_title") or target_id).strip() or target_id
                continue
            kept_items.append(item)
        if not found:
            raise FileNotFoundError(f"Article not found: {article_id}")

        now = utc_now()
        output["items"] = kept_items
        output["status"] = "completed" if kept_items else "empty"
        output["updated_at"] = now
        state.output = output
        state.status = "completed" if kept_items else "pending"
        state.error = None
        state.updated_at = now
        project.steps["article"] = state
        self.save_project(project)
        self.log(project_id, f"删除定稿正文：{deleted_title}")
        return project

    def delete_briefs(self, project_id: str, brief_ids: list[str]) -> Project:
        project = self.load_project(project_id)
        requested_ids = {str(item or "").strip() for item in brief_ids if str(item or "").strip()}
        if not requested_ids:
            raise ValueError("请选择要删除的 Brief。")

        brief_state = project.steps["brief"]
        brief_output = dict(brief_state.output or {})
        brief_items = output_items_from_mapping(brief_output)
        matched_ids: set[str] = set()
        kept_briefs: list[dict[str, Any]] = []
        deleted_titles: list[str] = []

        for item in brief_items:
            identifiers = {str(item.get(field) or "").strip() for field in ("id", "source_id") if item.get(field)}
            if identifiers & requested_ids:
                matched_ids.update(identifier for identifier in identifiers if identifier)
                deleted_titles.append(str(item.get("title") or item.get("source_id") or item.get("id") or "Brief").strip())
                continue
            kept_briefs.append(item)

        if not deleted_titles:
            raise FileNotFoundError("Brief not found.")

        article_items = output_items_from_mapping(project.steps["article"].output if "article" in project.steps else {})
        related_articles = [
            item
            for item in article_items
            if str(item.get("brief_id") or "").strip() in matched_ids
        ]
        if related_articles:
            raise ValueError("选中的 Brief 已生成正文，请先在正文审核页删除关联正文。")

        now = utc_now()
        brief_output["items"] = kept_briefs
        brief_output["status"] = "completed" if kept_briefs else "empty"
        brief_output["updated_at"] = now
        brief_state.output = brief_output
        brief_state.status = "completed" if kept_briefs else "pending"
        brief_state.error = None
        brief_state.updated_at = now
        project.steps["brief"] = brief_state
        self.save_project(project)
        self.log(project_id, f"删除 Brief：{len(deleted_titles)} 篇")
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
    project_dir: Path | None = None,
) -> CustomSource:
    title = required_custom_text(payload, "title", "标题")
    raw_payload = raw if raw is not None else payload.get("raw") if isinstance(payload.get("raw"), dict) else {}
    copied_source = copied_custom_source(project, raw_payload)
    resolved_group = require_custom_intent_group(project, payload)
    intent_group_id = resolved_group["intent_group_id"]
    intent_group = resolved_group["intent_group"]
    keyword = clean_custom_text(payload.get("keyword"))
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
            "intent_group": intent_group,
            "intent_group_id": intent_group_id,
            "keyword": keyword,
            "type": article_type,
            "source": "copied_source" if copied_source else "project_context",
        },
    }
    return CustomSource(
        id=custom_id,
        source_id=custom_id,
        intent_group_id=intent_group_id,
        intent_group=intent_group,
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


def require_custom_intent_group(project: Project, payload: dict[str, Any]) -> dict[str, str]:
    keyword = clean_custom_text(payload.get("keyword"))
    resolved = resolve_intent_group(
        project,
        group_id=payload.get("intent_group_id") or payload.get("intentGroupId"),
        name=payload.get("intent_group") or payload.get("intentGroup"),
        keyword=keyword,
    )
    intent_group = resolved["intent_group_id"] and resolved["intent_group"]
    if not intent_group:
        requested = normalize_intent_group_to_project(clean_custom_text(payload.get("intent_group") or payload.get("intentGroup")), project)
        if requested:
            resolved = {"intent_group_id": "", "intent_group": requested}
            intent_group = requested
    if not intent_group:
        if keyword:
            mapped = item_intent_group({"keyword": keyword}, project.steps["matrix"].output if "matrix" in project.steps else {})
            if mapped and mapped != "未归类意图簇":
                mapped_resolved = resolve_intent_group(project, name=mapped, keyword=keyword)
                resolved = mapped_resolved if mapped_resolved["intent_group_id"] else {"intent_group_id": "", "intent_group": normalize_intent_group_to_project(mapped, project) or mapped}
                intent_group = resolved["intent_group"]
            elif keyword in set(project_intent_group_names(project)):
                resolved = resolve_intent_group(project, name=keyword, keyword=keyword)
                intent_group = resolved["intent_group"] or keyword
    if not intent_group:
        raise ValueError("请选择自定义文章对应的意图簇。")
    return resolved if resolved["intent_group_id"] else {"intent_group_id": "", "intent_group": intent_group}


def normalize_intent_group_to_project(value: str, project: Project) -> str:
    names = project_intent_group_names(project)
    if not value:
        return ""
    if value in set(names):
        return value
    compact = compact_custom_text(value)
    for name in names:
        if compact_custom_text(name) == compact:
            return name
    return ""


def project_intent_group_names(project: Project) -> list[str]:
    canonical_names = [clean_custom_text(group.get("name")) for group in project.intent_groups if isinstance(group, dict) and clean_custom_text(group.get("name"))]
    if canonical_names:
        return canonical_names
    matrix_output = project.steps["matrix"].output if "matrix" in project.steps else {}
    groups = matrix_output.get("intent_groups") if isinstance(matrix_output, dict) else []
    names: list[str] = []
    seen: set[str] = set()
    for group in groups if isinstance(groups, list) else []:
        if not isinstance(group, dict):
            continue
        name = clean_custom_text(group.get("name") or group.get("intent_group") or group.get("id"))
        if not name or name in seen:
            continue
        names.append(name)
        seen.add(name)
    for item in matrix_output.get("items", []) if isinstance(matrix_output, dict) and isinstance(matrix_output.get("items"), list) else []:
        if not isinstance(item, dict):
            continue
        name = item_intent_group(item, matrix_output)
        if name == "未归类意图簇":
            name = clean_custom_text(item.get("keyword") or item.get("target_keyword") or item.get("目标关键词"))
        if name and name not in seen:
            names.append(name)
            seen.add(name)
    return names


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


def custom_batch_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items = payload.get("items")
    if isinstance(items, list):
        normalized: list[dict[str, Any]] = []
        seen_titles: set[str] = set()
        base = {key: value for key, value in payload.items() if key != "items"}
        for item in items:
            if not isinstance(item, dict):
                continue
            title = clean_custom_text(item.get("title"))
            if not title or title in seen_titles:
                continue
            row = {key: value for key, value in item.items() if value not in ("", [], {})}
            normalized.append({**base, **row, "title": title})
            seen_titles.add(title)
        return normalized
    return [{**payload, "title": title} for title in unique_custom_titles(payload.get("titles"))]


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
    for step in ("matrix",):
        for row in iter_custom_dicts(project.steps[step].output):
            row_id = clean_custom_text(row.get("source_id") or row.get("sourceId") or row.get("id"))
            if row_id == copied_id:
                return {**row, **copied}
    return copied


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


def output_items_from_mapping(output: Any) -> list[dict[str, Any]]:
    if not isinstance(output, dict):
        return []
    value = output.get("items")
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(output.get("markdown"), str) and output.get("markdown"):
        return [dict(output)]
    return []

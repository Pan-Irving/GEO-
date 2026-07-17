import hashlib
from pathlib import Path
from typing import Any


STEP_REFERENCES = {
    "intake": ["material-intake-rules.md"],
    "matrix": [
        "geo-semantic-content-matrix-planner.md",
        "pillar-title-rules.md",
        "listicle-title-rules.md",
        "comparison-title-rules.md",
        "scenario-title-rules.md",
        "product-evidence-title-rules.md",
        "faq-title-rules.md",
    ],
    "breakthrough": [
        "geo-semantic-content-matrix-planner.md",
        "pillar-title-rules.md",
        "listicle-title-rules.md",
        "comparison-title-rules.md",
        "scenario-title-rules.md",
        "product-evidence-title-rules.md",
        "faq-title-rules.md",
    ],
    "brief": ["geo-semantic-content-matrix-planner.md"],
    "article": [],
}

ARTICLE_TYPE_REFERENCES = {
    "支柱标准文": {
        "brief": ["pillar-title-rules.md", "pillar-brief-rules.md"],
        "article": ["pillar-article-rules.md"],
    },
    "榜单推荐文": {
        "brief": ["listicle-title-rules.md", "listicle-brief-rules.md"],
        "article": ["listicle-article-rules.md"],
    },
    "横评对比文": {
        "brief": ["comparison-title-rules.md", "comparison-brief-rules.md"],
        "article": ["comparison-article-rules.md"],
    },
    "场景选购文": {
        "brief": ["scenario-title-rules.md", "scenario-brief-rules.md"],
        "article": ["scenario-article-rules.md"],
    },
    "产品证据文": {
        "brief": ["product-evidence-title-rules.md", "product-evidence-brief-rules.md"],
        "article": ["product-evidence-article-rules.md"],
    },
    "FAQ问答文": {
        "brief": ["faq-title-rules.md", "faq-brief-rules.md"],
        "article": ["faq-title-rules.md", "faq-brief-rules.md"],
    },
}

ARTICLE_TYPE_ALIASES = {
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

FAQ_ARTICLE_GUIDANCE = """
# FAQ 正文生成补充约束
FAQ 没有独立正文规则文件。生成 FAQ 正文时，必须沿用 FAQ 标题与 Brief 规则，把集合级 Brief 和逐条答案要点展开为可发布的问答内容：
- 每条问题必须一题一意图，问题本身能脱离上下文独立成立。
- 每条答案先给一句可被引用的直接结论，再用 50-150 字补充依据、边界和实体植入。
- 不输出内部 Brief 字段名、执行说明或 GEO/AI推荐信号等后台话术。
"""


class SkillLoader:
    def __init__(self, skill_root: Path):
        self.skill_root = skill_root

    def available(self) -> bool:
        return (self.skill_root / "SKILL.md").exists()

    def load_main(self) -> str:
        return self._read(self.skill_root / "SKILL.md")

    def load_for_step(self, step: str, payload: dict[str, Any] | None = None) -> str:
        payload = payload or {}
        blocks = [self.load_main()]
        references = list(STEP_REFERENCES.get(step, []))
        snapshot_rules = self._snapshot_rules(step, payload)
        if not snapshot_rules:
            references.extend(self._article_type_references(step, payload))
        for name in unique_preserving_order(references):
            blocks.append(self._read(self.skill_root / "references" / name))
        for rule in snapshot_rules:
            article_type = rule.get("article_type") or "未分类"
            source = rule.get("source") or "内置规则"
            blocks.append(f"# {article_type} · 本次{step}规则（{source}）\n\n{rule['content']}")
        if step == "article" and "FAQ问答文" in self._selected_article_types(payload):
            blocks.append(FAQ_ARTICLE_GUIDANCE.strip())
        return "\n\n---\n\n".join(blocks)

    def builtin_slot_content(self, article_type: str, stage: str) -> str:
        names = ARTICLE_TYPE_REFERENCES.get(article_type, {}).get(stage, [])
        if not names:
            return ""
        return "\n\n---\n\n".join(self._read(self.skill_root / "references" / name) for name in names)

    @staticmethod
    def _snapshot_rules(step: str, payload: dict[str, Any]) -> list[dict[str, str]]:
        if step not in {"brief", "article"}:
            return []
        snapshot = payload.get("skill_snapshot")
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("rules"), list):
            return []
        return [
            {key: str(rule.get(key) or "") for key in ("article_type", "source", "content")}
            for rule in snapshot["rules"]
            if isinstance(rule, dict) and str(rule.get("content") or "").strip()
        ]

    def _article_type_references(self, step: str, payload: dict[str, Any]) -> list[str]:
        if step not in {"brief", "article"}:
            return []
        references: list[str] = []
        for article_type in self._selected_article_types(payload):
            references.extend(ARTICLE_TYPE_REFERENCES.get(article_type, {}).get(step, []))
        return references

    @staticmethod
    def _selected_article_types(payload: dict[str, Any]) -> list[str]:
        selected = payload.get("selected_briefs") or payload.get("selected_sources") or payload.get("selected_articles")
        if not isinstance(selected, list):
            selected = []
        article_types: list[str] = []
        for item in selected:
            if not isinstance(item, dict):
                continue
            raw_type = str(item.get("type") or item.get("article_type") or item.get("文章类型") or "").strip()
            article_type = normalize_article_type(raw_type)
            if article_type:
                article_types.append(article_type)
        return unique_preserving_order(article_types)

    @staticmethod
    def _read(path: Path) -> str:
        if not path.exists():
            raise FileNotFoundError(f"Missing skill file: {path}")
        return path.read_text(encoding="utf-8")


def normalize_article_type(value: str) -> str:
    if value in ARTICLE_TYPE_REFERENCES:
        return value
    lowered = value.lower()
    if lowered in ARTICLE_TYPE_ALIASES:
        return ARTICLE_TYPE_ALIASES[lowered]
    return ARTICLE_TYPE_ALIASES.get(value, "")


def unique_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


class SkillResolver:
    """Resolves the active global version once, before a job enters a worker process."""

    def __init__(self, repository: Any, skill_loader: SkillLoader):
        self.repository = repository
        self.skill_loader = skill_loader

    def snapshot_for_step(self, step: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        if step not in {"brief", "article"}:
            return None
        rules: list[dict[str, str]] = []
        fallback_slots: list[str] = []
        for article_type in self.skill_loader._selected_article_types(payload):
            selected = self.repository.read_active_skill_slot(article_type, step)
            if selected:
                content, slot = selected
                rules.append(
                    {
                        "article_type": article_type,
                        "source": f"已上传规则：{slot.get('filename') or '未命名'}",
                        "filename": str(slot.get("filename") or ""),
                        "sha256": str(slot.get("sha256") or hashlib.sha256(content.encode("utf-8")).hexdigest()),
                        "content": content,
                    }
                )
                continue
            content = self.skill_loader.builtin_slot_content(article_type, step)
            if content:
                fallback_slots.append(f"{article_type}:{step}")
                rules.append(
                    {
                        "article_type": article_type,
                        "source": "内置默认规则（回退）",
                        "filename": "",
                        "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                        "content": content,
                    }
                )
        return {
            "version_id": "per-slot",
            "version_name": "按槽位规则选择",
            "rules": rules,
            "fallback_slots": fallback_slots,
        }

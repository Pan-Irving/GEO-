from pathlib import Path


STEP_REFERENCES = {
    "intake": ["auto-intake-schema.md"],
    "matrix": ["geo-content-matrix-planner.md"],
    "breakthrough": ["geo-keyword-breakthrough-planner.md"],
    "brief": ["article-brief-generator.md"],
    "article": ["article-draft-generator.md"],
    "rewrite": ["article-draft-generator.md"],
}


class SkillLoader:
    def __init__(self, skill_root: Path):
        self.skill_root = skill_root

    def available(self) -> bool:
        return (self.skill_root / "SKILL.md").exists()

    def load_main(self) -> str:
        return self._read(self.skill_root / "SKILL.md")

    def load_for_step(self, step: str) -> str:
        blocks = [self.load_main()]
        for name in STEP_REFERENCES.get(step, []):
            blocks.append(self._read(self.skill_root / "references" / name))
        return "\n\n---\n\n".join(blocks)

    @staticmethod
    def _read(path: Path) -> str:
        if not path.exists():
            raise FileNotFoundError(f"Missing skill file: {path}")
        return path.read_text(encoding="utf-8")

"""Reusable Rune skill discovery."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from rune.config import DEFAULT_CONFIG_DIR


@dataclass
class SkillInfo:
    name: str
    path: Path
    scope: str
    description: str


class SkillStore:
    """Finds SKILL.md files from global and project skill directories."""

    def __init__(self, cwd: str | None = None) -> None:
        self.cwd = Path(cwd or os.getcwd()).expanduser().resolve()

    def roots(self) -> list[tuple[str, Path]]:
        return [
            ("global", DEFAULT_CONFIG_DIR / "skills"),
            ("project", self.cwd / ".rune" / "skills"),
        ]

    def list(self) -> List[SkillInfo]:
        skills: List[SkillInfo] = []
        for scope, root in self.roots():
            if not root.exists():
                continue
            for path in sorted(root.glob("*/SKILL.md")):
                skills.append(
                    SkillInfo(
                        name=path.parent.name,
                        path=path,
                        scope=scope,
                        description=_extract_description(path),
                    )
                )
        return skills

    def find(self, name: str) -> Optional[SkillInfo]:
        for skill in self.list():
            if skill.name == name:
                return skill
        return None

    def manifest_section(self) -> str:
        skills = self.list()
        if not skills:
            return ""
        lines = [
            "=== Rune Skills ===",
            "以下是可复用工作流 Skill。若用户请求与某个 Skill 匹配，请先调用 skill_read 读取完整 SKILL.md，再按其中步骤执行。",
            "",
        ]
        for skill in skills:
            lines.append(f"- {skill.name} ({skill.scope}): {skill.description}")
        return "\n".join(lines)


def _extract_description(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""

    lines = [line.strip() for line in text.splitlines()]
    for line in lines:
        if not line or line.startswith("#"):
            continue
        return line[:240]
    return ""

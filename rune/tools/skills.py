"""Tools for reading Rune Skills."""

from __future__ import annotations

from rune.skills import SkillStore
from rune.tools.base import PermissionLevel, ToolDefinition


def skill_list() -> str:
    skills = SkillStore().list()
    if not skills:
        return "No Rune skills found. Add SKILL.md files under ~/.rune/skills/<name>/ or .rune/skills/<name>/."
    return "\n".join(
        f"{skill.name} ({skill.scope}) — {skill.description}\n  {skill.path}"
        for skill in skills
    )


def skill_read(name: str) -> str:
    skill = SkillStore().find(name)
    if not skill:
        return f"Error: Skill not found — {name}"
    try:
        content = skill.path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"Error reading skill: {exc}"
    return f"--- Skill: {skill.name} ({skill.scope}) ---\nPath: {skill.path}\n\n{content}"


TOOLS = [
    ToolDefinition(
        name="skill_list",
        description="List available Rune skills from global and project skill directories.",
        parameters={"type": "object", "properties": {}, "required": []},
        permission_level=PermissionLevel.GREEN,
        handler=skill_list,
    ),
    ToolDefinition(
        name="skill_read",
        description="Read the full SKILL.md for a named Rune skill before applying its workflow.",
        parameters={
            "type": "object",
            "properties": {"name": {"type": "string", "description": "Skill name"}},
            "required": ["name"],
        },
        permission_level=PermissionLevel.GREEN,
        handler=skill_read,
    ),
]

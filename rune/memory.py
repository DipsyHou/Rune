"""
Layered memory and instruction files for Rune.

This is the lightweight equivalent of Claude Code's CLAUDE.md layers:
- global user memory: ~/.rune/MEMORY.md
- project instructions: <cwd>/.rune/RUNE.md
- local private project notes: <cwd>/.rune/local.md
- project auto-memory index: ~/.rune/projects/<project-key>/memory/MEMORY.md
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import List

from rune.config import DEFAULT_CONFIG_DIR
from rune.session import _project_key

MAX_LAYER_CHARS = 20_000


@dataclass
class MemoryLayer:
    name: str
    description: str
    path: Path
    required: bool = False


class MemoryStore:
    """Loads Rune memory/instruction layers for prompt injection."""

    def __init__(self, cwd: str | None = None) -> None:
        self.cwd = Path(cwd or os.getcwd()).expanduser().resolve()
        self.project_key = _project_key(str(self.cwd))

    def layers(self) -> List[MemoryLayer]:
        project_rune = self.cwd / ".rune"
        project_memory = DEFAULT_CONFIG_DIR / "projects" / self.project_key / "memory"
        return [
            MemoryLayer(
                name="Global Memory",
                description="用户全局偏好和长期规则，跨项目生效",
                path=DEFAULT_CONFIG_DIR / "MEMORY.md",
            ),
            MemoryLayer(
                name="Project Instructions",
                description="当前项目的共享规则，适合提交到仓库",
                path=project_rune / "RUNE.md",
            ),
            MemoryLayer(
                name="Local Project Memory",
                description="当前项目的本地私有规则，不建议提交",
                path=project_rune / "local.md",
            ),
            MemoryLayer(
                name="Auto Memory Index",
                description="当前项目的长期记忆索引，后续自动记忆会写到这里",
                path=project_memory / "MEMORY.md",
            ),
        ]

    def ensure_layer(self, layer: MemoryLayer) -> None:
        layer.path.parent.mkdir(parents=True, exist_ok=True)
        if layer.path.exists():
            return
        layer.path.write_text(_template_for(layer), encoding="utf-8")

    def ensure_all(self) -> None:
        for layer in self.layers():
            self.ensure_layer(layer)

    def get_system_prompt_section(self) -> str:
        sections: List[str] = []
        for layer in self.layers():
            if not layer.path.exists() or not layer.path.is_file():
                continue
            try:
                content = layer.path.read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                continue
            if not content:
                continue
            if len(content) > MAX_LAYER_CHARS:
                content = (
                    content[:MAX_LAYER_CHARS]
                    + f"\n\n... (truncated at {MAX_LAYER_CHARS} characters)"
                )
            sections.append(
                f"--- {layer.name}: {layer.path} ---\n{content}"
            )

        if not sections:
            return ""

        return (
            "=== Rune 分层记忆与项目指令 ===\n"
            "以下内容是用户或项目提供的长期上下文。请优先遵守项目指令；"
            "若记忆内容涉及当前文件/系统状态，请先用工具验证再行动。\n\n"
            + "\n\n".join(sections)
        )


def _template_for(layer: MemoryLayer) -> str:
    if layer.name == "Global Memory":
        return (
            "# Rune Global Memory\n\n"
            "记录跨项目生效的用户偏好、沟通方式和长期规则。\n\n"
            "- 示例：用户希望回复简洁，除非明确要求详细解释。\n"
        )
    if layer.name == "Project Instructions":
        return (
            "# Rune Project Instructions\n\n"
            "记录当前项目中 Rune 应该遵守的共享规则。\n\n"
            "- 示例：运行测试前先进入项目根目录。\n"
        )
    if layer.name == "Local Project Memory":
        return (
            "# Rune Local Project Memory\n\n"
            "记录仅在本机生效的项目偏好或私有路径，不建议提交到仓库。\n\n"
        )
    return (
        "# Rune Auto Memory Index\n\n"
        "这是当前项目的长期记忆索引。后续可将自动提取出的记忆链接到这里。\n\n"
    )

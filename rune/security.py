"""
Rune Security Manager.

Implements a three-tier permission gate:
  GREEN  → auto-execute (silent)
  YELLOW → execute with notification (optionally require confirmation)
  RED    → always require explicit user confirmation

Also provides a command-blocklist check for shell execution tools.
"""

from __future__ import annotations

import json
from typing import Any, Dict

from rich.console import Console
from rich.panel import Panel

from rune.config import RuneConfig, SecurityConfig
from rune.tools.base import PermissionLevel, ToolDefinition

console = Console()


class SecurityManager:
    """Gate-keeper that sits between the AI agent and tool execution."""

    def __init__(self, config: RuneConfig) -> None:
        self.sec: SecurityConfig = config.security

    # ---- public interface ----

    def check_permission(
        self, tool: ToolDefinition, args: Dict[str, Any]
    ) -> bool:
        """
        Decide whether *tool* may be executed with *args*.

        Returns True  → proceed with execution
        Returns False → the agent will receive "Operation cancelled by user"
        """
        level = tool.permission_level

        # 1.  Blocklist check (applies mainly to shell commands)
        if not self._blocklist_check(tool, args):
            console.print(
                f"  [bold red]⛔ BLOCKED[/bold red] — {tool.name} "
                f"matched a dangerous command pattern. Refusing to execute."
            )
            return False

        # 2. User-defined allow/deny/ask rules override default levels.
        rule_action = self._matching_rule_action(tool, args)
        if rule_action == "deny":
            console.print(f"  [bold red]⛔ DENIED[/bold red] — matched permission rule.")
            return False
        if rule_action == "allow":
            return True
        if rule_action == "ask":
            return self._prompt_user(tool, args)

        # 3.  Permission-level gate
        if level == PermissionLevel.GREEN:
            return True

        if level == PermissionLevel.YELLOW:
            if self.sec.require_confirmation_for_yellow:
                return self._prompt_user(tool, args)
            return True

        if level == PermissionLevel.RED:
            if self.sec.require_confirmation_for_red:
                return self._prompt_user(tool, args)
            return True

        return True  # unknown level → allow

    # ---- internal helpers ----

    def _blocklist_check(self, tool: ToolDefinition, args: Dict[str, Any]) -> bool:
        """Return False if any argument contains a blocked command substring."""
        # Combine all string argument values into one haystack
        haystack = " ".join(
            str(v) for v in args.values() if isinstance(v, str)
        ).lower()

        for pattern in self.sec.blocked_commands:
            if pattern.lower() in haystack:
                return False
        return True

    def _matching_rule_action(self, tool: ToolDefinition, args: Dict[str, Any]) -> str | None:
        """Return the first matching user permission rule action, if any."""
        haystack = json.dumps(args, ensure_ascii=False).lower()
        for rule in self.sec.permission_rules:
            if not isinstance(rule, dict):
                continue
            action = str(rule.get("action", "")).lower()
            if action not in {"allow", "deny", "ask"}:
                continue

            tool_pattern = str(rule.get("tool", "*"))
            if tool_pattern not in ("*", tool.name):
                continue

            contains = str(rule.get("contains", "")).strip().lower()
            if contains and contains not in haystack:
                continue

            return action
        return None

    @staticmethod
    def _prompt_user(tool: ToolDefinition, args: Dict[str, Any]) -> bool:
        """Show a rich confirmation panel and wait for y/n."""
        pretty_args = json.dumps(args, ensure_ascii=False, indent=2)

        level_label = tool.permission_level.value.upper()
        level_colour = "red" if tool.permission_level == PermissionLevel.RED else "yellow"

        panel_content = (
            f"[bold {level_colour}]⚠️  AI 请求执行以下操作:[/bold {level_colour}]\n\n"
            f"  工具: [bold]{tool.name}[/bold]\n"
            f"  参数:\n{_indent(pretty_args, 4)}\n"
            f"  风险等级: [bold {level_colour}]{level_label}[/bold {level_colour}]"
        )

        console.print(Panel(panel_content, title="🔒 安全确认", border_style=level_colour))
        answer = console.input("[bold]允许执行? (y/n): [/bold]").strip().lower()
        approved = answer in ("y", "yes", "是")
        if not approved:
            console.print("  [dim]已取消。[/dim]")
        return approved


def _indent(text: str, spaces: int) -> str:
    prefix = " " * spaces
    return "\n".join(prefix + line for line in text.splitlines())

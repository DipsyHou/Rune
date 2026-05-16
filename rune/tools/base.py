"""
Base definitions for Rune tools.

Every tool module under rune/tools/ exposes a module-level `TOOLS` list
containing ToolDefinition instances.  The registry discovers them automatically.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict


class PermissionLevel(Enum):
    """
    Three-tier permission model.

    GREEN  - Safe, read-only or low-risk  → auto-execute
    YELLOW - Moderate risk (file writes)  → notify user (optionally confirm)
    RED    - High risk (delete, kill, …)  → always require explicit confirmation
    """

    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"


@dataclass
class ToolDefinition:
    """Describes a single tool that the AI agent can invoke."""

    name: str
    description: str
    parameters: Dict[str, Any]  # JSON Schema
    permission_level: PermissionLevel
    handler: Callable[..., str]

    def to_openai_tool(self) -> dict:
        """Serialize to the OpenAI function-calling tool format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

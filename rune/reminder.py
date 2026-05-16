"""
Rune Reminder Store — Persistent user memos for the AI agent.

Reminders are stored in ~/.rune/reminders.yaml and injected into the
AI system prompt on every turn, so the agent always "remembers" them.

Users can manage reminders via:
  - The ``reminder`` CLI command (interactive)
  - Directly editing ~/.rune/reminders.yaml
  - Asking the AI to add/remove/edit reminders (controlled by
    ``security.allow_ai_edit_reminders``)
"""

from __future__ import annotations

import datetime
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from rune.config import DEFAULT_CONFIG_DIR

REMINDERS_FILE = DEFAULT_CONFIG_DIR / "reminders.yaml"


class ReminderStore:
    """Manages a list of persistent reminders."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = path or REMINDERS_FILE
        self._items: List[Dict[str, Any]] = []
        self.load()

    # ---- persistence ----

    def load(self) -> None:
        """Load reminders from YAML file."""
        if self.path.exists():
            try:
                with open(self.path, encoding="utf-8") as fh:
                    data = yaml.safe_load(fh)
                if isinstance(data, list):
                    self._items = data
                else:
                    self._items = []
            except Exception:
                self._items = []
        else:
            self._items = []

    def save(self) -> None:
        """Persist reminders to YAML file."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as fh:
            yaml.dump(
                self._items,
                fh,
                default_flow_style=False,
                allow_unicode=True,
            )

    # ---- CRUD ----

    def list_all(self) -> List[Dict[str, Any]]:
        """Return a copy of all reminder items."""
        return list(self._items)

    def add(self, text: str) -> Dict[str, Any]:
        """Add a new reminder and persist. Returns the created item."""
        item: Dict[str, Any] = {
            "id": uuid.uuid4().hex[:8],
            "text": text,
            "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        self._items.append(item)
        self.save()
        return item

    def remove(self, index: int) -> Optional[Dict[str, Any]]:
        """Remove a reminder by 0-based index. Returns removed item or None."""
        if 0 <= index < len(self._items):
            removed = self._items.pop(index)
            self.save()
            return removed
        return None

    def edit(self, index: int, new_text: str) -> Optional[Dict[str, Any]]:
        """Edit the text of a reminder by 0-based index. Returns updated item or None."""
        if 0 <= index < len(self._items):
            self._items[index]["text"] = new_text
            self.save()
            return self._items[index]
        return None

    def count(self) -> int:
        return len(self._items)

    # ---- formatted output ----

    def get_system_prompt_section(self) -> str:
        """Return a formatted string suitable for injection into the system prompt.

        Returns empty string if there are no reminders.
        """
        if not self._items:
            return ""
        lines = ["=== 用户备忘录 (Reminders) ==="]
        lines.append("以下是用户希望你始终记住的事项：")
        for i, item in enumerate(self._items, 1):
            lines.append(f"  {i}. {item['text']}  [添加于 {item.get('created_at', '未知')}]")
        lines.append("")
        return "\n".join(lines)

    def get_display_text(self) -> str:
        """Return a human-readable display for the CLI."""
        if not self._items:
            return "[dim](暂无备忘录)[/dim]"
        lines: list[str] = []
        for i, item in enumerate(self._items, 1):
            lines.append(
                f"  [bold]{i}.[/bold] {item['text']}\n"
                f"     [dim]ID: {item.get('id', '?')}  |  添加于: {item.get('created_at', '未知')}[/dim]"
            )
        return "\n".join(lines)

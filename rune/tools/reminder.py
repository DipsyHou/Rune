"""
Reminder management tools for the AI agent.

Allows the AI to list, add, remove, and edit persistent reminders.
Write operations are gated by ``security.allow_ai_edit_reminders``.
"""

from __future__ import annotations

from rune.config import RuneConfig
from rune.reminder import ReminderStore
from .base import PermissionLevel, ToolDefinition


def _get_store() -> ReminderStore:
    """Return a fresh ReminderStore (re-reads from disk)."""
    return ReminderStore()


def _is_edit_allowed() -> bool:
    """Check if AI editing of reminders is allowed in config."""
    config = RuneConfig.load()
    return config.security.allow_ai_edit_reminders


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

def reminder_list() -> str:
    """List all current reminders."""
    store = _get_store()
    items = store.list_all()
    if not items:
        return "当前没有备忘录。"
    lines = [f"共 {len(items)} 条备忘录："]
    for i, item in enumerate(items):
        lines.append(
            f"  [{i}] {item['text']}  (添加于 {item.get('created_at', '未知')})"
        )
    return "\n".join(lines)


def reminder_add(text: str) -> str:
    """Add a new reminder."""
    if not _is_edit_allowed():
        return "⛔ 用户已禁止 AI 编辑备忘录。请让用户在安全设置中开启 allow_ai_edit_reminders。"
    store = _get_store()
    item = store.add(text)
    return f"✅ 备忘录已添加 (ID: {item['id']}): {item['text']}"


def reminder_remove(index: int) -> str:
    """Remove a reminder by its 0-based index."""
    if not _is_edit_allowed():
        return "⛔ 用户已禁止 AI 编辑备忘录。请让用户在安全设置中开启 allow_ai_edit_reminders。"
    store = _get_store()
    removed = store.remove(index)
    if removed:
        return f"✅ 已删除备忘录 [{index}]: {removed['text']}"
    return f"❌ 索引 {index} 无效，当前共有 {store.count()} 条备忘录（索引 0-{store.count() - 1}）。"


def reminder_edit(index: int, new_text: str) -> str:
    """Edit the text of an existing reminder by its 0-based index."""
    if not _is_edit_allowed():
        return "⛔ 用户已禁止 AI 编辑备忘录。请让用户在安全设置中开启 allow_ai_edit_reminders。"
    store = _get_store()
    updated = store.edit(index, new_text)
    if updated:
        return f"✅ 备忘录 [{index}] 已更新为: {updated['text']}"
    return f"❌ 索引 {index} 无效，当前共有 {store.count()} 条备忘录（索引 0-{store.count() - 1}）。"


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS = [
    ToolDefinition(
        name="reminder_list",
        description="列出所有用户备忘录 (reminders)。备忘录是用户希望 AI 始终记住的事项。",
        parameters={"type": "object", "properties": {}, "required": []},
        permission_level=PermissionLevel.GREEN,
        handler=reminder_list,
    ),
    ToolDefinition(
        name="reminder_add",
        description="添加一条新的备忘录。用户告诉你「记住XXX」时使用此工具。",
        parameters={
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "备忘录内容",
                },
            },
            "required": ["text"],
        },
        permission_level=PermissionLevel.YELLOW,
        handler=reminder_add,
    ),
    ToolDefinition(
        name="reminder_remove",
        description="按索引删除一条备忘录。先调用 reminder_list 获取索引。",
        parameters={
            "type": "object",
            "properties": {
                "index": {
                    "type": "integer",
                    "description": "要删除的备忘录索引（从 0 开始）",
                },
            },
            "required": ["index"],
        },
        permission_level=PermissionLevel.YELLOW,
        handler=reminder_remove,
    ),
    ToolDefinition(
        name="reminder_edit",
        description="修改一条已有备忘录的内容。先调用 reminder_list 获取索引。",
        parameters={
            "type": "object",
            "properties": {
                "index": {
                    "type": "integer",
                    "description": "要修改的备忘录索引（从 0 开始）",
                },
                "new_text": {
                    "type": "string",
                    "description": "新的备忘录内容",
                },
            },
            "required": ["index", "new_text"],
        },
        permission_level=PermissionLevel.YELLOW,
        handler=reminder_edit,
    ),
]

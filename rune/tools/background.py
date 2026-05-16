"""Background command tools."""

from __future__ import annotations

from rune.background import manager
from rune.tools.base import PermissionLevel, ToolDefinition


def _tail(lines: list[str], max_lines: int) -> str:
    if len(lines) <= max_lines:
        return "".join(lines).rstrip() or "(no output)"
    hidden = len(lines) - max_lines
    return f"... (hidden {hidden} earlier lines)\n" + "".join(lines[-max_lines:]).rstrip()


def background_run_command(command: str, working_directory: str = "") -> str:
    task = manager.start(command, working_directory)
    return (
        f"Started background task {task.id}\n"
        f"Command: {task.command}\n"
        f"CWD: {task.cwd}\n"
        "Use background_status/background_output to inspect it."
    )


def background_list() -> str:
    tasks = manager.list()
    if not tasks:
        return "No background tasks."
    lines = []
    for task in tasks:
        state = "running" if task.running else f"exited {task.returncode}"
        lines.append(
            f"{task.id}  {state}  {task.elapsed_seconds:.1f}s  "
            f"{task.command}  ({task.cwd})"
        )
    return "\n".join(lines)


def background_status(task_id: str) -> str:
    task = manager.get(task_id)
    if not task:
        return f"Error: background task not found — {task_id}"
    state = "running" if task.running else f"exited {task.returncode}"
    return (
        f"Task: {task.id}\n"
        f"Status: {state}\n"
        f"Elapsed: {task.elapsed_seconds:.1f}s\n"
        f"Command: {task.command}\n"
        f"CWD: {task.cwd}\n"
        f"Stdout lines: {len(task.stdout)}\n"
        f"Stderr lines: {len(task.stderr)}"
    )


def background_output(task_id: str, max_lines: int = 120) -> str:
    task = manager.get(task_id)
    if not task:
        return f"Error: background task not found — {task_id}"
    stdout = _tail(task.stdout, max_lines)
    stderr = _tail(task.stderr, max_lines)
    state = "running" if task.running else f"exited {task.returncode}"
    return f"[{task.id} {state}]\n\n[stdout]\n{stdout}\n\n[stderr]\n{stderr}"


def background_stop(task_id: str) -> str:
    ok = manager.stop(task_id)
    if not ok:
        return f"Error: background task not found — {task_id}"
    return f"Stopped background task {task_id}."


TOOLS = [
    ToolDefinition(
        name="background_run_command",
        description=(
            "Start a shell command in the background and return immediately. "
            "Use for long-running servers, watchers, downloads, or commands you need to poll later."
        ),
        parameters={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to start"},
                "working_directory": {
                    "type": "string",
                    "description": "Working directory (default: current dir)",
                    "default": "",
                },
            },
            "required": ["command"],
        },
        permission_level=PermissionLevel.YELLOW,
        handler=background_run_command,
    ),
    ToolDefinition(
        name="background_list",
        description="List background tasks started in this Rune process.",
        parameters={"type": "object", "properties": {}, "required": []},
        permission_level=PermissionLevel.GREEN,
        handler=background_list,
    ),
    ToolDefinition(
        name="background_status",
        description="Get status and metadata for a background task.",
        parameters={
            "type": "object",
            "properties": {"task_id": {"type": "string", "description": "Background task id"}},
            "required": ["task_id"],
        },
        permission_level=PermissionLevel.GREEN,
        handler=background_status,
    ),
    ToolDefinition(
        name="background_output",
        description="Read recent stdout/stderr from a background task.",
        parameters={
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Background task id"},
                "max_lines": {"type": "integer", "description": "Max lines per stream", "default": 120},
            },
            "required": ["task_id"],
        },
        permission_level=PermissionLevel.GREEN,
        handler=background_output,
    ),
    ToolDefinition(
        name="background_stop",
        description="Terminate a background task.",
        parameters={
            "type": "object",
            "properties": {"task_id": {"type": "string", "description": "Background task id"}},
            "required": ["task_id"],
        },
        permission_level=PermissionLevel.RED,
        handler=background_stop,
    ),
]

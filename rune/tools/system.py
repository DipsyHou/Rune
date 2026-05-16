"""
System information and settings tools.

Provides the AI with awareness of the host system: OS details, hardware,
time, environment variables, and basic system-level controls.
"""

import datetime
import os
import platform
import shutil
from pathlib import Path

from .base import PermissionLevel, ToolDefinition


def get_system_info() -> str:
    """Comprehensive snapshot of the host system."""
    try:
        info: dict[str, str] = {
            "OS": f"{platform.system()} {platform.release()}",
            "OS Version": platform.version(),
            "Architecture": platform.machine(),
            "Hostname": platform.node(),
            "User": os.getenv("USER", os.getenv("USERNAME", "unknown")),
            "Home": str(Path.home()),
            "CWD": os.getcwd(),
            "Python": platform.python_version(),
            "CPU Cores": str(os.cpu_count()),
        }

        # RAM (Linux)
        meminfo = Path("/proc/meminfo")
        if meminfo.exists():
            for line in meminfo.read_text().splitlines():
                if line.startswith("MemTotal"):
                    info["RAM Total"] = f"{int(line.split()[1]) // 1024} MB"
                elif line.startswith("MemAvailable"):
                    info["RAM Available"] = f"{int(line.split()[1]) // 1024} MB"

        # Disk
        total, used, free = shutil.disk_usage("/")
        info["Disk Total"] = f"{total // (1 << 30)} GB"
        info["Disk Used"] = f"{used // (1 << 30)} GB"
        info["Disk Free"] = f"{free // (1 << 30)} GB"

        return "\n".join(f"  {k}: {v}" for k, v in info.items())
    except Exception as exc:
        return f"Error: {exc}"


def get_current_datetime() -> str:
    """Current local time, UTC, and Unix timestamp."""
    now = datetime.datetime.now()
    utc = datetime.datetime.now(datetime.timezone.utc)
    return (
        f"Local : {now.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"UTC   : {utc.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"Epoch : {int(now.timestamp())}"
    )


def get_environment_variable(name: str) -> str:
    val = os.environ.get(name)
    if val is None:
        return f"Environment variable '{name}' is not set."
    # Truncate extremely long values (like PATH)
    if len(val) > 2000:
        val = val[:2000] + "… (truncated)"
    return f"{name}={val}"


def set_environment_variable(name: str, value: str) -> str:
    try:
        os.environ[name] = value
        return f"Success: {name}={value}  (applies to current Rune session only)"
    except Exception as exc:
        return f"Error: {exc}"


def list_environment_variables(filter_prefix: str = "") -> str:
    """List environment variables, optionally filtered by prefix."""
    items = sorted(os.environ.items())
    if filter_prefix:
        items = [(k, v) for k, v in items if k.startswith(filter_prefix)]
    if not items:
        return "No matching environment variables found."
    lines = []
    for k, v in items[:150]:
        short_v = v if len(v) <= 80 else v[:77] + "..."
        lines.append(f"  {k}={short_v}")
    if len(items) > 150:
        lines.append(f"  … and {len(items) - 150} more")
    return "\n".join(lines)


def get_disk_usage(path: str = "/") -> str:
    """Disk usage for a specific mount point."""
    try:
        total, used, free = shutil.disk_usage(path)
        pct = used / total * 100
        return (
            f"  Mount: {path}\n"
            f"  Total: {total // (1 << 30)} GB\n"
            f"  Used : {used // (1 << 30)} GB ({pct:.1f}%)\n"
            f"  Free : {free // (1 << 30)} GB"
        )
    except Exception as exc:
        return f"Error: {exc}"


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS = [
    ToolDefinition(
        name="get_system_info",
        description="Get a comprehensive summary of the host system: OS, CPU, RAM, disk, Python version, current user, etc.",
        parameters={"type": "object", "properties": {}, "required": []},
        permission_level=PermissionLevel.GREEN,
        handler=get_system_info,
    ),
    ToolDefinition(
        name="get_current_datetime",
        description="Get the current date, time (local & UTC), and Unix timestamp.",
        parameters={"type": "object", "properties": {}, "required": []},
        permission_level=PermissionLevel.GREEN,
        handler=get_current_datetime,
    ),
    ToolDefinition(
        name="get_environment_variable",
        description="Read the value of a single environment variable.",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Variable name (e.g. PATH, HOME)"},
            },
            "required": ["name"],
        },
        permission_level=PermissionLevel.GREEN,
        handler=get_environment_variable,
    ),
    ToolDefinition(
        name="set_environment_variable",
        description="Set an environment variable for the current Rune session.",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Variable name"},
                "value": {"type": "string", "description": "Variable value"},
            },
            "required": ["name", "value"],
        },
        permission_level=PermissionLevel.YELLOW,
        handler=set_environment_variable,
    ),
    ToolDefinition(
        name="list_environment_variables",
        description="List all environment variables, optionally filtered by a prefix.",
        parameters={
            "type": "object",
            "properties": {
                "filter_prefix": {
                    "type": "string",
                    "description": "Only show variables whose name starts with this prefix (default: show all)",
                    "default": "",
                },
            },
            "required": [],
        },
        permission_level=PermissionLevel.GREEN,
        handler=list_environment_variables,
    ),
    ToolDefinition(
        name="get_disk_usage",
        description="Show disk usage (total/used/free) for a given mount point.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Mount point path (default: /)", "default": "/"},
            },
            "required": [],
        },
        permission_level=PermissionLevel.GREEN,
        handler=get_disk_usage,
    ),
]

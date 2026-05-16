"""
Process management tools.

Gives the AI the ability to inspect running processes, kill them,
and launch new applications.
"""

import os
import platform
import signal
import subprocess

from .base import PermissionLevel, ToolDefinition


def list_processes(filter_name: str = "", sort_by: str = "cpu") -> str:
    """List running processes, optionally filtered by name."""
    try:
        if platform.system() == "Linux" or platform.system() == "Darwin":
            # Use ps with useful columns
            cmd = "ps aux --sort=-%cpu" if sort_by == "cpu" else "ps aux --sort=-%mem"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
        else:
            result = subprocess.run("tasklist", shell=True, capture_output=True, text=True, timeout=10)

        lines = result.stdout.splitlines()
        if not lines:
            return "No processes found."

        header = lines[0]

        if filter_name:
            body = [l for l in lines[1:] if filter_name.lower() in l.lower()]
        else:
            body = lines[1:]

        # Limit output
        shown = body[:60]
        output = header + "\n" + "\n".join(shown)
        if len(body) > 60:
            output += f"\n\n… ({len(body) - 60} more processes not shown)"

        return output
    except Exception as exc:
        return f"Error: {exc}"


def kill_process(pid: int, force: bool = False) -> str:
    """Send termination signal to a process."""
    try:
        sig = signal.SIGKILL if force else signal.SIGTERM
        os.kill(pid, sig)
        mode = "SIGKILL (force)" if force else "SIGTERM"
        return f"Success: Sent {mode} to PID {pid}"
    except ProcessLookupError:
        return f"Error: No process with PID {pid}"
    except PermissionError:
        return f"Error: Permission denied — cannot kill PID {pid}. Try with sudo?"
    except Exception as exc:
        return f"Error: {exc}"


def launch_application(command: str, background: bool = True) -> str:
    """Launch an application / program."""
    try:
        if background:
            proc = subprocess.Popen(
                command,
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return f"Success: Launched in background — PID {proc.pid}\n  Command: {command}"
        else:
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True, timeout=30
            )
            output = result.stdout[:5000] if result.stdout else "(no output)"
            return f"[exit code {result.returncode}]\n{output}"
    except Exception as exc:
        return f"Error launching application: {exc}"


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS = [
    ToolDefinition(
        name="list_processes",
        description="List running processes. Optionally filter by name and sort by cpu or memory usage.",
        parameters={
            "type": "object",
            "properties": {
                "filter_name": {
                    "type": "string",
                    "description": "Only show processes whose name contains this string (case-insensitive)",
                    "default": "",
                },
                "sort_by": {
                    "type": "string",
                    "enum": ["cpu", "mem"],
                    "description": "Sort by 'cpu' or 'mem' (default: cpu)",
                    "default": "cpu",
                },
            },
            "required": [],
        },
        permission_level=PermissionLevel.GREEN,
        handler=list_processes,
    ),
    ToolDefinition(
        name="kill_process",
        description="Terminate a running process by its PID. Set force=true to send SIGKILL instead of SIGTERM.",
        parameters={
            "type": "object",
            "properties": {
                "pid": {"type": "integer", "description": "Process ID to kill"},
                "force": {
                    "type": "boolean",
                    "description": "Use SIGKILL instead of SIGTERM (default false)",
                    "default": False,
                },
            },
            "required": ["pid"],
        },
        permission_level=PermissionLevel.RED,
        handler=kill_process,
    ),
    ToolDefinition(
        name="launch_application",
        description=(
            "Launch an application or program. By default it runs in the background "
            "and returns the PID. Set background=false to wait for it to finish and "
            "capture output."
        ),
        parameters={
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Command to launch (e.g. 'firefox', 'code .', 'python3 server.py')",
                },
                "background": {
                    "type": "boolean",
                    "description": "Run in background (default true)",
                    "default": True,
                },
            },
            "required": ["command"],
        },
        permission_level=PermissionLevel.YELLOW,
        handler=launch_application,
    ),
]

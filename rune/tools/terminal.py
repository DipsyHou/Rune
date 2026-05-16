"""
Terminal / Shell command tools.

Provides the AI with direct shell access — the most powerful primitive
in the entire Rune toolkit.
"""

import subprocess

from .base import PermissionLevel, ToolDefinition


def _format_result(returncode: int, stdout_text: str, stderr_text: str) -> str:
    parts: list[str] = []

    if stdout_text:
        parts.append(stdout_text)
    if stderr_text:
        parts.append(f"[stderr]\n{stderr_text}")

    output = "\n".join(parts) if parts else "(no output)"
    if len(output) > 15_000:
        output = output[:15_000] + f"\n... (truncated, total {len(output)} chars)"

    return f"[exit code {returncode}]\n{output}"


def _run_with_tee(
    popen_args,
    *,
    shell: bool = False,
    timeout: int = 30,
    working_directory: str = "",
    input_text: str | None = None,
) -> str:
    """Run a subprocess silently and return captured output."""
    try:
        completed = subprocess.run(
            popen_args,
            shell=shell,
            cwd=working_directory or None,
            input=input_text,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return _format_result(completed.returncode, completed.stdout, completed.stderr)
    except subprocess.TimeoutExpired as exc:
        stdout_text = exc.stdout or ""
        stderr_text = exc.stderr or ""
        if isinstance(stdout_text, bytes):
            stdout_text = stdout_text.decode("utf-8", errors="replace")
        if isinstance(stderr_text, bytes):
            stderr_text = stderr_text.decode("utf-8", errors="replace")
        return f"Error: Command timed out after {timeout}s\n\n{_format_result(-1, stdout_text, stderr_text)}"


def run_command(
    command: str,
    timeout: int = 30,
    working_directory: str = "",
) -> str:
    """Execute a single shell command and return combined output."""
    try:
        return _run_with_tee(
            command,
            shell=True,
            timeout=timeout,
            working_directory=working_directory,
        )
    except subprocess.TimeoutExpired:
        return f"Error: Command timed out after {timeout}s"
    except Exception as exc:
        return f"Error: {exc}"


def run_script(
    script: str,
    interpreter: str = "bash",
    timeout: int = 60,
) -> str:
    """Execute a multi-line script via the given interpreter."""
    try:
        return _run_with_tee(
            [interpreter],
            timeout=timeout,
            input_text=script,
        )
    except subprocess.TimeoutExpired:
        return f"Error: Script timed out after {timeout}s"
    except FileNotFoundError:
        return f"Error: Interpreter '{interpreter}' not found"
    except Exception as exc:
        return f"Error: {exc}"


# ---------------------------------------------------------------------------
# Tool definitions exposed to the registry
# ---------------------------------------------------------------------------

TOOLS = [
    ToolDefinition(
        name="run_command",
        description=(
            "Execute a shell command in the system terminal and return its output. "
            "Use this for any system operation: installing packages, compiling code, "
            "checking disk usage, managing services, git operations, etc."
        ),
        parameters={
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Max seconds to wait (default 30)",
                    "default": 30,
                },
                "working_directory": {
                    "type": "string",
                    "description": "Working directory (default: current dir)",
                    "default": "",
                },
            },
            "required": ["command"],
        },
        permission_level=PermissionLevel.YELLOW,
        handler=run_command,
    ),
    ToolDefinition(
        name="run_script",
        description=(
            "Execute a multi-line shell script. Useful when you need to run "
            "several commands together as a single script, with variables, loops, "
            "or conditionals."
        ),
        parameters={
            "type": "object",
            "properties": {
                "script": {
                    "type": "string",
                    "description": "The script content",
                },
                "interpreter": {
                    "type": "string",
                    "description": "Interpreter to use: bash, python3, node, etc. (default: bash)",
                    "default": "bash",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Max seconds to wait (default 60)",
                    "default": 60,
                },
            },
            "required": ["script"],
        },
        permission_level=PermissionLevel.YELLOW,
        handler=run_script,
    ),
]

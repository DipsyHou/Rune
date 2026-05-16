"""
File-system operation tools.

Gives the AI full file-system read/write capabilities with proper
error handling and output truncation.
"""

import datetime
import difflib
import os
import shutil
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from .base import PermissionLevel, ToolDefinition

console = Console()


# ---- helpers ----

def _fmt_size(n: int) -> str:
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {u}"
        n /= 1024  # type: ignore[assignment]
    return f"{n:.1f} PB"


def _resolve(path: str) -> Path:
    return Path(path).expanduser().resolve()


# ---- tool implementations ----

def read_file(path: str, max_lines: int = 500) -> str:
    try:
        p = _resolve(path)
        if not p.exists():
            return f"Error: File not found — {p}"
        if not p.is_file():
            return f"Error: Not a regular file — {p}"

        text = p.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        if len(lines) > max_lines:
            return (
                "\n".join(lines[:max_lines])
                + f"\n\n… (showing first {max_lines} of {len(lines)} lines)"
            )
        return text
    except Exception as exc:
        return f"Error reading file: {exc}"


def write_file(path: str, content: str, append: bool = False) -> str:
    try:
        p = _resolve(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if append else "w"
        with open(p, mode, encoding="utf-8") as fh:
            fh.write(content)
        verb = "Appended to" if append else "Created/overwritten"
        return f"Success: {verb} {p}  ({len(content)} bytes written)"
    except Exception as exc:
        return f"Error writing file: {exc}"


def edit_file(
    path: str,
    old_string: str,
    new_string: str,
    expected_replacements: int = 1,
    dry_run: bool = False,
) -> str:
    """Safely edit a file by replacing an exact string after showing a diff."""
    try:
        p = _resolve(path)
        if not p.exists():
            return f"Error: File not found — {p}"
        if not p.is_file():
            return f"Error: Not a regular file — {p}"
        if not old_string:
            return "Error: old_string must not be empty."
        if expected_replacements < 1:
            return "Error: expected_replacements must be >= 1."

        original = p.read_text(encoding="utf-8", errors="replace")
        count = original.count(old_string)
        if count != expected_replacements:
            return (
                f"Error: old_string matched {count} time(s), expected "
                f"{expected_replacements}. Refusing to edit."
            )

        updated = original.replace(old_string, new_string, expected_replacements)
        diff = "\n".join(
            difflib.unified_diff(
                original.splitlines(),
                updated.splitlines(),
                fromfile=str(p),
                tofile=str(p),
                lineterm="",
            )
        )
        if not diff:
            return "No changes: new_string is identical to old_string."

        if dry_run:
            return f"Dry run diff for {p}:\n{diff}"

        console.print(
            Panel(
                diff,
                title=f"edit_file diff: {p}",
                border_style="yellow",
            )
        )
        answer = console.input("[bold]应用以上修改? (y/n): [/bold]").strip().lower()
        if answer not in ("y", "yes", "是"):
            return "Cancelled: user rejected edit_file diff."

        p.write_text(updated, encoding="utf-8")
        return f"Success: Edited {p} ({expected_replacements} replacement(s))"
    except Exception as exc:
        return f"Error editing file: {exc}"


def list_directory(path: str = ".", show_hidden: bool = False) -> str:
    try:
        p = _resolve(path)
        if not p.exists():
            return f"Error: Directory not found — {p}"
        if not p.is_dir():
            return f"Error: Not a directory — {p}"

        entries = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
        lines = [f"📂 {p}\n"]
        for entry in entries:
            if not show_hidden and entry.name.startswith("."):
                continue
            if entry.is_dir():
                lines.append(f"  📁 {entry.name}/")
            elif entry.is_symlink():
                lines.append(f"  🔗 {entry.name} → {os.readlink(entry)}")
            else:
                try:
                    sz = _fmt_size(entry.stat().st_size)
                except OSError:
                    sz = "?"
                lines.append(f"  📄 {entry.name}  ({sz})")
        if len(lines) == 1:
            lines.append("  (empty)")
        return "\n".join(lines)
    except Exception as exc:
        return f"Error: {exc}"


def search_files(pattern: str, directory: str = ".", recursive: bool = True) -> str:
    try:
        p = _resolve(directory)
        matches = list(p.rglob(pattern) if recursive else p.glob(pattern))
        if not matches:
            return f"No files matching '{pattern}' in {p}"
        total = len(matches)
        lines = [f"Found {total} match(es) for '{pattern}':\n"]
        for m in matches[:100]:
            rel = m.relative_to(p)
            tag = "📁" if m.is_dir() else "📄"
            lines.append(f"  {tag} {rel}")
        if total > 100:
            lines.append(f"\n  … and {total - 100} more")
        return "\n".join(lines)
    except Exception as exc:
        return f"Error: {exc}"


def create_directory(path: str) -> str:
    try:
        p = _resolve(path)
        p.mkdir(parents=True, exist_ok=True)
        return f"Success: Directory ready — {p}"
    except Exception as exc:
        return f"Error: {exc}"


def delete_path(path: str) -> str:
    try:
        p = _resolve(path)
        if not p.exists():
            return f"Error: Path not found — {p}"
        if p.is_file() or p.is_symlink():
            p.unlink()
            return f"Success: Deleted file — {p}"
        elif p.is_dir():
            count = sum(1 for _ in p.rglob("*"))
            shutil.rmtree(p)
            return f"Success: Deleted directory — {p} ({count} items removed)"
        else:
            return f"Error: Unknown path type — {p}"
    except Exception as exc:
        return f"Error: {exc}"


def move_path(source: str, destination: str) -> str:
    try:
        src = _resolve(source)
        dst = _resolve(destination)
        if not src.exists():
            return f"Error: Source not found — {src}"
        shutil.move(str(src), str(dst))
        return f"Success: Moved {src} → {dst}"
    except Exception as exc:
        return f"Error: {exc}"


def copy_path(source: str, destination: str) -> str:
    try:
        src = _resolve(source)
        dst = _resolve(destination)
        if not src.exists():
            return f"Error: Source not found — {src}"
        if src.is_dir():
            shutil.copytree(str(src), str(dst))
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src), str(dst))
        return f"Success: Copied {src} → {dst}"
    except Exception as exc:
        return f"Error: {exc}"


def get_file_info(path: str) -> str:
    try:
        p = _resolve(path)
        if not p.exists():
            return f"Error: Path not found — {p}"
        st = p.stat()
        info = {
            "Path": str(p),
            "Type": "Directory" if p.is_dir() else ("Symlink" if p.is_symlink() else "File"),
            "Size": _fmt_size(st.st_size),
            "Permissions": oct(st.st_mode)[-3:],
            "Owner UID": st.st_uid,
            "Group GID": st.st_gid,
            "Modified": datetime.datetime.fromtimestamp(st.st_mtime).isoformat(),
            "Accessed": datetime.datetime.fromtimestamp(st.st_atime).isoformat(),
        }
        return "\n".join(f"  {k}: {v}" for k, v in info.items())
    except Exception as exc:
        return f"Error: {exc}"


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS = [
    ToolDefinition(
        name="read_file",
        description="Read the text content of a file and return it.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to read"},
                "max_lines": {"type": "integer", "description": "Max lines (default 500)", "default": 500},
            },
            "required": ["path"],
        },
        permission_level=PermissionLevel.GREEN,
        handler=read_file,
    ),
    ToolDefinition(
        name="write_file",
        description="Write content to a file. Creates parent directories automatically. Set append=true to append instead of overwrite.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to write to"},
                "content": {"type": "string", "description": "Content to write"},
                "append": {"type": "boolean", "description": "Append instead of overwrite (default false)", "default": False},
            },
            "required": ["path", "content"],
        },
        permission_level=PermissionLevel.YELLOW,
        handler=write_file,
    ),
    ToolDefinition(
        name="edit_file",
        description=(
            "Safely edit an existing text file by replacing an exact old_string "
            "with new_string. Shows a unified diff and asks the user before writing."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to edit"},
                "old_string": {
                    "type": "string",
                    "description": "Exact text to replace. Must match expected_replacements times.",
                },
                "new_string": {"type": "string", "description": "Replacement text"},
                "expected_replacements": {
                    "type": "integer",
                    "description": "Required match count before editing (default 1)",
                    "default": 1,
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "Return the diff without writing (default false)",
                    "default": False,
                },
            },
            "required": ["path", "old_string", "new_string"],
        },
        permission_level=PermissionLevel.YELLOW,
        handler=edit_file,
    ),
    ToolDefinition(
        name="list_directory",
        description="List files and subdirectories in a directory with sizes.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path (default: .)", "default": "."},
                "show_hidden": {"type": "boolean", "description": "Include hidden files (default false)", "default": False},
            },
            "required": [],
        },
        permission_level=PermissionLevel.GREEN,
        handler=list_directory,
    ),
    ToolDefinition(
        name="search_files",
        description="Search for files matching a glob pattern (e.g. '*.py', '*.log').",
        parameters={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern to match"},
                "directory": {"type": "string", "description": "Search root (default: .)", "default": "."},
                "recursive": {"type": "boolean", "description": "Recurse into subdirs (default true)", "default": True},
            },
            "required": ["pattern"],
        },
        permission_level=PermissionLevel.GREEN,
        handler=search_files,
    ),
    ToolDefinition(
        name="create_directory",
        description="Create a directory (including any missing parent directories).",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path to create"},
            },
            "required": ["path"],
        },
        permission_level=PermissionLevel.GREEN,
        handler=create_directory,
    ),
    ToolDefinition(
        name="delete_path",
        description="Delete a file or an entire directory tree. ⚠️ IRREVERSIBLE!",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to delete"},
            },
            "required": ["path"],
        },
        permission_level=PermissionLevel.RED,
        handler=delete_path,
    ),
    ToolDefinition(
        name="move_path",
        description="Move or rename a file/directory.",
        parameters={
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "Source path"},
                "destination": {"type": "string", "description": "Destination path"},
            },
            "required": ["source", "destination"],
        },
        permission_level=PermissionLevel.YELLOW,
        handler=move_path,
    ),
    ToolDefinition(
        name="copy_path",
        description="Copy a file or directory tree to a new location.",
        parameters={
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "Source path"},
                "destination": {"type": "string", "description": "Destination path"},
            },
            "required": ["source", "destination"],
        },
        permission_level=PermissionLevel.GREEN,
        handler=copy_path,
    ),
    ToolDefinition(
        name="get_file_info",
        description="Get metadata about a file or directory: size, permissions, timestamps, etc.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to inspect"},
            },
            "required": ["path"],
        },
        permission_level=PermissionLevel.GREEN,
        handler=get_file_info,
    ),
]

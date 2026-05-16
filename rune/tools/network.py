"""
Network operation tools.

Gives the AI direct network capabilities: opening URLs, downloading files,
making HTTP requests, and checking connectivity.
"""

import platform
import subprocess
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from typing import Optional

from .base import PermissionLevel, ToolDefinition


def _is_wsl() -> bool:
    """Detect if running inside Windows Subsystem for Linux."""
    try:
        return "microsoft" in Path("/proc/version").read_text().lower()
    except Exception:
        return False


def open_url(url: str) -> str:
    """Open a URL in the system's default web browser."""
    try:
        if _is_wsl():
            # WSL: use Windows host browser via cmd.exe
            subprocess.Popen(
                ["cmd.exe", "/c", "start", url.replace("&", "^&")],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", url])
        elif platform.system() == "Windows":
            subprocess.Popen(["cmd", "/c", "start", url.replace("&", "^&")])
        else:
            webbrowser.open(url)
        return f"Success: Opened {url} in default browser"
    except Exception as exc:
        return f"Error: {exc}"


def download_file(url: str, destination: str) -> str:
    """Download a file from a URL and save it locally."""
    try:
        dst = Path(destination).expanduser().resolve()
        dst.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(url, str(dst))
        size = dst.stat().st_size
        for u in ("B", "KB", "MB", "GB"):
            if size < 1024:
                return f"Success: Downloaded → {dst}  ({size:.1f} {u})"
            size /= 1024  # type: ignore[assignment]
        return f"Success: Downloaded → {dst}"
    except Exception as exc:
        return f"Error downloading: {exc}"


def http_request(
    url: str,
    method: str = "GET",
    headers: Optional[str] = None,
    body: Optional[str] = None,
    timeout: int = 30,
) -> str:
    """
    Make a raw HTTP request.

    `headers` should be a JSON string of key-value pairs,
    e.g. '{"Content-Type": "application/json"}'.
    """
    import json as _json

    try:
        req = urllib.request.Request(url, method=method.upper())

        if headers:
            try:
                hdr_dict = _json.loads(headers)
                for k, v in hdr_dict.items():
                    req.add_header(k, v)
            except _json.JSONDecodeError:
                return "Error: `headers` must be valid JSON (e.g. '{\"Key\": \"Value\"}')"

        data = body.encode("utf-8") if body else None

        with urllib.request.urlopen(req, data=data, timeout=timeout) as resp:
            resp_body = resp.read().decode("utf-8", errors="replace")
            if len(resp_body) > 8000:
                resp_body = resp_body[:8000] + "\n… (truncated)"
            return (
                f"Status: {resp.status}\n"
                f"Headers: {dict(resp.headers)}\n\n"
                f"Body:\n{resp_body}"
            )
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")[:3000]
        return f"HTTP Error {exc.code}: {exc.reason}\n{body_text}"
    except Exception as exc:
        return f"Error: {exc}"


def check_connectivity(host: str = "8.8.8.8") -> str:
    """Ping a host to check network connectivity."""
    try:
        param = "-n" if platform.system() == "Windows" else "-c"
        result = subprocess.run(
            ["ping", param, "1", "-W", "3", host],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return f"✅ Network OK — ping to {host} succeeded"
        else:
            return f"❌ Network unreachable — ping to {host} failed"
    except FileNotFoundError:
        return "Error: 'ping' command not found on this system"
    except subprocess.TimeoutExpired:
        return f"❌ Network unreachable — ping to {host} timed out"
    except Exception as exc:
        return f"Error: {exc}"


def get_public_ip() -> str:
    """Get the machine's public IP address via an external service."""
    try:
        with urllib.request.urlopen("https://api.ipify.org?format=json", timeout=10) as resp:
            import json as _json
            data = _json.loads(resp.read().decode())
            return f"Public IP: {data.get('ip', 'unknown')}"
    except Exception as exc:
        return f"Error: {exc}"


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS = [
    ToolDefinition(
        name="open_url",
        description="Open a URL in the system's default web browser.",
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The URL to open (e.g. https://google.com)"},
            },
            "required": ["url"],
        },
        permission_level=PermissionLevel.GREEN,
        handler=open_url,
    ),
    ToolDefinition(
        name="download_file",
        description="Download a file from a URL and save it to a local path.",
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to download from"},
                "destination": {"type": "string", "description": "Local file path to save to"},
            },
            "required": ["url", "destination"],
        },
        permission_level=PermissionLevel.YELLOW,
        handler=download_file,
    ),
    ToolDefinition(
        name="http_request",
        description=(
            "Make an HTTP request (GET, POST, PUT, DELETE, etc.). "
            "Returns status code, headers, and response body. "
            "Useful for interacting with REST APIs."
        ),
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Request URL"},
                "method": {"type": "string", "description": "HTTP method (default GET)", "default": "GET"},
                "headers": {
                    "type": "string",
                    "description": "JSON string of headers, e.g. '{\"Authorization\": \"Bearer xxx\"}'",
                },
                "body": {"type": "string", "description": "Request body (for POST/PUT)"},
                "timeout": {"type": "integer", "description": "Timeout in seconds (default 30)", "default": 30},
            },
            "required": ["url"],
        },
        permission_level=PermissionLevel.YELLOW,
        handler=http_request,
    ),
    ToolDefinition(
        name="check_connectivity",
        description="Check if the machine has network connectivity by pinging a host.",
        parameters={
            "type": "object",
            "properties": {
                "host": {"type": "string", "description": "Host to ping (default: 8.8.8.8)", "default": "8.8.8.8"},
            },
            "required": [],
        },
        permission_level=PermissionLevel.GREEN,
        handler=check_connectivity,
    ),
    ToolDefinition(
        name="get_public_ip",
        description="Get this machine's public (external) IP address.",
        parameters={"type": "object", "properties": {}, "required": []},
        permission_level=PermissionLevel.GREEN,
        handler=get_public_ip,
    ),
]

"""
Feishu (Lark) tools - Personal messaging + Calendar.

Gives the AI the ability to send/receive messages, manage chats,
and interact with calendars via the Feishu Open API.
"""

from __future__ import annotations

PLUGIN_META = {
    "name": "飞书 (Feishu)",
    "description": "收发飞书消息、查看群聊、管理日程",
    "version": "1.0",
}


import json
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

from rune.tools.base import PermissionLevel, ToolDefinition

# ---------------------------------------------------------------------------
# Plugin config section
# ---------------------------------------------------------------------------
PLUGIN_CONFIG_SECTION = "feishu"

_DEFAULT_CONFIG: Dict[str, Any] = {
    "app_id": "",
    "app_secret": "",
    "refresh_token": "",
    "token_expires_at": 0.0,
}

# ---------------------------------------------------------------------------
# Auth & HTTP helpers
# ---------------------------------------------------------------------------

_BASE = "https://open.feishu.cn/open-apis"

# User access token cache (personal identity)
_user_token_cache: Dict[str, Any] = {"token": "", "expires_at": 0}


def _feishu_cfg() -> Dict[str, Any]:
    """Return the feishu config dict from plugin_data."""
    from rune.config import RuneConfig
    cfg = RuneConfig.load()
    data = {**_DEFAULT_CONFIG, **cfg.get_plugin_data("feishu")}
    if not data["app_id"] or not data["app_secret"]:
        raise RuntimeError(
            "飞书尚未配置。请运行 config 命令，选择「飞书」插件进行配置。"
        )
    return data


def _get_app_access_token() -> str:
    """Get app_access_token (used as the bearer for OAuth code exchange)."""
    fc = _feishu_cfg()
    body = json.dumps({"app_id": fc["app_id"], "app_secret": fc["app_secret"]}).encode()
    req = urllib.request.Request(
        f"{_BASE}/auth/v3/app_access_token/internal",
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())
    if data.get("code") != 0:
        raise RuntimeError(f"获取 app_access_token 失败: {data.get('msg', data)}")
    return data["app_access_token"]


def _get_user_token() -> str:
    """Get valid user_access_token (human identity). Refreshes automatically.
    Raises RuntimeError if no refresh_token is stored yet."""
    from rune.config import RuneConfig

    now = time.time()
    if _user_token_cache["token"] and _user_token_cache["expires_at"] > now + 60:
        return _user_token_cache["token"]

    cfg = RuneConfig.load()
    fc = {**_DEFAULT_CONFIG, **cfg.get_plugin_data("feishu")}
    if not fc["refresh_token"]:
        raise RuntimeError(
            "飞书用户身份未授权。请先运行 config  ->  飞书配置  ->  授权用户身份，"
            "完成 OAuth 登录后即可使用。"
        )

    # Refresh
    app_token = _get_app_access_token()
    body = json.dumps({
        "grant_type": "refresh_token",
        "refresh_token": fc["refresh_token"],
    }).encode()
    req = urllib.request.Request(
        f"{_BASE}/authen/v1/oidc/refresh_access_token",
        data=body,
        headers={
            "Authorization": f"Bearer {app_token}",
            "Content-Type": "application/json; charset=utf-8",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())
    if data.get("code") != 0:
        # Refresh token likely expired  - clear it so user knows to re-auth
        fc["refresh_token"] = ""
        cfg.set_plugin_data("feishu", fc)
        raise RuntimeError(
            f"用户 token 刷新失败（可能已过期，需重新授权）: {data.get('msg', data)}"
        )

    td = data.get("data", {})
    access_token = td["access_token"]
    new_refresh = td.get("refresh_token") or fc["refresh_token"]
    expires_in = td.get("expires_in", 7200)

    # Update cache
    _user_token_cache["token"] = access_token
    _user_token_cache["expires_at"] = now + expires_in

    # Persist updated tokens
    fc["refresh_token"] = new_refresh
    fc["token_expires_at"] = now + expires_in
    cfg.set_plugin_data("feishu", fc)

    return access_token


def _get_active_token() -> tuple[str, str]:
    """Return (token, identity_label).

    Only uses user_access_token (personal identity).
    Raises RuntimeError if user has not yet completed OAuth.
    """
    return _get_user_token(), "👤 用户身份"


def authorize_user(port: int = 18080) -> tuple[str, str, int]:
    """Run OAuth flow in browser, return (access_token, refresh_token, expires_in).

    Starts a temporary local HTTP server on `port` to capture the callback,
    opens the Feishu authorization page in the default browser.
    The redirect URI http://localhost:{port}/callback must be registered
    in the Feishu app OAuth settings.
    """
    import http.server
    import threading
    import urllib.parse
    import webbrowser

    fc = _feishu_cfg()
    redirect_uri = f"http://localhost:{port}/callback"
    code_holder: list[str] = []
    err_holder: list[str] = []

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)
            html_ok = "<h1>授权成功！可以关闭此窗口。</h1>".encode()
            html_err = "<h1>授权失败，请返回终端查看错误。</h1>".encode()
            if "code" in params:
                code_holder.append(params["code"][0])
                self._respond(200, html_ok)
            else:
                err = params.get("error_description", params.get("error", ["未知错误"]))[0]
                err_holder.append(err)
                self._respond(400, html_err)

        def _respond(self, status: int, body: bytes):
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass  # silence access log

    server = http.server.HTTPServer(("localhost", port), _Handler)

    # Scopes: messaging + calendar + contact read
    scopes = "im:message im:chat contact:user.base:readonly calendar:calendar"
    auth_url = (
        f"{_BASE.replace('/open-apis', '')}/open-apis/authen/v1/authorize"
        f"?app_id={fc['app_id']}"
        f"&redirect_uri={urllib.parse.quote(redirect_uri, safe='')}"
        f"&scope={urllib.parse.quote(scopes, safe='')}"
    )

    # Open browser, wait for exactly one callback
    webbrowser.open(auth_url)
    t = threading.Thread(target=server.handle_request, daemon=True)
    t.start()
    t.join(timeout=120)
    server.server_close()

    if err_holder:
        raise RuntimeError(f"飞书授权失败: {err_holder[0]}")
    if not code_holder:
        raise RuntimeError("超时未收到授权码（等待了 120 秒）")

    # Exchange code for tokens
    app_token = _get_app_access_token()
    body = json.dumps({
        "grant_type": "authorization_code",
        "code": code_holder[0],
    }).encode()
    req = urllib.request.Request(
        f"{_BASE}/authen/v1/oidc/access_token",
        data=body,
        headers={
            "Authorization": f"Bearer {app_token}",
            "Content-Type": "application/json; charset=utf-8",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())
    if data.get("code") != 0:
        raise RuntimeError(f"换取 token 失败: {data.get('msg', data)}")

    td = data.get("data", {})
    return td["access_token"], td.get("refresh_token", ""), td.get("expires_in", 7200)


# Feishu rate-limit error codes
_RATE_LIMIT_CODES = {99980041, 99980042}
# Minimum interval between sends to the same target (seconds)
# 5 QPS shared  ->  leave headroom  ->  1 message per 0.3 s ≈ 3.3 QPS
_SEND_MIN_INTERVAL = 0.3
_last_send_time: float = 0.0


def _feishu_api(
    method: str,
    path: str,
    body: Optional[dict] = None,
    params: Optional[dict] = None,
    _retries: int = 4,
) -> dict:
    """Make an authenticated request. Uses user token when available.

    Automatically retries on rate-limit responses (codes 99980041/99980042)
    with exponential back-off: 1 s, 2 s, 4 s, 8 s.
    For send operations also enforces a minimum inter-request interval so that
    rapid consecutive calls stay well inside the shared 5 QPS group quota.
    """
    global _last_send_time

    token, _ = _get_active_token()
    url = f"{_BASE}{path}"
    if params:
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{url}?{qs}"

    # Throttle consecutive sends
    if method in ("POST", "PATCH") and "messages" in path:
        gap = time.time() - _last_send_time
        if gap < _SEND_MIN_INTERVAL:
            time.sleep(_SEND_MIN_INTERVAL - gap)

    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"飞书 API {exc.code}: {error_body}") from exc
    finally:
        if method in ("POST", "PATCH") and "messages" in path:
            _last_send_time = time.time()

    # Rate-limit: back-off and retry
    if result.get("code") in _RATE_LIMIT_CODES and _retries > 0:
        wait = 2 ** (4 - _retries)   # 1, 2, 4, 8 s
        time.sleep(wait)
        return _feishu_api(method, path, body, params, _retries=_retries - 1)

    if result.get("code") != 0:
        code = result.get("code")
        msg = result.get("msg", "unknown error")
        raise RuntimeError(f"飞书 API 错误 (code={code}): {msg}")
    return result


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


def feishu_list_chats(page_size: int = 20) -> str:
    """List all chats (groups / P2P) visible to the current user."""
    try:
        result = _feishu_api("GET", "/im/v1/chats", params={"page_size": str(page_size)})
        items = result.get("data", {}).get("items", [])
        if not items:
            return "当前没有任何会话。"
        lines: list[str] = []
        for chat in items:
            chat_id = chat.get("chat_id", "?")
            name = chat.get("name", "(未命名)")
            chat_type = chat.get("chat_type", "?")
            owner = chat.get("owner_id", "?")
            lines.append(
                f"  [{chat_id}]\n"
                f"    名称: {name}\n"
                f"    类型: {chat_type}\n"
                f"    群主: {owner}"
            )
        return f"💬 所有会话 ({len(items)} 个):\n\n" + "\n\n".join(lines)
    except Exception as exc:
        return f"Error: {exc}"


# Lightweight sender-name cache (open_id -> display name)
_sender_name_cache: Dict[str, str] = {}


def _resolve_sender(open_id: str) -> str:
    """Try to resolve an open_id to a human-readable name. Returns the name
    or the original ID on failure (never raises)."""
    if not open_id or open_id == "?":
        return open_id
    if open_id in _sender_name_cache:
        return _sender_name_cache[open_id]
    try:
        result = _feishu_api(
            "GET",
            f"/contact/v3/users/{open_id}",
            params={"user_id_type": "open_id"},
        )
        name = result.get("data", {}).get("user", {}).get("name", open_id)
        _sender_name_cache[open_id] = name
        return name
    except Exception:
        _sender_name_cache[open_id] = open_id  # cache failures too
        return open_id


def feishu_list_messages(chat_id: str, page_size: int = 15) -> str:
    """List recent messages in a chat, with sender names and readable timestamps."""
    try:
        result = _feishu_api(
            "GET",
            f"/im/v1/messages",
            params={
                "container_id_type": "chat",
                "container_id": chat_id,
                "page_size": str(page_size),
            },
        )
        items = result.get("data", {}).get("items", [])
        if not items:
            return f"该会话中没有消息。"
        lines: list[str] = []
        for msg in items:
            msg_id = msg.get("message_id", "?")
            msg_type = msg.get("msg_type", "?")
            sender_id = msg.get("sender", {}).get("id", "?")
            sender_name = _resolve_sender(sender_id)
            create_time = msg.get("create_time", "?")
            time_str = _ts_to_str(create_time) if create_time != "?" else "?"
            # Parse body content
            body = msg.get("body", {}).get("content", "")
            try:
                content_obj = json.loads(body) if body else {}
                text = content_obj.get("text", body)
            except (json.JSONDecodeError, AttributeError):
                text = body
            # Non-text message types
            if msg_type != "text" and not text:
                text = f"[{msg_type} 消息]"
            lines.append(
                f"  [{msg_id}]\n"
                f"    发送者: {sender_name}\n"
                f"    时间: {time_str}\n"
                f"    内容: {text[:300]}"
            )
        return f"📨 最近 {len(items)} 条消息:\n\n" + "\n\n".join(lines)
    except Exception as exc:
        return f"Error: {exc}"


def feishu_send_message(
    receive_id: str,
    text: str,
    receive_id_type: str = "chat_id",
) -> str:
    """Send a text message to a user or chat."""
    import uuid as _uuid
    try:
        content = json.dumps({"text": text})
        result = _feishu_api(
            "POST",
            f"/im/v1/messages?receive_id_type={receive_id_type}",
            body={
                "receive_id": receive_id,
                "msg_type": "text",
                "content": content,
                "uuid": _uuid.uuid4().hex,  # prevent Feishu deduplication
            },
        )
        msg_id = result.get("data", {}).get("message_id", "?")
        return f"✅ 消息已发送 (message_id: {msg_id})"
    except Exception as exc:
        return f"Error: 发送失败  - {exc}"


def feishu_reply_message(message_id: str, text: str) -> str:
    """Reply to a specific message by message_id."""
    import uuid as _uuid
    try:
        content = json.dumps({"text": text})
        result = _feishu_api(
            "POST",
            f"/im/v1/messages/{message_id}/reply",
            body={
                "msg_type": "text",
                "content": content,
                "uuid": _uuid.uuid4().hex,
            },
        )
        new_msg_id = result.get("data", {}).get("message_id", "?")
        return f"✅ 已回复 (message_id: {new_msg_id})"
    except Exception as exc:
        return f"Error: 回复失败  - {exc}"


def feishu_get_user_info(user_id: str, user_id_type: str = "open_id") -> str:
    """Get basic info of a Feishu user."""
    try:
        result = _feishu_api(
            "GET",
            f"/contact/v3/users/{user_id}",
            params={"user_id_type": user_id_type},
        )
        user = result.get("data", {}).get("user", {})
        parts = [
            f"👤 用户信息:",
            f"  名称    : {user.get('name', '?')}",
            f"  Open ID : {user.get('open_id', '?')}",
            f"  邮箱    : {user.get('email', '(未公开)')}",
            f"  手机    : {user.get('mobile', '(未公开)')}",
            f"  部门    : {', '.join(user.get('department_ids', [])) or '?'}",
            f"  状态    : {'活跃' if user.get('status', {}).get('is_activated') else '未激活'}",
        ]
        return "\n".join(parts)
    except Exception as exc:
        return f"Error: {exc}"


def feishu_list_events(
    calendar_id: str = "primary",
    page_size: int = 10,
    start_time: str = "",
    end_time: str = "",
) -> str:
    """List upcoming calendar events."""
    try:
        import datetime

        params: dict[str, str] = {"page_size": str(page_size)}

        # Default: today 00:00 to +7 days
        if not start_time:
            now = datetime.datetime.now()
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            start_time = str(int(today_start.timestamp()))
        if not end_time:
            end_ts = int(start_time) + 7 * 86400
            end_time = str(end_ts)

        params["start_time"] = start_time
        params["end_time"] = end_time

        result = _feishu_api(
            "GET",
            f"/calendar/v4/calendars/{calendar_id}/events",
            params=params,
        )
        items = result.get("data", {}).get("items", [])
        if not items:
            return "📅 该时间段内没有日程。"

        lines: list[str] = []
        for ev in items:
            event_id = ev.get("event_id", "?")
            summary = ev.get("summary", "(无标题)")
            start = ev.get("start_time", {})
            end = ev.get("end_time", {})
            start_str = start.get("date", "") or _ts_to_str(start.get("timestamp", ""))
            end_str = end.get("date", "") or _ts_to_str(end.get("timestamp", ""))
            location = ev.get("location", {}).get("name", "")
            status = ev.get("status", "")
            lines.append(
                f"  [{event_id}]\n"
                f"    📌 {summary}\n"
                f"    ⏰ {start_str}  ->  {end_str}\n"
                + (f"    📍 {location}\n" if location else "")
                + (f"    状态: {status}" if status else "")
            )
        return f"📅 日程列表 ({len(items)} 个):\n\n" + "\n\n".join(lines)
    except Exception as exc:
        return f"Error: {exc}"


def feishu_create_event(
    summary: str,
    start_time: str,
    end_time: str,
    calendar_id: str = "primary",
    description: str = "",
    location: str = "",
) -> str:
    """Create a new calendar event. Times are Unix timestamps (seconds)."""
    try:
        body: dict[str, Any] = {
            "summary": summary,
            "start_time": {"timestamp": start_time},
            "end_time": {"timestamp": end_time},
        }
        if description:
            body["description"] = description
        if location:
            body["location"] = {"name": location}

        result = _feishu_api(
            "POST",
            f"/calendar/v4/calendars/{calendar_id}/events",
            body=body,
        )
        event_id = result.get("data", {}).get("event", {}).get("event_id", "?")
        return f"✅ 日程已创建 (event_id: {event_id})"
    except Exception as exc:
        return f"Error: 创建失败  - {exc}"


def _ts_to_str(ts: str) -> str:
    """Convert a Unix timestamp string to readable datetime."""
    if not ts:
        return "?"
    try:
        import datetime
        return datetime.datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ts


# ---------------------------------------------------------------------------
# Plugin hooks: setup wizard + config display (called by main.py dynamically)
# ---------------------------------------------------------------------------

def plugin_setup_wizard(console) -> None:
    """Interactive Feishu configuration wizard. Called from config command."""
    from rich.panel import Panel
    from rune.config import RuneConfig

    config = RuneConfig.load()
    data = {**_DEFAULT_CONFIG, **config.get_plugin_data("feishu")}

    _wizard_text = (
        "[bold yellow]飞书配置向导[/bold yellow]\n\n"
        "配置飞书企业自建应用后，AI 可以帮你收发飞书消息、管理日程。\n"
        "需要在 [bold]飞书开放平台[/bold] 创建应用并获取 App ID 和 App Secret。\n\n"
        "[dim]创建步骤:\n"
        "  1. 打开 https://open.feishu.cn → 开发者后台\n"
        "  2. 创建企业自建应用\n"
        '  3. 在「凭证与基础信息」中获取 App ID 和 App Secret\n'
        '  4. 在「权限管理」中开通: im:message, im:chat, calendar:calendar,\n'
        "     contact:user.base:readonly 等权限\n"
        "  5. 发布应用版本并通过审核[/dim]"
    )
    console.print(
        Panel(_wizard_text, title="🐦  Feishu Setup", border_style="yellow")
    )

    if data["refresh_token"]:
        identity = "[green]✅ 已授权（个人身份）[/green]"
    elif data["app_id"]:
        identity = "[yellow]⚠️  应用已配置，但尚未授权用户身份[/yellow]"
    else:
        identity = "[red]❌ 未配置[/red]"
    console.print(f"\n  当前状态: {identity}\n")

    console.print("[bold]选择操作:[/bold]")
    console.print("  1. 修改 App ID / App Secret")
    console.print("  2. 授权用户身份（以你本人发送/查看消息）")
    console.print("  3. 撤销用户授权")
    console.print("  0. 返回")
    choice = console.input("\n请输入序号 [0-3]: ").strip()

    if choice == "1":
        data["app_id"] = console.input("\nApp ID: ").strip()
        data["app_secret"] = console.input("App Secret: ").strip()
        config.set_plugin_data("feishu", data)
        console.print("[green]✅ 飞书应用凭证已保存。[/green]\n")
        test = console.input("是否测试应用凭证是否有效? (Y/n): ").strip().lower()
        if test != "n":
            _test_feishu_connection(console, data)

    elif choice == "2":
        _do_user_auth(console, config, data)

    elif choice == "3":
        data["refresh_token"] = ""
        data["token_expires_at"] = 0.0
        config.set_plugin_data("feishu", data)
        _user_token_cache["token"] = ""
        _user_token_cache["expires_at"] = 0
        console.print("[yellow]已清除用户授权。需要重新授权后才能使用飞书功能。[/yellow]\n")


def _do_user_auth(console, config, data: Dict[str, Any]) -> None:
    """Run the OAuth flow to get a user_access_token."""
    if not data["app_id"] or not data["app_secret"]:
        console.print("[bold red]❌ 请先填写 App ID 和 App Secret（选项 1）。[/bold red]\n")
        return

    port_str = console.input("本地回调端口 (默认 18080): ").strip()
    port = int(port_str) if port_str.isdigit() else 18080

    console.print(
        f"\n[bold]⚠️  授权前请确认：[/bold]\n"
        f"  飞书开放平台 → 应用 → 安全设置 → 重定向 URL 中已添加:\n"
        f"  [cyan]http://localhost:{port}/callback[/cyan]\n"
    )
    go = console.input("已添加，开始授权? (Y/n): ").strip().lower()
    if go == "n":
        return

    console.print("[dim]正在打开浏览器，请在飞书网页完成授权…[/dim]")
    try:
        access_token, refresh_token, expires_in = authorize_user(port=port)
    except Exception as exc:
        console.print(f"[bold red]❌ 授权失败: {exc}[/bold red]\n")
        return

    data["refresh_token"] = refresh_token
    data["token_expires_at"] = time.time() + expires_in
    config.set_plugin_data("feishu", data)

    _user_token_cache["token"] = access_token
    _user_token_cache["expires_at"] = data["token_expires_at"]

    console.print(
        f"[bold green]✅ 用户授权成功！[/bold green]\n"
        f"  有效期约 {expires_in // 3600} 小时，到期自动刷新。\n"
        f"  此后所有飞书操作将以[bold]你的身份[/bold]执行。\n"
    )


def _test_feishu_connection(console, data: Dict[str, Any]) -> None:
    """Try to get an app_access_token to verify app credentials."""
    console.print("[dim]正在验证飞书应用凭证...[/dim]")
    try:
        body = json.dumps({
            "app_id": data["app_id"],
            "app_secret": data["app_secret"],
        }).encode()
        req = urllib.request.Request(
            f"{_BASE}/auth/v3/app_access_token/internal",
            data=body,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
        if result.get("code") == 0:
            console.print("[green]✅ 应用凭证有效！接下来请授权用户身份（选项 2）。[/green]\n")
        else:
            console.print(f"[bold red]❌ 认证失败: {result.get('msg', result)}[/bold red]")
            console.print("[dim]请检查 App ID 和 App Secret 是否正确。[/dim]\n")
    except Exception as exc:
        console.print(f"[bold red]❌ 连接失败: {exc}[/bold red]\n")


def plugin_config_display() -> str:
    """Return a Rich-formatted string showing current feishu config for the config panel."""
    from rune.config import RuneConfig
    cfg = RuneConfig.load()
    data = {**_DEFAULT_CONFIG, **cfg.get_plugin_data("feishu")}
    if data["refresh_token"]:
        status = f"{data['app_id']}  [green]✅ 已授权[/green]"
    elif data["app_id"]:
        status = f"{data['app_id']}  [yellow]⚠️  未授权[/yellow]"
    else:
        status = "[red](未配置)[/red]"
    return (
        f"[bold]🐦 飞书[/bold]\n"
        f"  App ID  : {status}"
    )


# ---------------------------------------------------------------------------
# Tool definitions exposed to the registry
# ---------------------------------------------------------------------------

TOOLS = [
    ToolDefinition(
        name="feishu_list_chats",
        description="列出你在飞书中的所有会话（群聊和私信）。",
        parameters={
            "type": "object",
            "properties": {
                "page_size": {
                    "type": "integer",
                    "description": "最多返回条数（默认 20）",
                    "default": 20,
                },
            },
            "required": [],
        },
        permission_level=PermissionLevel.GREEN,
        handler=feishu_list_chats,
    ),
    ToolDefinition(
        name="feishu_list_messages",
        description=(
            "获取飞书某个群聊/私信会话中的最近消息，带发送者姓名和可读时间。"
            "需要先用 feishu_list_chats 获取 chat_id。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "chat_id": {
                    "type": "string",
                    "description": "群聊/会话 ID",
                },
                "page_size": {
                    "type": "integer",
                    "description": "最多返回条数（默认 15）",
                    "default": 15,
                },
            },
            "required": ["chat_id"],
        },
        permission_level=PermissionLevel.GREEN,
        handler=feishu_list_messages,
    ),
    ToolDefinition(
        name="feishu_send_message",
        description=(
            "通过飞书发送文本消息。可以发给群聊 (chat_id) 或用户 (open_id)。"
            "receive_id_type 可选: chat_id, open_id, user_id, union_id, email。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "receive_id": {
                    "type": "string",
                    "description": "接收者 ID（chat_id 或 open_id 等）",
                },
                "text": {
                    "type": "string",
                    "description": "消息文本内容",
                },
                "receive_id_type": {
                    "type": "string",
                    "description": "ID 类型: chat_id / open_id / user_id / union_id / email（默认 chat_id）",
                    "default": "chat_id",
                },
            },
            "required": ["receive_id", "text"],
        },
        permission_level=PermissionLevel.RED,
        handler=feishu_send_message,
    ),
    ToolDefinition(
        name="feishu_reply_message",
        description="回复飞书中的指定消息。需要提供 message_id。",
        parameters={
            "type": "object",
            "properties": {
                "message_id": {
                    "type": "string",
                    "description": "要回复的消息 ID",
                },
                "text": {
                    "type": "string",
                    "description": "回复文本内容",
                },
            },
            "required": ["message_id", "text"],
        },
        permission_level=PermissionLevel.RED,
        handler=feishu_reply_message,
    ),
    ToolDefinition(
        name="feishu_get_user_info",
        description="查询飞书用户的基本信息（姓名、邮箱、部门等）。",
        parameters={
            "type": "object",
            "properties": {
                "user_id": {
                    "type": "string",
                    "description": "用户 ID",
                },
                "user_id_type": {
                    "type": "string",
                    "description": "ID 类型: open_id / user_id / union_id（默认 open_id）",
                    "default": "open_id",
                },
            },
            "required": ["user_id"],
        },
        permission_level=PermissionLevel.GREEN,
        handler=feishu_get_user_info,
    ),
    ToolDefinition(
        name="feishu_list_events",
        description=(
            "获取飞书日历中的日程列表。默认返回今天起 7 天内的日程。"
            "时间参数为 Unix 时间戳（秒）。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "calendar_id": {
                    "type": "string",
                    "description": "日历 ID（默认 primary = 主日历）",
                    "default": "primary",
                },
                "page_size": {
                    "type": "integer",
                    "description": "最多返回条数（默认 10）",
                    "default": 10,
                },
                "start_time": {
                    "type": "string",
                    "description": "开始时间 Unix 时间戳（可选，默认今天零点）",
                    "default": "",
                },
                "end_time": {
                    "type": "string",
                    "description": "结束时间 Unix 时间戳（可选，默认 start+7天）",
                    "default": "",
                },
            },
            "required": [],
        },
        permission_level=PermissionLevel.GREEN,
        handler=feishu_list_events,
    ),
    ToolDefinition(
        name="feishu_create_event",
        description=(
            "在飞书日历中创建新日程。"
            "start_time 和 end_time 为 Unix 时间戳（秒）。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "日程标题",
                },
                "start_time": {
                    "type": "string",
                    "description": "开始时间 Unix 时间戳",
                },
                "end_time": {
                    "type": "string",
                    "description": "结束时间 Unix 时间戳",
                },
                "calendar_id": {
                    "type": "string",
                    "description": "日历 ID（默认 primary）",
                    "default": "primary",
                },
                "description": {
                    "type": "string",
                    "description": "日程描述（可选）",
                    "default": "",
                },
                "location": {
                    "type": "string",
                    "description": "地点（可选）",
                    "default": "",
                },
            },
            "required": ["summary", "start_time", "end_time"],
        },
        permission_level=PermissionLevel.YELLOW,
        handler=feishu_create_event,
    ),
]

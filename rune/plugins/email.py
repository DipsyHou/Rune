"""
Email tools - IMAP (read) + SMTP (send).

Gives the AI the ability to manage email: list, search, read, send, reply, delete.
Uses only Python standard library (imaplib, smtplib, email).
"""

from __future__ import annotations

PLUGIN_META = {
    "name": "邮箱 (Email)",
    "description": "收发邮件、管理收件箱、查看未读邮件",
    "version": "1.0",
}


import email as emaillib
import email.header
import email.mime.application
import email.mime.multipart
import email.mime.text
import email.utils
import imaplib
import mimetypes
import os
import smtplib
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from rune.tools.base import PermissionLevel, ToolDefinition

# ---------------------------------------------------------------------------
# Plugin config section name (matches the key in config.yaml)
# ---------------------------------------------------------------------------
PLUGIN_CONFIG_SECTION = "email"

_DEFAULT_CONFIG = {
    "address": "",
    "password": "",
    "imap_server": "",
    "imap_port": 993,
    "smtp_server": "",
    "smtp_port": 587,
    "use_tls": True,
}

# ---------------------------------------------------------------------------
# Lazy config loader — reads from RuneConfig.plugin_data["email"]
# ---------------------------------------------------------------------------

_cfg_cache: Dict[str, Any] | None = None


def _email_cfg() -> Dict[str, Any]:
    """Return email config dict. Cached after first call."""
    global _cfg_cache
    if _cfg_cache is None:
        from rune.config import RuneConfig

        cfg = RuneConfig.load()
        stored = cfg.get_plugin_data("email")
        merged = {**_DEFAULT_CONFIG, **stored}
        _cfg_cache = merged
    return _cfg_cache


def _require_cfg() -> Dict[str, Any]:
    """Return config or raise a friendly error if email is not configured."""
    cfg = _email_cfg()
    if not cfg["address"] or not cfg["password"] or not cfg["imap_server"]:
        raise RuntimeError(
            "邮箱尚未配置。请运行 config 命令，选择「邮箱」插件进行配置。"
        )
    return cfg


# ---------------------------------------------------------------------------
# Plugin hooks: setup wizard + config display (called by main.py dynamically)
# ---------------------------------------------------------------------------

def plugin_setup_wizard(console) -> None:
    """Interactive email configuration wizard. Called from config command."""
    from rich.panel import Panel
    from rune.config import RuneConfig

    config = RuneConfig.load()
    data = {**_DEFAULT_CONFIG, **config.get_plugin_data("email")}

    console.print(
        Panel(
            "[bold yellow]邮箱配置向导[/bold yellow]\n\n"
            "配置邮箱后，AI 可以帮你收发邮件。\n"
            "需要使用 [bold]应用专用密码 / 授权码[/bold]（不是登录密码）。",
            title="📧  Email Setup",
            border_style="yellow",
        )
    )

    _presets = {
        "1": ("QQ 邮箱",       "imap.qq.com",   993, "smtp.qq.com",   465, "设置 → 账户 → 开启 IMAP → 生成授权码"),
        "2": ("163 网易邮箱",   "imap.163.com",  993, "smtp.163.com",  465, "设置 → POP3/SMTP/IMAP → 开启 IMAP → 设置授权码"),
        "3": ("Gmail",         "imap.gmail.com", 993, "smtp.gmail.com", 587, "Google 账户 → 安全性 → 两步验证 → 应用专用密码"),
        "4": ("Outlook",       "outlook.office365.com", 993, "smtp-mail.outlook.com", 587, "使用 Microsoft 账户密码或应用密码"),
        "5": ("126 邮箱",      "imap.126.com",  993, "smtp.126.com",  465, "设置 → POP3/SMTP/IMAP → 开启 IMAP → 设置授权码"),
        "6": ("新浪邮箱",      "imap.sina.com", 993, "smtp.sina.com", 465, "设置 → 客户端 → 开启 IMAP"),
    }

    console.print("\n[bold]选择邮箱类型:[/bold]")
    for k, (name, *_) in _presets.items():
        console.print(f"  {k}. {name}")
    console.print("  0. 其他（手动输入服务器地址）")
    choice = console.input("\n请输入序号 [0-6]: ").strip()

    if choice in _presets:
        name, imap_s, imap_p, smtp_s, smtp_p, hint = _presets[choice]
        data["imap_server"] = imap_s
        data["imap_port"] = imap_p
        data["smtp_server"] = smtp_s
        data["smtp_port"] = smtp_p
        console.print(f"  [green]✓[/green] 已自动填入 {name} 服务器地址")
        console.print(f"  [dim]ℹ️  授权码获取: {hint}[/dim]")
    else:
        data["imap_server"] = console.input("IMAP 服务器地址: ").strip()
        port_str = console.input("IMAP 端口 (默认 993): ").strip()
        data["imap_port"] = int(port_str) if port_str else 993
        data["smtp_server"] = console.input("SMTP 服务器地址: ").strip()
        port_str = console.input("SMTP 端口 (默认 587): ").strip()
        data["smtp_port"] = int(port_str) if port_str else 587

    data["address"] = console.input("\n邮箱地址: ").strip()
    data["password"] = console.input("授权码 / 应用专用密码: ").strip()

    tls = console.input("启用 TLS 加密? (Y/n): ").strip().lower()
    data["use_tls"] = tls != "n"

    config.set_plugin_data("email", data)
    console.print("[green]✅ 邮箱配置已保存。[/green]\n")

    # Invalidate cache so tools pick up new settings
    global _cfg_cache
    _cfg_cache = None

    # Quick connectivity test
    test = console.input("是否测试连接? (Y/n): ").strip().lower()
    if test != "n":
        _test_connection(console, data)


def _test_connection(console, data: Dict[str, Any]) -> None:
    """Try to connect to the IMAP server to verify credentials."""
    import imaplib as _imaplib

    console.print("[dim]正在连接 IMAP 服务器...[/dim]")
    try:
        if data.get("use_tls", True):
            conn = _imaplib.IMAP4_SSL(data["imap_server"], data["imap_port"])
        else:
            conn = _imaplib.IMAP4(data["imap_server"], data["imap_port"])
        conn.login(data["address"], data["password"])
        status, count = conn.select("INBOX", readonly=True)
        msg_count = count[0].decode() if status == "OK" and count else "?"
        conn.logout()
        console.print(f"[green]✅ 连接成功！收件箱中有 {msg_count} 封邮件。[/green]\n")
    except Exception as exc:
        console.print(f"[bold red]❌ 连接失败: {exc}[/bold red]")
        console.print("[dim]请检查服务器地址、邮箱和授权码是否正确。[/dim]\n")


def plugin_config_display() -> str:
    """Return a Rich-formatted string showing current email config for the config panel."""
    from rune.config import RuneConfig
    cfg = RuneConfig.load()
    data = {**_DEFAULT_CONFIG, **cfg.get_plugin_data("email")}
    addr = data["address"] or "[red](未配置)[/red]"
    return (
        f"[bold]📧 邮箱[/bold]\n"
        f"  邮箱地址: {addr}\n"
        f"  IMAP    : {data['imap_server'] or '(未配置)'}:{data['imap_port']}\n"
        f"  SMTP    : {data['smtp_server'] or '(未配置)'}:{data['smtp_port']}"
    )


# ---------------------------------------------------------------------------
# IMAP helpers
# ---------------------------------------------------------------------------


def _imap_connect() -> imaplib.IMAP4_SSL | imaplib.IMAP4:
    """Open an authenticated IMAP connection."""
    cfg = _require_cfg()
    if cfg["use_tls"]:
        conn = imaplib.IMAP4_SSL(cfg["imap_server"], cfg["imap_port"])
    else:
        conn = imaplib.IMAP4(cfg["imap_server"], cfg["imap_port"])
    conn.login(cfg["address"], cfg["password"])
    return conn


def _decode_header(raw: str | None) -> str:
    """Decode RFC-2047 encoded header value into a plain string."""
    if not raw:
        return ""
    parts = email.header.decode_header(raw)
    decoded: list[str] = []
    for data, charset in parts:
        if isinstance(data, bytes):
            decoded.append(data.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(data)
    return " ".join(decoded)


def _extract_body(msg: emaillib.message.Message) -> str:
    """Extract the best plain-text body from an email message."""
    if msg.is_multipart():
        # Try text/plain first, fall back to text/html
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/plain" and part.get_content_disposition() != "attachment":
                payload = part.get_payload(decode=True)
                charset = part.get_content_charset() or "utf-8"
                return payload.decode(charset, errors="replace") if payload else ""
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/html" and part.get_content_disposition() != "attachment":
                payload = part.get_payload(decode=True)
                charset = part.get_content_charset() or "utf-8"
                return (
                    "[HTML 内容]\n"
                    + (payload.decode(charset, errors="replace") if payload else "")
                )
    else:
        payload = msg.get_payload(decode=True)
        charset = msg.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="replace") if payload else ""
    return "(无法解析正文)"


def _list_attachments(msg: emaillib.message.Message) -> list[str]:
    """Return a list of attachment filenames."""
    names: list[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            disp = part.get_content_disposition()
            if disp == "attachment":
                fn = _decode_header(part.get_filename())
                names.append(fn or "(未命名附件)")
    return names


def _fetch_envelope(conn: imaplib.IMAP4_SSL | imaplib.IMAP4, uid: str) -> dict:
    """Fetch essential headers for a single message by UID."""
    status, data = conn.uid("fetch", uid, "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE)])")
    if status != "OK" or not data or not data[0]:
        return {"uid": uid, "subject": "?", "from": "?", "date": "?"}
    raw = data[0][1] if isinstance(data[0], tuple) else data[0]
    msg = emaillib.message_from_bytes(raw if isinstance(raw, bytes) else raw.encode())
    return {
        "uid": uid,
        "subject": _decode_header(msg["Subject"]),
        "from": _decode_header(msg["From"]),
        "date": msg["Date"] or "?",
    }


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


def email_list_folders() -> str:
    """List all mailbox folders."""
    try:
        conn = _imap_connect()
        try:
            status, folders = conn.list()
            if status != "OK":
                return "Error: 无法获取文件夹列表"
            lines: list[str] = []
            for item in folders:
                if isinstance(item, bytes):
                    # Format: b'(\\flags) "/" "folder_name"'
                    decoded = item.decode("utf-8", errors="replace")
                    # Extract folder name (last quoted string or last word)
                    parts = decoded.rsplit('"', 2)
                    if len(parts) >= 2:
                        lines.append(parts[-2])
                    else:
                        lines.append(decoded)
            return "邮箱文件夹:\n" + "\n".join(f"  📁 {f}" for f in lines)
        finally:
            conn.logout()
    except Exception as exc:
        return f"Error: {exc}"


def email_list_inbox(
    folder: str = "INBOX",
    limit: int = 15,
    since: str = "",
) -> str:
    """List the most recent emails in a folder."""
    try:
        conn = _imap_connect()
        try:
            status, _ = conn.select(folder, readonly=True)
            if status != "OK":
                return f"Error: 无法打开文件夹 '{folder}'"

            # Build IMAP search criteria
            if since:
                # Accept YYYY-MM-DD or natural strings
                try:
                    dt = datetime.strptime(since, "%Y-%m-%d")
                    imap_date = dt.strftime("%d-%b-%Y")
                    criteria = f'(SINCE "{imap_date}")'
                except ValueError:
                    criteria = "ALL"
            else:
                criteria = "ALL"

            status, uid_data = conn.uid("search", None, criteria)
            if status != "OK":
                return "Error: 搜索失败"

            uids = uid_data[0].split() if uid_data[0] else []
            # Take the most recent `limit` messages
            uids = uids[-limit:]
            uids.reverse()  # newest first

            if not uids:
                return f"文件夹 '{folder}' 中没有符合条件的邮件。"

            lines: list[str] = []
            for uid in uids:
                env = _fetch_envelope(conn, uid.decode() if isinstance(uid, bytes) else uid)
                lines.append(
                    f"  [{env['uid']}] {env['date']}\n"
                    f"        From: {env['from']}\n"
                    f"        Subject: {env['subject']}"
                )
            header = f"📬 {folder} — 最近 {len(uids)} 封邮件:\n"
            return header + "\n".join(lines)
        finally:
            conn.logout()
    except Exception as exc:
        return f"Error: {exc}"


def email_search(
    keyword: str = "",
    from_addr: str = "",
    subject: str = "",
    since: str = "",
    folder: str = "INBOX",
    limit: int = 20,
) -> str:
    """Search emails by keyword, sender, subject, or date."""
    try:
        conn = _imap_connect()
        try:
            conn.select(folder, readonly=True)

            parts: list[str] = []
            if keyword:
                parts.append(f'TEXT "{keyword}"')
            if from_addr:
                parts.append(f'FROM "{from_addr}"')
            if subject:
                parts.append(f'SUBJECT "{subject}"')
            if since:
                try:
                    dt = datetime.strptime(since, "%Y-%m-%d")
                    parts.append(f'SINCE "{dt.strftime("%d-%b-%Y")}"')
                except ValueError:
                    pass

            criteria = " ".join(parts) if parts else "ALL"
            status, uid_data = conn.uid("search", None, f"({criteria})")
            if status != "OK":
                return "Error: 搜索失败"

            uids = uid_data[0].split() if uid_data[0] else []
            uids = uids[-limit:]
            uids.reverse()

            if not uids:
                return "没有找到匹配的邮件。"

            lines: list[str] = []
            for uid in uids:
                env = _fetch_envelope(conn, uid.decode() if isinstance(uid, bytes) else uid)
                lines.append(
                    f"  [{env['uid']}] {env['date']}\n"
                    f"        From: {env['from']}\n"
                    f"        Subject: {env['subject']}"
                )
            return f"🔍 搜索结果 ({len(uids)} 封):\n" + "\n".join(lines)
        finally:
            conn.logout()
    except Exception as exc:
        return f"Error: {exc}"


def email_read(uid: str, folder: str = "INBOX") -> str:
    """Read a specific email by UID, including body and attachment list."""
    try:
        conn = _imap_connect()
        try:
            conn.select(folder, readonly=True)
            status, data = conn.uid("fetch", uid, "(RFC822)")
            if status != "OK" or not data or not data[0]:
                return f"Error: 无法获取邮件 UID={uid}"

            raw = data[0][1] if isinstance(data[0], tuple) else data[0]
            msg = emaillib.message_from_bytes(
                raw if isinstance(raw, bytes) else raw.encode()
            )

            subject = _decode_header(msg["Subject"])
            from_ = _decode_header(msg["From"])
            to_ = _decode_header(msg["To"])
            date_ = msg["Date"] or "?"
            cc_ = _decode_header(msg.get("Cc", ""))
            body = _extract_body(msg)
            attachments = _list_attachments(msg)

            parts: list[str] = [
                f"📧 邮件详情 (UID: {uid})",
                f"  Subject : {subject}",
                f"  From    : {from_}",
                f"  To      : {to_}",
            ]
            if cc_:
                parts.append(f"  Cc      : {cc_}")
            parts.append(f"  Date    : {date_}")
            if attachments:
                parts.append(f"  附件    : {', '.join(attachments)}")
            parts.append(f"\n--- 正文 ---\n{body}")

            result = "\n".join(parts)
            # Truncate very long bodies
            if len(result) > 12_000:
                result = result[:12_000] + "\n... (正文过长，已截断)"
            return result
        finally:
            conn.logout()
    except Exception as exc:
        return f"Error: {exc}"


def email_send(
    to: str,
    subject: str,
    body: str,
    cc: str = "",
    attachment_paths: str = "",
) -> str:
    """Send a new email. attachment_paths is comma-separated file paths."""
    try:
        cfg = _require_cfg()
        from_addr = cfg["address"]

        msg = email.mime.multipart.MIMEMultipart()
        msg["From"] = from_addr
        msg["To"] = to
        msg["Subject"] = subject
        if cc:
            msg["Cc"] = cc
        msg["Date"] = email.utils.formatdate(localtime=True)

        msg.attach(email.mime.text.MIMEText(body, "plain", "utf-8"))

        # Attachments
        if attachment_paths:
            for path_str in attachment_paths.split(","):
                path = Path(path_str.strip()).expanduser().resolve()
                if not path.exists():
                    return f"Error: 附件不存在 — {path}"
                if path.stat().st_size > 25 * 1024 * 1024:
                    return f"Error: 附件超过 25MB 限制 — {path.name}"
                ctype, _ = mimetypes.guess_type(str(path))
                maintype, subtype = (ctype or "application/octet-stream").split("/", 1)
                with open(path, "rb") as f:
                    att = email.mime.application.MIMEApplication(f.read(), Name=path.name)
                att["Content-Disposition"] = f'attachment; filename="{path.name}"'
                msg.attach(att)

        # Send
        recipients = [a.strip() for a in to.split(",")]
        if cc:
            recipients += [a.strip() for a in cc.split(",")]

        if cfg["use_tls"]:
            with smtplib.SMTP(cfg["smtp_server"], cfg["smtp_port"]) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(cfg["address"], cfg["password"])
                server.sendmail(from_addr, recipients, msg.as_string())
        else:
            with smtplib.SMTP(cfg["smtp_server"], cfg["smtp_port"]) as server:
                server.login(cfg["address"], cfg["password"])
                server.sendmail(from_addr, recipients, msg.as_string())

        return f"✅ 邮件已发送至 {to}" + (f" (抄送: {cc})" if cc else "")
    except Exception as exc:
        return f"Error: 发送失败 — {exc}"


def email_reply(
    uid: str,
    body: str,
    folder: str = "INBOX",
    reply_all: bool = False,
) -> str:
    """Reply to an email identified by UID."""
    try:
        cfg = _require_cfg()
        conn = _imap_connect()
        try:
            conn.select(folder, readonly=True)
            status, data = conn.uid("fetch", uid, "(RFC822)")
            if status != "OK" or not data or not data[0]:
                return f"Error: 无法获取邮件 UID={uid}"

            raw = data[0][1] if isinstance(data[0], tuple) else data[0]
            orig = emaillib.message_from_bytes(
                raw if isinstance(raw, bytes) else raw.encode()
            )
        finally:
            conn.logout()

        orig_from = _decode_header(orig["From"])
        orig_subject = _decode_header(orig["Subject"])
        orig_message_id = orig.get("Message-ID", "")
        orig_cc = _decode_header(orig.get("Cc", ""))

        # Build reply-to address
        reply_to = _decode_header(orig.get("Reply-To", "")) or orig_from

        re_subject = orig_subject if orig_subject.lower().startswith("re:") else f"Re: {orig_subject}"

        msg = email.mime.multipart.MIMEMultipart()
        msg["From"] = cfg["address"]
        msg["To"] = reply_to
        msg["Subject"] = re_subject
        msg["Date"] = email.utils.formatdate(localtime=True)
        if orig_message_id:
            msg["In-Reply-To"] = orig_message_id
            msg["References"] = orig_message_id

        recipients = [reply_to]
        if reply_all and orig_cc:
            msg["Cc"] = orig_cc
            recipients += [a.strip() for a in orig_cc.split(",")]

        # Include original body
        orig_body = _extract_body(orig)
        full_body = (
            f"{body}\n\n"
            f"--- 原始邮件 ---\n"
            f"From: {orig_from}\n"
            f"Date: {orig.get('Date', '?')}\n"
            f"Subject: {orig_subject}\n\n"
            f"{orig_body}"
        )
        msg.attach(email.mime.text.MIMEText(full_body, "plain", "utf-8"))

        # Send
        if cfg["use_tls"]:
            with smtplib.SMTP(cfg["smtp_server"], cfg["smtp_port"]) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(cfg["address"], cfg["password"])
                server.sendmail(cfg["address"], recipients, msg.as_string())
        else:
            with smtplib.SMTP(cfg["smtp_server"], cfg["smtp_port"]) as server:
                server.login(cfg["address"], cfg["password"])
                server.sendmail(cfg["address"], recipients, msg.as_string())

        return f"✅ 已回复 {reply_to}" + (f" (reply-all, 抄送: {orig_cc})" if reply_all else "")
    except Exception as exc:
        return f"Error: 回复失败 — {exc}"


def email_delete(uid: str, folder: str = "INBOX") -> str:
    """Mark an email as deleted (move to Trash / expunge)."""
    try:
        conn = _imap_connect()
        try:
            conn.select(folder)
            # Flag as deleted
            status, _ = conn.uid("store", uid, "+FLAGS", "(\\Deleted)")
            if status != "OK":
                return f"Error: 无法删除邮件 UID={uid}"
            conn.expunge()
            return f"🗑️ 邮件 UID={uid} 已删除。"
        finally:
            conn.logout()
    except Exception as exc:
        return f"Error: 删除失败 — {exc}"


# ---------------------------------------------------------------------------
# Tool definitions exposed to the registry
# ---------------------------------------------------------------------------

TOOLS = [
    ToolDefinition(
        name="email_list_folders",
        description="列出邮箱中所有文件夹（收件箱、已发送、草稿箱等）。",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
        permission_level=PermissionLevel.GREEN,
        handler=email_list_folders,
    ),
    ToolDefinition(
        name="email_list_inbox",
        description=(
            "列出邮箱文件夹中最近的邮件摘要（UID、发件人、主题、日期）。"
            "可指定文件夹、数量限制、起始日期。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "folder": {
                    "type": "string",
                    "description": "邮箱文件夹名，默认 INBOX",
                    "default": "INBOX",
                },
                "limit": {
                    "type": "integer",
                    "description": "最多返回多少封邮件（默认 15）",
                    "default": 15,
                },
                "since": {
                    "type": "string",
                    "description": "只返回该日期之后的邮件，格式 YYYY-MM-DD（可选）",
                    "default": "",
                },
            },
            "required": [],
        },
        permission_level=PermissionLevel.GREEN,
        handler=email_list_inbox,
    ),
    ToolDefinition(
        name="email_search",
        description=(
            "搜索邮件。支持按关键词、发件人、主题、日期筛选。"
            "返回匹配邮件的 UID 列表和摘要。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "在邮件全文中搜索的关键词",
                    "default": "",
                },
                "from_addr": {
                    "type": "string",
                    "description": "按发件人地址筛选",
                    "default": "",
                },
                "subject": {
                    "type": "string",
                    "description": "按主题筛选",
                    "default": "",
                },
                "since": {
                    "type": "string",
                    "description": "起始日期 YYYY-MM-DD",
                    "default": "",
                },
                "folder": {
                    "type": "string",
                    "description": "邮箱文件夹，默认 INBOX",
                    "default": "INBOX",
                },
                "limit": {
                    "type": "integer",
                    "description": "最多返回条数（默认 20）",
                    "default": 20,
                },
            },
            "required": [],
        },
        permission_level=PermissionLevel.GREEN,
        handler=email_search,
    ),
    ToolDefinition(
        name="email_read",
        description=(
            "读取指定 UID 邮件的完整内容，包括发件人、收件人、主题、正文和附件列表。"
            "先用 email_list_inbox 或 email_search 获取 UID。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "uid": {
                    "type": "string",
                    "description": "邮件的 UID",
                },
                "folder": {
                    "type": "string",
                    "description": "邮箱文件夹，默认 INBOX",
                    "default": "INBOX",
                },
            },
            "required": ["uid"],
        },
        permission_level=PermissionLevel.GREEN,
        handler=email_read,
    ),
    ToolDefinition(
        name="email_send",
        description=(
            "发送一封新邮件。支持抄送和附件。"
            "附件通过逗号分隔的文件路径传入。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "收件人地址（多个用逗号分隔）",
                },
                "subject": {
                    "type": "string",
                    "description": "邮件主题",
                },
                "body": {
                    "type": "string",
                    "description": "邮件正文",
                },
                "cc": {
                    "type": "string",
                    "description": "抄送地址（可选，逗号分隔）",
                    "default": "",
                },
                "attachment_paths": {
                    "type": "string",
                    "description": "附件文件路径（可选，逗号分隔）",
                    "default": "",
                },
            },
            "required": ["to", "subject", "body"],
        },
        permission_level=PermissionLevel.RED,
        handler=email_send,
    ),
    ToolDefinition(
        name="email_reply",
        description=(
            "回复指定 UID 的邮件。自动引用原文、设置 Re: 前缀和 In-Reply-To 头。"
            "可选择回复全部（reply_all）。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "uid": {
                    "type": "string",
                    "description": "要回复的邮件 UID",
                },
                "body": {
                    "type": "string",
                    "description": "回复正文",
                },
                "folder": {
                    "type": "string",
                    "description": "邮箱文件夹，默认 INBOX",
                    "default": "INBOX",
                },
                "reply_all": {
                    "type": "boolean",
                    "description": "是否回复所有人（默认 false）",
                    "default": False,
                },
            },
            "required": ["uid", "body"],
        },
        permission_level=PermissionLevel.RED,
        handler=email_reply,
    ),
    ToolDefinition(
        name="email_delete",
        description="删除指定 UID 的邮件（标记为删除并清除）。",
        parameters={
            "type": "object",
            "properties": {
                "uid": {
                    "type": "string",
                    "description": "要删除的邮件 UID",
                },
                "folder": {
                    "type": "string",
                    "description": "邮箱文件夹，默认 INBOX",
                    "default": "INBOX",
                },
            },
            "required": ["uid"],
        },
        permission_level=PermissionLevel.RED,
        handler=email_delete,
    ),
]

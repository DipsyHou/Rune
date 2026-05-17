"""
Rune — Main entry point and interactive CLI.

Run with:  python -m rune
"""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion, merge_completers
from prompt_toolkit.filters import emacs_insert_mode, has_completions
from prompt_toolkit.key_binding import KeyBindings
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from rune import __version__
from rune.agent import Agent
from rune.config import RuneConfig
from rune.memory import MemoryStore
from rune.registry import ToolRegistry
from rune.security import SecurityManager
from rune.session import SessionStore, list_sessions, resume_session
from rune.skills import SkillStore

console = Console()

BANNER = r"""
    ██████╗ ██╗   ██╗███╗   ██╗███████╗
    ██╔══██╗██║   ██║████╗  ██║██╔════╝
    ██████╔╝██║   ██║██╔██╗ ██║█████╗
    ██╔══██╗██║   ██║██║╚██╗██║██╔══╝
    ██║  ██║╚██████╔╝██║ ╚████║███████╗
    ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═══╝╚══════╝
"""

HELP_TEXT = """\
[bold]内置命令:[/bold]
  [cyan]/help[/cyan]              显示此帮助
  [cyan]/clear[/cyan]             清空对话历史
  [cyan]/compact[/cyan]           压缩旧对话上下文
  [cyan]/config[/cyan]            管理配置
  [cyan]/exit[/cyan]              退出 Rune
  [cyan]/memory[/cyan]            查看/初始化分层记忆文件
  [cyan]/permissions[/cyan]       管理 allow/deny/ask 权限规则
  [cyan]/plugins[/cyan]           管理插件
  [cyan]/skills[/cyan]            列出可用 Skills
  [cyan]/resume[/cyan]            按序号选择并恢复历史会话
  [cyan]/tools[/cyan]             列出所有已加载的工具

[dim]任何不以 / 开头的输入都会发送给 AI 代理处理。[/dim]
[dim]输入 @文件路径 可引用本地文件，AI 会在本轮对话中阅读该文件内容。[/dim]"""

BUILTIN_SLASH_COMMANDS = [
    "/help",
    "/clear",
    "/compact",
    "/config",
    "/exit",
    "/memory",
    "/permissions",
    "/plugins",
    "/skills",
    "/resume",
    "/tools",
]

_AT_FILE_MAX_CHARS = 30_000
_AT_REF_PATTERN = re.compile(r'@("([^"]+)"|\'([^\']+)\'|([^\s@]+))')


class SlashCommandCompleter(Completer):
    """Autocomplete built-in slash commands while typing."""

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if " " in text or not text.startswith("/"):
            return
        for command in BUILTIN_SLASH_COMMANDS:
            if command.startswith(text):
                yield Completion(command, start_position=-len(text))


class AtFileCompleter(Completer):
    """Autocomplete file paths after @."""

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        at = text.rfind("@")
        if at < 0:
            return

        prefix = text[at + 1 :]
        if " " in prefix:
            return

        for candidate in _complete_relative_paths(prefix):
            yield Completion(candidate, start_position=-len(prefix))


def _complete_relative_paths(partial: str) -> list[str]:
    partial = partial.replace("\\", "/")
    cwd = Path.cwd().resolve()

    if "/" in partial:
        dir_part, _, name_part = partial.rpartition("/")
        root = (cwd / dir_part).resolve() if dir_part else cwd
    else:
        root = cwd
        dir_part = ""
        name_part = partial

    if not root.is_dir():
        root = cwd
        dir_part = ""
        name_part = partial

    results: list[str] = []
    parent = "../" if not dir_part else f"{dir_part}/../"
    results.append(parent)

    try:
        entries = sorted(root.iterdir(), key=lambda p: (not p.is_file(), p.name.lower()))
    except OSError:
        return results

    for entry in entries:
        if name_part and not entry.name.lower().startswith(name_part.lower()):
            continue
        if "/" in partial:
            candidate = f"{dir_part}/{entry.name}".lstrip("/")
        else:
            try:
                candidate = entry.relative_to(cwd).as_posix()
            except ValueError:
                candidate = entry.name
        if entry.is_dir():
            candidate = f"{candidate}/"
        results.append(candidate)
        if len(results) >= 40:
            break
    return results


def _resolve_at_path(raw: str) -> Path:
    path = Path(raw.strip("\"'")).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve()


def _expand_file_mentions(text: str) -> str:
    """Inject referenced file contents for @path mentions in user input."""
    matches = list(_AT_REF_PATTERN.finditer(text))
    if not matches:
        return text

    blocks: list[str] = []
    for match in matches:
        raw = match.group(2) or match.group(3) or match.group(4) or ""
        path = _resolve_at_path(raw)
        if not path.exists():
            blocks.append(f"[引用文件不存在: {path}]")
            continue
        if path.is_dir():
            blocks.append(f"[引用路径是目录: {path}]")
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            blocks.append(f"[无法读取文件 {path}: {exc}]")
            continue

        if len(content) > _AT_FILE_MAX_CHARS:
            content = content[:_AT_FILE_MAX_CHARS] + "\n...(文件内容已截断)"

        blocks.append(
            "用户通过 @ 引用了文件，请仔细阅读以下内容：\n"
            f"文件: {path}\n"
            f"```\n{content}\n```"
        )

    return "\n\n".join(blocks) + "\n\n用户消息：\n" + text


_USER_MESSAGE_MARKER = "\n\n用户消息：\n"


def _user_display_text(msg: dict) -> str:
    """Prefer stored display text; fall back to stripping @file injection blocks."""
    display = msg.get("display")
    if display is not None:
        return str(display).strip()
    content = str(msg.get("content", "")).strip()
    if _USER_MESSAGE_MARKER in content:
        return content.split(_USER_MESSAGE_MARKER, 1)[1].strip()
    return content


def _print_conversation_history(conversation: list[dict]) -> None:
    """Replay user input and assistant replies in live-session order."""
    shown = False
    for msg in conversation:
        role = msg.get("role")
        if role == "system":
            continue

        if role == "user":
            display = _user_display_text(msg)
            if display:
                console.print(f"[bold]You >[/bold] {display}")
                shown = True
            continue

        if role != "assistant":
            continue

        content = str(msg.get("content", "")).strip()
        if not content:
            continue
        console.print()
        console.print(Panel(content, title="🔮 Rune", border_style="cyan", padding=(0, 1)))
        console.print()
        shown = True

    if not shown:
        console.print("[dim]该会话没有可显示的历史消息。[/dim]\n")


def _highlight_completion(buffer, index: int | None) -> None:
    """Update menu highlight only; do not insert text into the input."""
    state = buffer.complete_state
    if not state or not state.completions:
        return
    state.go_to_index(index)
    buffer.on_completions_changed.fire()


def _build_prompt_key_bindings() -> KeyBindings:
    """Arrows highlight completions; only Tab inserts the selected item."""
    kb = KeyBindings()

    @kb.add("tab", filter=emacs_insert_mode)
    def tab_complete(event) -> None:
        buffer = event.current_buffer
        state = buffer.complete_state
        if state and state.completions:
            index = state.complete_index if state.complete_index is not None else 0
            buffer.apply_completion(state.completions[index])
            return
        buffer.start_completion(select_first=False)

    @kb.add("down", filter=has_completions & emacs_insert_mode)
    def completion_down(event) -> None:
        buffer = event.current_buffer
        state = buffer.complete_state
        if not state:
            return
        if state.complete_index is None:
            _highlight_completion(buffer, 0)
        elif state.complete_index < len(state.completions) - 1:
            _highlight_completion(buffer, state.complete_index + 1)

    @kb.add("up", filter=has_completions & emacs_insert_mode)
    def completion_up(event) -> None:
        buffer = event.current_buffer
        state = buffer.complete_state
        if not state:
            return
        if state.complete_index is None:
            _highlight_completion(buffer, len(state.completions) - 1)
        elif state.complete_index > 0:
            _highlight_completion(buffer, state.complete_index - 1)
        else:
            _highlight_completion(buffer, None)

    return kb


# ---------------------------------------------------------------------------
# Setup wizards
# ---------------------------------------------------------------------------


def _setup_llm(config: RuneConfig) -> None:
    """Interactive LLM configuration wizard."""
    console.print(
        Panel(
            "[bold yellow]LLM 配置向导[/bold yellow]\n\n"
            "Rune 需要连接一个大语言模型 (LLM) 来工作。\n"
            "支持任何 OpenAI 兼容 API或本地 Ollama。",
            title="⚙️  LLM Setup",
            border_style="yellow",
        )
    )

    console.print("\n[bold]选择连接方式:[/bold]")
    console.print("  1. OpenAI 兼容 API")
    console.print("  2. Ollama")
    choice = console.input("\n请输入序号 [1/2] (默认 1): ").strip() or "1"

    if choice == "2":
        config.llm.provider = "ollama"
        config.llm.base_url = console.input(
            "Ollama API 地址 (默认 http://localhost:11434/v1): "
        ).strip() or "http://localhost:11434/v1"
        config.llm.model = console.input(
            "模型名称 (默认 llama3): "
        ).strip() or "llama3"
        config.llm.api_key = "ollama"
    else:
        config.llm.provider = "compatible"
        config.llm.base_url = console.input("API Base URL: ").strip()
        config.llm.api_key = console.input("API Key: ").strip()
        config.llm.model = console.input("模型名称 (如 gpt-4o): ").strip()

    config.save()
    console.print("[green]✅ LLM 配置已保存。[/green]\n")


def _setup_security(config: RuneConfig) -> None:
    """Interactive security settings wizard."""
    console.print(
        Panel(
            "[bold yellow]安全设置[/bold yellow]\n\n"
            "控制 AI 执行操作时的确认行为。",
            title="🔒  Security",
            border_style="yellow",
        )
    )

    console.print(f"\n  当前: 高危操作(RED)需确认 = [bold]{'是' if config.security.require_confirmation_for_red else '否'}[/bold]")
    console.print(f"  当前: 中危操作(YELLOW)需确认 = [bold]{'是' if config.security.require_confirmation_for_yellow else '否'}[/bold]")

    red = console.input("\n高危操作（删除文件、发邮件等）需确认? (Y/n): ").strip().lower()
    config.security.require_confirmation_for_red = red != "n"

    yellow = console.input("中危操作（执行命令、写文件等）需确认? (y/N): ").strip().lower()
    config.security.require_confirmation_for_yellow = yellow == "y"

    config.save()
    console.print("[green]✅ 安全设置已保存。[/green]\n")


def _first_run_setup(config: RuneConfig) -> RuneConfig:
    """Complete first-run setup wizard: LLM → Security (optional)."""
    console.print(
        Panel(
            "[bold cyan]欢迎使用 Rune！[/bold cyan]\n\n"
            "这是首次运行，让我们快速完成初始配置。",
            title="🚀  首次配置向导",
            border_style="cyan",
        )
    )

    # Step 1: LLM (required)
    console.print("\n[bold]━━━ 第 1 步: 配置 LLM（必需）━━━[/bold]\n")
    _setup_llm(config)

    # Step 2: Security (optional)
    console.print("[bold]━━━ 第 2 步: 安全设置（可选）━━━[/bold]\n")
    setup_sec = console.input("是否调整安全设置? (y/N): ").strip().lower()
    if setup_sec == "y":
        _setup_security(config)
    else:
        console.print("[dim]已跳过，使用默认设置（高危操作需确认）。[/dim]\n")

    console.print(
        Panel(
            "[bold green]🎉 配置完成！[/bold green]\n\n"
            "现在你可以用自然语言告诉 AI 做任何事情了。\n"
            "输入 [cyan]plugins[/cyan] 管理插件（邮箱、飞书等）。\n\n"
            "[dim]配置文件保存在: ~/.rune/config.yaml\n"
            "随时输入 config 可重新修改配置。[/dim]",
            title="✅  Ready",
            border_style="green",
        )
    )

    return config


# ---- Built-in commands ----

def _cmd_tools(registry: ToolRegistry) -> None:
    console.print(f"\n[bold]已加载 {registry.count} 个工具:[/bold]\n")
    for tool in registry.get_all():
        lvl = tool.permission_level.value
        colour = {"green": "green", "yellow": "yellow", "red": "red"}[lvl]
        console.print(
            f"  [{colour}]●[/{colour}] [bold]{tool.name}[/bold]  "
            f"[dim]({lvl})[/dim]  — {tool.description[:80]}"
        )
    console.print()


def _show_recent_sessions(limit: int = 10):
    """Print recent sessions without exposing raw session ids."""
    sessions = list_sessions(limit=limit)
    if not sessions:
        console.print("[dim]暂无已保存会话。[/dim]\n")
        return []

    console.print(f"\n[bold]最近 {len(sessions)} 个会话:[/bold]\n")
    for idx, info in enumerate(sessions, 1):
        console.print(
            f"  [bold]{idx}.[/bold] [dim]{info.updated_at} · {info.message_count} messages[/dim]\n"
            f"     {info.title}\n"
            f"     [dim]{info.cwd or info.project}[/dim]"
        )
    console.print()
    return sessions


def _cmd_memory() -> None:
    """Show and initialize layered memory files."""
    store = MemoryStore()
    store.ensure_all()
    console.print("\n[bold]Rune 分层记忆文件:[/bold]\n")
    for idx, layer in enumerate(store.layers(), 1):
        exists = "[green]已存在[/green]" if layer.path.exists() else "[red]缺失[/red]"
        console.print(
            f"  [bold]{idx}.[/bold] {layer.name}  {exists}\n"
            f"     [dim]{layer.description}[/dim]\n"
            f"     [cyan]{layer.path}[/cyan]"
        )
    console.print(
        "\n[dim]这些文件会在每次请求时注入 system prompt；编辑后下一轮对话立即生效。[/dim]\n"
    )


def _cmd_compact(agent: Agent) -> None:
    """Manually compact older conversation turns into a summary."""
    ok, message = agent.compact_history(manual=True)
    style = "green" if ok else "dim"
    console.print(f"[{style}]{message}[/{style}]\n")


def _cmd_permissions(config: RuneConfig, agent: Agent) -> None:
    """Interactive permission rule management."""
    while True:
        rules = config.security.permission_rules
        console.print("\n[bold]权限规则（按顺序匹配，优先于默认风险等级）:[/bold]\n")
        if not rules:
            console.print("  [dim](暂无规则)[/dim]")
        else:
            for idx, rule in enumerate(rules, 1):
                action = rule.get("action", "?")
                tool = rule.get("tool", "*")
                contains = rule.get("contains", "")
                suffix = f" contains={contains!r}" if contains else ""
                console.print(f"  {idx}. [cyan]{action}[/cyan] tool={tool!r}{suffix}")

        console.print("\n[bold]操作:[/bold]")
        console.print("  a <allow|deny|ask> <tool|*> [contains]  — 添加规则")
        console.print("  d <序号>                           — 删除规则")
        console.print("  0                                  — 返回")
        choice = console.input("\n> ").strip()
        if choice in ("", "0"):
            break

        parts = choice.split(maxsplit=3)
        if parts and parts[0].lower() == "a":
            if len(parts) < 3 or parts[1].lower() not in {"allow", "deny", "ask"}:
                console.print("[red]格式: a <allow|deny|ask> <tool|*> [contains][/red]\n")
                continue
            rule = {"action": parts[1].lower(), "tool": parts[2]}
            if len(parts) == 4:
                rule["contains"] = parts[3]
            rules.append(rule)
            config.save()
            agent.security = SecurityManager(config)
            console.print("[green]✅ 权限规则已添加。[/green]\n")
            continue

        if parts and parts[0].lower() == "d":
            if len(parts) < 2 or not parts[1].isdigit():
                console.print("[red]格式: d <序号>[/red]\n")
                continue
            idx = int(parts[1]) - 1
            if 0 <= idx < len(rules):
                removed = rules.pop(idx)
                config.save()
                agent.security = SecurityManager(config)
                console.print(f"[green]✅ 已删除规则: {removed}[/green]\n")
            else:
                console.print("[red]无效的序号。[/red]\n")
            continue

        console.print("[dim]无效输入。[/dim]\n")


def _cmd_skills() -> None:
    """List discovered reusable Rune skills."""
    store = SkillStore()
    skills = store.list()
    if not skills:
        console.print(
            "[dim]暂无 Skills。可添加 ~/.rune/skills/<name>/SKILL.md "
            "或当前项目 .rune/skills/<name>/SKILL.md。[/dim]\n"
        )
        return

    console.print("\n[bold]可用 Rune Skills:[/bold]\n")
    for idx, skill in enumerate(skills, 1):
        console.print(
            f"  [bold]{idx}.[/bold] [cyan]{skill.name}[/cyan] "
            f"[dim]({skill.scope})[/dim]\n"
            f"     {skill.description}\n"
            f"     [dim]{skill.path}[/dim]"
        )
    console.print("\n[dim]AI 会在需要时调用 skill_read 读取完整 SKILL.md。[/dim]\n")


def _cmd_resume(agent: Agent, selection: str | None = None) -> SessionStore | None:
    """Resume a saved session by selecting a displayed index."""
    sessions = _show_recent_sessions(limit=10)
    if not sessions:
        return None

    if not selection:
        selection = console.input("输入要恢复的序号（留空取消）: ").strip()
    if not selection:
        console.print("[dim]已取消恢复。[/dim]\n")
        return None
    if not selection.isdigit():
        console.print("[red]请输入会话序号，例如: 1[/red]\n")
        return None

    idx = int(selection) - 1
    if not 0 <= idx < len(sessions):
        console.print("[red]无效的序号。[/red]\n")
        return None

    info = sessions[idx]
    store = resume_session(info.session_id)
    if not store:
        console.print("[red]未找到该会话。[/red]\n")
        return None

    conversation = store.restore_conversation()
    agent.session_store = store
    agent.load_history(conversation)
    console.print(
        f"[green]✅ 已恢复会话 {store.session_id}[/green]\n"
        f"[dim]已加载 {len(conversation)} 条对话消息。Transcript: {store.path}[/dim]"
    )
    _print_conversation_history(conversation)
    return store


def _cmd_plugins(config: RuneConfig, registry: ToolRegistry) -> None:
    """Interactive plugin management: list, enable, disable, reload."""
    while True:
        available = ToolRegistry.list_available_plugins()
        enabled_set = set(config.plugins.enabled)

        console.print(f"\n[bold]可用插件:[/bold]\n")
        if not available:
            console.print("  [dim](未找到任何插件)[/dim]\n")
        else:
            for idx, p in enumerate(available, 1):
                status = "[green]✅ 已启用[/green]" if p["name"] in enabled_set else "[dim]○ 未启用[/dim]"
                src_tag = f"[dim][{p['source']}][/dim]"
                console.print(
                    f"  {idx}. {status}  [bold]{p['display_name']}[/bold]  v{p['version']}  "
                    f"{src_tag}\n"
                    f"     [dim]{p['description']}  （{p['tool_count']} 个工具）[/dim]"
                )
        console.print()
        console.print("[bold]操作:[/bold]")
        console.print("  e <序号>  — 启用插件")
        console.print("  d <序号>  — 禁用插件")
        console.print("  r        — 重新加载已启用插件到当前会话")
        console.print("  0        — 返回")

        choice = console.input("\n> ").strip()
        if choice == "0" or choice == "":
            break

        if choice == "r":
            reloaded = registry.load_plugins(config.plugins.enabled)
            console.print(f"[green]✅ 已重新加载 {reloaded} 个插件工具。[/green]\n")
            continue

        parts = choice.split(None, 1)
        if len(parts) == 2 and parts[0] in ("e", "d") and parts[1].isdigit():
            idx = int(parts[1]) - 1
            if 0 <= idx < len(available):
                pname = available[idx]["name"]
                if parts[0] == "e":
                    if pname not in enabled_set:
                        config.plugins.enabled.append(pname)
                        config.save()
                        # Load into current session immediately
                        registry.load_plugins([pname])
                        console.print(f"[green]✅ 已启用插件: {available[idx]['display_name']}[/green]\n")
                    else:
                        console.print("[dim]该插件已处于启用状态。[/dim]\n")
                else:
                    if pname in enabled_set:
                        config.plugins.enabled.remove(pname)
                        config.save()
                        console.print(
                            f"[yellow]⚠️  已禁用插件: {available[idx]['display_name']}\n"
                            f"   注意: 需要重启 Rune 才能从当前会话卸载该插件的工具。[/yellow]\n"
                        )
                    else:
                        console.print("[dim]该插件未启用。[/dim]\n")
            else:
                console.print("[red]无效的序号。[/red]\n")
        else:
            console.print("[dim]无效输入，请输入 e/d <序号> 或 r 或 0。[/dim]\n")


def _cmd_config(config: RuneConfig, agent: Agent) -> None:
    """Interactive config menu — view & edit all settings.

    Plugin-specific sections are loaded dynamically from enabled plugins
    that expose ``plugin_config_display()`` and ``plugin_setup_wizard(console)``.
    """
    import importlib

    while True:
        # --- Gather plugin display sections ---
        plugin_sections: list[str] = []
        plugin_modules: list[tuple[str, object]] = []  # (display_name, module)
        for pname in config.plugins.enabled:
            try:
                mod = importlib.import_module(f"rune.plugins.{pname}")
            except ImportError:
                continue
            if hasattr(mod, "plugin_config_display"):
                plugin_sections.append(mod.plugin_config_display())
            if hasattr(mod, "plugin_setup_wizard"):
                meta = getattr(mod, "PLUGIN_META", {})
                plugin_modules.append((meta.get("name", pname), mod))

        # --- Display current settings ---
        key_display = config.llm.api_key[:8] + "..." if len(config.llm.api_key) > 8 else "[red](未设置)[/red]"

        panel_text = (
            f"[bold]🤖 LLM[/bold]\n"
            f"  提供商  : {config.llm.provider}\n"
            f"  Base URL: {config.llm.base_url}\n"
            f"  模型    : {config.llm.model}\n"
            f"  API Key : {key_display}\n"
            f"  温度    : {config.llm.temperature}\n"
            f"  Max Tok : {config.llm.max_tokens}\n"
            f"\n"
            f"[bold]🔒 安全[/bold]\n"
            f"  高危操作确认: {'是' if config.security.require_confirmation_for_red else '否'}\n"
            f"  中危操作确认: {'是' if config.security.require_confirmation_for_yellow else '否'}\n"
            f"  权限规则数: {len(config.security.permission_rules)}"
        )
        for section in plugin_sections:
            panel_text += f"\n\n{section}"

        console.print(Panel(panel_text, title="⚙️  当前配置", border_style="cyan"))

        # --- Build menu ---
        console.print("[bold]修改设置:[/bold]")
        console.print("  1. 修改 LLM 配置")
        console.print("  2. 修改安全设置")
        for idx, (display_name, _mod) in enumerate(plugin_modules, 3):
            console.print(f"  {idx}. 修改 {display_name} 配置")
        console.print("  0. 返回")

        max_choice = 2 + len(plugin_modules)
        choice = console.input(f"\n请输入序号 [0-{max_choice}]: ").strip()

        if choice == "1":
            _setup_llm(config)
            agent.client = __import__("openai").OpenAI(
                api_key=config.llm.api_key or "not-set",
                base_url=config.llm.base_url,
            )
            agent.config = config
            console.print("[green]✅ LLM 客户端已热更新，无需重启。[/green]\n")
        elif choice == "2":
            _setup_security(config)
            agent.security = SecurityManager(config)
        elif choice.isdigit() and 3 <= int(choice) <= max_choice:
            _display_name, _mod = plugin_modules[int(choice) - 3]
            _mod.plugin_setup_wizard(console)
            console.print(f"[green]✅ {_display_name} 配置已热更新。[/green]\n")
        else:
            console.print()
            break


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="rune", description="Rune interactive agent")
    parser.add_argument(
        "-C",
        "--cwd",
        help="启动后切换到指定工作目录。适合从任意位置启动 Rune 后指定项目目录。",
    )
    parser.add_argument("--version", action="version", version=f"Rune {__version__}")
    return parser.parse_args(argv)


def _parse_builtin(user_input: str) -> tuple[str, str] | None:
    """Return (command, args) for slash commands only."""
    if user_input.startswith("/"):
        text = user_input[1:].strip()
        if not text:
            return "help", ""
        command, _, args = text.partition(" ")
        return command.lower(), args.strip()
    return None


def _choose_start_session() -> tuple[SessionStore, list[dict]]:
    """Ask whether to start a fresh session or resume an existing one."""
    while True:
        console.print("[bold]选择会话:[/bold]")
        console.print("  1. 开启新对话")
        console.print("  2. 加载已有对话")
        choice = console.input("\n请输入序号 [1/2] (默认 1): ").strip() or "1"
        console.print()

        if choice == "1":
            return SessionStore(), []

        if choice == "2":
            sessions = _show_recent_sessions(limit=10)
            if not sessions:
                return SessionStore(), []

            selection = console.input("输入要恢复的序号（留空取消并开启新对话）: ").strip()
            if not selection:
                console.print("[dim]已取消恢复，开启新对话。[/dim]\n")
                return SessionStore(), []
            if not selection.isdigit():
                console.print("[red]请输入有效序号。[/red]\n")
                continue

            idx = int(selection) - 1
            if not 0 <= idx < len(sessions):
                console.print("[red]无效的序号。[/red]\n")
                continue

            store = resume_session(sessions[idx].session_id)
            if not store:
                console.print("[red]恢复失败：会话不存在。[/red]\n")
                continue

            conversation = store.restore_conversation()
            console.print(
                f"[green]✅ 已恢复会话[/green]\n"
                f"[dim]已加载 {len(conversation)} 条对话消息。Transcript: {store.path}[/dim]"
            )
            _print_conversation_history(conversation)
            return store, conversation

        console.print("[red]请输入 1 或 2。[/red]\n")


# ---- Main loop ----

def main(argv: list[str] | None = None) -> None:
    """Entry point."""
    args = _parse_args(argv)
    if args.cwd:
        target = os.path.abspath(os.path.expanduser(args.cwd))
        os.chdir(target)

    # Load config
    config = RuneConfig.load()

    # First-run setup if no API key
    if not config.is_api_key_set:
        config = _first_run_setup(config)

    # Minimal startup screen
    console.print(Text(BANNER, style="bold cyan"))
    console.print(f"  [bold]Rune[/bold]  v{__version__}")
    console.print(f"  工作目录: [bold]{os.getcwd()}[/bold]")
    console.print(f"  模型: [bold]{config.llm.model}[/bold]")
    console.print(f"  输入 [cyan]/help[/cyan] 查看帮助，[cyan]/exit[/cyan] 退出\n")

    # Discover and load core tools
    registry = ToolRegistry()
    registry.discover_and_load()
    # Load enabled plugins
    registry.load_plugins(config.plugins.enabled)
    session_store, restored_conversation = _choose_start_session()

    # Init agent
    security = SecurityManager(config)
    agent = Agent(config, registry, security, session_store=session_store)
    if restored_conversation:
        agent.load_history(restored_conversation)
    prompt_session = PromptSession(
        message=[("class:prompt", "You > ")],
        completer=merge_completers([SlashCommandCompleter(), AtFileCompleter()]),
        complete_while_typing=True,
        key_bindings=_build_prompt_key_bindings(),
    )

    # REPL
    while True:
        try:
            user_input = prompt_session.prompt().strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]再见！[/dim]")
            break

        if not user_input:
            continue

        # Built-in commands
        builtin = _parse_builtin(user_input)
        if builtin:
            command, command_args = builtin
        else:
            command, command_args = "", ""

        if command in ("exit", "quit", "q"):
            console.print("[dim]再见！[/dim]")
            break
        if command == "help":
            console.print(HELP_TEXT)
            continue
        if command == "tools":
            _cmd_tools(registry)
            continue
        if command == "plugins":
            _cmd_plugins(config, registry)
            continue
        if command == "clear":
            agent.clear_history()
            console.print("[dim]对话历史已清空。[/dim]\n")
            continue
        if command == "compact":
            _cmd_compact(agent)
            continue
        if command == "memory":
            _cmd_memory()
            continue
        if command == "permissions":
            _cmd_permissions(config, agent)
            continue
        if command == "skills":
            _cmd_skills()
            continue
        if command == "resume":
            requested_id = command_args or None
            resumed_store = _cmd_resume(agent, requested_id)
            if resumed_store:
                session_store = resumed_store
            continue
        if command == "config":
            _cmd_config(config, agent)
            continue

        if user_input.startswith("/"):
            console.print(f"[red]未知内置命令: {user_input}[/red]  [dim]输入 /help 查看可用命令。[/dim]\n")
            continue

        # Send to AI agent
        console.print()  # spacing
        try:
            response = agent.chat(
                _expand_file_mentions(user_input),
                user_display=user_input,
            )
        except KeyboardInterrupt:
            console.print("\n[yellow]⏸ 已中断当前操作。[/yellow]\n")
            continue
        except Exception as exc:
            console.print(f"[bold red]Agent error: {exc}[/bold red]\n")
            continue

        # Display response
        if response and response.strip():
            console.print()
            console.print(Panel(response, title="🔮 Rune", border_style="cyan", padding=(0, 1)))
            console.print()


if __name__ == "__main__":
    main()

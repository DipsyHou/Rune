"""
Rune — Main entry point and interactive CLI.

Run with:  python -m rune
"""

from __future__ import annotations

import argparse
import os

from prompt_toolkit import PromptSession
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from rune import __version__
from rune.agent import Agent
from rune.config import RuneConfig
from rune.memory import MemoryStore
from rune.registry import ToolRegistry
from rune.reminder import ReminderStore
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
  [cyan]/reminder[/cyan]          管理备忘录
  [cyan]/skills[/cyan]            列出可用 Skills
  [cyan]/resume[/cyan]            按序号选择并恢复历史会话
  [cyan]/tools[/cyan]             列出所有已加载的工具

[dim]任何不以 / 开头的输入都会发送给 AI 代理处理。[/dim]"""

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

    ai_rem = console.input("允许 AI 编辑备忘录 (Reminders)? (Y/n): ").strip().lower()
    config.security.allow_ai_edit_reminders = ai_rem != "n"

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
        f"[dim]已加载 {len(conversation)} 条对话消息。Transcript: {store.path}[/dim]\n"
    )
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


def _cmd_reminder() -> None:
    """Interactive reminder management menu."""
    store = ReminderStore()
    while True:
        console.print(Panel(store.get_display_text(), title=f"📝 备忘录 ({store.count()} 条)", border_style="yellow"))
        console.print("[bold]操作:[/bold]")
        console.print("  a        — 添加备忘录")
        console.print("  d <序号>  — 删除备忘录（序号从 1 开始）")
        console.print("  e <序号>  — 编辑备忘录")
        console.print("  0        — 返回")
        console.print(f"  [dim]文件位置: {store.path}[/dim]")

        choice = console.input("\n> ").strip()
        if choice in ("0", ""):
            break

        if choice.lower() == "a":
            text = console.input("输入备忘内容: ").strip()
            if text:
                item = store.add(text)
                console.print(f"[green]✅ 已添加: {item['text']}[/green]\n")
            else:
                console.print("[dim]已取消。[/dim]\n")
            continue

        parts = choice.split(None, 1)
        if len(parts) >= 1 and parts[0].lower() == "d":
            if len(parts) < 2 or not parts[1].isdigit():
                console.print("[red]请输入要删除的序号，例如: d 1[/red]\n")
                continue
            idx = int(parts[1]) - 1  # display is 1-based, store is 0-based
            removed = store.remove(idx)
            if removed:
                console.print(f"[green]✅ 已删除: {removed['text']}[/green]\n")
            else:
                console.print(f"[red]无效的序号。[/red]\n")
            continue

        if len(parts) >= 1 and parts[0].lower() == "e":
            if len(parts) < 2 or not parts[1].isdigit():
                console.print("[red]请输入要编辑的序号，例如: e 1[/red]\n")
                continue
            idx = int(parts[1]) - 1
            items = store.list_all()
            if 0 <= idx < len(items):
                console.print(f"  当前内容: {items[idx]['text']}")
                new_text = console.input("  新内容: ").strip()
                if new_text:
                    store.edit(idx, new_text)
                    console.print(f"[green]✅ 已更新。[/green]\n")
                else:
                    console.print("[dim]已取消。[/dim]\n")
            else:
                console.print(f"[red]无效的序号。[/red]\n")
            continue

        console.print("[dim]无效输入。[/dim]\n")


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
            f"  AI编辑备忘录: {'是' if config.security.allow_ai_edit_reminders else '否'}\n"
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


# ---- Main loop ----

def main(argv: list[str] | None = None) -> None:
    """Entry point."""
    args = _parse_args(argv)
    if args.cwd:
        target = os.path.abspath(os.path.expanduser(args.cwd))
        os.chdir(target)

    # Banner
    console.print(Text(BANNER, style="bold cyan"))
    console.print(f"  [bold]Natural language control for your PC[/bold]  v{__version__}")
    console.print(f"  输入 [cyan]/help[/cyan] 查看帮助，[cyan]/exit[/cyan] 退出")
    console.print(f"  工作目录: [bold]{os.getcwd()}[/bold]\n")

    # Load config
    config = RuneConfig.load()

    # First-run setup if no API key
    if not config.is_api_key_set:
        config = _first_run_setup(config)

    # Discover and load core tools
    registry = ToolRegistry()
    core_loaded = registry.discover_and_load()
    # Load enabled plugins
    plugin_loaded = registry.load_plugins(config.plugins.enabled)
    total_loaded = core_loaded + plugin_loaded
    plugin_names = ", ".join(config.plugins.enabled) if config.plugins.enabled else "(无)"
    console.print(f"  ⚡ 已加载 [bold]{total_loaded}[/bold] 个工具（系统 {core_loaded} + 插件 {plugin_loaded}）")
    console.print(f"  🔌 启用插件: [bold]{plugin_names}[/bold]")
    console.print(f"  🤖 模型: [bold]{config.llm.model}[/bold] @ {config.llm.base_url}")
    console.print(f"  🔒 安全模式: 高危操作需确认={config.security.require_confirmation_for_red}")
    console.print(f"               中危操作需确认={config.security.require_confirmation_for_yellow}")
    console.print(f"               权限规则={len(config.security.permission_rules)}")
    reminder_store = ReminderStore()
    console.print(f"  📝 备忘录: [bold]{reminder_store.count()}[/bold] 条")
    memory_store = MemoryStore()
    existing_layers = sum(1 for layer in memory_store.layers() if layer.path.exists())
    console.print(f"  🧠 记忆层: [bold]{existing_layers}[/bold] / {len(memory_store.layers())}")
    skill_count = len(SkillStore().list())
    console.print(f"  🧩 Skills: [bold]{skill_count}[/bold] 个")
    session_store = SessionStore()
    console.print(f"  💾 会话: [bold]{session_store.session_id}[/bold]")
    console.print(f"       [dim]{session_store.path}[/dim]")
    console.print()

    # Init agent
    security = SecurityManager(config)
    agent = Agent(config, registry, security, session_store=session_store)
    prompt_session = PromptSession(message=[("class:prompt", "You > ")])

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
        if command == "reminder":
            _cmd_reminder()
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
            response = agent.chat(user_input)
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

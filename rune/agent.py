"""
Rune Agent — The Brain.

Implements a ReAct-style (Reason + Act) loop:
  1.  Receive user intent in natural language.
  2.  Send intent + conversation history + available tools to the LLM.
  3.  If the LLM returns tool calls → execute them (with security checks)
      and feed results back to the LLM.
  4.  Repeat until the LLM responds with plain text (task complete).
"""

from __future__ import annotations

import datetime
import json
import os
import platform
import traceback
from typing import Any, Callable, Dict, List, Optional

from openai import OpenAI
from rich.console import Console
from rich.status import Status

from rune.config import RuneConfig
from rune.memory import MemoryStore
from rune.registry import ToolRegistry
from rune.reminder import ReminderStore
from rune.security import SecurityManager
from rune.session import SessionStore
from rune.skills import SkillStore
from rune.tool_log import ToolCallLog, format_args_short

console = Console()

# Maximum tool-calling iterations to prevent infinite loops
MAX_ITERATIONS = 50
AUTO_COMPACT_MESSAGE_LIMIT = 40
COMPACT_KEEP_RECENT_MESSAGES = 10
COMPACT_MAX_CHARS = 60_000


def _sanitize(text: str) -> str:
    """Remove surrogate characters that break UTF-8 encoding on Windows/WSL."""
    return text.encode("utf-8", errors="replace").decode("utf-8")


class Agent:
    """Core AI agent that converts natural-language intent into system actions."""

    def __init__(
        self,
        config: RuneConfig,
        registry: ToolRegistry,
        security: SecurityManager,
        session_store: Optional[SessionStore] = None,
        event_sink: Optional[Callable[[Dict[str, Any]], None]] = None,
        display_tool_calls: bool = True,
        show_status: bool = True,
    ) -> None:
        self.config = config
        self.registry = registry
        self.security = security
        self.session_store = session_store
        self.tool_log = ToolCallLog()
        self.event_sink = event_sink
        self.display_tool_calls = display_tool_calls
        self.show_status = show_status

        # Conversation memory (persists across turns in one session)
        self.conversation: List[Dict[str, Any]] = []

        # OpenAI-compatible client (works with OpenAI, Ollama, LM Studio, etc.)
        self.client = OpenAI(
            api_key=config.llm.api_key or "not-set",
            base_url=config.llm.base_url,
        )

    # ---- public API ----

    def chat(self, user_input: str) -> str:
        """
        Process one user turn.

        May trigger zero or more tool calls before returning the final
        assistant response as a string.
        """
        # Sanitize & append user message to conversation memory
        user_input = _sanitize(user_input)
        self.conversation.append({"role": "user", "content": user_input})
        self._emit({"type": "user", "content": user_input})
        if self.session_store:
            self.session_store.append("user_message", {"content": user_input})

        self.maybe_compact_history()

        # Build the full message list: system prompt + conversation history
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": self._system_prompt()},
            *self.conversation,
        ]

        tools_payload = self.registry.get_openai_tools()

        for _iteration in range(MAX_ITERATIONS):
            try:
                if self.show_status:
                    with Status("思考中...", console=console, spinner="dots"):
                        response = self.client.chat.completions.create(
                            model=self.config.llm.model,
                            messages=messages,
                            tools=tools_payload or None,  # type: ignore[arg-type]
                            temperature=self.config.llm.temperature,
                            max_tokens=self.config.llm.max_tokens,
                        )
                else:
                    response = self.client.chat.completions.create(
                        model=self.config.llm.model,
                        messages=messages,
                        tools=tools_payload or None,  # type: ignore[arg-type]
                        temperature=self.config.llm.temperature,
                        max_tokens=self.config.llm.max_tokens,
                    )
            except Exception as exc:
                error_msg = f"❌ LLM API 调用失败: {exc}"
                if self.show_status:
                    console.print(f"[bold red]{error_msg}[/bold red]")
                self._emit({"type": "error", "content": error_msg})
                return error_msg

            choice = response.choices[0]
            message = choice.message

            # --- Case A: LLM wants to call one or more tools ---
            if message.tool_calls:
                # Append assistant's decision (with tool_calls) to messages
                assistant_msg: Dict[str, Any] = {
                    "role": "assistant",
                    "content": message.content,  # may be None
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in message.tool_calls
                    ],
                }
                
                # Append reasoning_content if the model returns it (DeepSeek R1 / Reasoner compatibility)
                if hasattr(message, "reasoning_content") and message.reasoning_content:
                    assistant_msg["reasoning_content"] = message.reasoning_content
                
                messages.append(assistant_msg)
                if self.session_store:
                    self.session_store.append("assistant_tool_call", assistant_msg)

                # Execute each tool call
                for tc in message.tool_calls:
                    result_str = self._execute_tool_call(
                        tc.function.name, tc.function.arguments
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": result_str,
                        }
                    )
                    if self.session_store:
                        self.session_store.append(
                            "tool_result",
                            {
                                "tool_call_id": tc.id,
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                                "content": result_str,
                            },
                        )
                # Loop back — let the LLM see the results and decide next step
                continue

            # --- Case B: LLM responds with plain text — done ---
            text = message.content or ""
            self.conversation.append({"role": "assistant", "content": text})
            self._emit({"type": "assistant", "content": text})
            if self.session_store:
                self.session_store.append("assistant_message", {"content": text})
            return text

        # If we exhaust all iterations
        warning = "⚠️ 已达到最大迭代次数。任务可能过于复杂，请尝试拆分成更小的步骤。"
        self._emit({"type": "warning", "content": warning})
        if self.session_store:
            self.session_store.append("agent_warning", {"content": warning})
        return warning

    def clear_history(self) -> None:
        """Reset conversation memory."""
        self.conversation.clear()
        if self.session_store:
            self.session_store.append("history_cleared", {})

    def load_history(self, conversation: List[Dict[str, Any]]) -> None:
        """Replace in-memory conversation with a restored transcript."""
        self.conversation = list(conversation)

    def _emit(self, event: Dict[str, Any]) -> None:
        if self.event_sink:
            self.event_sink(event)

    def maybe_compact_history(self) -> bool:
        """Compact old conversation turns once the in-memory context grows large."""
        if len(self.conversation) <= AUTO_COMPACT_MESSAGE_LIMIT:
            return False
        ok, _message = self.compact_history(manual=False)
        return ok

    def compact_history(
        self,
        keep_recent: int = COMPACT_KEEP_RECENT_MESSAGES,
        manual: bool = True,
    ) -> tuple[bool, str]:
        """Summarize older turns into one system message and keep recent turns raw."""
        if len(self.conversation) <= keep_recent + 1:
            return False, "当前对话还不需要压缩。"

        old_messages = self.conversation[:-keep_recent]
        recent_messages = self.conversation[-keep_recent:]
        summary = self._summarize_messages(old_messages)
        if not summary:
            return False, "压缩失败：无法生成摘要。"

        compact_message = {
            "role": "system",
            "content": (
                "=== 已压缩的早期对话摘要 ===\n"
                "以下摘要来自本会话较早的消息，用于延续上下文。"
                "如果摘要与当前文件或系统状态冲突，请以工具读取到的最新状态为准。\n\n"
                f"{summary}"
            ),
        }
        self.conversation = [compact_message, *recent_messages]

        if self.session_store:
            self.session_store.append(
                "conversation_compacted",
                {
                    "summary": summary,
                    "compacted_messages": len(old_messages),
                    "kept_messages": len(recent_messages),
                    "recent_messages": recent_messages,
                    "manual": manual,
                },
            )

        return True, f"已压缩 {len(old_messages)} 条旧消息，保留最近 {len(recent_messages)} 条消息。"

    # ---- internal ----

    def _system_prompt(self) -> str:
        """Build a dynamic system prompt with live system state."""
        tool_count = self.registry.count
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        user = os.getenv("USER", os.getenv("USERNAME", "unknown"))
        cwd = os.getcwd()
        sys_info = f"{platform.system()} {platform.release()} ({platform.machine()})"
        hostname = platform.node()

        # Reminder section — injected so the agent always "remembers"
        reminder_section = ""
        try:
            store = ReminderStore()
            reminder_section = store.get_system_prompt_section()
        except Exception:
            pass

        memory_section = ""
        try:
            memory_section = MemoryStore(cwd=cwd).get_system_prompt_section()
        except Exception:
            pass

        plugin_section = ""
        try:
            plugin_section = self.registry.get_plugin_instructions()
        except Exception:
            pass

        skills_section = ""
        try:
            skills_section = SkillStore(cwd=cwd).manifest_section()
        except Exception:
            pass

        prompt = f"""\
你是 **Rune**，一个运行在用户本机的智能电脑控制代理。你通过工具直接读取文件、运行命令、管理进程、调用插件，并把结果反馈给用户。

=== 当前运行环境 ===
- 系统: {sys_info}
- 主机: {hostname}
- 用户: {user}
- 工作目录: {cwd}
- 当前时间: {now}
- 可用工具数: {tool_count}

=== 核心工作方式 ===
1. 先判断用户真正想完成什么；如果信息足够，就直接行动，不要把可执行任务只写成建议。
2. 多步骤任务按「观察 → 行动 → 校验 → 总结」推进。每次工具返回后根据真实结果决定下一步。
3. 对文件、环境、依赖、进程状态不要凭记忆猜测；需要依据时先调用读取/查询工具验证。
4. 修改已有文件时优先使用 edit_file；创建新文件或用户明确要求完整覆盖时再使用 write_file。
5. 长时间运行的服务、watcher、下载、构建任务优先使用 background_run_command，再用 background_status/background_output 检查。
6. 如果可用 Skills 中有匹配任务的工作流，先调用 skill_read 读取完整 SKILL.md，再按其中步骤执行。
7. 当用户要求「记住」长期偏好或事实时，使用 reminder_add；临时会话信息不要写入长期记忆。
8. 对删除、覆盖、大范围移动、发送外部消息等高风险行为，先说明影响，并遵守权限确认结果。
9. 工具失败时先读错误信息并尝试修复；不要重复执行同一个明显失败的操作。
10. 默认用中文简洁回复，重点说明做了什么、结果如何、是否还有风险或下一步。
"""
        if reminder_section:
            prompt += "\n" + reminder_section
        if memory_section:
            prompt += "\n\n" + memory_section
        if plugin_section:
            prompt += "\n\n" + plugin_section
        if skills_section:
            prompt += "\n\n" + skills_section

        return _sanitize(prompt)

    def _summarize_messages(self, messages: List[Dict[str, Any]]) -> str:
        """Use the configured LLM to create a compact, future-facing summary."""
        lines: List[str] = []
        for msg in messages:
            role = str(msg.get("role", "unknown"))
            content = msg.get("content", "")
            if content is None:
                continue
            if not isinstance(content, str):
                content = json.dumps(content, ensure_ascii=False)
            lines.append(f"{role.upper()}:\n{content}")

        transcript = "\n\n".join(lines)
        if len(transcript) > COMPACT_MAX_CHARS:
            transcript = transcript[-COMPACT_MAX_CHARS:]

        try:
            with Status("压缩上下文...", console=console, spinner="dots"):
                response = self.client.chat.completions.create(
                    model=self.config.llm.model,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "你是 Rune 的上下文压缩器。请把早期对话压缩成给未来助手读取的摘要。"
                                "保留用户目标、关键决定、已修改文件、工具执行结果、待办事项、错误和约束。"
                                "不要添加不存在的事实。用中文，结构清晰但简洁。"
                            ),
                        },
                        {"role": "user", "content": transcript},
                    ],
                    temperature=0,
                    max_tokens=min(self.config.llm.max_tokens, 2048),
                )
        except Exception as exc:
            if self.session_store:
                self.session_store.append("compact_error", {"error": str(exc)})
            return ""

        return _sanitize(response.choices[0].message.content or "").strip()

    def _execute_tool_call(self, func_name: str, raw_arguments: str) -> str:
        """Parse arguments, check security, and run the tool handler."""
        tool = self.registry.get(func_name)
        if tool is None:
            return f"Error: 未知工具 '{func_name}'"

        # Parse JSON arguments
        try:
            args: Dict[str, Any] = json.loads(raw_arguments) if raw_arguments else {}
        except json.JSONDecodeError as exc:
            return f"Error: 参数解析失败 — {exc}"

        # Security gate
        record = self.tool_log.add(func_name, args)
        if self.display_tool_calls:
            self._display_tool_call(record.id, tool.permission_level.value, func_name, args)
        self._emit(
            {
                "type": "tool_call",
                "record_id": record.id,
                "name": func_name,
                "args": args,
                "level": tool.permission_level.value,
            }
        )
        approved = self.security.check_permission(tool, args)
        if not approved:
            self.tool_log.update(record.id, "⛔ 操作已被用户取消。", approved=False)
            self._emit({"type": "tool_result", "record_id": record.id, "result": "⛔ 操作已被用户取消。"})
            return "⛔ 操作已被用户取消。"

        # Execute
        try:
            result = tool.handler(**args)
            result_str = _sanitize(str(result))
            self.tool_log.update(record.id, result_str, approved=True)
            self._emit({"type": "tool_result", "record_id": record.id, "result": result_str})
            return result_str
        except TypeError as exc:
            result_str = f"Error: 参数不匹配 — {exc}"
            self.tool_log.update(record.id, result_str, approved=True)
            self._emit({"type": "tool_result", "record_id": record.id, "result": result_str})
            return result_str
        except Exception as exc:
            tb = traceback.format_exc()
            # Give the LLM the traceback so it can potentially self-correct
            result_str = _sanitize(f"Error executing {func_name}: {exc}\n\nTraceback:\n{tb}")
            self.tool_log.update(record.id, result_str, approved=True)
            self._emit({"type": "tool_result", "record_id": record.id, "result": result_str})
            return result_str

    @staticmethod
    def _display_tool_call(record_id: int, level: str, func_name: str, args: Dict[str, Any]) -> None:
        """Display one compact tool-call line."""
        colour = {"green": "dim", "yellow": "yellow", "red": "bold red"}.get(level, "cyan")
        short_args = format_args_short(args)
        console.print(
            f"  🔧 [cyan]#{record_id}[/cyan] [{colour}]{func_name}[/{colour}]({short_args})"
        )

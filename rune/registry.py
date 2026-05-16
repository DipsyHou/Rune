"""
Rune Tool Registry.

Central registry that discovers, stores, and provides look-up for all
tool definitions.  Tools are loaded automatically from the `rune.tools`
package — any module that exposes a top-level `TOOLS` list is picked up.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from rune.config import DEFAULT_CONFIG_DIR
from rune.tools.base import ToolDefinition


class ToolRegistry:
    """Stores tool definitions and provides fast look-up by name."""

    def __init__(self) -> None:
        self._tools: Dict[str, ToolDefinition] = {}
        self._plugin_instructions: Dict[str, str] = {}

    # ---- registration ----

    def register(self, tool: ToolDefinition) -> None:
        """Register a single tool.  Duplicate names overwrite silently."""
        self._tools[tool.name] = tool

    def register_many(self, tools: List[ToolDefinition]) -> None:
        for t in tools:
            self.register(t)

    # ---- look-up ----

    def get(self, name: str) -> Optional[ToolDefinition]:
        return self._tools.get(name)

    def get_all(self) -> List[ToolDefinition]:
        return list(self._tools.values())

    def get_openai_tools(self) -> List[dict]:
        """Return all tools in OpenAI function-calling format."""
        return [t.to_openai_tool() for t in self._tools.values()]

    def get_plugin_instructions(self) -> str:
        """Return enabled plugin instructions for system prompt injection."""
        if not self._plugin_instructions:
            return ""
        return (
            "=== 已启用插件说明 ===\n"
            "以下说明来自已启用插件。使用插件工具前请遵守对应说明。\n\n"
            + "\n\n".join(self._plugin_instructions.values())
        )

    @property
    def count(self) -> int:
        return len(self._tools)

    # ---- auto-discovery ----

    def discover_and_load(self) -> int:
        """Import every sub-module under rune.tools (core tools, always loaded).
        Returns the number of tools loaded."""
        import importlib
        import pkgutil

        import rune.tools as tools_pkg

        loaded = 0
        for _importer, modname, _ispkg in pkgutil.iter_modules(tools_pkg.__path__):
            if modname == "base":
                continue
            try:
                module = importlib.import_module(f"rune.tools.{modname}")
                tool_list = getattr(module, "TOOLS", [])
                self.register_many(tool_list)
                loaded += len(tool_list)
            except Exception as exc:
                import sys
                print(f"[warning] Failed to load tool module '{modname}': {exc}", file=sys.stderr)
        return loaded

    def load_plugins(self, enabled_plugins: List[str]) -> int:
        """Load enabled plugins from rune/plugins/ and ~/.rune/plugins/.
        Returns the number of tool definitions loaded."""
        import importlib
        import importlib.util
        import sys
        from pathlib import Path

        loaded = 0
        for plugin_name in enabled_plugins:
            # 1) Try bundled plugins (rune/plugins/<name>.py)
            try:
                module = importlib.import_module(f"rune.plugins.{plugin_name}")
                tool_list = getattr(module, "TOOLS", [])
                self.register_many(tool_list)
                self._plugin_instructions[plugin_name] = self._build_plugin_instruction(
                    plugin_name, module, tool_list
                )
                loaded += len(tool_list)
                continue
            except ImportError:
                pass

            # 2) Try user plugins (~/.rune/plugins/<name>.py)
            plugin_path = DEFAULT_CONFIG_DIR / "plugins" / f"{plugin_name}.py"
            if plugin_path.exists():
                try:
                    mod_name = f"_rune_plugin_{plugin_name}"
                    spec = importlib.util.spec_from_file_location(mod_name, plugin_path)
                    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
                    sys.modules[mod_name] = module
                    spec.loader.exec_module(module)  # type: ignore[union-attr]
                    tool_list = getattr(module, "TOOLS", [])
                    self.register_many(tool_list)
                    self._plugin_instructions[plugin_name] = self._build_plugin_instruction(
                        plugin_name, module, tool_list
                    )
                    loaded += len(tool_list)
                except Exception as exc:
                    print(f"[warning] 加载用户插件 '{plugin_name}' 失败: {exc}", file=sys.stderr)
            else:
                print(
                    f"[warning] 插件 '{plugin_name}' 未找到（已查找 rune/plugins/ 和 ~/.rune/plugins/）",
                    file=sys.stderr,
                )
        return loaded

    @staticmethod
    def _build_plugin_instruction(plugin_name: str, module: object, tool_list: List[ToolDefinition]) -> str:
        """Build a prompt section from a plugin's explicit or inferred instructions."""
        if hasattr(module, "plugin_instructions"):
            try:
                text = getattr(module, "plugin_instructions")()
                if text:
                    return str(text).strip()
            except Exception:
                pass

        explicit = getattr(module, "PLUGIN_INSTRUCTIONS", "")
        if explicit:
            return str(explicit).strip()

        meta = getattr(module, "PLUGIN_META", {}) or {}
        display_name = meta.get("display_name") or meta.get("name") or plugin_name
        description = meta.get("description", "")
        tool_names = ", ".join(tool.name for tool in tool_list) or "(no tools)"
        return (
            f"--- Plugin: {display_name} ---\n"
            f"{description}\n"
            f"Available tools: {tool_names}"
        )

    @staticmethod
    def list_available_plugins() -> List[dict]:
        """Scan rune/plugins/ and ~/.rune/plugins/ for all available plugins.
        Returns list of dicts with keys: name, display_name, description, version,
        tool_count, source ('bundled' or 'user')."""
        import importlib
        import importlib.util
        import pkgutil
        import sys
        from pathlib import Path

        plugins: List[dict] = []

        # Bundled plugins
        try:
            import rune.plugins as plugins_pkg
            for _importer, modname, _ispkg in pkgutil.iter_modules(plugins_pkg.__path__):
                try:
                    module = importlib.import_module(f"rune.plugins.{modname}")
                    meta = getattr(module, "PLUGIN_META", {})
                    plugins.append({
                        "name": modname,
                        "display_name": meta.get("name", modname),
                        "description": meta.get("description", ""),
                        "version": meta.get("version", "?"),
                        "tool_count": len(getattr(module, "TOOLS", [])),
                        "source": "bundled",
                    })
                except Exception:
                    pass
        except ImportError:
            pass

        # User plugins
        user_plugin_dir = DEFAULT_CONFIG_DIR / "plugins"
        if user_plugin_dir.exists():
            for plugin_file in sorted(user_plugin_dir.glob("*.py")):
                modname = plugin_file.stem
                if any(p["name"] == modname for p in plugins):
                    continue  # bundled version takes priority
                try:
                    mod_name = f"_rune_plugin_scan_{modname}"
                    spec = importlib.util.spec_from_file_location(mod_name, plugin_file)
                    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
                    spec.loader.exec_module(module)  # type: ignore[union-attr]
                    meta = getattr(module, "PLUGIN_META", {})
                    plugins.append({
                        "name": modname,
                        "display_name": meta.get("name", modname),
                        "description": meta.get("description", ""),
                        "version": meta.get("version", "?"),
                        "tool_count": len(getattr(module, "TOOLS", [])),
                        "source": "user",
                    })
                except Exception:
                    pass

        return plugins

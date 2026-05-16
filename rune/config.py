"""
Rune Configuration Management.

Supports loading from:
  1. Default values
  2. Config file (~/.rune/config.yaml)
  3. Environment variables (highest priority)
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

import yaml
from dotenv import load_dotenv

# Load .env file if present in working directory
load_dotenv()

DEFAULT_CONFIG_DIR = Path.home() / ".rune"
DEFAULT_CONFIG_FILE = DEFAULT_CONFIG_DIR / "config.yaml"


@dataclass
class LLMConfig:
    """Large Language Model connection settings."""

    provider: str = "openai"  # openai | ollama | compatible
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o"
    temperature: float = 0.1
    max_tokens: int = 4096


@dataclass
class SecurityConfig:
    """Security and permission settings."""

    require_confirmation_for_red: bool = True
    require_confirmation_for_yellow: bool = False
    # Whether the AI agent is allowed to add/edit/remove reminders
    allow_ai_edit_reminders: bool = True
    # Ordered permission rules. Each rule:
    # {action: allow|deny|ask, tool: tool_name|*, contains: optional string}
    permission_rules: List[Dict[str, Any]] = field(default_factory=list)
    # Shell commands containing these substrings are always blocked
    blocked_commands: List[str] = field(
        default_factory=lambda: [
            "rm -rf /",
            "rm -rf /*",
            "mkfs.",
            "dd if=/dev/zero",
            "dd if=/dev/random",
            ":(){ :|:& };:",  # fork bomb
            "> /dev/sda",
            "chmod -R 777 /",
        ]
    )


@dataclass
class PluginsConfig:
    """Plugin management settings."""

    # List of plugin names to load on startup.
    # Bundled plugins: 'email', 'feishu'
    # User plugins:    any .py file placed in ~/.rune/plugins/
    enabled: List[str] = field(default_factory=list)


@dataclass
class RuneConfig:
    """Root configuration object for Rune."""

    llm: LLMConfig = field(default_factory=LLMConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    plugins: PluginsConfig = field(default_factory=PluginsConfig)

    # Generic storage for plugin-specific config sections.
    # Each key is the plugin name (e.g. "email", "feishu") → dict of settings.
    # Plugins read/write here via get_plugin_data() / set_plugin_data().
    plugin_data: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # ---- persistence ----

    @classmethod
    def load(cls) -> "RuneConfig":
        """Load configuration with priority: env vars > config file > defaults."""
        config = cls()

        # --- Layer 1: config file ---
        if DEFAULT_CONFIG_FILE.exists():
            try:
                with open(DEFAULT_CONFIG_FILE, encoding="utf-8") as fh:
                    data = yaml.safe_load(fh) or {}
                if "llm" in data and isinstance(data["llm"], dict):
                    for key, val in data["llm"].items():
                        if hasattr(config.llm, key):
                            setattr(config.llm, key, val)
                if "security" in data and isinstance(data["security"], dict):
                    for key, val in data["security"].items():
                        if hasattr(config.security, key):
                            setattr(config.security, key, val)
                if "plugins" in data and isinstance(data["plugins"], dict):
                    for key, val in data["plugins"].items():
                        if hasattr(config.plugins, key):
                            setattr(config.plugins, key, val)

                # Load plugin-specific data sections
                # Any top-level key that isn't a core section is treated as
                # plugin config (e.g. "email", "feishu").
                _core_keys = {"llm", "security", "plugins"}
                for section, values in data.items():
                    if section not in _core_keys and isinstance(values, dict):
                        config.plugin_data[section] = values

                # --- Migration: auto-enable for legacy config files ---
                if not config.plugins.enabled:
                    if config.plugin_data.get("email", {}).get("address"):
                        config.plugins.enabled.append("email")
                    if config.plugin_data.get("feishu", {}).get("app_id"):
                        config.plugins.enabled.append("feishu")

            except Exception:
                pass  # If config is broken, just use defaults

        # --- Layer 2: environment variables (override) ---
        if os.getenv("RUNE_API_KEY"):
            config.llm.api_key = os.getenv("RUNE_API_KEY", "")
        if os.getenv("RUNE_BASE_URL"):
            config.llm.base_url = os.getenv("RUNE_BASE_URL", "")
        if os.getenv("RUNE_MODEL"):
            config.llm.model = os.getenv("RUNE_MODEL", "")
        if os.getenv("RUNE_PROVIDER"):
            config.llm.provider = os.getenv("RUNE_PROVIDER", "")

        return config

    def save(self) -> None:
        """Persist current configuration to ~/.rune/config.yaml.

        Plugin-specific sections are always written from plugin_data,
        even for disabled plugins, so users don't lose their config.
        """
        DEFAULT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        data: dict = {
            "llm": {
                "provider": self.llm.provider,
                "api_key": self.llm.api_key,
                "base_url": self.llm.base_url,
                "model": self.llm.model,
                "temperature": self.llm.temperature,
                "max_tokens": self.llm.max_tokens,
            },
            "security": {
                "require_confirmation_for_red": self.security.require_confirmation_for_red,
                "require_confirmation_for_yellow": self.security.require_confirmation_for_yellow,
                "allow_ai_edit_reminders": self.security.allow_ai_edit_reminders,
                "permission_rules": self.security.permission_rules,
                "blocked_commands": self.security.blocked_commands,
            },
            "plugins": {
                "enabled": self.plugins.enabled,
            },
        }
        # Write ALL plugin-specific config sections (even for disabled plugins)
        for name, pdata in self.plugin_data.items():
            data[name] = pdata
        with open(DEFAULT_CONFIG_FILE, "w", encoding="utf-8") as fh:
            yaml.dump(data, fh, default_flow_style=False, allow_unicode=True)

    # ---- plugin data helpers ----

    def get_plugin_data(self, plugin_name: str) -> Dict[str, Any]:
        """Return the config dict for a plugin (empty dict if none)."""
        return self.plugin_data.get(plugin_name, {})

    def set_plugin_data(self, plugin_name: str, data: Dict[str, Any]) -> None:
        """Set (replace) the config dict for a plugin and persist."""
        self.plugin_data[plugin_name] = data
        self.save()

    # ---- helpers ----

    @property
    def is_api_key_set(self) -> bool:
        return bool(self.llm.api_key and self.llm.api_key.strip())

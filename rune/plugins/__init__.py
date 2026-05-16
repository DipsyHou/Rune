"""
Rune Plugin System.

Bundled optional plugins live here (email, feishu, ...).
User-created plugins go in ~/.rune/plugins/.

Each plugin is a Python module that exposes:
  TOOLS        : List[ToolDefinition]   (required)
  PLUGIN_META  : dict                   (optional, for UI display)
    {
        "name":        str,   # display name, e.g. "飞书 (Feishu)"
        "description": str,   # one-line description
        "version":     str,   # e.g. "1.0"
    }
  PLUGIN_INSTRUCTIONS: str              (optional, injected into system prompt)
  plugin_instructions() -> str          (optional, dynamic prompt instructions)
"""

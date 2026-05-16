"""In-memory tool call log for the interactive UI."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


def format_args_short(args: Dict[str, Any], max_len: int = 96) -> str:
    parts = []
    for key, value in args.items():
        if isinstance(value, str):
            rendered = json.dumps(value, ensure_ascii=False)
        else:
            rendered = json.dumps(value, ensure_ascii=False, default=str)
        if len(rendered) > 44:
            rendered = rendered[:41] + "..."
        parts.append(f"{key}={rendered}")
    text = ", ".join(parts)
    if len(text) > max_len:
        text = text[: max_len - 3] + "..."
    return text


@dataclass
class ToolCallRecord:
    id: int
    name: str
    args: Dict[str, Any]
    result: str = ""
    approved: bool = True


class ToolCallLog:
    """Stores tool calls so users can inspect full arguments/results later."""

    def __init__(self) -> None:
        self._records: List[ToolCallRecord] = []

    def add(self, name: str, args: Dict[str, Any]) -> ToolCallRecord:
        record = ToolCallRecord(id=len(self._records) + 1, name=name, args=args)
        self._records.append(record)
        return record

    def update(self, record_id: int, result: str, approved: bool = True) -> None:
        record = self.get(record_id)
        if record:
            record.result = result
            record.approved = approved

    def get(self, record_id: int) -> Optional[ToolCallRecord]:
        if 1 <= record_id <= len(self._records):
            return self._records[record_id - 1]
        return None

    def list_recent(self, limit: int = 20) -> List[ToolCallRecord]:
        return self._records[-limit:]

    def count(self) -> int:
        return len(self._records)

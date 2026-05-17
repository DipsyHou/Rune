"""
Session transcript storage for Rune.

Each interactive run writes an append-only JSONL transcript under
~/.rune/sessions/<project-key>/<session-id>.jsonl. The transcript keeps full
tool activity for debugging, while resume restores the compact conversation
history that the agent already uses between turns.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from rune.config import DEFAULT_CONFIG_DIR

SESSIONS_DIR = DEFAULT_CONFIG_DIR / "sessions"


def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def _project_key(cwd: str) -> str:
    """Create a stable, filesystem-safe project key from a working directory."""
    resolved = str(Path(cwd).expanduser().resolve())
    key = re.sub(r"[^A-Za-z0-9._-]+", "-", resolved).strip("-")
    return key[:120] or "unknown"


def _short(text: str, limit: int = 80) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


@dataclass
class SessionInfo:
    session_id: str
    path: Path
    project: str
    cwd: str
    created_at: str
    updated_at: str
    message_count: int
    title: str


class SessionStore:
    """Append-only JSONL transcript for the current Rune session."""

    def __init__(self, cwd: Optional[str] = None, session_id: Optional[str] = None) -> None:
        self.cwd = str(Path(cwd or os.getcwd()).expanduser().resolve())
        self.project = _project_key(self.cwd)
        self.session_id = session_id or uuid.uuid4().hex[:12]
        self.dir = SESSIONS_DIR / self.project
        self.path = self.dir / f"{self.session_id}.jsonl"
        self.dir.mkdir(parents=True, exist_ok=True)

        if not self.path.exists():
            self.append(
                "session_start",
                {
                    "cwd": self.cwd,
                    "project": self.project,
                    "session_id": self.session_id,
                },
            )

    def append(self, event: str, data: Dict[str, Any]) -> None:
        record = {
            "timestamp": _now(),
            "event": event,
            "session_id": self.session_id,
            "cwd": self.cwd,
            "data": data,
        }
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def restore_conversation(self) -> List[Dict[str, Any]]:
        """Load user/final-assistant turns back into Agent.conversation."""
        return load_conversation(self.path)

    def mark_resumed(self) -> None:
        self.append("session_resumed", {"path": str(self.path)})


def iter_session_records(path: Path) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return records


def load_conversation(path: Path) -> List[Dict[str, Any]]:
    conversation: List[Dict[str, Any]] = []
    for record in iter_session_records(path):
        event = record.get("event")
        data = record.get("data") or {}
        if event == "user_message":
            entry: Dict[str, Any] = {
                "role": "user",
                "content": data.get("content", ""),
            }
            if data.get("display") is not None:
                entry["display"] = data.get("display")
            conversation.append(entry)
        elif event == "assistant_message":
            conversation.append({"role": "assistant", "content": data.get("content", "")})
        elif event == "conversation_compacted":
            summary = str(data.get("summary", "")).strip()
            if summary:
                recent_messages = data.get("recent_messages", [])
                if not isinstance(recent_messages, list):
                    recent_messages = []
                conversation = [
                    {
                        "role": "system",
                        "content": (
                            "=== 已压缩的早期对话摘要 ===\n"
                            "以下摘要来自本会话较早的消息，用于延续上下文。\n\n"
                            f"{summary}"
                        ),
                    }
                ] + recent_messages
    return conversation


def _summarize_session(path: Path) -> Optional[SessionInfo]:
    records = iter_session_records(path)
    if not records:
        return None

    first = records[0]
    last = records[-1]
    first_data = first.get("data") or {}
    cwd = first_data.get("cwd") or first.get("cwd") or ""
    project = first_data.get("project") or path.parent.name
    title = "(no user message)"
    message_count = 0

    for record in records:
        event = record.get("event")
        data = record.get("data") or {}
        if event in {"user_message", "assistant_message"}:
            message_count += 1
        if event == "user_message" and title == "(no user message)":
            title = _short(str(data.get("content", "")))

    return SessionInfo(
        session_id=path.stem,
        path=path,
        project=project,
        cwd=cwd,
        created_at=str(first.get("timestamp", "")),
        updated_at=str(last.get("timestamp", "")),
        message_count=message_count,
        title=title,
    )


def list_sessions(limit: int = 20, cwd: Optional[str] = None) -> List[SessionInfo]:
    root = SESSIONS_DIR
    if cwd:
        root = root / _project_key(cwd)

    if not root.exists():
        return []

    paths = sorted(root.rglob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    sessions: List[SessionInfo] = []
    for path in paths[:limit]:
        info = _summarize_session(path)
        if info:
            sessions.append(info)
    return sessions


def find_session(session_id: str) -> Optional[SessionInfo]:
    matches = sorted(SESSIONS_DIR.rglob(f"{session_id}*.jsonl")) if SESSIONS_DIR.exists() else []
    if not matches:
        return None
    return _summarize_session(matches[0])


def resume_session(session_id: str) -> Optional[SessionStore]:
    info = find_session(session_id)
    if not info:
        return None
    store = SessionStore(cwd=info.cwd or os.getcwd(), session_id=info.session_id)
    store.mark_resumed()
    return store

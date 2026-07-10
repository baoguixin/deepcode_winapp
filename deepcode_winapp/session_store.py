from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .paths import SESSIONS_DIR


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ChatSession:
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    title: str = "New chat"
    provider: str = ""
    model: str = ""
    workspace: str = ""
    messages: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ChatSession":
        session = cls()
        for key in asdict(session):
            if key in data:
                setattr(session, key, data[key])
        if not isinstance(session.messages, list):
            session.messages = []
        return session


class SessionStore:
    def __init__(self, sessions_dir: Path = SESSIONS_DIR) -> None:
        self.sessions_dir = sessions_dir
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def list_sessions(self) -> list[ChatSession]:
        sessions: list[ChatSession] = []
        for path in self.sessions_dir.glob("*.json"):
            try:
                sessions.append(ChatSession.from_dict(json.loads(path.read_text(encoding="utf-8"))))
            except (OSError, json.JSONDecodeError):
                continue
        return sorted(sessions, key=lambda item: item.updated_at, reverse=True)

    def save(self, session: ChatSession) -> Path:
        session.updated_at = utc_now()
        path = self.sessions_dir / f"{session.id}.json"
        path.write_text(json.dumps(asdict(session), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return path

    def load(self, session_id: str) -> ChatSession:
        path = self.sessions_dir / f"{session_id}.json"
        return ChatSession.from_dict(json.loads(path.read_text(encoding="utf-8")))

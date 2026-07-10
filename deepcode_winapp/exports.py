from __future__ import annotations

from datetime import datetime
from typing import Any


def messages_to_markdown(title: str, messages: list[dict[str, Any]]) -> str:
    lines = [f"# {title or 'DeepCode Chat'}", "", f"Exported: {datetime.now().isoformat(timespec='seconds')}", ""]
    for message in messages:
        role = str(message.get("role") or "")
        if role == "system":
            continue
        content = str(message.get("content") or "").strip()
        reasoning = str(message.get("reasoning_content") or message.get("reasoning") or "").strip()
        if role == "user":
            lines.extend(["## You", "", content, ""])
        elif role == "assistant":
            if reasoning:
                lines.extend(["## Reasoning", "", reasoning, ""])
            if content:
                lines.extend(["## Assistant", "", content, ""])
        elif role == "tool":
            lines.extend(["## Tool", "", "```json", content, "```", ""])
    return "\n".join(lines).rstrip() + "\n"


def last_assistant_markdown(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "assistant":
            content = str(message.get("content") or "").strip()
            if content:
                return content + "\n"
    return ""

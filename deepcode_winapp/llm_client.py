from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .diagnostics import append_diagnostic
from .providers import normalize_chat_url


class LlmClientError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None, detail: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail or message


@dataclass
class ChatCompletionRequest:
    provider: str
    base_url: str
    api_key: str
    model: str
    messages: list[dict[str, Any]]
    temperature: float = 0.2
    tools: list[dict[str, Any]] | None = None
    tool_choice: str | None = None
    thinking_enabled: bool = False
    reasoning_effort: str = "high"


class OpenAICompatibleClient:
    def chat(self, request: ChatCompletionRequest, timeout: int = 180) -> dict[str, Any]:
        if not request.api_key.strip():
            raise LlmClientError("API key is required.")
        if not request.model.strip():
            raise LlmClientError("Model name is required.")

        payload = build_chat_payload(request)
        if request.tools:
            payload["tools"] = request.tools
            payload["tool_choice"] = request.tool_choice or "auto"

        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        url = normalize_chat_url(request.base_url)
        append_diagnostic(
            f"POST {url} provider={request.provider} model={request.model} "
            f"messages={len(request.messages)} tools={bool(request.tools)} thinking={request.thinking_enabled}"
        )
        http_request = urllib.request.Request(
            url,
            data=data,
            method="POST",
            headers={
                "Authorization": f"Bearer {request.api_key.strip()}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "deepcode-winapp/0.1",
            },
        )
        try:
            with urllib.request.urlopen(http_request, timeout=timeout) as response:
                body = response.read().decode("utf-8")
                append_diagnostic(f"HTTP {response.status} OK provider={request.provider} model={request.model}")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            append_diagnostic(f"HTTP {exc.code} ERROR provider={request.provider} model={request.model}: {detail[:1000]}")
            raise LlmClientError(f"HTTP {exc.code} from {url}: {detail}", status_code=exc.code, detail=detail) from exc
        except urllib.error.URLError as exc:
            append_diagnostic(f"NETWORK ERROR provider={request.provider} model={request.model}: {exc.reason}")
            raise LlmClientError(f"Network error while calling {url}: {exc.reason}") from exc
        except TimeoutError as exc:
            append_diagnostic(f"TIMEOUT provider={request.provider} model={request.model}")
            raise LlmClientError(f"Request timed out while calling {url}.") from exc

        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise LlmClientError(f"Invalid JSON response: {body[:500]}") from exc


def build_chat_payload(request: ChatCompletionRequest) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": request.model.strip(),
        "messages": sanitize_messages_for_api(request.messages),
    }

    provider = request.provider.strip().lower()
    is_deepseek = provider == "deepseek" or "deepseek" in request.base_url.lower()
    is_deepseek_v4 = is_deepseek and request.model.strip().lower().startswith("deepseek-v4")
    if is_deepseek_v4:
        payload["thinking"] = {"type": "enabled" if request.thinking_enabled else "disabled"}
        if request.thinking_enabled:
            payload["reasoning_effort"] = request.reasoning_effort if request.reasoning_effort in {"high", "max"} else "high"
        if not request.thinking_enabled:
            payload["temperature"] = request.temperature
    else:
        payload["temperature"] = request.temperature
    return payload


def sanitize_messages_for_api(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    allowed_by_role = {
        "system": {"role", "content", "name"},
        "user": {"role", "content", "name"},
        "assistant": {"role", "content", "name", "tool_calls"},
        "tool": {"role", "content", "tool_call_id", "name"},
    }
    sanitized: list[dict[str, Any]] = []
    for message in messages:
        role = str(message.get("role") or "")
        allowed = allowed_by_role.get(role)
        if not allowed:
            continue
        cleaned = {key: value for key, value in message.items() if key in allowed}
        if cleaned.get("content") is None and role != "assistant":
            cleaned["content"] = ""
        sanitized.append(cleaned)
    return sanitized


def extract_assistant_message(response: dict[str, Any]) -> dict[str, Any]:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LlmClientError(f"No choices in response: {response}")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise LlmClientError(f"No message in response: {response}")
    return message

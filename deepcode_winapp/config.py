from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .paths import DATA_DIR, PROJECT_ROOT, SETTINGS_PATH
from .providers import get_preset


DEFAULT_SYSTEM_PROMPT = """You are DeepCode Windows App, a coding assistant running on the user's Windows machine.
Answer in the user's language. When workspace tools are enabled, inspect files before proposing edits.
When the user asks to search the web, find latest/current information, identify trends, or gather sources, use the web_search tool before answering and cite source URLs.
Prefer small, reversible changes and explain risky shell commands before requesting them."""


@dataclass
class AppSettings:
    provider: str = "DeepSeek"
    base_url: str = "https://api.deepseek.com"
    api_key: str = ""
    model: str = "deepseek-v4-pro"
    language: str = "zh"
    temperature: float = 0.2
    workspace: str = str(PROJECT_ROOT)
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    enable_tools: bool = True
    enable_network_tools: bool = True
    ask_before_shell_or_write: bool = True
    permission_mode: str = "ask_sensitive"
    thinking_enabled: bool = True
    reasoning_effort: str = "high"
    response_format: str = "markdown"
    auto_load_skills: bool = True
    selected_skills: list[str] | None = None
    max_tool_rounds: int = 6

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppSettings":
        settings = cls()
        for field_name in asdict(settings):
            if field_name in data:
                setattr(settings, field_name, data[field_name])
        preset = get_preset(settings.provider)
        if not settings.base_url and preset.base_url:
            settings.base_url = preset.base_url
        if not settings.model and preset.default_model:
            settings.model = preset.default_model
        if settings.provider == "DeepSeek" and settings.model == "deepseek-chat":
            settings.model = "deepseek-v4-pro"
        settings.temperature = _coerce_float(settings.temperature, 0.2)
        settings.max_tool_rounds = max(1, int(_coerce_float(settings.max_tool_rounds, 6)))
        settings.enable_tools = _coerce_bool(settings.enable_tools, True)
        settings.enable_network_tools = _coerce_bool(settings.enable_network_tools, True)
        settings.ask_before_shell_or_write = _coerce_bool(settings.ask_before_shell_or_write, True)
        if "permission_mode" not in data:
            settings.permission_mode = "ask_sensitive" if settings.ask_before_shell_or_write else "auto_approve"
        if settings.permission_mode not in {"ask_sensitive", "ask_all", "auto_approve"}:
            settings.permission_mode = "ask_sensitive"
        settings.ask_before_shell_or_write = settings.permission_mode != "auto_approve"
        settings.thinking_enabled = _coerce_bool(settings.thinking_enabled, True)
        settings.auto_load_skills = _coerce_bool(settings.auto_load_skills, True)
        if settings.language not in {"zh", "en"}:
            settings.language = "zh"
        if settings.reasoning_effort not in {"high", "max"}:
            settings.reasoning_effort = "high"
        if settings.response_format not in {"auto", "markdown", "report", "table", "json"}:
            settings.response_format = "markdown"
        if settings.selected_skills is None:
            settings.selected_skills = []
        elif not isinstance(settings.selected_skills, list):
            settings.selected_skills = []
        else:
            settings.selected_skills = [str(name) for name in settings.selected_skills if str(name).strip()]
        settings.workspace = str(Path(settings.workspace).expanduser())
        return settings

    def to_safe_dict(self) -> dict[str, Any]:
        return asdict(self)


def _coerce_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on", "enabled"}:
            return True
        if normalized in {"0", "false", "no", "off", "disabled"}:
            return False
    if value is None:
        return default
    return bool(value)


def load_settings(path: Path = SETTINGS_PATH) -> AppSettings:
    if not path.exists():
        return AppSettings()
    try:
        return AppSettings.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return AppSettings()


def save_settings(settings: AppSettings, path: Path = SETTINGS_PATH) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(settings.to_safe_dict(), indent=2, ensure_ascii=False) + "\n"
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    bak_path = path.with_suffix(path.suffix + ".bak")
    if path.exists():
        try:
            bak_path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        except OSError:
            pass
    tmp_path.write_text(payload, encoding="utf-8")
    tmp_path.replace(path)

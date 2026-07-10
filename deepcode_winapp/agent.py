from __future__ import annotations

import json
from dataclasses import replace
from dataclasses import dataclass
from typing import Any, Callable

from .config import AppSettings
from .llm_client import ChatCompletionRequest, LlmClientError, OpenAICompatibleClient, extract_assistant_message
from .skills import discover_skills, format_skill_system_message, select_skills
from .web_tools import web_fetch, web_search
from .workspace import WorkspaceError, WorkspaceService


ApprovalCallback = Callable[[str, str], bool]
EventCallback = Callable[[str], None]


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files under the current workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "relative_path": {"type": "string", "description": "Directory relative to workspace."},
                    "pattern": {"type": "string", "description": "Filename glob pattern."},
                    "max_results": {"type": "integer", "minimum": 1, "maximum": 1000},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the public web for current information and return titles, URLs, and snippets. Use this when the user asks to search online, find latest/current information, trends, news, references, or sources.",
            "parameters": {
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string", "description": "Search query."},
                    "max_results": {"type": "integer", "minimum": 1, "maximum": 10},
                    "region": {"type": "string", "description": "DuckDuckGo region, e.g. cn-zh, us-en."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": "Fetch and extract readable text from a public web URL. Use after web_search when a result needs more detail.",
            "parameters": {
                "type": "object",
                "required": ["url"],
                "properties": {
                    "url": {"type": "string", "description": "HTTP or HTTPS URL to fetch."},
                    "max_chars": {"type": "integer", "minimum": 1000, "maximum": 50000},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a UTF-8 text file from the current workspace.",
            "parameters": {
                "type": "object",
                "required": ["path"],
                "properties": {
                    "path": {"type": "string", "description": "File path relative to workspace."},
                    "max_chars": {"type": "integer", "minimum": 1000, "maximum": 60000},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write a UTF-8 text file inside the current workspace.",
            "parameters": {
                "type": "object",
                "required": ["path", "content"],
                "properties": {
                    "path": {"type": "string", "description": "File path relative to workspace."},
                    "content": {"type": "string", "description": "Full file content to write."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "replace_in_file",
            "description": "Replace the first exact occurrence of text in a UTF-8 file.",
            "parameters": {
                "type": "object",
                "required": ["path", "old", "new"],
                "properties": {
                    "path": {"type": "string", "description": "File path relative to workspace."},
                    "old": {"type": "string", "description": "Exact existing text."},
                    "new": {"type": "string", "description": "Replacement text."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_powershell",
            "description": "Run a PowerShell command in the current workspace.",
            "parameters": {
                "type": "object",
                "required": ["command"],
                "properties": {
                    "command": {"type": "string", "description": "PowerShell command to execute."},
                    "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 600},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_path",
            "description": "Open a workspace file, workspace folder, or URL with the default Windows application after user approval.",
            "parameters": {
                "type": "object",
                "required": ["target"],
                "properties": {
                    "target": {"type": "string", "description": "Workspace-relative file/folder path or http(s) URL."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "launch_app",
            "description": "Launch a Windows application after user approval. Prefer this over shell commands when simply opening another program.",
            "parameters": {
                "type": "object",
                "required": ["executable"],
                "properties": {
                    "executable": {"type": "string", "description": "Executable name or absolute path, e.g. notepad.exe."},
                    "arguments": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional argument list passed without a shell.",
                    },
                },
            },
        },
    },
]


NETWORK_TOOL_NAMES = {"web_search", "web_fetch"}
SENSITIVE_TOOL_NAMES = {"write_file", "replace_in_file", "run_powershell", "open_path", "launch_app"}


@dataclass
class AgentResult:
    messages: list[dict[str, Any]]
    assistant_text: str


class CodingAgent:
    def __init__(
        self,
        client: OpenAICompatibleClient | None = None,
        on_event: EventCallback | None = None,
        on_approval: ApprovalCallback | None = None,
    ) -> None:
        self.client = client or OpenAICompatibleClient()
        self.on_event = on_event or (lambda _text: None)
        self.on_approval = on_approval or (lambda _title, _detail: True)

    def run(self, settings: AppSettings, messages: list[dict[str, Any]]) -> AgentResult:
        workspace = WorkspaceService(settings.workspace)
        original_messages = list(messages)
        working_messages = self._prepare_messages(settings, original_messages)
        tools = _tool_definitions_for_settings(settings)
        assistant_text = ""

        for round_index in range(settings.max_tool_rounds):
            self.on_event(f"Calling {settings.provider}/{settings.model}...")
            request = ChatCompletionRequest(
                provider=settings.provider,
                base_url=settings.base_url,
                api_key=settings.api_key,
                model=settings.model,
                messages=working_messages,
                temperature=settings.temperature,
                tools=tools,
                tool_choice="auto",
                thinking_enabled=settings.thinking_enabled,
                reasoning_effort=settings.reasoning_effort,
            )
            try:
                response = self.client.chat(request)
            except LlmClientError as exc:
                if tools and _looks_like_tool_compatibility_error(exc):
                    self.on_event("Provider rejected tool schema; retrying this turn without tools.")
                    tools = None
                    request = replace(request, tools=None, tool_choice=None)
                    response = self.client.chat(request)
                else:
                    raise
            assistant_message = extract_assistant_message(response)
            working_messages.append(assistant_message)
            assistant_text = str(assistant_message.get("content") or "")
            tool_calls = assistant_message.get("tool_calls")
            if not settings.enable_tools or not tool_calls:
                return AgentResult(_strip_ephemeral_messages(working_messages), assistant_text)

            for tool_call in tool_calls:
                tool_result = self._execute_tool_call(workspace, tool_call, settings)
                working_messages.append(tool_result)
            self.on_event(f"Tool round {round_index + 1} completed.")

        assistant_text += "\n\n[Stopped after max tool rounds.]"
        working_messages.append({"role": "assistant", "content": assistant_text})
        return AgentResult(_strip_ephemeral_messages(working_messages), assistant_text)

    def _execute_tool_call(
        self, workspace: WorkspaceService, tool_call: dict[str, Any], settings: AppSettings
    ) -> dict[str, Any]:
        function = tool_call.get("function") if isinstance(tool_call, dict) else None
        name = function.get("name") if isinstance(function, dict) else ""
        raw_args = function.get("arguments") if isinstance(function, dict) else "{}"
        call_id = str(tool_call.get("id") or name or "tool_call")

        try:
            args = json.loads(raw_args or "{}")
        except json.JSONDecodeError:
            args = {}

        detail = json.dumps(args, ensure_ascii=False, indent=2)
        self.on_event(f"Tool requested: {name}\n{detail}")

        try:
            self._require_tool_approval(settings, name, detail)
            if name == "list_files":
                result = workspace.list_files(
                    relative_path=str(args.get("relative_path") or "."),
                    pattern=str(args.get("pattern") or "*"),
                    max_results=int(args.get("max_results") or 200),
                )
            elif name == "read_file":
                result = workspace.read_file(str(args.get("path") or ""), int(args.get("max_chars") or 12000))
            elif name == "write_file":
                result = workspace.write_file(str(args.get("path") or ""), str(args.get("content") or ""))
            elif name == "replace_in_file":
                result = workspace.replace_in_file(
                    str(args.get("path") or ""), str(args.get("old") or ""), str(args.get("new") or "")
                )
            elif name == "run_powershell":
                result = workspace.run_powershell(
                    str(args.get("command") or ""), int(args.get("timeout_seconds") or 30)
                )
            elif name == "open_path":
                result = workspace.open_path(str(args.get("target") or ""))
            elif name == "launch_app":
                raw_arguments = args.get("arguments") or []
                arguments = raw_arguments if isinstance(raw_arguments, list) else []
                result = workspace.launch_app(str(args.get("executable") or ""), [str(item) for item in arguments])
            elif name == "web_search":
                if not settings.enable_network_tools:
                    raise WorkspaceError("Network search tools are disabled in settings.")
                result = _tool_result(web_search(
                    str(args.get("query") or ""),
                    int(args.get("max_results") or 5),
                    str(args.get("region") or "cn-zh"),
                ))
            elif name == "web_fetch":
                if not settings.enable_network_tools:
                    raise WorkspaceError("Network fetch tools are disabled in settings.")
                result = _tool_result(web_fetch(str(args.get("url") or ""), int(args.get("max_chars") or 12000)))
            else:
                raise WorkspaceError(f"Unknown tool: {name}")
            content = json.dumps({"ok": result.ok, "content": result.content, "data": result.data}, ensure_ascii=False)
        except Exception as exc:
            content = json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

        self.on_event(f"Tool finished: {name}")
        return {"role": "tool", "tool_call_id": call_id, "content": content}

    def _require_tool_approval(self, settings: AppSettings, tool_name: str, detail: str) -> None:
        if not _tool_requires_approval(settings, tool_name):
            return
        if not self.on_approval(f"Approve tool: {tool_name}", detail):
            raise WorkspaceError("User denied tool execution.")

    def _prepare_messages(self, settings: AppSettings, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        working_messages = list(messages)
        last_user_text = ""
        for message in reversed(working_messages):
            if message.get("role") == "user":
                last_user_text = str(message.get("content") or "")
                break
        skills = select_skills(
            discover_skills(settings.workspace),
            last_user_text,
            settings.selected_skills or [],
            settings.auto_load_skills,
        )
        skill_prompt = format_skill_system_message(skills)
        if skill_prompt:
            self.on_event("Loaded skills: " + ", ".join(skill.name for skill in skills))
            insert_at = 1 if working_messages and working_messages[0].get("role") == "system" else 0
            working_messages.insert(
                insert_at,
                {
                    "role": "system",
                    "content": skill_prompt,
                    "meta": {"ephemeral_skill_context": True, "skills": [skill.name for skill in skills]},
                },
            )
        format_prompt = _response_format_prompt(settings.response_format)
        if format_prompt:
            insert_at = 1 if working_messages and working_messages[0].get("role") == "system" else 0
            working_messages.insert(
                insert_at,
                {
                    "role": "system",
                    "content": format_prompt,
                    "meta": {"ephemeral_context": True, "response_format": settings.response_format},
                },
            )
        return working_messages


def _strip_ephemeral_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for message in messages:
        meta = message.get("meta")
        if isinstance(meta, dict) and (meta.get("ephemeral_skill_context") or meta.get("ephemeral_context")):
            continue
        result.append(message)
    return result


def _tool_definitions_for_settings(settings: AppSettings) -> list[dict[str, Any]] | None:
    if not settings.enable_tools:
        return None
    if settings.enable_network_tools:
        return TOOL_DEFINITIONS
    filtered: list[dict[str, Any]] = []
    for definition in TOOL_DEFINITIONS:
        function = definition.get("function", {})
        name = function.get("name") if isinstance(function, dict) else ""
        if name not in NETWORK_TOOL_NAMES:
            filtered.append(definition)
    return filtered


def _tool_result(content: str):
    return type("_WebToolResult", (), {"ok": True, "content": content, "data": None})()


def _looks_like_tool_compatibility_error(error: LlmClientError) -> bool:
    detail = (error.detail or str(error)).lower()
    if error.status_code not in {400, 404, 422}:
        return False
    return any(term in detail for term in ("tool", "tools", "function", "tool_choice", "tool_calls"))


def _tool_requires_approval(settings: AppSettings, tool_name: str) -> bool:
    mode = getattr(settings, "permission_mode", "ask_sensitive")
    if mode == "auto_approve":
        return False
    if mode == "ask_all":
        return True
    return tool_name in SENSITIVE_TOOL_NAMES


def _response_format_prompt(response_format: str) -> str:
    prompts = {
        "markdown": "Format final answers in clear Markdown with concise headings, bullets, tables, and code fences when useful.",
        "report": "Format substantial final answers as a polished report with a short executive summary, findings, and actionable next steps.",
        "table": "When the task asks for comparison, extraction, planning, or options, prefer compact Markdown tables plus brief notes.",
        "json": "When the user asks for structured output, return valid JSON only unless explanation is explicitly requested.",
    }
    return prompts.get(response_format, "")

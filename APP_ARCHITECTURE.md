# DeepCode Windows App Architecture

## Goal

Build a Python Windows desktop app, inspired by Codex-style coding assistants,
while reusing the original Deep Code CLI ideas:

- OpenAI-compatible `base_url` plus API key configuration.
- Persistent sessions.
- Workspace-aware coding tools.
- Confirmation before risky local operations.

The original `deepcode-cli-main` source is TypeScript/Node, so this app is a
new Python implementation placed beside it.

## Main Modules

- `deepcode_winapp/providers.py`
  Provider presets and URL normalization. Presets are editable starter values.
- `deepcode_winapp/config.py`
  Local settings stored in `deepcode_winapp/data/settings.json`.
- `deepcode_winapp/attachments.py`
  Converts user-selected local attachments into bounded text previews or file
  metadata for the next prompt.
- `deepcode_winapp/exports.py`
  Converts chats and final answers into Markdown files.
- `deepcode_winapp/llm_client.py`
  Standard-library HTTP client for OpenAI-compatible chat completions,
  DeepSeek v4 thinking payloads, API message sanitization, and diagnostics.
- `deepcode_winapp/web_tools.py`
  Standard-library web search and URL fetch helpers exposed as model tools,
  with multi-engine fallback for Sogou Weixin, DuckDuckGo HTML/Lite, Bing, and
  Baidu.
- `deepcode_winapp/skills.py`
  Codex/DeepCode-compatible skill discovery, frontmatter parsing, resource
  listing, explicit invocation, and temporary system-context injection.
- `deepcode_winapp/workspace.py`
  Workspace file and PowerShell tools with path-escape protection, output
  truncation, and basic destructive-command blocking.
- `deepcode_winapp/agent.py`
  Tool-call loop: model response, local tool execution, tool result feedback.
- `deepcode_winapp/session_store.py`
  JSON chat persistence under `deepcode_winapp/data/sessions`.
- `deepcode_winapp/app.py`
  Tkinter desktop UI.

## MVP Boundaries

Implemented:

- Chat with domestic model providers through configurable OpenAI-compatible APIs.
- Editable provider, URL, key, model, temperature, and workspace.
- API connection test button and local diagnostics log.
- DeepSeek v4 thinking/reasoning payload support.
- Web search/fetch tools for current-information tasks, including fallback
  across multiple search engines and engine-status diagnostics.
- Explicit skill loading through `/skill`, `@skill`, `$skill`, UI selection, and `/skills`.
- Tool-capable coding loop for file inspection, file edits, and PowerShell.
- Permission modes for sensitive-only approval, every-tool approval, or auto-approval.
- `open_path` tool for opening workspace files/folders or URLs with the default
  Windows app after approval.
- `launch_app` tool for starting a Windows application with explicit arguments
  after approval, without shell string interpolation.
- Text attachment upload and Markdown export/save-answer flows.
- Chinese/English UI switching and output-format preference prompts.
- Local settings/session persistence.
- Tests for URL normalization, DeepSeek payloads, settings coercion, workspace
  safety, skill discovery, attachment/export helpers, multi-engine web-search
  parsing/fallback, provider tool fallback, permission approval, and tool loops.

Intentionally left for a later iteration:

- Streaming token display.
- MCP servers.
- Multi-image/multimodal attachments.
- Rich diff viewer before writes.
- Sandboxed process runner beyond current workspace confirmation.
- Visual screen-control automation for arbitrary desktop apps.
- Native installer generation.

## Extension Points

Add a provider:

1. Edit `deepcode_winapp/providers.py`.
2. Add a `ProviderPreset`.
3. Keep base URL editable in the UI because vendor endpoints can change.

Add a tool:

1. Add the JSON schema to `TOOL_DEFINITIONS` in `agent.py`.
2. Add the execution method in `WorkspaceService` if it touches local state.
3. Add approval gating for write, shell, delete, network, or other risky actions.
4. Add a focused unit test.

Add or call a skill:

1. Put `SKILL.md` under one of the scanned roots listed in `README.md`.
2. Include `name` and `description` frontmatter.
3. Use `/skills` to verify discovery.
4. Invoke with `/name`, `@name`, `$name`, or select it in the UI.

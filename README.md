# DeepCode Windows App

This is a Python/Tkinter Windows desktop MVP built beside the original
`deepcode-cli-main` TypeScript CLI source. It keeps the original CLI untouched
and adds a local app under `D:\Project\deepcode\deepcode_winapp`.

## What Works

- Provider presets for DeepSeek, Qwen, Kimi, GLM, MiniMax, Doubao, ERNIE, and Custom.
- Editable `base_url`, API key, model, temperature, and workspace.
- DeepSeek defaults to `deepseek-v4-pro` and supports thinking/reasoning controls.
- Chinese/English UI switching from the top toolbar.
- `Test API` button for verifying URL, key, model, and response format before chatting.
- OpenAI-compatible `/chat/completions` requests through Python standard library HTTP.
- Persistent local settings and chat sessions under `deepcode_winapp\data`.
- Diagnostics log under `deepcode_winapp\data\logs\diagnostics.log`.
- Attachment upload for text/code/Markdown/CSV/JSON files, with unsupported binary
  files passed as local path metadata.
- Markdown export for full chats and one-click save for the last assistant answer.
- Output-format preference (`auto`, `markdown`, `report`, `table`, `json`).
- Web search tools exposed to tool-capable models:
  - `web_search`
  - `web_fetch`
- Codex/DeepCode-style skill discovery and loading:
  - workspace `.deepcode\skills`
  - workspace `.agents\skills`
  - workspace `.codex\skills`
  - user `~\.deepcode\skills`
  - user `~\.agents\skills`
  - user `~\.codex\skills`
  - bundled DeepCode CLI skills when available
- Optional workspace tools exposed to tool-capable models:
  - `list_files`
  - `read_file`
  - `write_file`
  - `replace_in_file`
  - `run_powershell`
  - `open_path`
  - `launch_app`
- Permission modes: approve sensitive tools, approve every tool, or auto-approve.

## Run

```powershell
cd D:\Project\deepcode\deepcode_winapp
python .\run_app.py
```

You can also double-click:

```text
D:\Project\deepcode\deepcode_winapp\Launch-DeepCodeWinApp.cmd
```

No Python package dependency is required for the MVP. Tkinter is included in
most standard Python builds on Windows.

## Skills

Use `/skills` in the chat box to list available skills. You can call a skill
explicitly with `/skill-name`, `@skill-name`, or `$skill-name`, or select skills
from the left panel before sending. Automatic skill matching is available but
can be controlled with `Auto-load matching skills`; it is on by default for new
settings so Codex-style skill invocation works without extra setup.

## Permissions, Attachments, And Export

Use `Tools & Permissions` to choose how much local execution should require
approval:

- `ask_sensitive`: approve writes, PowerShell, file/URL opening, and app launching.
- `ask_all`: approve every tool call, including reads and search.
- `auto_approve`: run tools without prompts.

Use `Attach Files` below the prompt box to include local files in the next user
message. Text-like files are embedded into the prompt; binary or unsupported
files are represented by path and size metadata. `Export Chat` saves the whole
conversation as Markdown, and `Save Answer` saves the latest assistant reply.

## Web Search

Keep `Enable workspace tools` and `Enable network search` checked. When the
user asks for online search, trends, current information, news, references, or
sources, the model receives `web_search` and `web_fetch` tools. `web_search`
uses Python standard-library HTTP with multiple fallback engines: Sogou Weixin
for WeChat/public-account style Chinese queries, then DuckDuckGo HTML,
DuckDuckGo Lite, Bing, and Baidu. If an engine is blocked by the local network
or its HTML changes, the tool continues to the next engine and returns an
`Engine status` summary. Details are written to `data\logs\diagnostics.log`.

## Build A Windows EXE

Install PyInstaller only when you are ready to package:

```powershell
cd D:\Project\deepcode\deepcode_winapp
python -m pip install pyinstaller
python -m PyInstaller --noconsole --name DeepCodeWinApp .\run_app.py
```

The executable will be generated under `dist\DeepCodeWinApp`. Runtime settings
for the packaged app are stored beside the EXE in `dist\DeepCodeWinApp\data`,
not under `_internal`.

## Notes

- Most listed providers expose OpenAI-compatible APIs, but endpoint paths and
  model names can change. The app treats presets as starting values; edit them
  in the UI if your vendor console shows a different URL or model.
- API keys are stored locally in `data\settings.json`. Keep this folder private.
- If an older build created `dist\DeepCodeWinApp\_internal\data\settings.json`,
  do not distribute that folder; it may contain an API key.
- The original CLI uses `~/.deepcode/settings.json`; this MVP stores data inside
  the app folder because the requested output location is `D:\Project\deepcode`.
- See `APP_ARCHITECTURE.md` for module boundaries and extension points.

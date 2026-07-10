from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk
from typing import Any

from .agent import CodingAgent
from .attachments import build_attachment_context
from .config import AppSettings, load_settings, save_settings
from .exports import last_assistant_markdown, messages_to_markdown
from .llm_client import ChatCompletionRequest, LlmClientError, OpenAICompatibleClient, extract_assistant_message
from .providers import get_preset, provider_names
from .session_store import ChatSession, SessionStore
from .skills import discover_skills, format_skill_list


UI_TEXT = {
    "zh": {
        "app_title": "DeepCode Windows App",
        "new_chat": "新建",
        "save_chat": "保存会话",
        "export_chat": "导出会话",
        "save_answer": "保存回答",
        "test_api": "测试 API",
        "language": "语言",
        "model_tab": "模型",
        "tools_tab": "工具与权限",
        "skills_tab": "Skills",
        "sessions_tab": "会话",
        "provider": "模型供应商",
        "base_url": "调用地址",
        "api_key": "API 密钥",
        "model": "模型",
        "temperature": "温度",
        "workspace": "工作区",
        "browse": "选择文件夹",
        "thinking": "DeepSeek 思考",
        "reasoning": "推理强度",
        "response_format": "结果格式",
        "save_settings": "保存设置",
        "enable_tools": "启用工作区工具",
        "enable_network": "启用网络搜索",
        "permission_mode": "权限审批",
        "perm_ask_sensitive": "敏感操作审批",
        "perm_ask_all": "每个工具都审批",
        "perm_auto": "自动批准",
        "auto_skills": "自动加载匹配 Skills",
        "reload_skills": "刷新 Skills",
        "saved_chats": "已保存会话",
        "load_selected": "加载选中",
        "attach": "上传附件",
        "clear_attachments": "清空附件",
        "send": "发送",
        "ready": "就绪",
        "busy_title": "正在处理",
        "busy_message": "助手仍在工作。",
        "settings_saved": "设置已保存。",
        "testing_api": "正在测试 API...",
        "api_test": "API 测试",
        "api_test_failed": "API 测试失败",
        "api_ok": "API 正常",
        "new_chat_status": "已新建会话。",
        "chat_saved": "会话已保存。",
        "chat_loaded": "会话已加载。",
        "completed": "已完成。",
        "failed": "失败。",
        "skills_loaded": "已加载 {count} 个 skills。",
        "no_attachments": "未上传附件",
        "attachments": "附件：{count} 个",
        "approve": "批准",
        "deny": "拒绝",
        "approve_detail": "模型请求执行下面的本地/网络工具。请确认后再继续。",
        "export_done": "已导出：{path}",
        "nothing_to_save": "没有可保存的助手回答。",
        "you": "你",
        "assistant": "助手",
        "reasoning_label": "推理过程",
        "tool": "工具",
        "requested_tools": "助手请求调用工具。",
    },
    "en": {
        "app_title": "DeepCode Windows App",
        "new_chat": "New",
        "save_chat": "Save Chat",
        "export_chat": "Export Chat",
        "save_answer": "Save Answer",
        "test_api": "Test API",
        "language": "Language",
        "model_tab": "Model",
        "tools_tab": "Tools & Permissions",
        "skills_tab": "Skills",
        "sessions_tab": "Sessions",
        "provider": "Provider",
        "base_url": "Base URL",
        "api_key": "API Key",
        "model": "Model",
        "temperature": "Temperature",
        "workspace": "Workspace",
        "browse": "Browse",
        "thinking": "DeepSeek thinking",
        "reasoning": "Reasoning",
        "response_format": "Output format",
        "save_settings": "Save Settings",
        "enable_tools": "Enable workspace tools",
        "enable_network": "Enable network search",
        "permission_mode": "Permission approval",
        "perm_ask_sensitive": "Ask sensitive",
        "perm_ask_all": "Ask every tool",
        "perm_auto": "Auto approve",
        "auto_skills": "Auto-load matching skills",
        "reload_skills": "Reload Skills",
        "saved_chats": "Saved chats",
        "load_selected": "Load Selected",
        "attach": "Attach Files",
        "clear_attachments": "Clear Attachments",
        "send": "Send",
        "ready": "Ready",
        "busy_title": "Busy",
        "busy_message": "The assistant is still working.",
        "settings_saved": "Settings saved.",
        "testing_api": "Testing API...",
        "api_test": "API Test",
        "api_test_failed": "API test failed",
        "api_ok": "API OK",
        "new_chat_status": "New chat.",
        "chat_saved": "Chat saved.",
        "chat_loaded": "Chat loaded.",
        "completed": "Completed.",
        "failed": "Failed.",
        "skills_loaded": "Loaded {count} skills.",
        "no_attachments": "No attachments",
        "attachments": "Attachments: {count}",
        "approve": "Approve",
        "deny": "Deny",
        "approve_detail": "The model requested the local/network tool below. Review before continuing.",
        "export_done": "Exported: {path}",
        "nothing_to_save": "No assistant answer to save.",
        "you": "You",
        "assistant": "Assistant",
        "reasoning_label": "Reasoning",
        "tool": "Tool",
        "requested_tools": "Assistant requested tools.",
    },
}


class DeepCodeApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.geometry("1280x820")
        self.minsize(980, 660)

        self.settings = load_settings()
        self.store = SessionStore()
        self.session = ChatSession(
            provider=self.settings.provider,
            model=self.settings.model,
            workspace=self.settings.workspace,
            messages=[{"role": "system", "content": self.settings.system_prompt}],
        )
        self.ui_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.saved_sessions: list[ChatSession] = []
        self.skill_items = []
        self.pending_attachment_paths: list[str] = []
        self.localized_widgets: list[tuple[Any, str]] = []
        self.notebook_tabs: list[tuple[ttk.Notebook, Any, str]] = []

        self._create_variables()
        self._build_ui()
        self._load_skills()
        self._load_session_list()
        self._render_chat()
        self.after(100, self._drain_ui_queue)

    def _create_variables(self) -> None:
        self.language_var = tk.StringVar(value=self.settings.language)
        self.provider_var = tk.StringVar(value=self.settings.provider)
        self.base_url_var = tk.StringVar(value=self.settings.base_url)
        self.api_key_var = tk.StringVar(value=self.settings.api_key)
        self.model_var = tk.StringVar(value=self.settings.model)
        self.temperature_var = tk.StringVar(value=str(self.settings.temperature))
        self.workspace_var = tk.StringVar(value=self.settings.workspace)
        self.enable_tools_var = tk.BooleanVar(value=self.settings.enable_tools)
        self.enable_network_tools_var = tk.BooleanVar(value=self.settings.enable_network_tools)
        self.permission_mode_var = tk.StringVar(value=self.settings.permission_mode)
        self.thinking_var = tk.BooleanVar(value=self.settings.thinking_enabled)
        self.reasoning_var = tk.StringVar(value=self.settings.reasoning_effort)
        self.response_format_var = tk.StringVar(value=self.settings.response_format)
        self.auto_skills_var = tk.BooleanVar(value=self.settings.auto_load_skills)
        self.status_var = tk.StringVar(value=self._t("ready"))
        self.session_var = tk.StringVar(value="")
        self.attachment_var = tk.StringVar(value=self._attachment_summary())

    def _build_ui(self) -> None:
        self._configure_style()
        self.localized_widgets = []
        self.notebook_tabs = []
        self.title(self._t("app_title"))
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        toolbar = ttk.Frame(self, padding=(10, 8))
        toolbar.grid(row=0, column=0, sticky="ew")
        toolbar.columnconfigure(6, weight=1)
        self._button(toolbar, "new_chat", self._new_chat).grid(row=0, column=0, padx=(0, 6))
        self._button(toolbar, "save_chat", self._save_session).grid(row=0, column=1, padx=(0, 6))
        self._button(toolbar, "export_chat", self._export_chat_markdown).grid(row=0, column=2, padx=(0, 6))
        self._button(toolbar, "save_answer", self._save_last_answer).grid(row=0, column=3, padx=(0, 6))
        self._button(toolbar, "test_api", self._test_api_connection).grid(row=0, column=4, padx=(0, 12))
        self._label(toolbar, "language").grid(row=0, column=7, padx=(0, 6), sticky="e")
        language = ttk.Combobox(toolbar, textvariable=self.language_var, values=["zh", "en"], state="readonly", width=6)
        language.grid(row=0, column=8, sticky="e")
        language.bind("<<ComboboxSelected>>", self._change_language)

        root = ttk.PanedWindow(self, orient="horizontal")
        root.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))

        sidebar = ttk.Frame(root, padding=(0, 0, 10, 0), width=350)
        main = ttk.Frame(root)
        root.add(sidebar, weight=0)
        root.add(main, weight=1)

        notebook = ttk.Notebook(sidebar)
        notebook.pack(fill="both", expand=True)
        model_tab = ttk.Frame(notebook, padding=10)
        tools_tab = ttk.Frame(notebook, padding=10)
        skills_tab = ttk.Frame(notebook, padding=10)
        sessions_tab = ttk.Frame(notebook, padding=10)
        notebook.add(model_tab, text=self._t("model_tab"))
        notebook.add(tools_tab, text=self._t("tools_tab"))
        notebook.add(skills_tab, text=self._t("skills_tab"))
        notebook.add(sessions_tab, text=self._t("sessions_tab"))
        self.notebook_tabs.extend(
            [
                (notebook, model_tab, "model_tab"),
                (notebook, tools_tab, "tools_tab"),
                (notebook, skills_tab, "skills_tab"),
                (notebook, sessions_tab, "sessions_tab"),
            ]
        )

        self._build_model_tab(model_tab)
        self._build_tools_tab(tools_tab)
        self._build_skills_tab(skills_tab)
        self._build_sessions_tab(sessions_tab)
        self._build_chat_area(main)

    def _build_model_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        self._label(parent, "provider").grid(row=0, column=0, sticky="w")
        provider = ttk.Combobox(parent, textvariable=self.provider_var, values=provider_names(), state="readonly")
        provider.grid(row=1, column=0, sticky="ew", pady=(2, 8))
        provider.bind("<<ComboboxSelected>>", lambda _event: self._apply_provider_preset())

        self._label(parent, "base_url").grid(row=2, column=0, sticky="w")
        ttk.Entry(parent, textvariable=self.base_url_var).grid(row=3, column=0, sticky="ew", pady=(2, 8))

        self._label(parent, "api_key").grid(row=4, column=0, sticky="w")
        ttk.Entry(parent, textvariable=self.api_key_var, show="*").grid(row=5, column=0, sticky="ew", pady=(2, 8))

        self._label(parent, "model").grid(row=6, column=0, sticky="w")
        ttk.Entry(parent, textvariable=self.model_var).grid(row=7, column=0, sticky="ew", pady=(2, 8))

        self._label(parent, "temperature").grid(row=8, column=0, sticky="w")
        ttk.Spinbox(parent, from_=0.0, to=2.0, increment=0.1, textvariable=self.temperature_var, width=8).grid(
            row=9, column=0, sticky="w", pady=(2, 8)
        )

        self._label(parent, "workspace").grid(row=10, column=0, sticky="w")
        ttk.Entry(parent, textvariable=self.workspace_var).grid(row=11, column=0, sticky="ew", pady=(2, 4))
        self._button(parent, "browse", self._choose_workspace).grid(row=12, column=0, sticky="ew", pady=(0, 8))

        self._check(parent, "thinking", self.thinking_var).grid(row=13, column=0, sticky="w")
        self._label(parent, "reasoning").grid(row=14, column=0, sticky="w", pady=(8, 0))
        ttk.Combobox(parent, textvariable=self.reasoning_var, values=["high", "max"], state="readonly", width=10).grid(
            row=15, column=0, sticky="w", pady=(2, 8)
        )

        self._label(parent, "response_format").grid(row=16, column=0, sticky="w")
        ttk.Combobox(
            parent,
            textvariable=self.response_format_var,
            values=["auto", "markdown", "report", "table", "json"],
            state="readonly",
        ).grid(row=17, column=0, sticky="ew", pady=(2, 8))

        self._button(parent, "save_settings", self._save_settings_from_ui).grid(row=18, column=0, sticky="ew")

    def _build_tools_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        self._check(parent, "enable_tools", self.enable_tools_var).grid(row=0, column=0, sticky="w", pady=(0, 6))
        self._check(parent, "enable_network", self.enable_network_tools_var).grid(row=1, column=0, sticky="w", pady=(0, 12))
        self._label(parent, "permission_mode").grid(row=2, column=0, sticky="w")
        ttk.Combobox(
            parent,
            textvariable=self.permission_mode_var,
            values=["ask_sensitive", "ask_all", "auto_approve"],
            state="readonly",
        ).grid(row=3, column=0, sticky="ew", pady=(2, 12))
        ttk.Label(parent, text=self._permission_help(), wraplength=300, foreground="#555").grid(
            row=4, column=0, sticky="ew"
        )

    def _build_skills_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)
        self._check(parent, "auto_skills", self.auto_skills_var).grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.skill_listbox = tk.Listbox(parent, selectmode="extended", height=12, exportselection=False)
        self.skill_listbox.grid(row=1, column=0, sticky="nsew", pady=(0, 8))
        self._button(parent, "reload_skills", self._load_skills).grid(row=2, column=0, sticky="ew")

    def _build_sessions_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        self._label(parent, "saved_chats").grid(row=0, column=0, sticky="w")
        self.session_combo = ttk.Combobox(parent, textvariable=self.session_var, values=[], state="readonly")
        self.session_combo.grid(row=1, column=0, sticky="ew", pady=(2, 6))
        self._button(parent, "load_selected", self._load_selected_session).grid(row=2, column=0, sticky="ew")

    def _build_chat_area(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)

        self.chat_text = scrolledtext.ScrolledText(parent, wrap="word", state="disabled", font=("Microsoft YaHei UI", 10))
        self.chat_text.grid(row=0, column=0, sticky="nsew")
        self.chat_text.tag_configure("role_user", foreground="#0f6cbd", font=("Microsoft YaHei UI", 10, "bold"))
        self.chat_text.tag_configure("role_assistant", foreground="#107c10", font=("Microsoft YaHei UI", 10, "bold"))
        self.chat_text.tag_configure("role_tool", foreground="#8a6d3b", font=("Microsoft YaHei UI", 10, "bold"))
        self.chat_text.tag_configure("reasoning", foreground="#666666")

        input_frame = ttk.Frame(parent)
        input_frame.grid(row=1, column=0, sticky="ew", pady=(8, 4))
        input_frame.columnconfigure(0, weight=1)
        self.input_text = tk.Text(input_frame, height=5, wrap="word", font=("Microsoft YaHei UI", 10))
        self.input_text.grid(row=0, column=0, sticky="ew")
        self.input_text.bind("<Control-Return>", lambda _event: self._send_message())
        self._button(input_frame, "send", self._send_message).grid(row=0, column=1, sticky="ns", padx=(8, 0))

        attachment_frame = ttk.Frame(parent)
        attachment_frame.grid(row=2, column=0, sticky="ew", pady=(0, 4))
        attachment_frame.columnconfigure(2, weight=1)
        self._button(attachment_frame, "attach", self._attach_files).grid(row=0, column=0, padx=(0, 6))
        self._button(attachment_frame, "clear_attachments", self._clear_attachments).grid(row=0, column=1, padx=(0, 8))
        ttk.Label(attachment_frame, textvariable=self.attachment_var).grid(row=0, column=2, sticky="w")

        ttk.Label(parent, textvariable=self.status_var).grid(row=3, column=0, sticky="w")

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TButton", padding=(8, 5))
        style.configure("TNotebook.Tab", padding=(12, 6))

    def _t(self, key: str) -> str:
        lang = getattr(self.settings, "language", "zh")
        return UI_TEXT.get(lang, UI_TEXT["zh"]).get(key, UI_TEXT["en"].get(key, key))

    def _label(self, parent: Any, key: str) -> ttk.Label:
        widget = ttk.Label(parent, text=self._t(key))
        self.localized_widgets.append((widget, key))
        return widget

    def _button(self, parent: Any, key: str, command: Any) -> ttk.Button:
        widget = ttk.Button(parent, text=self._t(key), command=command)
        self.localized_widgets.append((widget, key))
        return widget

    def _check(self, parent: Any, key: str, variable: tk.BooleanVar) -> ttk.Checkbutton:
        widget = ttk.Checkbutton(parent, text=self._t(key), variable=variable)
        self.localized_widgets.append((widget, key))
        return widget

    def _permission_help(self) -> str:
        if self.settings.language == "en":
            return "ask_sensitive approves write/shell/open operations; ask_all prompts for every tool; auto_approve runs tools without prompts."
        return "ask_sensitive 只审批写入、命令、打开文件/网页等敏感操作；ask_all 每个工具都审批；auto_approve 不弹出审批。"

    def _change_language(self, _event: Any = None) -> None:
        self.settings = self._settings_from_ui()
        save_settings(self.settings)
        self.status_var.set(self._t("settings_saved"))
        for child in self.winfo_children():
            child.destroy()
        self._build_ui()
        self._load_skills()
        self._load_session_list()
        self._render_chat()

    def _apply_provider_preset(self) -> None:
        preset = get_preset(self.provider_var.get())
        if preset.base_url:
            self.base_url_var.set(preset.base_url)
        if preset.default_model:
            self.model_var.set(preset.default_model)
        if preset.name == "DeepSeek":
            self.thinking_var.set(True)
            self.reasoning_var.set("high")
        self.status_var.set(preset.note or "Preset applied.")

    def _choose_workspace(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.workspace_var.get() or ".")
        if selected:
            self.workspace_var.set(selected)

    def _settings_from_ui(self) -> AppSettings:
        settings = AppSettings.from_dict(
            {
                "provider": self.provider_var.get(),
                "base_url": self.base_url_var.get(),
                "api_key": self.api_key_var.get(),
                "model": self.model_var.get(),
                "language": self.language_var.get(),
                "temperature": self.temperature_var.get(),
                "workspace": self.workspace_var.get(),
                "system_prompt": self.settings.system_prompt,
                "enable_tools": self.enable_tools_var.get(),
                "enable_network_tools": self.enable_network_tools_var.get(),
                "permission_mode": self.permission_mode_var.get(),
                "thinking_enabled": self.thinking_var.get(),
                "reasoning_effort": self.reasoning_var.get(),
                "response_format": self.response_format_var.get(),
                "auto_load_skills": self.auto_skills_var.get(),
                "selected_skills": self._selected_skill_names(),
                "max_tool_rounds": self.settings.max_tool_rounds,
            }
        )
        return settings

    def _save_settings_from_ui(self) -> None:
        self.settings = self._settings_from_ui()
        save_settings(self.settings)
        self.status_var.set(self._t("settings_saved"))

    def _test_api_connection(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo(self._t("busy_title"), self._t("busy_message"))
            return
        self._save_settings_from_ui()
        self.status_var.set(self._t("testing_api"))
        self.worker = threading.Thread(target=self._test_api_thread, daemon=True)
        self.worker.start()

    def _test_api_thread(self) -> None:
        try:
            response = OpenAICompatibleClient().chat(
                ChatCompletionRequest(
                    provider=self.settings.provider,
                    base_url=self.settings.base_url,
                    api_key=self.settings.api_key,
                    model=self.settings.model,
                    messages=[
                        {"role": "system", "content": "Reply with exactly: ok"},
                        {"role": "user", "content": "connection test"},
                    ],
                    temperature=0,
                    thinking_enabled=self.settings.thinking_enabled,
                    reasoning_effort=self.settings.reasoning_effort,
                ),
                timeout=60,
            )
            message = extract_assistant_message(response)
            text = str(message.get("content") or "").strip() or "(empty response)"
            self.ui_queue.put(("test_ok", f"{self._t('api_ok')}: {text[:300]}"))
        except Exception as exc:
            self.ui_queue.put(("test_failed", f"{type(exc).__name__}: {exc}"))

    def _new_chat(self) -> None:
        self._save_settings_from_ui()
        self.pending_attachment_paths = []
        self.attachment_var.set(self._attachment_summary())
        self.session = ChatSession(
            provider=self.settings.provider,
            model=self.settings.model,
            workspace=self.settings.workspace,
            messages=[{"role": "system", "content": self.settings.system_prompt}],
        )
        self._render_chat()
        self.status_var.set(self._t("new_chat_status"))

    def _save_session(self) -> None:
        self.session.provider = self.provider_var.get()
        self.session.model = self.model_var.get()
        self.session.workspace = self.workspace_var.get()
        self.store.save(self.session)
        self._load_session_list()
        self.status_var.set(self._t("chat_saved"))

    def _load_session_list(self) -> None:
        self.saved_sessions = self.store.list_sessions()
        labels = [f"{s.title} | {s.updated_at[:19]} | {s.id[:8]}" for s in self.saved_sessions]
        if hasattr(self, "session_combo"):
            self.session_combo.configure(values=labels)
        if labels:
            self.session_var.set(labels[0])

    def _load_selected_session(self) -> None:
        index = self.session_combo.current()
        if index < 0 or index >= len(self.saved_sessions):
            return
        self.session = self.saved_sessions[index]
        self.provider_var.set(self.session.provider or self.provider_var.get())
        if self.session.provider:
            self._apply_provider_preset()
        self.model_var.set(self.session.model or self.model_var.get())
        self.workspace_var.set(self.session.workspace or self.workspace_var.get())
        self._load_skills()
        self._render_chat()
        self.status_var.set(self._t("chat_loaded"))

    def _attach_files(self) -> None:
        paths = filedialog.askopenfilenames(initialdir=self.workspace_var.get() or ".")
        if not paths:
            return
        existing = set(self.pending_attachment_paths)
        for path in paths:
            if path not in existing:
                self.pending_attachment_paths.append(path)
        self.attachment_var.set(self._attachment_summary())

    def _clear_attachments(self) -> None:
        self.pending_attachment_paths = []
        self.attachment_var.set(self._attachment_summary())

    def _attachment_summary(self) -> str:
        count = len(getattr(self, "pending_attachment_paths", []))
        if count == 0:
            return self._t("no_attachments")
        return self._t("attachments").format(count=count)

    def _compose_user_content(self, text: str) -> str:
        attachment_context = build_attachment_context(self.pending_attachment_paths)
        if not attachment_context:
            return text
        return f"{text}\n\n{attachment_context}"

    def _send_message(self) -> str:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo(self._t("busy_title"), self._t("busy_message"))
            return "break"
        text = self.input_text.get("1.0", "end").strip()
        if not text and not self.pending_attachment_paths:
            return "break"
        self.input_text.delete("1.0", "end")
        self._save_settings_from_ui()
        if text.strip() == "/skills":
            self.session.messages.append({"role": "user", "content": text})
            self.session.messages.append(
                {"role": "assistant", "content": format_skill_list(discover_skills(self.settings.workspace))}
            )
            self._render_chat()
            self.store.save(self.session)
            self._load_session_list()
            return "break"
        title_text = text[:48] or Path(self.pending_attachment_paths[0]).name
        message_content = self._compose_user_content(text or "Please inspect the attached file(s).")
        self.pending_attachment_paths = []
        self.attachment_var.set(self._attachment_summary())
        if len([m for m in self.session.messages if m.get("role") == "user"]) == 0:
            self.session.title = title_text or "New chat"
        self.session.messages.append({"role": "user", "content": message_content})
        self._render_chat()
        self.store.save(self.session)
        self._load_session_list()
        self.worker = threading.Thread(target=self._run_agent_thread, daemon=True)
        self.worker.start()
        return "break"

    def _run_agent_thread(self) -> None:
        try:
            agent = CodingAgent(on_event=self._queue_event, on_approval=self._ask_approval_threadsafe)
            result = agent.run(self.settings, self.session.messages)
            self.session.messages = result.messages
            self.ui_queue.put(("render", None))
            self.ui_queue.put(("status", self._t("completed")))
            self.store.save(self.session)
            self.ui_queue.put(("sessions", None))
        except LlmClientError as exc:
            self.ui_queue.put(("assistant_error", str(exc)))
        except Exception as exc:
            self.ui_queue.put(("assistant_error", f"{type(exc).__name__}: {exc}"))

    def _queue_event(self, text: str) -> None:
        self.ui_queue.put(("event", text))

    def _ask_approval_threadsafe(self, title: str, detail: str) -> bool:
        event = threading.Event()
        answer = {"value": False}

        def ask() -> None:
            answer["value"] = self._show_approval_dialog(title, detail)
            event.set()

        self.ui_queue.put(("approval", ask))
        event.wait()
        return bool(answer["value"])

    def _show_approval_dialog(self, title: str, detail: str) -> bool:
        result = {"approved": False}
        dialog = tk.Toplevel(self)
        dialog.title(title)
        dialog.transient(self)
        dialog.grab_set()
        dialog.geometry("620x420")
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(1, weight=1)

        ttk.Label(dialog, text=self._t("approve_detail"), wraplength=580).grid(
            row=0, column=0, sticky="ew", padx=12, pady=(12, 6)
        )
        detail_text = scrolledtext.ScrolledText(dialog, wrap="word", height=12)
        detail_text.grid(row=1, column=0, sticky="nsew", padx=12, pady=6)
        detail_text.insert("1.0", detail)
        detail_text.configure(state="disabled")

        buttons = ttk.Frame(dialog)
        buttons.grid(row=2, column=0, sticky="e", padx=12, pady=(6, 12))

        def approve() -> None:
            result["approved"] = True
            dialog.destroy()

        def deny() -> None:
            result["approved"] = False
            dialog.destroy()

        self._button(buttons, "deny", deny).grid(row=0, column=0, padx=(0, 8))
        self._button(buttons, "approve", approve).grid(row=0, column=1)
        dialog.protocol("WM_DELETE_WINDOW", deny)
        self.wait_window(dialog)
        return bool(result["approved"])

    def _drain_ui_queue(self) -> None:
        try:
            while True:
                kind, payload = self.ui_queue.get_nowait()
                if kind == "status":
                    self.status_var.set(str(payload))
                elif kind == "event":
                    self._append_chat(self._t("tool"), str(payload))
                    self.status_var.set(str(payload).splitlines()[0])
                elif kind == "render":
                    self._render_chat()
                elif kind == "sessions":
                    self._load_session_list()
                elif kind == "approval":
                    payload()
                elif kind == "assistant_error":
                    self.session.messages.append({"role": "assistant", "content": f"[Error] {payload}"})
                    self._render_chat()
                    self.store.save(self.session)
                    self._load_session_list()
                    self.status_var.set(self._t("failed"))
                elif kind == "test_ok":
                    self.status_var.set(str(payload))
                    messagebox.showinfo(self._t("api_test"), str(payload))
                elif kind == "test_failed":
                    self.status_var.set(self._t("api_test_failed"))
                    messagebox.showerror(self._t("api_test_failed"), str(payload))
        except queue.Empty:
            pass
        self.after(100, self._drain_ui_queue)

    def _load_skills(self) -> None:
        try:
            self.skill_items = discover_skills(self.workspace_var.get())
        except Exception:
            self.skill_items = []
        selected = set(self.settings.selected_skills or [])
        if not hasattr(self, "skill_listbox"):
            return
        self.skill_listbox.delete(0, "end")
        for index, skill in enumerate(self.skill_items):
            label = f"{skill.name} [{skill.source}]"
            if skill.description:
                label += f" - {skill.description[:80]}"
            self.skill_listbox.insert("end", label)
            if skill.name in selected:
                self.skill_listbox.selection_set(index)
        self.status_var.set(self._t("skills_loaded").format(count=len(self.skill_items)))

    def _selected_skill_names(self) -> list[str]:
        names: list[str] = []
        if not hasattr(self, "skill_listbox"):
            return self.settings.selected_skills or []
        for index in self.skill_listbox.curselection():
            try:
                names.append(self.skill_items[int(index)].name)
            except (IndexError, ValueError):
                continue
        return names

    def _export_chat_markdown(self) -> None:
        self._save_settings_from_ui()
        target = filedialog.asksaveasfilename(
            initialdir=self.settings.workspace,
            initialfile=f"{self.session.title or 'deepcode-chat'}.md",
            defaultextension=".md",
            filetypes=[("Markdown", "*.md"), ("Text", "*.txt"), ("All files", "*.*")],
        )
        if not target:
            return
        Path(target).write_text(messages_to_markdown(self.session.title, self.session.messages), encoding="utf-8")
        self.status_var.set(self._t("export_done").format(path=target))

    def _save_last_answer(self) -> None:
        content = last_assistant_markdown(self.session.messages)
        if not content:
            messagebox.showinfo(self._t("save_answer"), self._t("nothing_to_save"))
            return
        target = filedialog.asksaveasfilename(
            initialdir=self.workspace_var.get() or ".",
            initialfile="deepcode-answer.md",
            defaultextension=".md",
            filetypes=[("Markdown", "*.md"), ("Text", "*.txt"), ("All files", "*.*")],
        )
        if not target:
            return
        Path(target).write_text(content, encoding="utf-8")
        self.status_var.set(self._t("export_done").format(path=target))

    def _render_chat(self) -> None:
        self.chat_text.configure(state="normal")
        self.chat_text.delete("1.0", "end")
        for message in self.session.messages:
            role = str(message.get("role", ""))
            if role == "system":
                continue
            if role == "tool":
                content = str(message.get("content") or "")
                self.chat_text.insert("end", f"\n[{self._t('tool')}]\n", "role_tool")
                self.chat_text.insert("end", f"{content}\n")
            elif role == "assistant":
                content = str(message.get("content") or "")
                reasoning = str(message.get("reasoning_content") or message.get("reasoning") or "")
                if reasoning:
                    self.chat_text.insert("end", f"\n{self._t('reasoning_label')}\n", "reasoning")
                    self.chat_text.insert("end", f"{reasoning}\n", "reasoning")
                if content:
                    self.chat_text.insert("end", f"\n{self._t('assistant')}\n", "role_assistant")
                    self.chat_text.insert("end", f"{content}\n")
                if message.get("tool_calls"):
                    self.chat_text.insert("end", f"\n{self._t('requested_tools')}\n", "role_tool")
            elif role == "user":
                self.chat_text.insert("end", f"\n{self._t('you')}\n", "role_user")
                self.chat_text.insert("end", f"{message.get('content') or ''}\n")
        self.chat_text.configure(state="disabled")
        self.chat_text.see("end")

    def _append_chat(self, role: str, text: str) -> None:
        self.chat_text.configure(state="normal")
        self.chat_text.insert("end", f"\n[{role}]\n", "role_tool")
        self.chat_text.insert("end", f"{text}\n")
        self.chat_text.configure(state="disabled")
        self.chat_text.see("end")


def main() -> None:
    app = DeepCodeApp()
    app.mainloop()

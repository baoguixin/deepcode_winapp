import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from deepcode_winapp.agent import CodingAgent
from deepcode_winapp.attachments import build_attachment_context
from deepcode_winapp.config import AppSettings
from deepcode_winapp.exports import last_assistant_markdown, messages_to_markdown
from deepcode_winapp.llm_client import ChatCompletionRequest, LlmClientError, build_chat_payload
from deepcode_winapp.providers import get_preset, normalize_chat_url
from deepcode_winapp.skills import discover_skills, format_skill_system_message, select_skills
from deepcode_winapp.web_tools import (
    html_to_text,
    normalize_duckduckgo_url,
    parse_baidu_html,
    parse_bing_html,
    parse_duckduckgo_html,
    parse_duckduckgo_lite_html,
    parse_sogou_weixin_html,
    web_search,
)
from deepcode_winapp.workspace import WorkspaceError, WorkspaceService, is_dangerous_shell_command


class ProviderTests(unittest.TestCase):
    def test_deepseek_preset_uses_v4_model(self) -> None:
        preset = get_preset("DeepSeek")
        self.assertEqual(preset.base_url, "https://api.deepseek.com")
        self.assertEqual(preset.default_model, "deepseek-v4-pro")

    def test_normalize_chat_url_appends_chat_completions(self) -> None:
        self.assertEqual(normalize_chat_url("https://example.com/v1"), "https://example.com/v1/chat/completions")

    def test_normalize_chat_url_for_deepseek(self) -> None:
        self.assertEqual(normalize_chat_url("https://api.deepseek.com"), "https://api.deepseek.com/chat/completions")

    def test_normalize_chat_url_keeps_full_url(self) -> None:
        self.assertEqual(
            normalize_chat_url("https://example.com/v1/chat/completions"),
            "https://example.com/v1/chat/completions",
        )


class SettingsTests(unittest.TestCase):
    def test_default_settings_use_deepseek_v4_and_auto_skills(self) -> None:
        settings = AppSettings()
        self.assertEqual(settings.model, "deepseek-v4-pro")
        self.assertTrue(settings.auto_load_skills)

    def test_settings_support_language_permission_and_format(self) -> None:
        settings = AppSettings.from_dict({"language": "en", "permission_mode": "ask_all", "response_format": "table"})
        self.assertEqual(settings.language, "en")
        self.assertEqual(settings.permission_mode, "ask_all")
        self.assertEqual(settings.response_format, "table")

    def test_old_approval_setting_migrates_to_auto_approve(self) -> None:
        settings = AppSettings.from_dict({"ask_before_shell_or_write": False})
        self.assertEqual(settings.permission_mode, "auto_approve")
        self.assertFalse(settings.ask_before_shell_or_write)

    def test_settings_coerces_temperature(self) -> None:
        settings = AppSettings.from_dict({"temperature": "0.7", "max_tool_rounds": "3"})
        self.assertEqual(settings.temperature, 0.7)
        self.assertEqual(settings.max_tool_rounds, 3)

    def test_settings_coerces_bool_strings(self) -> None:
        settings = AppSettings.from_dict(
            {"enable_tools": "false", "ask_before_shell_or_write": "off", "auto_load_skills": "no"}
        )
        self.assertFalse(settings.enable_tools)
        self.assertFalse(settings.ask_before_shell_or_write)
        self.assertFalse(settings.auto_load_skills)

    def test_settings_migrates_old_deepseek_default_model(self) -> None:
        settings = AppSettings.from_dict({"provider": "DeepSeek", "model": "deepseek-chat"})
        self.assertEqual(settings.model, "deepseek-v4-pro")


class PayloadTests(unittest.TestCase):
    def test_deepseek_v4_payload_includes_thinking(self) -> None:
        payload = build_chat_payload(
            ChatCompletionRequest(
                provider="DeepSeek",
                base_url="https://api.deepseek.com",
                api_key="sk-test",
                model="deepseek-v4-pro",
                messages=[{"role": "user", "content": "hi"}],
                thinking_enabled=True,
                reasoning_effort="max",
            )
        )
        self.assertEqual(payload["thinking"], {"type": "enabled"})
        self.assertEqual(payload["reasoning_effort"], "max")
        self.assertNotIn("temperature", payload)

    def test_deepseek_old_model_does_not_add_thinking(self) -> None:
        payload = build_chat_payload(
            ChatCompletionRequest(
                provider="DeepSeek",
                base_url="https://api.deepseek.com",
                api_key="sk-test",
                model="deepseek-chat",
                messages=[{"role": "user", "content": "hi"}],
            )
        )
        self.assertNotIn("thinking", payload)
        self.assertIn("temperature", payload)


class WorkspaceTests(unittest.TestCase):
    def test_workspace_blocks_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = WorkspaceService(tmp)
            with self.assertRaises(WorkspaceError):
                workspace.resolve_inside("../outside.txt")

    def test_read_write_inside_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = WorkspaceService(tmp)
            workspace.write_file("hello.txt", "hi")
            result = workspace.read_file("hello.txt")
            self.assertEqual(result.content, "hi")
            self.assertTrue((Path(tmp) / "hello.txt").exists())

    def test_open_path_uses_default_app_for_workspace_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "hello.txt").write_text("hi", encoding="utf-8")
            workspace = WorkspaceService(tmp)
            with patch("deepcode_winapp.workspace._open_target") as opened:
                result = workspace.open_path("hello.txt")
            self.assertTrue(result.ok)
            opened.assert_called_once()

    def test_launch_app_uses_popen_without_shell(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = WorkspaceService(tmp)
            with patch("deepcode_winapp.workspace.subprocess.Popen") as popen:
                popen.return_value.pid = 123
                result = workspace.launch_app("notepad.exe", ["a.txt"])
            self.assertTrue(result.ok)
            self.assertEqual(result.data["pid"], 123)
            popen.assert_called_once_with(["notepad.exe", "a.txt"], cwd=str(Path(tmp).resolve()))

    def test_shell_policy_blocks_dangerous_commands(self) -> None:
        self.assertTrue(is_dangerous_shell_command("Remove-Item . -Recurse -Force"))
        self.assertTrue(is_dangerous_shell_command("git reset --hard HEAD"))
        self.assertFalse(is_dangerous_shell_command("Get-ChildItem"))


class SkillsTests(unittest.TestCase):
    def test_discovers_and_formats_skill(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = Path(tmp) / ".deepcode" / "skills" / "review"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                "---\nname: review\ndescription: Review Python code. Use when reviewing code.\n---\n# Review\nRead diffs.",
                encoding="utf-8",
            )
            skills = discover_skills(tmp)
            self.assertIn("review", [skill.name for skill in skills])
            selected = select_skills(skills, "please /review this", [], False)
            self.assertIn("review", [skill.name for skill in selected])
            self.assertIn("<review-skill", format_skill_system_message(selected))


class WebToolTests(unittest.TestCase):
    def test_parse_duckduckgo_html(self) -> None:
        body = """
        <div class="result">
          <a class="result__a" href="/l/?uddg=https%3A%2F%2Fexample.com%2Fa">Example &amp; Title</a>
          <a class="result__snippet">Snippet <b>text</b></a>
        </div></div>
        """
        results = parse_duckduckgo_html(body)
        self.assertEqual(results[0].title, "Example & Title")
        self.assertEqual(results[0].url, "https://example.com/a")
        self.assertEqual(results[0].snippet, "Snippet text")

    def test_parse_duckduckgo_lite_html(self) -> None:
        body = """
        <tr><td><a rel="nofollow" href="/l/?uddg=https%3A%2F%2Fexample.com%2Flite">Lite Title</a></td></tr>
        <tr><td class="result-snippet">Lite snippet</td></tr>
        """
        results = parse_duckduckgo_lite_html(body)
        self.assertEqual(results[0].title, "Lite Title")
        self.assertEqual(results[0].url, "https://example.com/lite")

    def test_parse_bing_html(self) -> None:
        body = '<li class="b_algo"><h2><a href="https://example.com/b">Bing Title</a></h2><p>Bing snippet</p></li>'
        results = parse_bing_html(body)
        self.assertEqual(results[0].title, "Bing Title")
        self.assertEqual(results[0].url, "https://example.com/b")

    def test_parse_baidu_html(self) -> None:
        body = '<div class="result c-container" mu="https://example.com/baidu"><h3><a href="https://baidu.com/link">百度标题</a></h3><span>摘要</span></div>'
        results = parse_baidu_html(body)
        self.assertEqual(results[0].title, "百度标题")
        self.assertEqual(results[0].url, "https://example.com/baidu")

    def test_parse_sogou_weixin_html(self) -> None:
        body = '<li><h3><a href="https://mp.weixin.qq.com/s/abc">公众号标题</a></h3><p class="txt-info">微信摘要</p></li>'
        results = parse_sogou_weixin_html(body)
        self.assertEqual(results[0].title, "公众号标题")
        self.assertEqual(results[0].url, "https://mp.weixin.qq.com/s/abc")

    def test_parse_sogou_weixin_protocol_relative_url(self) -> None:
        body = '<li><h3><a href="//mp.weixin.qq.com/s/abc">公众号标题</a></h3><p class="txt-info">微信摘要</p></li>'
        results = parse_sogou_weixin_html(body)
        self.assertEqual(results[0].url, "https://mp.weixin.qq.com/s/abc")

    def test_web_search_falls_back_to_later_engine(self) -> None:
        def fake_fetch(url, timeout, max_bytes):
            if "sogou" in url or "duckduckgo" in url:
                return "<html>blocked</html>"
            if "bing.com" in url:
                return '<li class="b_algo"><h2><a href="https://example.com/topic">Topic</a></h2><p>Snippet</p></li>'
            return ""

        with patch("deepcode_winapp.web_tools._fetch_text", side_effect=fake_fetch):
            output = web_search("公众号 爆款 选题", max_results=2)
        self.assertIn("https://example.com/topic", output)
        self.assertIn("Engine status:", output)

    def test_html_to_text(self) -> None:
        self.assertEqual(html_to_text("<h1>A</h1><script>x</script><p>B&nbsp;C</p>"), "A B C")

    def test_normalize_duckduckgo_url(self) -> None:
        self.assertEqual(
            normalize_duckduckgo_url("/l/?uddg=https%3A%2F%2Fexample.com%2Ftopic"),
            "https://example.com/topic",
        )


class AttachmentAndExportTests(unittest.TestCase):
    def test_build_attachment_context_embeds_text_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "note.md")
            path.write_text("# Hello\ncontent", encoding="utf-8")
            context = build_attachment_context([str(path)])
            self.assertIn("<attachments>", context)
            self.assertIn("# Hello", context)

    def test_markdown_export_and_last_answer(self) -> None:
        messages = [
            {"role": "system", "content": "hidden"},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "answer"},
        ]
        exported = messages_to_markdown("Title", messages)
        self.assertIn("# Title", exported)
        self.assertIn("## You", exported)
        self.assertNotIn("hidden", exported)
        self.assertEqual(last_assistant_markdown(messages), "answer\n")


class FakeToolClient:
    def __init__(self) -> None:
        self.calls = 0

    def chat(self, request, timeout=180):
        self.calls += 1
        if self.calls == 1:
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "list_files",
                                        "arguments": '{"relative_path": ".", "pattern": "*.txt"}',
                                    },
                                }
                            ],
                        }
                    }
                ]
            }
        return {"choices": [{"message": {"role": "assistant", "content": "done"}}]}


class FakeWebSearchClient:
    def __init__(self) -> None:
        self.calls = 0

    def chat(self, request, timeout=180):
        self.calls += 1
        if self.calls == 1:
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call_web",
                                    "type": "function",
                                    "function": {
                                        "name": "web_search",
                                        "arguments": '{"query": "公众号 爆款 选题", "max_results": 3}',
                                    },
                                }
                            ],
                        }
                    }
                ]
            }
        return {"choices": [{"message": {"role": "assistant", "content": "searched"}}]}


class FakeCaptureToolsClient:
    def __init__(self) -> None:
        self.tools = None

    def chat(self, request, timeout=180):
        self.tools = request.tools
        return {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}


class FakeRejectToolsClient:
    def __init__(self) -> None:
        self.requests = []

    def chat(self, request, timeout=180):
        self.requests.append(request)
        if len(self.requests) == 1:
            raise LlmClientError("HTTP 400: tools not supported", status_code=400, detail="tools not supported")
        return {"choices": [{"message": {"role": "assistant", "content": "plain"}}]}


class AgentTests(unittest.TestCase):
    def test_agent_runs_tool_loop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "a.txt").write_text("hello", encoding="utf-8")
            settings = AppSettings.from_dict(
                {
                    "api_key": "test",
                    "model": "fake",
                    "workspace": tmp,
                    "enable_tools": True,
                    "auto_load_skills": False,
                    "max_tool_rounds": 3,
                }
            )
            agent = CodingAgent(client=FakeToolClient())
            result = agent.run(settings, [{"role": "user", "content": "list files"}])
            self.assertEqual(result.assistant_text, "done")
            self.assertTrue(any(message.get("role") == "tool" for message in result.messages))

    def test_agent_asks_approval_for_all_tools_when_configured(self) -> None:
        approvals: list[str] = []
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "a.txt").write_text("hello", encoding="utf-8")
            settings = AppSettings.from_dict(
                {
                    "api_key": "test",
                    "model": "fake",
                    "workspace": tmp,
                    "enable_tools": True,
                    "permission_mode": "ask_all",
                    "auto_load_skills": False,
                }
            )
            agent = CodingAgent(client=FakeToolClient(), on_approval=lambda title, _detail: approvals.append(title) or True)
            result = agent.run(settings, [{"role": "user", "content": "list files"}])
            self.assertEqual(result.assistant_text, "done")
            self.assertEqual(approvals, ["Approve tool: list_files"])

    def test_agent_retries_without_tools_when_provider_rejects_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = AppSettings.from_dict(
                {"api_key": "test", "model": "fake", "workspace": tmp, "enable_tools": True, "auto_load_skills": False}
            )
            client = FakeRejectToolsClient()
            agent = CodingAgent(client=client)
            result = agent.run(settings, [{"role": "user", "content": "hi"}])
            self.assertEqual(result.assistant_text, "plain")
            self.assertIsNotNone(client.requests[0].tools)
            self.assertIsNone(client.requests[1].tools)

    def test_agent_runs_web_search_tool_loop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = AppSettings.from_dict(
                {
                    "api_key": "test",
                    "model": "fake",
                    "workspace": tmp,
                    "enable_tools": True,
                    "enable_network_tools": True,
                    "auto_load_skills": False,
                }
            )
            agent = CodingAgent(client=FakeWebSearchClient())
            with patch("deepcode_winapp.agent.web_search", return_value="1. Result\n   URL: https://example.com"):
                result = agent.run(settings, [{"role": "user", "content": "请搜索网络"}])
            self.assertEqual(result.assistant_text, "searched")
            self.assertTrue(any("https://example.com" in str(message.get("content")) for message in result.messages))

    def test_network_tools_can_be_hidden(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = AppSettings.from_dict(
                {
                    "api_key": "test",
                    "model": "fake",
                    "workspace": tmp,
                    "enable_tools": True,
                    "enable_network_tools": False,
                    "auto_load_skills": False,
                }
            )
            client = FakeCaptureToolsClient()
            CodingAgent(client=client).run(settings, [{"role": "user", "content": "hi"}])
            names = [tool["function"]["name"] for tool in client.tools]
            self.assertNotIn("web_search", names)
            self.assertNotIn("web_fetch", names)


if __name__ == "__main__":
    unittest.main()

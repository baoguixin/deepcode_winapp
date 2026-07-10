from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderPreset:
    name: str
    base_url: str
    default_model: str
    note: str = ""


PROVIDER_PRESETS: dict[str, ProviderPreset] = {
    "DeepSeek": ProviderPreset(
        name="DeepSeek",
        base_url="https://api.deepseek.com",
        default_model="deepseek-v4-pro",
        note="OpenAI-compatible DeepSeek v4 endpoint. Use deepseek-v4-flash for cheaper/faster calls.",
    ),
    "Qwen": ProviderPreset(
        name="Qwen",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        default_model="qwen-plus",
        note="Alibaba Cloud Model Studio OpenAI-compatible endpoint.",
    ),
    "Kimi": ProviderPreset(
        name="Kimi",
        base_url="https://api.moonshot.cn/v1",
        default_model="kimi-k2-0711-preview",
        note="Moonshot AI OpenAI-compatible endpoint.",
    ),
    "GLM": ProviderPreset(
        name="GLM",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        default_model="glm-4.5",
        note="Zhipu/Open Platform OpenAI-compatible endpoint.",
    ),
    "MiniMax": ProviderPreset(
        name="MiniMax",
        base_url="https://api.minimax.chat/v1",
        default_model="MiniMax-M1",
        note="MiniMax OpenAI-compatible endpoint.",
    ),
    "Doubao": ProviderPreset(
        name="Doubao",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        default_model="doubao-seed-1-6",
        note="Volcengine Ark OpenAI-compatible endpoint.",
    ),
    "ERNIE": ProviderPreset(
        name="ERNIE",
        base_url="https://qianfan.baidubce.com/v2",
        default_model="ernie-4.5-turbo-128k",
        note="Baidu Qianfan OpenAI-compatible endpoint.",
    ),
    "Custom": ProviderPreset(
        name="Custom",
        base_url="",
        default_model="",
        note="Use any OpenAI-compatible chat-completions endpoint.",
    ),
}


def provider_names() -> list[str]:
    return list(PROVIDER_PRESETS.keys())


def get_preset(name: str) -> ProviderPreset:
    return PROVIDER_PRESETS.get(name, PROVIDER_PRESETS["Custom"])


def normalize_chat_url(base_url: str) -> str:
    cleaned = base_url.strip().rstrip("/")
    if not cleaned:
        raise ValueError("Base URL is required.")
    if cleaned.endswith("/chat/completions"):
        return cleaned
    return f"{cleaned}/chat/completions"

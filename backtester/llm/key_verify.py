"""Lightweight checks that API keys are accepted by providers (no heavy completions)."""

from __future__ import annotations

from backtester.config import MODEL_ALIASES


def verify_openai_api_key(api_key: str) -> tuple[bool, str]:
    key = (api_key or "").strip()
    if not key:
        return False, "Empty API key"
    try:
        from openai import OpenAI

        client = OpenAI(api_key=key)
        for _ in client.models.list():
            break
        return True, ""
    except Exception as e:
        return False, (str(e) or type(e).__name__)[:400]


def verify_nvidia_qwen_api_key(api_key: str) -> tuple[bool, str]:
    key = (api_key or "").strip()
    if not key:
        return False, "Empty API key"
    try:
        from openai import OpenAI

        from backtester.llm.nvidia_qwen_provider import DEFAULT_MODEL, NVIDIA_BASE_URL

        client = OpenAI(api_key=key, base_url=NVIDIA_BASE_URL)
        client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=[{"role": "user", "content": "ok"}],
            max_tokens=1,
        )
        return True, ""
    except Exception as e:
        return False, (str(e) or type(e).__name__)[:400]


def verify_deepseek_api_key(api_key: str) -> tuple[bool, str]:
    key = (api_key or "").strip()
    if not key:
        return False, "Empty API key"
    try:
        from openai import OpenAI

        client = OpenAI(api_key=key, base_url="https://api.deepseek.com")
        client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": "ok"}],
            max_tokens=1,
        )
        return True, ""
    except Exception as e:
        return False, (str(e) or type(e).__name__)[:400]


def verify_anthropic_api_key(api_key: str) -> tuple[bool, str]:
    key = (api_key or "").strip()
    if not key:
        return False, "Empty API key"
    try:
        from anthropic import Anthropic

        client = Anthropic(api_key=key)
        # Must match MODEL_ALIASES["opus"] — retired model IDs (e.g. claude-3-5-haiku-20241022) return 404.
        client.messages.create(
            model=MODEL_ALIASES["opus"],
            max_tokens=1,
            messages=[{"role": "user", "content": "ok"}],
        )
        return True, ""
    except Exception as e:
        return False, (str(e) or type(e).__name__)[:400]

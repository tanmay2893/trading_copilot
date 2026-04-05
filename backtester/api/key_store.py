"""In-memory API keys for the web app (set via Settings). CLI uses .env via cfg instead."""

from __future__ import annotations

import threading
from typing import Literal

_lock = threading.Lock()
_keys: dict[str, str] = {"openai": "", "anthropic": "", "deepseek": ""}

KeyKind = Literal["openai", "anthropic", "deepseek"]


def set_key(kind: KeyKind, value: str) -> None:
    with _lock:
        _keys[kind] = value.strip()


def get_stored_api_key(model_alias: str) -> str:
    """Return the stored secret for an LLM alias (openai | opus | deepseek)."""
    alias = model_alias.lower()
    with _lock:
        if alias == "openai":
            return _keys["openai"]
        if alias == "opus":
            return _keys["anthropic"]
        if alias == "deepseek":
            return _keys["deepseek"]
    return ""


def configured_flags() -> dict[str, bool]:
    with _lock:
        return {
            "openai_configured": bool(_keys["openai"]),
            "anthropic_configured": bool(_keys["anthropic"]),
            "deepseek_configured": bool(_keys["deepseek"]),
        }

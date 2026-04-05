"""Curated API model IDs for the web UI (allowlist). Unknown IDs fall back to alias defaults."""

from __future__ import annotations

# (api_model_id, short_label) — IDs must match provider APIs.
ANTHROPIC_MODELS: list[tuple[str, str]] = [
    ("claude-opus-4-20250514", "Claude Opus 4"),
    ("claude-sonnet-4-20250514", "Claude Sonnet 4"),
    ("claude-3-7-sonnet-20250219", "Claude 3.7 Sonnet"),
    ("claude-3-5-sonnet-20241022", "Claude 3.5 Sonnet"),
    ("claude-3-5-sonnet-20240620", "Claude 3.5 Sonnet (Jun 2024)"),
    ("claude-3-opus-20240229", "Claude 3 Opus"),
    ("claude-3-haiku-20240307", "Claude 3 Haiku"),
]

OPENAI_MODELS: list[tuple[str, str]] = [
    ("gpt-4o", "GPT-4o"),
    ("gpt-4o-mini", "GPT-4o mini"),
    ("gpt-4-turbo", "GPT-4 Turbo"),
    ("gpt-3.5-turbo", "GPT-3.5 Turbo"),
    ("o1", "o1"),
    ("o1-mini", "o1 mini"),
    ("o3-mini", "o3 mini"),
]

DEEPSEEK_MODELS: list[tuple[str, str]] = [
    ("deepseek-chat", "DeepSeek Chat"),
    ("deepseek-reasoner", "DeepSeek Reasoner"),
]

_ALIAS_FOR_PROVIDER = {"anthropic": "opus", "openai": "openai", "deepseek": "deepseek"}

ALLOWED_BY_PROVIDER: dict[str, frozenset[str]] = {
    "anthropic": frozenset(m[0] for m in ANTHROPIC_MODELS),
    "openai": frozenset(m[0] for m in OPENAI_MODELS),
    "deepseek": frozenset(m[0] for m in DEEPSEEK_MODELS),
}


def alias_for_model_id(model_id: str) -> str | None:
    mid = (model_id or "").strip()
    if not mid:
        return None
    for provider, allowed in ALLOWED_BY_PROVIDER.items():
        if mid in allowed:
            return _ALIAS_FOR_PROVIDER[provider]
    return None


def resolve_web_api_model(provider_name: str, effective_alias: str, llm_model_id: str | None, default_for_alias: str) -> str:
    """Return the API model string: explicit allowlisted id, else default_for_alias (usually MODEL_ALIASES[effective_alias])."""
    if llm_model_id and (mid := llm_model_id.strip()):
        allowed = ALLOWED_BY_PROVIDER.get(provider_name, frozenset())
        if mid in allowed:
            return mid
    return default_for_alias


def llm_model_options_for_web() -> list[dict[str, str]]:
    """Flat list for JSON: id, label, alias (openai|opus|deepseek)."""
    out: list[dict[str, str]] = []
    for mid, label in ANTHROPIC_MODELS:
        out.append({"id": mid, "label": label, "alias": "opus"})
    for mid, label in OPENAI_MODELS:
        out.append({"id": mid, "label": label, "alias": "openai"})
    for mid, label in DEEPSEEK_MODELS:
        out.append({"id": mid, "label": label, "alias": "deepseek"})
    return out

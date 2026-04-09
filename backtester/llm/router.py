from __future__ import annotations

from backtester.config import MODEL_ALIASES, PROVIDER_FOR_ALIAS, cfg
from backtester.llm.anthropic_provider import AnthropicProvider
from backtester.llm.model_catalog import resolve_web_api_model
from backtester.llm.base import BaseLLMProvider
from backtester.llm.deepseek_provider import DeepSeekProvider
from backtester.llm.nvidia_qwen_provider import NvidiaQwenProvider
from backtester.llm.openai_provider import OpenAIProvider

_PROVIDER_LABEL = {
    "openai": "OpenAI",
    "opus": "Anthropic",
    "deepseek": "DeepSeek",
}


def _web_alias_fallback_chain(start: str) -> list[str]:
    """Order of aliases to try when the requested provider has no web (Settings) key."""
    s = start.lower()
    if s == "openai":
        return ["openai", "opus", "deepseek"]
    if s == "opus":
        return ["opus", "openai", "deepseek"]
    if s == "deepseek":
        return ["deepseek", "openai", "opus"]
    return [s]


def resolve_web_model_alias(requested: str) -> str:
    """Pick the first model alias in the fallback chain that has a key in Settings (key_store).

    Example: session is 'openai' but only Anthropic is configured → 'opus'.
    If nothing is configured, returns the requested alias (get_provider will error clearly).
    """
    requested = (requested or "openai").lower()
    if requested not in PROVIDER_FOR_ALIAS:
        return requested
    from backtester.api.key_store import get_stored_api_key

    for cand in _web_alias_fallback_chain(requested):
        if get_stored_api_key(cand).strip():
            return cand
    return requested


def get_provider(
    model_alias: str,
    *,
    use_env_keys: bool = False,
    llm_model_id: str | None = None,
) -> BaseLLMProvider:
    """Build an LLM provider for the given model alias.

    - use_env_keys=False (default): web API — keys come from Settings (in-memory key_store only).
    - use_env_keys=True: CLI — keys come from environment / .env via cfg.
    - llm_model_id: optional API model id (web only); must be allowlisted for the resolved provider.
    """
    alias = model_alias.lower()
    if alias not in PROVIDER_FOR_ALIAS:
        raise ValueError(
            f"Unknown model alias '{model_alias}'. Use one of: {list(PROVIDER_FOR_ALIAS.keys())}"
        )
    if use_env_keys:
        effective = alias
        try:
            api_key = cfg.api_key_for(alias)
        except ValueError as e:
            raise ValueError(str(e)) from e
    else:
        from backtester.api.key_store import get_stored_api_key

        effective = resolve_web_model_alias(alias)
        api_key = get_stored_api_key(effective).strip()
        if not api_key:
            raise ValueError(
                "No LLM API key configured. Open Settings (gear) and add at least one provider key "
                "(OpenAI, Anthropic, or DeepSeek)."
            )
    provider_name = PROVIDER_FOR_ALIAS[effective]
    default_id = MODEL_ALIASES[effective]
    if use_env_keys:
        model = default_id
    else:
        model = resolve_web_api_model(provider_name, effective, llm_model_id, default_id)
    if provider_name == "anthropic":
        return AnthropicProvider(api_key=api_key, model=model)
    if provider_name == "openai":
        return OpenAIProvider(api_key=api_key, model=model)
    if provider_name == "deepseek":
        return DeepSeekProvider(api_key=api_key, model=model)
    raise ValueError(f"No provider implementation for '{provider_name}'")


def get_chat_provider(
    model_alias: str,
    *,
    llm_model_id: str | None = None,
) -> BaseLLMProvider:
    """Provider for web chat (WebSocket). If NVIDIA Qwen is configured in Settings, it is always used for chat."""
    from backtester.api.key_store import get_nvidia_qwen_key

    nvidia_key = get_nvidia_qwen_key().strip()
    if nvidia_key:
        return NvidiaQwenProvider(api_key=nvidia_key)
    return get_provider(model_alias, llm_model_id=llm_model_id)

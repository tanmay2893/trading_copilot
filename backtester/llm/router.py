from __future__ import annotations

from backtester.config import MODEL_ALIASES, PROVIDER_FOR_ALIAS, cfg
from backtester.llm.anthropic_provider import AnthropicProvider
from backtester.llm.base import BaseLLMProvider
from backtester.llm.deepseek_provider import DeepSeekProvider
from backtester.llm.openai_provider import OpenAIProvider

_PROVIDER_LABEL = {
    "openai": "OpenAI",
    "opus": "Anthropic",
    "deepseek": "DeepSeek",
}


def get_provider(model_alias: str, *, use_env_keys: bool = False) -> BaseLLMProvider:
    """Build an LLM provider for the given model alias.

    - use_env_keys=False (default): web API — keys come from Settings (in-memory key_store only).
    - use_env_keys=True: CLI — keys come from environment / .env via cfg.
    """
    alias = model_alias.lower()
    if alias not in PROVIDER_FOR_ALIAS:
        raise ValueError(
            f"Unknown model alias '{model_alias}'. Use one of: {list(PROVIDER_FOR_ALIAS.keys())}"
        )
    if use_env_keys:
        try:
            api_key = cfg.api_key_for(alias)
        except ValueError as e:
            raise ValueError(str(e)) from e
    else:
        from backtester.api.key_store import get_stored_api_key

        api_key = get_stored_api_key(alias).strip()
        if not api_key:
            label = _PROVIDER_LABEL.get(alias, alias)
            raise ValueError(
                f"No {label} API key configured. Open Settings (gear) and add your API keys."
            )
    model = MODEL_ALIASES[alias]
    provider_name = PROVIDER_FOR_ALIAS[alias]
    if provider_name == "anthropic":
        return AnthropicProvider(api_key=api_key, model=model)
    if provider_name == "openai":
        return OpenAIProvider(api_key=api_key, model=model)
    if provider_name == "deepseek":
        return DeepSeekProvider(api_key=api_key, model=model)
    raise ValueError(f"No provider implementation for '{provider_name}'")

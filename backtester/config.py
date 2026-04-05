"""Configuration management: env vars, paths, model defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

_env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(_env_path)

APP_DIR = Path.home() / ".backtester"
CACHE_DIR = APP_DIR / "cache"
RUNS_DIR = APP_DIR / "runs"
SESSIONS_DIR = APP_DIR / "sessions"

for _d in (APP_DIR, CACHE_DIR, RUNS_DIR, SESSIONS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

MODEL_ALIASES = {
    "opus": "claude-sonnet-4-20250514",
    "openai": "gpt-4o",
    "deepseek": "deepseek-chat",
}

PROVIDER_FOR_ALIAS = {
    "opus": "anthropic",
    "openai": "openai",
    "deepseek": "deepseek",
}


@dataclass
class Config:
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    deepseek_api_key: str = field(default_factory=lambda: os.getenv("DEEPSEEK_API_KEY", ""))
    default_model: str = field(default_factory=lambda: os.getenv("DEFAULT_MODEL", "openai"))
    max_iterations: int = field(default_factory=lambda: int(os.getenv("MAX_ITERATIONS", "10")))

    def api_key_for(self, alias: str) -> str:
        mapping = {
            "opus": self.anthropic_api_key,
            "openai": self.openai_api_key,
            "deepseek": self.deepseek_api_key,
        }
        key = mapping.get(alias, "")
        if not key:
            raise ValueError(
                f"No API key configured for model '{alias}'. "
                f"Set the appropriate env var in .env"
            )
        return key


cfg = Config()

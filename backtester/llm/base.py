from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class LLMResponse:
    content: str
    model: str
    input_tokens: int
    output_tokens: int
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = ""


class BaseLLMProvider(ABC):
    @abstractmethod
    def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        images: list[str] | None = None,
    ) -> LLMResponse:
        """Generate a response. *images* is an optional list of base64-encoded PNGs."""
        ...

    def generate_with_tools(
        self,
        messages: list[dict],
        system_prompt: str,
        tools: list[dict],
    ) -> LLMResponse:
        """Generate a response that may include tool calls.

        Subclasses should override this to support the orchestrator agent loop.
        """
        raise NotImplementedError("Tool-calling not supported by this provider")

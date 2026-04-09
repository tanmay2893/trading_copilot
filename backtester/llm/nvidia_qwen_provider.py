from __future__ import annotations

import json
import logging

from openai import OpenAI

from backtester.llm.base import BaseLLMProvider, LLMResponse, ToolCall

log = logging.getLogger(__name__)

NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_MODEL = "qwen/qwen3-coder-480b-a35b-instruct"


class NvidiaQwenProvider(BaseLLMProvider):
    """OpenAI-compatible NVIDIA NIM API (Qwen Coder). Used for web chat when configured in Settings."""

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL):
        self._client = OpenAI(api_key=api_key, base_url=NVIDIA_BASE_URL)
        self._model = model

    def generate(self, prompt: str, system_prompt: str = "", images: list[str] | None = None) -> LLMResponse:
        if images:
            log.info("NVIDIA Qwen chat: vision not used for this provider — chart image ignored")
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            max_tokens=4096,
            temperature=0.7,
            top_p=0.8,
        )
        choice = resp.choices[0]
        return LLMResponse(
            content=choice.message.content or "",
            model=self._model,
            input_tokens=resp.usage.prompt_tokens if resp.usage else 0,
            output_tokens=resp.usage.completion_tokens if resp.usage else 0,
        )

    def generate_with_tools(
        self,
        messages: list[dict],
        system_prompt: str,
        tools: list[dict],
    ) -> LLMResponse:
        api_messages = []
        if system_prompt:
            api_messages.append({"role": "system", "content": system_prompt})
        api_messages.extend(messages)

        kwargs: dict = {
            "model": self._model,
            "messages": api_messages,
            "max_tokens": 4096,
            "temperature": 0.7,
            "top_p": 0.8,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        resp = self._client.chat.completions.create(**kwargs)
        choice = resp.choices[0]

        tool_calls: list[ToolCall] = []
        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except (json.JSONDecodeError, TypeError):
                    args = {}
                tool_calls.append(
                    ToolCall(
                        id=tc.id,
                        name=tc.function.name,
                        arguments=args,
                    )
                )

        stop = "tool_use" if choice.finish_reason == "tool_calls" else "end_turn"
        return LLMResponse(
            content=choice.message.content or "",
            model=self._model,
            input_tokens=resp.usage.prompt_tokens if resp.usage else 0,
            output_tokens=resp.usage.completion_tokens if resp.usage else 0,
            tool_calls=tool_calls,
            stop_reason=stop,
        )

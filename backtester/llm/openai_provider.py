from __future__ import annotations

import json
import logging
import time

from openai import OpenAI, RateLimitError

from backtester.llm.base import BaseLLMProvider, LLMResponse, ToolCall

log = logging.getLogger(__name__)

MAX_RETRIES = 4
INITIAL_BACKOFF = 5


class OpenAIProvider(BaseLLMProvider):
    def __init__(self, api_key: str, model: str = "gpt-4o"):
        self._client = OpenAI(api_key=api_key)
        self._model = model

    def generate(self, prompt: str, system_prompt: str = "", images: list[str] | None = None) -> LLMResponse:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        if images:
            content: list[dict] = [{"type": "text", "text": prompt}]
            for img_b64 in images:
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{img_b64}", "detail": "high"},
                })
            messages.append({"role": "user", "content": content})
        else:
            messages.append({"role": "user", "content": prompt})

        last_exc = None
        for attempt in range(MAX_RETRIES):
            try:
                resp = self._client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    max_tokens=4096,
                )
                choice = resp.choices[0]
                return LLMResponse(
                    content=choice.message.content or "",
                    model=self._model,
                    input_tokens=resp.usage.prompt_tokens if resp.usage else 0,
                    output_tokens=resp.usage.completion_tokens if resp.usage else 0,
                )
            except RateLimitError as e:
                last_exc = e
                wait = INITIAL_BACKOFF * (2 ** attempt)
                log.warning("Rate limit hit, waiting %ds before retry %d/%d", wait, attempt + 1, MAX_RETRIES)
                time.sleep(wait)

        raise last_exc

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
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        last_exc = None
        for attempt in range(MAX_RETRIES):
            try:
                resp = self._client.chat.completions.create(**kwargs)
                break
            except RateLimitError as e:
                last_exc = e
                wait = INITIAL_BACKOFF * (2 ** attempt)
                log.warning("Rate limit hit, waiting %ds before retry %d/%d", wait, attempt + 1, MAX_RETRIES)
                time.sleep(wait)
        else:
            raise last_exc

        choice = resp.choices[0]
        tool_calls: list[ToolCall] = []
        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except (json.JSONDecodeError, TypeError):
                    args = {}
                tool_calls.append(ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=args,
                ))

        stop = "tool_use" if choice.finish_reason == "tool_calls" else "end_turn"
        return LLMResponse(
            content=choice.message.content or "",
            model=self._model,
            input_tokens=resp.usage.prompt_tokens if resp.usage else 0,
            output_tokens=resp.usage.completion_tokens if resp.usage else 0,
            tool_calls=tool_calls,
            stop_reason=stop,
        )

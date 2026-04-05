from __future__ import annotations

import json

from anthropic import Anthropic

from backtester.llm.base import BaseLLMProvider, LLMResponse, ToolCall


def _openai_tools_to_anthropic(tools: list[dict]) -> list[dict]:
    """Convert OpenAI-format tool schemas to Anthropic format."""
    converted = []
    for t in tools:
        func = t.get("function", t)
        converted.append({
            "name": func["name"],
            "description": func.get("description", ""),
            "input_schema": func.get("parameters", {"type": "object", "properties": {}}),
        })
    return converted


class AnthropicProvider(BaseLLMProvider):
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514"):
        self._client = Anthropic(api_key=api_key)
        self._model = model

    def generate(self, prompt: str, system_prompt: str = "", images: list[str] | None = None) -> LLMResponse:
        if images:
            user_content: list[dict] = [{"type": "text", "text": prompt}]
            for img_b64 in images:
                user_content.append({
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/png", "data": img_b64},
                })
            msg = {"role": "user", "content": user_content}
        else:
            msg = {"role": "user", "content": prompt}

        kwargs = {"model": self._model, "max_tokens": 4096, "messages": [msg]}
        if system_prompt:
            kwargs["system"] = system_prompt
        resp = self._client.messages.create(**kwargs)
        content = resp.content[0].text if resp.content else ""
        return LLMResponse(
            content=content,
            model=self._model,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
        )

    def generate_with_tools(
        self,
        messages: list[dict],
        system_prompt: str,
        tools: list[dict],
    ) -> LLMResponse:
        api_messages = _convert_messages_for_anthropic(messages)
        anthropic_tools = _openai_tools_to_anthropic(tools)

        kwargs: dict = {
            "model": self._model,
            "max_tokens": 4096,
            "messages": api_messages,
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        if anthropic_tools:
            kwargs["tools"] = anthropic_tools

        resp = self._client.messages.create(**kwargs)

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in resp.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(
                    id=block.id,
                    name=block.name,
                    arguments=block.input if isinstance(block.input, dict) else {},
                ))

        stop = "tool_use" if resp.stop_reason == "tool_use" else "end_turn"
        return LLMResponse(
            content="\n".join(text_parts),
            model=self._model,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
            tool_calls=tool_calls,
            stop_reason=stop,
        )


def _convert_messages_for_anthropic(messages: list[dict]) -> list[dict]:
    """Convert OpenAI-style messages to Anthropic format.

    Handles tool_calls / tool results which use different shapes.
    """
    converted = []
    for msg in messages:
        role = msg.get("role", "user")
        if role == "system":
            continue
        if role == "tool":
            converted.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": msg.get("tool_call_id", ""),
                    "content": msg.get("content", ""),
                }],
            })
        elif role == "assistant" and msg.get("tool_calls"):
            blocks: list[dict] = []
            if msg.get("content"):
                blocks.append({"type": "text", "text": msg["content"]})
            for tc in msg["tool_calls"]:
                func = tc.get("function", tc)
                args = func.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except (json.JSONDecodeError, TypeError):
                        args = {}
                blocks.append({
                    "type": "tool_use",
                    "id": tc.get("id", ""),
                    "name": func.get("name", ""),
                    "input": args,
                })
            converted.append({"role": "assistant", "content": blocks})
        else:
            converted.append({"role": role, "content": msg.get("content", "")})
    return converted

"""LLM-powered orchestrator — the core agent loop.

Receives user messages, decides which tools to call via LLM function-calling,
executes tools, feeds results back, and returns a final text response.
"""

from __future__ import annotations

import json
import logging
from typing import Callable, Awaitable

from backtester.agent.events import (
    DoneEvent,
    ErrorEvent,
    TextEvent,
    ToolEndEvent,
    ToolStartEvent,
)
from backtester.agent.prompts import TOOL_SCHEMAS, build_orchestrator_system_prompt
from backtester.agent.session import ChatSession
from backtester.agent.tools import execute_tool
from backtester.llm.base import BaseLLMProvider

log = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 8

Callback = Callable[..., Awaitable[None]]


async def agent_loop(
    session: ChatSession,
    user_message: str,
    provider: BaseLLMProvider,
    on_event: Callback,
) -> None:
    """Run the full agent loop for a single user turn.

    The loop continues until the LLM produces a final text response (no more
    tool calls) or the maximum number of tool rounds is reached.
    """
    session.add_message("user", user_message)

    system_prompt = build_orchestrator_system_prompt(session.state_summary())

    messages = session.to_llm_messages()

    pending_strategy_version_id: str | None = None
    total_input_tokens = 0
    total_output_tokens = 0
    last_model = ""

    for _round in range(MAX_TOOL_ROUNDS):
        try:
            response = provider.generate_with_tools(messages, system_prompt, TOOL_SCHEMAS)
        except NotImplementedError:
            response = _fallback_generate(provider, messages, system_prompt)
        except Exception as exc:
            log.error("LLM call failed: %s", exc)
            await on_event(ErrorEvent(message=f"LLM error: {exc}"))
            await on_event(DoneEvent())
            return

        total_input_tokens += response.input_tokens
        total_output_tokens += response.output_tokens
        last_model = response.model or ""

        if response.content and not response.tool_calls:
            session.add_message(
                "assistant",
                response.content,
                strategy_version_id=pending_strategy_version_id,
            )
            pending_strategy_version_id = None
            await on_event(TextEvent(content=response.content))
            await on_event(DoneEvent(
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
                model=last_model,
            ))
            return

        if response.tool_calls:
            if response.content:
                await on_event(TextEvent(content=response.content))
            # tokens already accumulated above

            assistant_msg: dict = {"role": "assistant", "content": response.content or ""}
            assistant_msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments),
                    },
                }
                for tc in response.tool_calls
            ]
            messages.append(assistant_msg)
            session.add_message(
                "assistant",
                response.content or "",
                tool_calls=assistant_msg["tool_calls"],
            )

            for tc in response.tool_calls:
                await on_event(ToolStartEvent(tool_name=tc.name, arguments=tc.arguments))

                result = await execute_tool(
                    session=session,
                    tool_name=tc.name,
                    arguments=tc.arguments,
                    on_event=on_event,
                    provider=provider,
                )

                await on_event(ToolEndEvent(tool_name=tc.name, result=result))

                result_str = json.dumps(result, default=str)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_str,
                })
                session.add_message(
                    "tool",
                    result_str,
                    tool_call_id=tc.id,
                    name=tc.name,
                )

                if isinstance(result, dict) and "strategy_version_id" in result:
                    pending_strategy_version_id = str(result["strategy_version_id"])

            continue

        # No content and no tool calls — unusual, treat as end
        session.add_message("assistant", response.content or "(no response)")
        await on_event(TextEvent(content=response.content or ""))
        await on_event(DoneEvent(
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
            model=last_model,
        ))
        return

    # Exhausted tool rounds
    session.add_message("assistant", "I've reached the maximum number of steps for this request. Please try a simpler query or break it into smaller parts.")
    await on_event(TextEvent(content="I've reached the maximum number of steps for this request. Please try a simpler query or break it into smaller parts."))
    await on_event(DoneEvent(
        input_tokens=total_input_tokens,
        output_tokens=total_output_tokens,
        model=last_model,
    ))


def _fallback_generate(provider: BaseLLMProvider, messages: list[dict], system_prompt: str):
    """Fallback for providers that don't support tool-calling: use plain generate."""
    last_user = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            last_user = msg.get("content", "")
            break
    from backtester.llm.base import LLMResponse
    resp = provider.generate(last_user, system_prompt)
    return resp

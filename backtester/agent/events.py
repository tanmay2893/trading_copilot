"""Typed event system for streaming progress from tool execution to the frontend.

Events bridge the existing engine's step-by-step execution pattern to the
WebSocket stream consumed by the chat UI.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum


class EventType(str, Enum):
    TEXT = "text"
    PROGRESS = "progress"
    TOOL_START = "tool_start"
    TOOL_END = "tool_end"
    CODE = "code"
    TABLE = "table"
    IMAGE = "image"
    ERROR = "error"
    DONE = "done"
    REQUEST_DATE_RANGE = "request_date_range"
    STRATEGY_VERSION = "strategy_version"
    FOLLOW_UP_SUGGESTIONS = "follow_up_suggestions"


@dataclass
class BaseEvent:
    type: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TextEvent(BaseEvent):
    content: str = ""
    type: str = field(default=EventType.TEXT, init=False)


@dataclass
class ProgressEvent(BaseEvent):
    step: str = ""
    status: str = "running"  # running | success | failed
    detail: str = ""
    type: str = field(default=EventType.PROGRESS, init=False)


@dataclass
class ToolStartEvent(BaseEvent):
    tool_name: str = ""
    arguments: dict = field(default_factory=dict)
    type: str = field(default=EventType.TOOL_START, init=False)


@dataclass
class ToolEndEvent(BaseEvent):
    tool_name: str = ""
    result: dict = field(default_factory=dict)
    type: str = field(default=EventType.TOOL_END, init=False)


@dataclass
class CodeEvent(BaseEvent):
    code: str = ""
    language: str = "python"
    type: str = field(default=EventType.CODE, init=False)


@dataclass
class TableEvent(BaseEvent):
    headers: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    title: str = ""
    formula: str = ""  # optional; e.g. Risk/Reward equation for backtesting summary
    type: str = field(default=EventType.TABLE, init=False)


@dataclass
class ImageEvent(BaseEvent):
    url: str = ""
    alt: str = "Chart screenshot"
    type: str = field(default=EventType.IMAGE, init=False)


@dataclass
class ErrorEvent(BaseEvent):
    message: str = ""
    type: str = field(default=EventType.ERROR, init=False)


@dataclass
class DoneEvent(BaseEvent):
    """Sent when a turn completes. Optional usage from the LLM for this turn."""
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""  # e.g. gpt-4o, deepseek-chat
    type: str = field(default=EventType.DONE, init=False)


@dataclass
class RequestDateRangeEvent(BaseEvent):
    """Ask the client to show a calendar to pick start and end dates for backtesting."""

    message: str = "Select start and end dates for backtesting. These will be used for the whole conversation."
    suggested_start_date: str | None = None
    suggested_end_date: str | None = None
    type: str = field(default=EventType.REQUEST_DATE_RANGE, init=False)


@dataclass
class StrategyVersionEvent(BaseEvent):
    """Notify the client that a new strategy code version has been created."""
    version_id: str = ""
    type: str = field(default=EventType.STRATEGY_VERSION, init=False)


@dataclass
class FollowUpSuggestionsEvent(BaseEvent):
    """LLM-generated suggested next user messages (label + full prompt each)."""

    suggestions: list[dict] = field(default_factory=list)
    type: str = field(default=EventType.FOLLOW_UP_SUGGESTIONS, init=False)

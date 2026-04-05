"""Unified chat session that tracks full state across all agent capabilities.

Extends the idea from engine/session.py to cover the full interactive lifecycle:
active strategy, data, signals, and full conversation history including tool calls.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from backtester.config import SESSIONS_DIR

AGENT_SESSIONS_DIR = SESSIONS_DIR / "agent"
AGENT_SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

log = logging.getLogger(__name__)

TOKEN_BUDGET = 12_000


@dataclass
class ChatMessage:
    role: str  # user | assistant | tool
    content: str
    tool_calls: list[dict] | None = None
    tool_call_id: str | None = None
    name: str | None = None
    timestamp: str = ""
    strategy_version_id: str | None = None

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


@dataclass
class RunSummary:
    """Lightweight record of a completed backtest run within the session."""
    ticker: str
    strategy: str
    interval: str
    signal_count: int
    buy_count: int
    sell_count: int
    attempts: int
    success: bool
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


@dataclass
class ChatSession:
    session_id: str
    messages: list[ChatMessage] = field(default_factory=list)
    title: str | None = None
    active_ticker: str | None = None
    active_strategy: str | None = None
    active_code: str | None = None
    active_interval: str | None = None
    run_history: list[RunSummary] = field(default_factory=list)
    model: str = "openai"
    created_at: str = ""
    updated_at: str = ""
    # Date range for backtesting — set once via calendar, used for whole conversation
    start_date: str | None = None
    end_date: str | None = None
    # When we request date range, we buffer the user message that triggered it (not persisted)
    _pending_user_message: str | None = field(default=None, repr=False)

    active_indicator_columns: list[str] = field(default_factory=list)

    _active_signals_df: pd.DataFrame | None = field(default=None, repr=False)
    _active_data_df: pd.DataFrame | None = field(default=None, repr=False)
    _active_indicator_df: pd.DataFrame | None = field(default=None, repr=False)

    pending_chart_image: str | None = field(default=None, repr=False)

    # Version selected in strategies panel for "add to chat" — refine/fix use this version's code when set
    chat_base_version_id: str | None = None

    def __post_init__(self):
        now = datetime.now(timezone.utc).isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now

    @staticmethod
    def new(model: str = "openai") -> ChatSession:
        return ChatSession(
            session_id=uuid.uuid4().hex[:12],
            model=model,
        )

    @property
    def active_signals_df(self) -> pd.DataFrame | None:
        return self._active_signals_df

    @active_signals_df.setter
    def active_signals_df(self, df: pd.DataFrame | None):
        self._active_signals_df = df

    @property
    def active_data_df(self) -> pd.DataFrame | None:
        return self._active_data_df

    @active_data_df.setter
    def active_data_df(self, df: pd.DataFrame | None):
        self._active_data_df = df

    @property
    def active_indicator_df(self) -> pd.DataFrame | None:
        return self._active_indicator_df

    @active_indicator_df.setter
    def active_indicator_df(self, df: pd.DataFrame | None):
        self._active_indicator_df = df

    def add_message(self, role: str, content: str, **kwargs: Any):
        self.messages.append(ChatMessage(role=role, content=content, **kwargs))
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def add_run(self, summary: RunSummary):
        self.run_history.append(summary)
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def state_summary(self) -> str:
        """One-paragraph summary of current session state for the orchestrator prompt."""
        parts: list[str] = []
        if self.start_date and self.end_date:
            parts.append(f"Date range (use for all backtests): {self.start_date} to {self.end_date}")
        if self.active_ticker:
            parts.append(f"Active ticker: {self.active_ticker}")
        if self.active_strategy:
            parts.append(f"Strategy: {self.active_strategy[:200]}")
        if self.active_interval:
            parts.append(f"Interval: {self.active_interval}")
        if self._active_signals_df is not None:
            df = self._active_signals_df
            buy = int((df["Signal"] == "BUY").sum()) if "Signal" in df.columns else 0
            sell = int((df["Signal"] == "SELL").sum()) if "Signal" in df.columns else 0
            parts.append(f"Signals: {len(df)} total ({buy} BUY, {sell} SELL)")
        if self.active_code:
            parts.append("Strategy code: available (use show_code tool to display)")
        if self.run_history:
            parts.append(f"Past runs in session: {len(self.run_history)}")
        if not parts:
            return "No active backtest. The user has not run anything yet."
        return " | ".join(parts)

    def chat_summary_for_analysis(self, max_messages: int = 12, max_content_len: int = 400) -> str:
        """Condensed recent conversation for custom analysis context. User/assistant only; tool results skipped or truncated."""
        lines: list[str] = []
        for msg in self.messages[-max_messages:]:
            role = (msg.role or "").lower()
            content = (msg.content or "").strip()
            if len(content) > max_content_len:
                content = content[:max_content_len] + "..."
            if role == "user":
                lines.append(f"User: {content}")
            elif role == "assistant":
                lines.append(f"Assistant: {content}")
            elif role == "tool":
                lines.append(f"[Tool result: {content[:200]}...]" if len(content) > 200 else f"[Tool result: {content}]")
        return "\n".join(lines) if lines else "No prior messages."

    def to_llm_messages(self, token_budget: int = TOKEN_BUDGET) -> list[dict]:
        """Serialize message history for the LLM, respecting a token budget."""
        result: list[dict] = []
        used = 0
        for msg in self.messages:
            entry: dict = {"role": msg.role, "content": msg.content}
            if msg.tool_calls:
                entry["tool_calls"] = msg.tool_calls
            if msg.tool_call_id:
                entry["tool_call_id"] = msg.tool_call_id
            if msg.name:
                entry["name"] = msg.name

            est = max(1, len(json.dumps(entry)) // 4)
            if used + est > token_budget and len(result) > 4:
                result.insert(0, {
                    "role": "system",
                    "content": f"[Earlier conversation truncated — {len(self.messages) - len(result)} messages omitted]",
                })
                break
            result.append(entry)
            used += est
        return result

    # -- Persistence --

    def save(self) -> Path:
        path = AGENT_SESSIONS_DIR / f"{self.session_id}.json"
        data = {
            "session_id": self.session_id,
            "model": self.model,
            "title": self.title,
            "active_ticker": self.active_ticker,
            "active_strategy": self.active_strategy,
            "active_code": self.active_code,
            "active_interval": self.active_interval,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "active_indicator_columns": self.active_indicator_columns,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "chat_base_version_id": self.chat_base_version_id,
            "messages": [asdict(m) for m in self.messages],
            "run_history": [asdict(r) for r in self.run_history],
        }
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        latest = AGENT_SESSIONS_DIR / "latest"
        latest.write_text(self.session_id, encoding="utf-8")
        return path

    @staticmethod
    def load(session_id: str) -> ChatSession | None:
        path = AGENT_SESSIONS_DIR / f"{session_id}.json"
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            log.warning("Session %s load failed (read/json): %s", session_id, e)
            return None
        msgs = []
        for m in raw.pop("messages", []):
            if not isinstance(m, dict):
                continue
            try:
                msgs.append(ChatMessage(
                    role=m.get("role", "user"),
                    content=m.get("content", ""),
                    tool_calls=m.get("tool_calls"),
                    tool_call_id=m.get("tool_call_id"),
                    name=m.get("name"),
                    timestamp=m.get("timestamp", ""),
                    strategy_version_id=m.get("strategy_version_id"),
                ))
            except Exception:
                continue
        runs = []
        for r in raw.pop("run_history", []):
            if not isinstance(r, dict):
                continue
            try:
                runs.append(RunSummary(
                    ticker=r.get("ticker", ""),
                    strategy=r.get("strategy", ""),
                    interval=r.get("interval", ""),
                    signal_count=int(r.get("signal_count", 0)),
                    buy_count=int(r.get("buy_count", 0)),
                    sell_count=int(r.get("sell_count", 0)),
                    attempts=int(r.get("attempts", 0)),
                    success=bool(r.get("success", False)),
                    timestamp=r.get("timestamp", ""),
                ))
            except Exception:
                continue
        # Legacy sessions may not have start_date/end_date; only pass known fields
        raw.setdefault("start_date", None)
        raw.setdefault("end_date", None)
        raw.setdefault("title", None)
        raw.setdefault("chat_base_version_id", None)
        allowed = {"session_id", "model", "title", "active_ticker", "active_strategy", "active_code",
                   "active_interval", "created_at", "updated_at", "start_date", "end_date", "active_indicator_columns", "chat_base_version_id"}
        kwargs = {k: v for k, v in raw.items() if k in allowed}
        try:
            return ChatSession(**kwargs, messages=msgs, run_history=runs)
        except Exception as e:
            log.warning("Session %s load failed (build): %s", session_id, e)
            return None

    @staticmethod
    def get_strategy_code_for_version(session_id: str, version_id: str) -> str | None:
        """Return code for a specific strategy version from disk. None if file missing or invalid."""
        if not version_id or not version_id.isalnum():
            return None
        path = AGENT_SESSIONS_DIR / session_id / "strategy_versions" / f"{version_id}.py"
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    @staticmethod
    def get_latest_strategy_code_from_disk(session_id: str) -> str | None:
        """Return code from the most recently saved strategy version (manifest last entry, else newest by mtime).
        Used when session.active_code is missing or for 'Latest' rerun."""
        base_dir = AGENT_SESSIONS_DIR / session_id / "strategy_versions"
        if not base_dir.exists():
            return None
        # Prefer manifest order (chronological) so "latest" is the last saved run, not filesystem mtime
        try:
            from backtester.compliance.manifest import load_manifest
            manifest = load_manifest(session_id)
            if manifest:
                last_entry = manifest[-1]
                version_id = last_entry.get("version_id")
                if version_id and isinstance(version_id, str) and version_id.isalnum():
                    path = base_dir / f"{version_id}.py"
                    if path.exists():
                        return path.read_text(encoding="utf-8")
        except Exception:
            pass
        # Fallback: newest .py by mtime
        files = list(base_dir.glob("*.py"))
        if not files:
            return None
        latest = max(files, key=lambda f: f.stat().st_mtime)
        return latest.read_text(encoding="utf-8")

    @staticmethod
    def list_sessions() -> list[dict]:
        sessions = []
        for path in sorted(AGENT_SESSIONS_DIR.glob("*.json"), reverse=True):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                sessions.append({
                    "session_id": data["session_id"],
                    "model": data.get("model", "openai"),
                    "title": data.get("title"),
                    "active_ticker": data.get("active_ticker"),
                    "active_strategy": (data.get("active_strategy") or "")[:80],
                    "messages": len(data.get("messages", [])),
                    "runs": len(data.get("run_history", [])),
                    "updated_at": data.get("updated_at", ""),
                })
            except (json.JSONDecodeError, KeyError):
                continue
        return sessions

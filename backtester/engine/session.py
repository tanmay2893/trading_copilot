"""Conversation session management for interactive strategy refinement.

Tracks the full history of user change requests and resulting code versions,
enabling context-aware iterative modifications via LLM.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from backtester.config import SESSIONS_DIR

TOKEN_BUDGET_CONVERSATION = 6000


@dataclass
class ConversationTurn:
    request: str
    code_before: str
    code_after: str
    summary: str
    attempt_count: int
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


@dataclass
class RefineSession:
    session_id: str
    ticker: str
    interval: str
    strategy_description: str
    data_path: str
    current_code: str
    conversation: list[ConversationTurn] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        now = datetime.now(timezone.utc).isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now

    @staticmethod
    def new_session(
        ticker: str,
        interval: str,
        strategy_description: str,
        data_path: str,
        current_code: str,
    ) -> RefineSession:
        return RefineSession(
            session_id=uuid.uuid4().hex[:12],
            ticker=ticker,
            interval=interval,
            strategy_description=strategy_description,
            data_path=data_path,
            current_code=current_code,
        )

    def add_turn(self, turn: ConversationTurn):
        self.conversation.append(turn)
        self.current_code = turn.code_after
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def undo(self) -> bool:
        """Revert to the previous code version. Returns False if nothing to undo."""
        if not self.conversation:
            return False
        removed = self.conversation.pop()
        self.current_code = removed.code_before
        self.updated_at = datetime.now(timezone.utc).isoformat()
        return True

    def to_prompt_context(self, token_budget: int = TOKEN_BUDGET_CONVERSATION) -> str:
        """Serialize conversation history for prompt inclusion, respecting a token budget."""
        if not self.conversation:
            return ""

        lines: list[str] = []
        used_tokens = 0

        for i, turn in enumerate(self.conversation, 1):
            entry = f"Turn {i}: User requested: \"{turn.request}\"\n  Result: {turn.summary}"
            entry_tokens = _est_tokens(entry)
            if used_tokens + entry_tokens > token_budget:
                remaining = len(self.conversation) - i + 1
                lines.append(f"... ({remaining} earlier turns omitted for brevity)")
                break
            lines.append(entry)
            used_tokens += entry_tokens

        return "\n".join(lines)

    def save(self) -> Path:
        path = SESSIONS_DIR / f"{self.session_id}.json"
        data = asdict(self)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        latest = SESSIONS_DIR / "latest"
        latest.write_text(self.session_id, encoding="utf-8")
        return path

    @staticmethod
    def load(session_id: str) -> RefineSession | None:
        path = SESSIONS_DIR / f"{session_id}.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        turns = [ConversationTurn(**t) for t in data.pop("conversation", [])]
        session = RefineSession(**data, conversation=turns)
        return session

    @staticmethod
    def load_latest() -> RefineSession | None:
        latest = SESSIONS_DIR / "latest"
        if not latest.exists():
            return None
        session_id = latest.read_text(encoding="utf-8").strip()
        return RefineSession.load(session_id)

    @staticmethod
    def list_sessions() -> list[dict]:
        """Return a summary of all saved sessions, newest first."""
        sessions = []
        for path in sorted(SESSIONS_DIR.glob("*.json"), reverse=True):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                sessions.append({
                    "session_id": data["session_id"],
                    "ticker": data["ticker"],
                    "strategy": data["strategy_description"][:80],
                    "turns": len(data.get("conversation", [])),
                    "updated_at": data.get("updated_at", ""),
                })
            except (json.JSONDecodeError, KeyError):
                continue
        return sessions


def _est_tokens(text: str) -> int:
    return max(1, len(text) // 4)

"""Compliance status per session per version: reproducibility and quiz pass, paper trading gate."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backtester.agent.session import AGENT_SESSIONS_DIR


def _compliance_path(session_id: str, version_id: str) -> Path:
    return AGENT_SESSIONS_DIR / session_id / "compliance" / f"{version_id}.json"


def load_compliance_status(session_id: str, version_id: str) -> dict[str, Any]:
    """Load compliance status for this session and version. Returns empty dict if not found."""
    path = _compliance_path(session_id, version_id)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_compliance_status(
    session_id: str,
    version_id: str,
    *,
    reproducibility_passed: bool | None = None,
    reproducibility_choice: str | None = None,
    quiz_passed: bool | None = None,
    paper_trading_unlocked_at: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """
    Update and persist compliance status. Only provided fields are updated.
    reproducibility_choice: "original" | "rebuild_1" | "rebuild_2" when user chose after failed match.
    """
    path = _compliance_path(session_id, version_id)
    current = load_compliance_status(session_id, version_id)

    if reproducibility_passed is not None:
        current["reproducibility_passed"] = reproducibility_passed
    if reproducibility_choice is not None:
        current["reproducibility_choice"] = reproducibility_choice
    if quiz_passed is not None:
        current["quiz_passed"] = quiz_passed
    if paper_trading_unlocked_at is not None:
        current["paper_trading_unlocked_at"] = paper_trading_unlocked_at
    for k, v in kwargs.items():
        current[k] = v

    current["updated_at"] = datetime.now(timezone.utc).isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, indent=2), encoding="utf-8")
    return current


def _status_is_ready(status: dict[str, Any]) -> bool:
    """True if both reproducibility and quiz are passed."""
    return (
        status.get("reproducibility_passed") is True
        and status.get("quiz_passed") is True
    )


def compliance_ready_for_paper_trading(session_id: str, version_id: str) -> bool:
    """True if both reproducibility and quiz are passed for this version."""
    status = load_compliance_status(session_id, version_id)
    return _status_is_ready(status)


def get_ready_for_paper_trading_version_ids(session_id: str) -> list[str]:
    """Return version_ids in this session that have passed both reproducibility and quiz (only those can be paper traded)."""
    compliance_dir = AGENT_SESSIONS_DIR / session_id / "compliance"
    if not compliance_dir.exists():
        return []
    ready: list[str] = []
    for path in compliance_dir.glob("*.json"):
        if path.name.startswith("quiz_"):
            continue
        version_id = path.stem
        status = load_compliance_status(session_id, version_id)
        if _status_is_ready(status):
            ready.append(version_id)
    return ready


def get_ready_for_paper_trading_versions(session_id: str) -> list[dict]:
    """
    Return list of versions that have passed both reproducibility and quiz, with labels.
    Only these versions are allowed to be paper traded. Returns [{"version_id": str, "label": str}, ...].
    """
    from backtester.compliance.manifest import get_compliance_eligible_versions

    eligible = get_compliance_eligible_versions(session_id)
    ready_ids = set(get_ready_for_paper_trading_version_ids(session_id))
    return [e for e in eligible if e["version_id"] in ready_ids]

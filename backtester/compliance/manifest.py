"""Version manifest: commands and run params up to a selected version for reproducibility."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from backtester.agent.session import AGENT_SESSIONS_DIR


@dataclass
class CommandsUpToVersion:
    """Commands and run params to replay strategy build up to a version."""

    initial_strategy: str
    change_requests: list[str]
    ticker: str
    start_date: str
    end_date: str
    interval: str


def _manifest_path(session_id: str) -> Path:
    return AGENT_SESSIONS_DIR / session_id / "strategy_versions" / "manifest.json"


def load_manifest(session_id: str) -> list[dict]:
    """Load version manifest for session. Returns list of entries in chronological order."""
    path = _manifest_path(session_id)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def get_compliance_eligible_versions(session_id: str) -> list[dict]:
    """
    Return list of versions that can be used for compliance (reproducibility + quiz).
    Only versions that appear in the manifest with a valid first run_backtest entry are included.
    Returns [{"version_id": str, "label": str}, ...] ordered chronologically.
    """
    manifest = load_manifest(session_id)
    if not manifest:
        return []
    first = manifest[0]
    if first.get("source") != "run_backtest" or not first.get("strategy_text"):
        return []
    result: list[dict] = []
    for entry in manifest:
        vid = entry.get("version_id")
        if not vid:
            continue
        created = entry.get("created_at") or ""
        if created and len(created) >= 16:
            try:
                dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                label = dt.strftime("%Y-%m-%d %H:%M")
            except Exception:
                label = created[:16]
        else:
            label = vid
        result.append({"version_id": vid, "label": label})
    return result


def get_commands_up_to_version(
    session_id: str,
    version_id: str,
) -> CommandsUpToVersion | None:
    """
    Get initial strategy text and ordered change requests that built the given version.
    Uses run params (ticker, dates, interval) from the first run_backtest entry or the version entry.
    Returns None if version_id not in manifest or first entry is not run_backtest.
    """
    manifest = load_manifest(session_id)
    if not manifest:
        return None

    idx = None
    for i, entry in enumerate(manifest):
        if entry.get("version_id") == version_id:
            idx = i
            break
    if idx is None:
        return None

    first = manifest[0]
    if first.get("source") != "run_backtest" or not first.get("strategy_text"):
        return None

    initial_strategy = first["strategy_text"]
    change_requests: list[str] = []
    for j in range(1, idx + 1):
        req = manifest[j].get("change_request")
        if req:
            change_requests.append(req)

    ticker = first.get("ticker") or ""
    start_date = first.get("start_date") or "2020-01-01"
    end_date = first.get("end_date") or "2025-01-01"
    interval = first.get("interval") or "1d"

    return CommandsUpToVersion(
        initial_strategy=initial_strategy,
        change_requests=change_requests,
        ticker=ticker,
        start_date=start_date,
        end_date=end_date,
        interval=interval,
    )

"""REST endpoints for session management and file downloads."""

from __future__ import annotations

import asyncio
import json
import math
import re
import shutil
import uuid
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from backtester.agent.session import ChatSession
from backtester.agent.tools import compute_chart_backtest_extras
from backtester.api import key_store
from backtester.llm.key_verify import (
    verify_anthropic_api_key,
    verify_deepseek_api_key,
    verify_nvidia_qwen_api_key,
    verify_openai_api_key,
)

router = APIRouter(tags=["sessions"])


class CreateSessionRequest(BaseModel):
    model: str = "openai"


class GlobalLLMKeysRequest(BaseModel):
    """Fields are sent from Settings. Empty string clears that provider."""

    openai_api_key: str = ""
    anthropic_api_key: str = ""
    deepseek_api_key: str = ""
    nvidia_qwen_api_key: str = ""


def _apply_global_key(value: str, verify, kind: key_store.KeyKind) -> dict:
    stripped = (value or "").strip()
    if not stripped:
        key_store.set_key(kind, "")
        return {"status": "cleared"}
    ok, err = verify(stripped)
    if ok:
        key_store.set_key(kind, stripped)
        return {"status": "ok"}
    return {"status": "failed", "error": err}


class RunParametersFromCodeRequest(BaseModel):
    """Optional code to extract parameters from (e.g. current code from editor). If omitted, session code is used."""
    code: str | None = None


class VersionTagRequest(BaseModel):
    tag: str


class ChatBaseRequest(BaseModel):
    """Set or clear the version used as chat base for refine (null to clear)."""
    version_id: str | None = None


class SessionSummary(BaseModel):
    session_id: str
    model: str
    title: str | None = None
    active_ticker: str | None = None
    active_strategy: str | None = None
    messages: int = 0
    runs: int = 0
    updated_at: str = ""
    ready_for_paper_trading_count: int = 0  # only these version(s) can be paper traded


@router.get("/sessions", response_model=list[SessionSummary])
async def list_sessions():
    from backtester.compliance.status import get_ready_for_paper_trading_version_ids

    sessions = ChatSession.list_sessions()
    for s in sessions:
        s["ready_for_paper_trading_count"] = len(
            get_ready_for_paper_trading_version_ids(s["session_id"])
        )
    return sessions


@router.post("/sessions", response_model=dict)
async def create_session(req: CreateSessionRequest):
    from backtester.llm.router import resolve_web_model_alias

    model = resolve_web_model_alias(req.model)
    session = ChatSession.new(model=model)
    session.save()
    return {"session_id": session.session_id, "model": session.model}


def _llm_option_visible(opt: dict[str, str], flags: dict[str, bool]) -> bool:
    a = opt.get("alias", "")
    if a == "opus":
        return bool(flags.get("anthropic_configured"))
    if a == "openai":
        return bool(flags.get("openai_configured"))
    if a == "deepseek":
        return bool(flags.get("deepseek_configured"))
    return False


@router.get("/settings/llm-keys")
async def get_llm_keys_status():
    """Return which providers have keys configured (never returns secrets)."""
    return key_store.configured_flags()


@router.get("/settings/llm-model-options")
async def get_llm_model_options():
    """Return allowlisted models for each provider that has a configured web API key."""
    from backtester.llm.model_catalog import (
        ANTHROPIC_MODELS,
        DEEPSEEK_MODELS,
        OPENAI_MODELS,
        llm_model_options_for_web,
    )

    flags = key_store.configured_flags()
    by_provider: dict[str, list[dict[str, str]]] = {
        "anthropic": [{"id": mid, "label": lab, "alias": "opus"} for mid, lab in ANTHROPIC_MODELS],
        "openai": [{"id": mid, "label": lab, "alias": "openai"} for mid, lab in OPENAI_MODELS],
        "deepseek": [{"id": mid, "label": lab, "alias": "deepseek"} for mid, lab in DEEPSEEK_MODELS],
    }
    out: dict[str, list[dict[str, str]]] = {}
    if flags.get("anthropic_configured"):
        out["anthropic"] = by_provider["anthropic"]
    if flags.get("openai_configured"):
        out["openai"] = by_provider["openai"]
    if flags.get("deepseek_configured"):
        out["deepseek"] = by_provider["deepseek"]
    return {
        "by_provider": out,
        "all": [o for o in llm_model_options_for_web() if _llm_option_visible(o, flags)],
    }


@router.post("/settings/llm-keys")
async def post_global_llm_keys(body: GlobalLLMKeysRequest):
    """Verify and store API keys for the web app (process memory only)."""
    return {
        "openai": _apply_global_key(body.openai_api_key, verify_openai_api_key, "openai"),
        "anthropic": _apply_global_key(body.anthropic_api_key, verify_anthropic_api_key, "anthropic"),
        "deepseek": _apply_global_key(body.deepseek_api_key, verify_deepseek_api_key, "deepseek"),
        "nvidia_qwen": _apply_global_key(body.nvidia_qwen_api_key, verify_nvidia_qwen_api_key, "nvidia_qwen"),
    }


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    from backtester.compliance.status import get_ready_for_paper_trading_versions

    session = ChatSession.load(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    ready_versions = get_ready_for_paper_trading_versions(session_id)
    return {
        "session_id": session.session_id,
        "model": session.model,
        "llm_model_id": session.llm_model_id,
        "title": session.title,
        "active_ticker": session.active_ticker,
        "active_strategy": session.active_strategy,
        "active_interval": session.active_interval,
        "has_code": session.active_code is not None,
        "messages": len(session.messages),
        "runs": len(session.run_history),
        "run_history": [
            {
                "ticker": r.ticker,
                "strategy": r.strategy[:80],
                "signal_count": r.signal_count,
                "success": r.success,
                "timestamp": r.timestamp,
            }
            for r in session.run_history
        ],
        "created_at": session.created_at,
        "updated_at": session.updated_at,
        "chat_base_version_id": getattr(session, "chat_base_version_id", None),
        "ready_for_paper_trading_count": len(ready_versions),
        "ready_for_paper_trading_versions": ready_versions,
    }


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, request: Request):
    from backtester.agent.session import AGENT_SESSIONS_DIR

    path = AGENT_SESSIONS_DIR / f"{session_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Session not found")
    path.unlink()
    sub = AGENT_SESSIONS_DIR / session_id
    if sub.exists():
        shutil.rmtree(sub, ignore_errors=True)
    sessions = getattr(request.app.state, "sessions", {})
    if isinstance(sessions, dict):
        sessions.pop(session_id, None)
    return {"deleted": session_id}


def _get_session_for_run_params(session_id: str, request: Request) -> ChatSession | None:
    """Prefer in-memory session so rerun parameters and current code use latest active_code (e.g. after adding gap_pct)."""
    sessions = getattr(request.app.state, "sessions", {})
    if session_id in sessions:
        return sessions[session_id]
    return ChatSession.load(session_id)


@router.get("/sessions/{session_id}/code")
async def get_session_code(session_id: str, request: Request):
    """Return current strategy code. Uses in-memory session when available so 'Latest' matches what the user sees."""
    session = _get_session_for_run_params(session_id, request)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    code = session.active_code
    if not code or not code.strip():
        code = ChatSession.get_latest_strategy_code_from_disk(session_id)
    if not code:
        raise HTTPException(status_code=404, detail="No strategy code in this session")
    return {"code": code, "ticker": session.active_ticker}


def _load_version_tags(session_id: str) -> dict[str, str]:
    """Load version_id -> tag from strategy_versions/tags.json."""
    from backtester.agent.session import AGENT_SESSIONS_DIR
    tags_path = AGENT_SESSIONS_DIR / session_id / "strategy_versions" / "tags.json"
    if not tags_path.exists():
        return {}
    try:
        data = json.loads(tags_path.read_text(encoding="utf-8"))
        return dict(data) if isinstance(data, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _load_version_sources(session_id: str) -> dict[str, str]:
    """Load version_id -> source from strategy_versions/manifest.json. Used to skip tag requirement for rerun versions."""
    from backtester.agent.session import AGENT_SESSIONS_DIR
    manifest_path = AGENT_SESSIONS_DIR / session_id / "strategy_versions" / "manifest.json"
    if not manifest_path.exists():
        return {}
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        entries = data if isinstance(data, list) else []
        return {e["version_id"]: e.get("source", "") for e in entries if isinstance(e, dict) and e.get("version_id")}
    except (json.JSONDecodeError, TypeError):
        return {}


def _load_deleted_versions(session_id: str) -> set[str]:
    """Load set of version_ids that are soft-deleted (excluded from rerun options)."""
    from backtester.agent.session import AGENT_SESSIONS_DIR
    path = AGENT_SESSIONS_DIR / session_id / "strategy_versions" / "deleted.json"
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return set(data) if isinstance(data, list) else set()
    except (json.JSONDecodeError, TypeError):
        return set()


def _save_deleted_versions(session_id: str, deleted_ids: set[str]) -> None:
    from backtester.agent.session import AGENT_SESSIONS_DIR
    base_dir = AGENT_SESSIONS_DIR / session_id / "strategy_versions"
    base_dir.mkdir(parents=True, exist_ok=True)
    path = base_dir / "deleted.json"
    path.write_text(json.dumps(sorted(deleted_ids), indent=2), encoding="utf-8")


@router.get("/sessions/{session_id}/code-versions")
async def get_code_versions(session_id: str):
    """Return list of code versions for this session: Latest (current) + saved strategy versions from history.
    Excludes soft-deleted versions (so they do not appear in rerun options).
    Includes source (run_backtest, refine_strategy, fix_strategy, rerun) so frontend can skip tag requirement for rerun."""
    session = ChatSession.load(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    from backtester.agent.session import AGENT_SESSIONS_DIR
    from datetime import datetime as dt
    tags = _load_version_tags(session_id)
    sources = _load_version_sources(session_id)
    deleted = _load_deleted_versions(session_id)
    versions = [{"version_id": None, "label": "Latest (current)", "tag": None, "source": None}]
    base_dir = AGENT_SESSIONS_DIR / session_id / "strategy_versions"
    if base_dir.exists():
        files = [(f.stem, f.stat().st_mtime) for f in base_dir.glob("*.py")]
        for version_id, mtime in sorted(files, key=lambda x: -x[1]):
            if version_id in deleted:
                continue
            tag = tags.get(version_id)
            source = sources.get(version_id)
            try:
                date_label = dt.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
            except Exception:
                date_label = version_id
            label = tag if tag else date_label
            versions.append({"version_id": version_id, "label": label, "tag": tag, "source": source})
    return {"versions": versions}


@router.get("/sessions/{session_id}/strategy-versions")
async def get_strategy_versions_all(session_id: str):
    """Return all strategy versions for the right panel (including soft-deleted). Each has version_id, label, tag, deleted."""
    session = ChatSession.load(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    from backtester.agent.session import AGENT_SESSIONS_DIR
    from datetime import datetime as dt
    tags = _load_version_tags(session_id)
    deleted = _load_deleted_versions(session_id)
    result: list[dict] = []
    base_dir = AGENT_SESSIONS_DIR / session_id / "strategy_versions"
    if base_dir.exists():
        files = [(f.stem, f.stat().st_mtime) for f in base_dir.glob("*.py")]
        for version_id, mtime in sorted(files, key=lambda x: -x[1]):
            tag = tags.get(version_id)
            try:
                date_label = dt.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
            except Exception:
                date_label = version_id
            label = tag if tag else date_label
            result.append({
                "version_id": version_id,
                "label": label,
                "tag": tag,
                "deleted": version_id in deleted,
            })
    return {"versions": result}


class VersionDeletedRequest(BaseModel):
    deleted: bool


@router.put("/sessions/{session_id}/code/{version_id}/deleted")
async def set_version_deleted(session_id: str, version_id: str, body: VersionDeletedRequest):
    """Soft-delete or restore a version. Deleted versions stay in the panel (strikethrough) but are excluded from rerun options."""
    from backtester.agent.session import AGENT_SESSIONS_DIR
    if not version_id.isalnum():
        raise HTTPException(status_code=400, detail="Invalid version id")
    base_dir = AGENT_SESSIONS_DIR / session_id / "strategy_versions"
    path = base_dir / f"{version_id}.py"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Strategy version not found")
    deleted = _load_deleted_versions(session_id)
    if body.deleted:
        deleted.add(version_id)
    else:
        deleted.discard(version_id)
    _save_deleted_versions(session_id, deleted)
    return {"version_id": version_id, "deleted": body.deleted}


@router.put("/sessions/{session_id}/code/{version_id}/tag")
async def set_version_tag(session_id: str, version_id: str, body: VersionTagRequest):
    """Set a mandatory user-facing tag (name) for this strategy version. Required before continuing chat."""
    from backtester.agent.session import AGENT_SESSIONS_DIR
    if not version_id.isalnum():
        raise HTTPException(status_code=400, detail="Invalid version id")
    tag = (body.tag or "").strip()
    if not tag:
        raise HTTPException(status_code=400, detail="Tag is required and cannot be empty")
    base_dir = AGENT_SESSIONS_DIR / session_id / "strategy_versions"
    path = base_dir / f"{version_id}.py"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Strategy version not found")
    tags_path = base_dir / "tags.json"
    tags = _load_version_tags(session_id)
    tags[version_id] = tag
    base_dir.mkdir(parents=True, exist_ok=True)
    tags_path.write_text(json.dumps(tags, indent=2), encoding="utf-8")
    return {"version_id": version_id, "tag": tag}


@router.put("/sessions/{session_id}/chat-base")
async def set_chat_base(session_id: str, body: ChatBaseRequest):
    """Set or clear the strategy version used as chat base for refine. Only one version can be in chat; setting another replaces it. Pass version_id: null to clear."""
    session = ChatSession.load(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    version_id = (body.version_id or "").strip() or None
    if version_id:
        from backtester.agent.session import AGENT_SESSIONS_DIR
        if not version_id.isalnum():
            raise HTTPException(status_code=400, detail="Invalid version id")
        path = AGENT_SESSIONS_DIR / session_id / "strategy_versions" / f"{version_id}.py"
        if not path.exists():
            raise HTTPException(status_code=404, detail="Strategy version not found")
    else:
        version_id = None
    session.chat_base_version_id = version_id
    session.save()
    return {"chat_base_version_id": session.chat_base_version_id}


@router.get("/sessions/{session_id}/run-parameters")
async def get_run_parameters(session_id: str, request: Request, version_id: str | None = None):
    """Return strategy parameters for the current run or a specific code version, for rerun-with-overrides UI.
    Uses in-memory session when available so the latest code (e.g. with new params like gap_pct) is used."""
    session = _get_session_for_run_params(session_id, request)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if version_id:
        # Load code for the selected version from disk
        from backtester.agent.session import AGENT_SESSIONS_DIR
        if not version_id.isalnum():
            raise HTTPException(status_code=400, detail="Invalid version id")
        path = AGENT_SESSIONS_DIR / session_id / "strategy_versions" / f"{version_id}.py"
        if not path.exists():
            raise HTTPException(status_code=404, detail="Strategy version not found")
        code = path.read_text(encoding="utf-8")
    else:
        code = session.active_code
        if not code or not code.strip():
            code = ChatSession.get_latest_strategy_code_from_disk(session_id)
        if not code:
            raise HTTPException(status_code=404, detail="No strategy code in this session")
    from backtester.engine.parameter_extractor import extract_parameters_from_code
    params = extract_parameters_from_code(code)
    return {"parameters": params}


@router.post("/sessions/{session_id}/run-parameters")
async def post_run_parameters(
    session_id: str, request: Request, body: RunParametersFromCodeRequest | None = None
):
    """Extract parameters from provided code or from session (when code omitted). Use when frontend has current code (e.g. edited in UI)."""
    from backtester.engine.parameter_extractor import extract_parameters_from_code

    if body and body.code and body.code.strip():
        params = extract_parameters_from_code(body.code.strip())
        return {"parameters": params}
    # Same as GET: use session code
    session = _get_session_for_run_params(session_id, request)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    code = session.active_code
    if not code or not code.strip():
        code = ChatSession.get_latest_strategy_code_from_disk(session_id)
    if not code:
        raise HTTPException(status_code=404, detail="No strategy code in this session")
    params = extract_parameters_from_code(code)
    return {"parameters": params}


@router.get("/sessions/{session_id}/messages")
async def get_session_messages(session_id: str, request: Request):
    session = ChatSession.load(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    has_successful_run = any(r.success for r in session.run_history)

    # Check if in-memory session has live chart data
    live_sessions: dict[str, ChatSession] = getattr(request.app.state, "sessions", {})
    mem = live_sessions.get(session_id)
    has_live_chart = mem is not None and (mem.active_indicator_df is not None or mem.active_data_df is not None)

    return {
        "messages": [
            {
                "role": m.role,
                "content": m.content,
                "timestamp": m.timestamp,
                "tool_calls": m.tool_calls,
                "name": m.name,
                "strategy_version_id": getattr(m, "strategy_version_id", None),
            }
            for m in session.messages
            if m.role in ("user", "assistant")
        ],
        "has_successful_run": has_successful_run,
        "has_chart_data": has_live_chart,
        "start_date": getattr(session, "start_date", None),
        "end_date": getattr(session, "end_date", None),
    }


@router.get("/sessions/{session_id}/code/{version_id}")
async def get_session_code_version(session_id: str, version_id: str):
    """Return the persisted strategy code for a specific version in this session."""
    from backtester.agent.session import AGENT_SESSIONS_DIR

    if not version_id.isalnum():
        raise HTTPException(status_code=400, detail="Invalid version id")

    base_dir = AGENT_SESSIONS_DIR / session_id / "strategy_versions"
    path = base_dir / f"{version_id}.py"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Strategy version not found")

    code = path.read_text(encoding="utf-8")
    return {"code": code, "version_id": version_id}


@router.get("/sessions/{session_id}/chart-data")
async def get_chart_data(session_id: str, request: Request):
    sessions: dict[str, ChatSession] = request.app.state.sessions
    session = sessions.get(session_id)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail="Session not in memory. Run a backtest first or reconnect.",
        )

    indicator_df = session.active_indicator_df
    signals_df = session.active_signals_df
    data_df = session.active_data_df

    if indicator_df is None and data_df is None:
        raise HTTPException(status_code=404, detail="No chart data available. Run a backtest first.")

    def _safe(v):
        if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
            return None
        return v

    chart_df = indicator_df if indicator_df is not None else data_df
    date_col = "Date" if "Date" in chart_df.columns else "Datetime" if "Datetime" in chart_df.columns else chart_df.columns[0]

    ohlcv = []
    for _, row in chart_df.iterrows():
        ohlcv.append({
            "time": str(row[date_col]),
            "open": _safe(row.get("Open")),
            "high": _safe(row.get("High")),
            "low": _safe(row.get("Low")),
            "close": _safe(row.get("Close")),
            "volume": _safe(row.get("Volume")),
        })

    signals = []
    if signals_df is not None:
        for _, row in signals_df.iterrows():
            signals.append({
                "time": str(row.get("Date", "")),
                "signal": row.get("Signal", ""),
                "price": _safe(row.get("Price")),
            })

    indicators: dict[str, list] = {}
    for col in session.active_indicator_columns:
        if col not in chart_df.columns:
            continue
        if not pd.api.types.is_numeric_dtype(chart_df[col]):
            continue
        series = []
        for _, row in chart_df.iterrows():
            val = _safe(row[col])
            if val is not None:
                series.append({"time": str(row[date_col]), "value": val})
        indicators[col] = series

    equity_curve = None
    backtest_summary = None
    if signals_df is not None and len(signals_df) > 0:
        ec, summ = compute_chart_backtest_extras(signals_df)
        equity_curve = ec
        backtest_summary = summ

    return {
        "ticker": session.active_ticker or "",
        "interval": session.active_interval or "",
        "ohlcv": ohlcv,
        "signals": signals,
        "indicators": indicators,
        "equity_curve": equity_curve,
        "backtest_summary": backtest_summary,
    }


# ---------------------------------------------------------------------------
# Compliance (paper-trading pre-requisites)
# ---------------------------------------------------------------------------


class ReproducibilityRequest(BaseModel):
    version_id: str


class ReproducibilityChooseRequest(BaseModel):
    version_id: str
    choice: str  # "original" | "rebuild_1" | "rebuild_2"


class QuizGenerateRequest(BaseModel):
    version_id: str


class QuizSubmitRequest(BaseModel):
    version_id: str
    answers: list[int]


@router.get("/sessions/{session_id}/compliance/versions")
async def get_compliance_versions(session_id: str):
    """Return only versions that are in the manifest and eligible for compliance (first entry must be run_backtest)."""
    session = ChatSession.load(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    from backtester.compliance.manifest import get_compliance_eligible_versions
    versions = get_compliance_eligible_versions(session_id)
    return {"versions": versions}


@router.get("/sessions/{session_id}/compliance/ready-versions")
async def get_ready_for_paper_trading_versions(session_id: str):
    """Return only versions that have passed both reproducibility and quiz. Only these may be paper traded."""
    session = ChatSession.load(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    from backtester.compliance.status import get_ready_for_paper_trading_versions
    versions = get_ready_for_paper_trading_versions(session_id)
    return {"versions": versions}


@router.post("/sessions/{session_id}/compliance/reproducibility")
async def run_reproducibility_check(session_id: str, body: ReproducibilityRequest):
    """Run reproducibility: rebuild strategy from commands up to version, compare signals. If mismatch, rebuild again and summarize; user must choose."""
    session = ChatSession.load(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    version_id = body.version_id.strip()
    if not version_id or not version_id.isalnum():
        raise HTTPException(status_code=400, detail="Invalid version_id")

    from backtester.compliance.reproducibility import run_reproducibility
    from backtester.compliance.status import save_compliance_status
    from backtester.llm.router import get_provider

    try:
        provider = get_provider(session.model, llm_model_id=session.llm_model_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    data_df = getattr(session, "active_data_df", None)
    result = run_reproducibility(
        session_id=session_id,
        version_id=version_id,
        provider=provider,
        data_df=data_df,
    )

    if result.error:
        return {
            "success": False,
            "passed": False,
            "error": result.error,
        }

    if result.passed:
        save_compliance_status(
            session_id,
            version_id,
            reproducibility_passed=True,
        )
        return {
            "success": True,
            "passed": True,
            "summary": result.summary,
        }

    if result.choice_required:
        return {
            "success": True,
            "passed": False,
            "choice_required": True,
            "summary": result.summary,
            "summary_bullets": result.summary_bullets,
            "options": result.options,
        }

    return {
        "success": True,
        "passed": False,
        "summary": result.summary or "Signals did not match.",
    }


@router.post("/sessions/{session_id}/compliance/reproducibility/choose")
async def choose_reproducibility(session_id: str, body: ReproducibilityChooseRequest):
    """Record user's choice after failed reproducibility (original, rebuild_1, or rebuild_2)."""
    session = ChatSession.load(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    version_id = body.version_id.strip()
    choice = (body.choice or "").strip().lower()
    if choice not in ("original", "rebuild_1", "rebuild_2"):
        raise HTTPException(status_code=400, detail="choice must be original, rebuild_1, or rebuild_2")
    if not version_id or not version_id.isalnum():
        raise HTTPException(status_code=400, detail="Invalid version_id")

    from backtester.compliance.status import save_compliance_status

    save_compliance_status(
        session_id,
        version_id,
        reproducibility_passed=True,
        reproducibility_choice=choice,
    )
    return {
        "success": True,
        "choice": choice,
        "message": "Reproducibility step completed. You can proceed to the understanding quiz.",
    }


@router.post("/sessions/{session_id}/compliance/quiz/generate")
async def generate_quiz(session_id: str, body: QuizGenerateRequest):
    """Generate understanding quiz questions for the selected version. Correct answers stored server-side."""
    session = ChatSession.load(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    version_id = body.version_id.strip()
    if not version_id or not version_id.isalnum():
        raise HTTPException(status_code=400, detail="Invalid version_id")

    from backtester.agent.session import AGENT_SESSIONS_DIR
    from backtester.compliance.manifest import get_commands_up_to_version
    from backtester.compliance.quiz import generate_quiz_questions
    from backtester.llm.router import get_provider

    code_path = AGENT_SESSIONS_DIR / session_id / "strategy_versions" / f"{version_id}.py"
    if not code_path.exists():
        raise HTTPException(status_code=404, detail="Strategy version not found")
    strategy_code = code_path.read_text(encoding="utf-8")
    commands = get_commands_up_to_version(session_id, version_id)
    strategy_description = (commands.initial_strategy if commands else None) or session.active_strategy or ""

    try:
        provider = get_provider(session.model, llm_model_id=session.llm_model_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    out = generate_quiz_questions(
        provider=provider,
        strategy_code=strategy_code,
        strategy_description=strategy_description,
        session_id=session_id,
        version_id=version_id,
    )
    if out.get("error"):
        raise HTTPException(status_code=500, detail=out.get("error", "Quiz generation failed"))
    return {"success": True, "questions": out["questions"]}


@router.post("/sessions/{session_id}/compliance/quiz/submit")
async def submit_quiz(session_id: str, body: QuizSubmitRequest):
    """Submit quiz answers. Returns pass/fail; if pass, updates compliance status and may unlock paper trading."""
    session = ChatSession.load(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    version_id = body.version_id.strip()
    if not version_id or not version_id.isalnum():
        raise HTTPException(status_code=400, detail="Invalid version_id")

    from datetime import datetime, timezone

    from backtester.compliance.quiz import grade_quiz
    from backtester.compliance.status import load_compliance_status, save_compliance_status

    result = grade_quiz(session_id=session_id, version_id=version_id, answers=body.answers)
    if result.get("passed"):
        save_compliance_status(session_id, version_id, quiz_passed=True)
        status = load_compliance_status(session_id, version_id)
        if status.get("reproducibility_passed") and status.get("quiz_passed"):
            save_compliance_status(
                session_id,
                version_id,
                paper_trading_unlocked_at=datetime.now(timezone.utc).isoformat(),
            )
    return {
        "success": True,
        "passed": result.get("passed", False),
        "score": result.get("score", ""),
        "message": result.get("message", ""),
    }


@router.get("/sessions/{session_id}/compliance/status")
async def get_compliance_status(session_id: str, version_id: str):
    """Get compliance status for a version. Required before paper trading."""
    session = ChatSession.load(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if not version_id or not version_id.isalnum():
        raise HTTPException(status_code=400, detail="Invalid version_id")

    from backtester.compliance import compliance_ready_for_paper_trading, load_compliance_status

    status = load_compliance_status(session_id, version_id)
    ready = compliance_ready_for_paper_trading(session_id, version_id)
    return {
        "version_id": version_id,
        "reproducibility_passed": status.get("reproducibility_passed", False),
        "reproducibility_choice": status.get("reproducibility_choice"),
        "quiz_passed": status.get("quiz_passed", False),
        "paper_trading_unlocked_at": status.get("paper_trading_unlocked_at"),
        "ready_for_paper_trading": ready,
        "updated_at": status.get("updated_at"),
    }


def _get_stocks_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _get_tickers_by_country(country: str) -> list[tuple[str, str]]:
    """Return list of (symbol, name) for the given country (US or INDIA)."""
    import csv
    root = _get_stocks_root()
    if country.upper() == "US":
        path = root / "us_stocks.csv"
    elif country.upper() == "INDIA":
        path = root / "india_stocks.csv"
    else:
        return []
    if not path.exists():
        return []
    out: list[tuple[str, str]] = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            out.append((row["Symbol"], row["Name"]))
    return out


@router.get("/tickers")
async def list_tickers():
    """Return available US and India stock tickers from us_stocks.csv and india_stocks.csv."""
    import csv
    root = _get_stocks_root()
    us_path = root / "us_stocks.csv"
    india_path = root / "india_stocks.csv"
    if not us_path.exists() and not india_path.exists():
        raise HTTPException(status_code=404, detail="Ticker list not found")

    tickers = []
    for path, country in [(us_path, "US"), (india_path, "INDIA")]:
        if not path.exists():
            continue
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                tickers.append({
                    "symbol": row["Symbol"],
                    "name": row["Name"],
                    "country": country,
                })
    return tickers


@router.get("/sessions/{session_id}/stocks")
async def list_stocks_by_country(session_id: str, country: str = "US"):
    """Return list of { symbol, name } for the given country (US or INDIA) for batch rerun."""
    if country.upper() not in ("US", "INDIA"):
        raise HTTPException(status_code=400, detail="country must be US or INDIA")
    pairs = _get_tickers_by_country(country)
    return [{"symbol": s, "name": n} for s, n in pairs]


# ---------------------------------------------------------------------------
# Batch rerun: run strategy on all tickers for a country (background job)
# ---------------------------------------------------------------------------

_batch_jobs: dict[str, dict] = {}


async def _run_batch_rerun(
    job_id: str,
    session_id: str,
    country: str,
    param_overrides: dict | None,
    version_id: str | None,
    start_date: str,
    end_date: str,
) -> None:
    from backtester.agent.tools import handle_rerun_on_ticker, compute_backtest_metrics_numeric

    job = _batch_jobs.get(job_id)
    if not job or job["status"] != "running":
        return
    session = ChatSession.load(session_id)
    if not session:
        job["status"] = "failed"
        job["error"] = "Session not found"
        return
    tickers = _get_tickers_by_country(country)
    job["total"] = len(tickers)

    async def noop(*args, **kwargs):
        pass

    for symbol, name in tickers:
        if job.get("status") != "running":
            break
        try:
            result = await handle_rerun_on_ticker(
                session=session,
                on_event=noop,
                ticker=symbol,
                start=start_date or "",
                end=end_date or "",
                param_overrides=param_overrides,
                version_id=version_id,
            )
            if not result.get("success"):
                job["results"].append({
                    "ticker": symbol,
                    "name": name,
                    "profit_factor": None,
                    "risk_reward": None,
                    "max_loss_pct": None,
                    "success": False,
                    "error": result.get("error", "Unknown error"),
                })
            elif session.active_signals_df is not None and len(session.active_signals_df) > 0:
                metrics = compute_backtest_metrics_numeric(session.active_signals_df)
                job["results"].append({
                    "ticker": symbol,
                    "name": name,
                    "profit_factor": metrics["profit_factor"],
                    "risk_reward": metrics["risk_reward"],
                    "max_loss_pct": metrics["max_loss_pct"],
                    "success": True,
                })
            else:
                job["results"].append({
                    "ticker": symbol,
                    "name": name,
                    "profit_factor": None,
                    "risk_reward": None,
                    "max_loss_pct": None,
                    "success": True,
                })
        except Exception as e:
            job["results"].append({
                "ticker": symbol,
                "name": name,
                "profit_factor": None,
                "risk_reward": None,
                "max_loss_pct": None,
                "success": False,
                "error": str(e),
            })
        job["completed"] = job["completed"] + 1
    job["status"] = "cancelled" if job.get("status") == "cancelled" else "done"
    session.save()


class BatchRerunRequest(BaseModel):
    country: str  # US | INDIA
    param_overrides: dict | None = None
    version_id: str | None = None
    start_date: str = ""
    end_date: str = ""


class ParameterRangeSpec(BaseModel):
    start: float
    end: float
    step: float


class ParameterSearchRequest(BaseModel):
    ticker: str
    parameter_ranges: dict[str, ParameterRangeSpec]
    version_id: str | None = None
    start_date: str = ""
    end_date: str = ""
    max_combinations: int = 200


class ParameterSearchApplyRequest(BaseModel):
    ticker: str
    selected_parameters: dict[str, str]
    version_id: str | None = None
    start_date: str = ""
    end_date: str = ""


def _generate_numeric_values(start: float, end: float, step: float) -> list[float]:
    if step <= 0:
        raise ValueError("step must be > 0")
    lo, hi = (start, end) if start <= end else (end, start)
    values: list[float] = []
    cur = lo
    guard = 0
    while cur <= hi + (abs(step) * 1e-9):
        values.append(round(cur, 10))
        cur += step
        guard += 1
        if guard > 5000:
            break
    if not values:
        values = [round(lo, 10)]
    return values


def _format_param_value_for_override(v: float) -> str:
    """Serialize numeric combo values while preserving integers (e.g. 18 vs 18.0)."""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def _save_strategy_version_snapshot(
    session: ChatSession,
    code: str,
    *,
    source: str,
    change_request: str | None = None,
    ticker: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    interval: str | None = None,
) -> str:
    from datetime import datetime, timezone
    from backtester.agent.session import AGENT_SESSIONS_DIR

    version_id = uuid.uuid4().hex[:12]
    base_dir = AGENT_SESSIONS_DIR / session.session_id / "strategy_versions"
    base_dir.mkdir(parents=True, exist_ok=True)
    (base_dir / f"{version_id}.py").write_text(code, encoding="utf-8")

    manifest_path = base_dir / "manifest.json"
    manifest: list[dict] = []
    if manifest_path.exists():
        try:
            loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest = loaded if isinstance(loaded, list) else []
        except (json.JSONDecodeError, TypeError):
            manifest = []
    manifest.append({
        "version_id": version_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "strategy_text": session.active_strategy,
        "change_request": change_request,
        "ticker": ticker or session.active_ticker,
        "start_date": start_date or getattr(session, "start_date", None),
        "end_date": end_date or getattr(session, "end_date", None),
        "interval": interval or getattr(session, "active_interval", None),
    })
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return version_id


def _coerce_value_literal(raw: str) -> str:
    s = str(raw).strip()
    low = s.lower()
    if low in ("true", "false"):
        return "True" if low == "true" else "False"
    if low in ("none", "null"):
        return "None"
    if re.fullmatch(r"-?\d+", s):
        return s
    if re.fullmatch(r"-?\d+(\.\d+)?", s):
        return s
    # Keep as a quoted string fallback.
    escaped = s.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _apply_parameter_defaults_to_code(code: str, selected_parameters: dict[str, str]) -> str:
    """Bake selected parameters into strategy code defaults (__init__ first, class attrs fallback)."""
    updated = code

    # 1) Update __init__ signature defaults (most common path used by parameter extractor).
    m = re.search(r"def\s+__init__\s*\((?P<sig>.*?)\)\s*:", updated, flags=re.DOTALL)
    if m:
        sig = m.group("sig")
        new_sig = sig
        for name, value in selected_parameters.items():
            lit = _coerce_value_literal(value)
            # Replace occurrences like: name = oldvalue
            pattern = rf"(\b{name}\s*=\s*)([^,\n\)]*)"
            new_sig = re.sub(pattern, rf"\g<1>{lit}", new_sig)
        updated = updated[: m.start("sig")] + new_sig + updated[m.end("sig") :]

    # 2) Fallback: update class-level assignments if present.
    for name, value in selected_parameters.items():
        lit = _coerce_value_literal(value)
        updated = re.sub(
            rf"(^[ \t]*{re.escape(name)}\s*=\s*)(.+)$",
            rf"\g<1>{lit}",
            updated,
            flags=re.MULTILINE,
        )

    return updated


@router.post("/sessions/{session_id}/batch_rerun")
async def start_batch_rerun(session_id: str, req: BatchRerunRequest):
    """Start a background job to run the current strategy on all stocks for the given country. Returns job_id to poll."""
    if req.country.upper() not in ("US", "INDIA"):
        raise HTTPException(status_code=400, detail="country must be US or INDIA")
    session = ChatSession.load(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if not session.active_code:
        raise HTTPException(status_code=400, detail="No strategy to rerun. Run a backtest first.")
    job_id = str(uuid.uuid4())
    _batch_jobs[job_id] = {
        "job_id": job_id,
        "session_id": session_id,
        "status": "running",
        "total": 0,
        "completed": 0,
        "results": [],
        "country": req.country,
        "param_overrides": req.param_overrides,
        "version_id": req.version_id,
        "start_date": req.start_date,
        "end_date": req.end_date,
    }
    asyncio.create_task(_run_batch_rerun(
        job_id, session_id, req.country,
        req.param_overrides, req.version_id,
        req.start_date or "", req.end_date or "",
    ))
    return {"job_id": job_id}


def _json_safe_float(x: float | None) -> float | None:
    """Return None for inf/nan so JSON serialization does not fail."""
    if x is None:
        return None
    if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
        return None
    return x


@router.post("/sessions/{session_id}/batch_rerun/{job_id}/cancel")
async def cancel_batch_rerun(session_id: str, job_id: str):
    """Request to stop the batch job. Processing will stop after the current ticker completes."""
    job = _batch_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["session_id"] != session_id:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] == "running":
        job["status"] = "cancelled"
    return {"job_id": job_id, "status": job["status"]}


@router.get("/sessions/{session_id}/batch_rerun/{job_id}")
async def get_batch_rerun_status(session_id: str, job_id: str):
    """Return current status and results of a batch rerun job. Poll until status is done, failed, or cancelled."""
    job = _batch_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["session_id"] != session_id:
        raise HTTPException(status_code=404, detail="Job not found")
    # Sanitize results so inf/nan are not sent (JSON does not allow them)
    results = []
    for r in job["results"]:
        row = {
            "ticker": r["ticker"],
            "name": r["name"],
            "profit_factor": _json_safe_float(r.get("profit_factor")),
            "risk_reward": _json_safe_float(r.get("risk_reward")),
            "max_loss_pct": _json_safe_float(r.get("max_loss_pct")),
            "success": r.get("success", True),
        }
        if r.get("error") is not None:
            row["error"] = r["error"]
        results.append(row)
    return {
        "job_id": job_id,
        "status": job["status"],
        "total": job["total"],
        "completed": job["completed"],
        "results": results,
        "country": job.get("country"),
        "error": job.get("error"),
    }


@router.post("/sessions/{session_id}/parameter-search")
async def run_parameter_search(session_id: str, req: ParameterSearchRequest):
    from itertools import product
    from backtester.agent.tools import (
        execute_parameter_search_combo,
        load_full_history_ohlcv_for_parameter_search,
        mark_parameter_search_overfitting,
        parameter_search_split_calendar_days,
        parameter_search_train_test_from_signals,
    )

    session = ChatSession.load(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if not session.active_code:
        raise HTTPException(status_code=400, detail="No strategy to optimize. Run a backtest first.")
    if not req.parameter_ranges:
        raise HTTPException(status_code=400, detail="parameter_ranges is required")
    if req.max_combinations <= 0:
        raise HTTPException(status_code=400, detail="max_combinations must be > 0")

    param_names: list[str] = []
    value_lists: list[list[float]] = []
    for name, spec in req.parameter_ranges.items():
        try:
            vals = _generate_numeric_values(spec.start, spec.end, spec.step)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid range for {name}: {exc}")
        param_names.append(name)
        value_lists.append(vals)

    total_combinations = 1
    for vals in value_lists:
        total_combinations *= max(1, len(vals))
    if total_combinations > req.max_combinations:
        raise HTTPException(
            status_code=400,
            detail=f"Too many combinations ({total_combinations}). Reduce ranges or increase max_combinations.",
        )

    original_state = {
        "active_ticker": session.active_ticker,
        "active_data_df": session.active_data_df,
        "active_signals_df": session.active_signals_df,
        "active_indicator_df": session.active_indicator_df,
        "active_indicator_columns": session.active_indicator_columns,
    }

    rows: list[dict] = []
    meta: dict = {}
    try:
        loaded = await load_full_history_ohlcv_for_parameter_search(
            session, req.ticker.strip(), req.version_id
        )
        if not loaded.get("success"):
            raise HTTPException(status_code=400, detail=loaded.get("error", "Failed to load data"))

        data_df = loaded["data_df"]
        code_to_run = loaded["code_to_run"]
        strategy_nl = loaded["strategy_nl"]
        corporate_needs = loaded["corporate_needs"]
        hist_start = loaded["history_start"]
        hist_end = loaded["history_end"]
        was_clamped = loaded["was_clamped"]
        interval = loaded["interval"]

        from backtester.data.interval import INTERVAL_LABELS

        iv_label = INTERVAL_LABELS.get(interval, interval)
        seg = parameter_search_split_calendar_days(data_df)
        meta = {
            "optimization_note": (
                "Parameter search uses a fresh download of the widest available history for this symbol "
                f"({iv_label}), not the chart date range. "
                "Metrics use an 80% train / 20% test split by bar count (first 80% of rows vs last 20%). "
                "Train/Test profit % columns are estimated annual %: linear scaling of sum-of-trade % P&L over each "
                "segment’s calendar span (×365.25/days), so different-length train vs test windows are comparable. "
                "After you pick parameters, Apply runs on your Start/End dates in this dialog."
            ),
            "profit_annualization": (
                "linear: segment_sum_trade_pct × (365.25 / segment_calendar_days); "
                "segment days = inclusive calendar span from first to last bar in that split."
            ),
            "interval": interval,
            "history_start": hist_start,
            "history_end": hist_end,
            "date_range_was_clamped": was_clamped,
        }
        if seg:
            sidx = int(seg["split_idx"])
            te_raw = data_df["Date"].iloc[sidx - 1]
            ts_raw = data_df["Date"].iloc[sidx]
            meta["train_end_date"] = te_raw.strftime("%Y-%m-%d") if hasattr(te_raw, "strftime") else str(te_raw)[:10]
            meta["test_start_date"] = ts_raw.strftime("%Y-%m-%d") if hasattr(ts_raw, "strftime") else str(ts_raw)[:10]
            meta["train_bars"] = seg["train_bars"]
            meta["test_bars"] = seg["test_bars"]
            meta["train_period_calendar_days"] = seg["train_period_calendar_days"]
            meta["test_period_calendar_days"] = seg["test_period_calendar_days"]

        for combo in product(*value_lists):
            overrides = {
                param_names[i]: _format_param_value_for_override(combo[i])
                for i in range(len(param_names))
            }
            result = await execute_parameter_search_combo(
                code_to_run,
                data_df,
                strategy_nl,
                corporate_needs,
                overrides,
            )
            row: dict = {**overrides}
            if not result.get("success"):
                row.update({
                    "success": False,
                    "error": result.get("error", "Unknown error"),
                    "win_rate_pct": None,
                    "total_return_pct": None,
                    "profit_factor": None,
                    "risk_reward": None,
                    "max_loss_pct": None,
                    "train_win_rate_pct": None,
                    "train_total_return_pct": None,
                    "train_profit_factor": None,
                    "train_risk_reward": None,
                    "train_max_loss_pct": None,
                    "test_win_rate_pct": None,
                    "test_total_return_pct": None,
                    "test_profit_factor": None,
                    "test_risk_reward": None,
                    "test_max_loss_pct": None,
                    "annual_return_gap": None,
                    "overfitting_risk": False,
                })
            else:
                sig = result["signals_df"]
                tt = parameter_search_train_test_from_signals(sig, data_df)
                if tt.get("error"):
                    row.update({
                        "success": False,
                        "error": tt["error"],
                        "win_rate_pct": None,
                        "total_return_pct": None,
                        "profit_factor": None,
                        "risk_reward": None,
                        "max_loss_pct": None,
                        "train_win_rate_pct": None,
                        "train_total_return_pct": None,
                        "train_profit_factor": None,
                        "train_risk_reward": None,
                        "train_max_loss_pct": None,
                        "test_win_rate_pct": None,
                        "test_total_return_pct": None,
                        "test_profit_factor": None,
                        "test_risk_reward": None,
                        "test_max_loss_pct": None,
                        "annual_return_gap": None,
                        "overfitting_risk": False,
                    })
                else:
                    tw = tt.get("train_win_rate_pct")
                    ttret = tt.get("train_total_return_pct")
                    tpf = tt.get("train_profit_factor")
                    trr = tt.get("train_risk_reward")
                    tml = tt.get("train_max_loss_pct")
                    row.update({
                        "success": True,
                        "error": None,
                        "win_rate_pct": _json_safe_float(tw),
                        "total_return_pct": _json_safe_float(ttret),
                        "profit_factor": _json_safe_float(tpf),
                        "risk_reward": _json_safe_float(trr),
                        "max_loss_pct": _json_safe_float(tml),
                        "train_win_rate_pct": _json_safe_float(tw),
                        "train_total_return_pct": _json_safe_float(ttret),
                        "train_total_return_pct_period": _json_safe_float(tt.get("train_total_return_pct_period")),
                        "train_profit_factor": _json_safe_float(tpf),
                        "train_risk_reward": _json_safe_float(trr),
                        "train_max_loss_pct": _json_safe_float(tml),
                        "test_win_rate_pct": _json_safe_float(tt.get("test_win_rate_pct")),
                        "test_total_return_pct": _json_safe_float(tt.get("test_total_return_pct")),
                        "test_total_return_pct_period": _json_safe_float(tt.get("test_total_return_pct_period")),
                        "test_profit_factor": _json_safe_float(tt.get("test_profit_factor")),
                        "test_risk_reward": _json_safe_float(tt.get("test_risk_reward")),
                        "test_max_loss_pct": _json_safe_float(tt.get("test_max_loss_pct")),
                        "annual_return_gap": _json_safe_float(tt.get("annual_return_gap")),
                        "overfitting_risk": False,
                    })
            rows.append(row)

        mark_parameter_search_overfitting(rows)
    finally:
        # Restore previous chart/session state after search; selection apply will set the chosen state.
        session.active_ticker = original_state["active_ticker"]
        session.active_data_df = original_state["active_data_df"]
        session.active_signals_df = original_state["active_signals_df"]
        session.active_indicator_df = original_state["active_indicator_df"]
        session.active_indicator_columns = original_state["active_indicator_columns"]
        session.save()

    out = {
        "ticker": req.ticker.strip(),
        "version_id": req.version_id,
        "total_combinations": total_combinations,
        "rows": rows,
        **meta,
    }
    return out


@router.post("/sessions/{session_id}/parameter-search/apply")
async def apply_parameter_search_selection(session_id: str, req: ParameterSearchApplyRequest):
    from backtester.agent.tools import handle_rerun_on_ticker

    session = ChatSession.load(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if not req.selected_parameters:
        raise HTTPException(status_code=400, detail="selected_parameters is required")

    async def noop(*args, **kwargs):
        return None

    rerun_result = await handle_rerun_on_ticker(
        session=session,
        on_event=noop,
        ticker=req.ticker.strip(),
        start=req.start_date or "",
        end=req.end_date or "",
        param_overrides=req.selected_parameters,
        version_id=req.version_id,
    )
    if not rerun_result.get("success"):
        raise HTTPException(status_code=400, detail=rerun_result.get("error", "Failed to apply parameters"))

    code_for_version = ChatSession.get_latest_strategy_code_from_disk(session.session_id) or session.active_code
    if not code_for_version or not code_for_version.strip():
        raise HTTPException(status_code=400, detail="No strategy code available to version")
    code_for_version = _apply_parameter_defaults_to_code(code_for_version, req.selected_parameters)
    session.active_code = code_for_version

    version_id = _save_strategy_version_snapshot(
        session,
        code_for_version,
        source="optimize_parameters",
        change_request=f"Best-parameter selection on {req.ticker.strip()}: {json.dumps(req.selected_parameters)}",
        ticker=req.ticker.strip(),
        start_date=req.start_date or None,
        end_date=req.end_date or None,
        interval=session.active_interval,
    )
    session.save()
    return {
        "success": True,
        "strategy_version_id": version_id,
        "ticker": req.ticker.strip(),
        "selected_parameters": req.selected_parameters,
    }


@router.get("/health")
async def health():
    return {"status": "ok"}

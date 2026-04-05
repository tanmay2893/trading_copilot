"""FastAPI application with WebSocket chat endpoint.

Start with: uvicorn backtester.api.server:app --reload --port 6700
"""

from __future__ import annotations

import json
import logging

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backtester.agent.date_range_infer import infer_suggested_backtest_dates
from backtester.agent.events import DoneEvent, ErrorEvent, RequestDateRangeEvent
from backtester.agent.orchestrator import agent_loop
from backtester.agent.session import ChatSession
from backtester.agent.tools import handle_rerun_on_ticker
from backtester.api.routes import router
from backtester.llm.router import get_provider

log = logging.getLogger(__name__)

app = FastAPI(
    title="Backtester Agent API",
    description="HTTP and WebSocket API for strategy backtesting and chat sessions",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Log full traceback for 500s so you can see the cause in the server console."""
    log.exception("Unhandled exception: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "type": type(exc).__name__},
    )


_sessions: dict[str, ChatSession] = {}
app.state.sessions = _sessions


def _get_or_create_session(session_id: str, model: str = "openai") -> ChatSession:
    if session_id in _sessions:
        return _sessions[session_id]
    session = ChatSession.load(session_id)
    if session is None:
        session = ChatSession(session_id=session_id, model=model)
    _sessions[session_id] = session
    return session


def _generate_session_title(provider, first_user_message: str) -> str:
    """Generate a short, 5–10 word title from the first user message."""
    prompt = f"""\
Create a concise 5–10 word title for this chat session.

Rules:
- Output plain text only (no quotes, no markdown, no trailing punctuation).
- Use Title Case.
- Do not include ticker symbols unless central.

User message:
{first_user_message.strip()}
"""
    try:
        resp = provider.generate(prompt, "You generate short session titles.")
        text = (resp.content or "").strip()
    except Exception:
        text = ""

    # Sanitize (strip surrounding quotes and collapse whitespace)
    text = text.strip().strip('"').strip("'").strip()
    text = " ".join(text.split())
    text = text.rstrip(" .,:;!-")

    # Enforce word count as best-effort without extra LLM calls
    if not text:
        text = " ".join(first_user_message.strip().split()[:10])
        text = " ".join(text.split())
    words = text.split()
    if len(words) > 10:
        text = " ".join(words[:10])
    elif len(words) < 5:
        fallback_words = first_user_message.strip().split()
        if len(fallback_words) >= 5:
            text = " ".join(fallback_words[:10])
        else:
            text = f"Session {first_user_message.strip()[:48]}".strip()
        text = " ".join(text.split()).rstrip(" .,:;!-")

    # Never return empty: fallback to first 8 words of the message
    if not text or not text.strip():
        words = first_user_message.strip().split()[:8]
        text = " ".join(words).strip() or "New chat"
    return text[:80].strip()


@app.websocket("/ws/chat/{session_id}")
async def chat_ws(websocket: WebSocket, session_id: str):
    await websocket.accept()
    session = _get_or_create_session(session_id)

    provider = None

    try:
        while True:
            try:
                raw = await websocket.receive_text()
            except RuntimeError as e:
                if "not connected" in str(e).lower() or "accept" in str(e).lower():
                    log.info("WebSocket closed: %s", session_id)
                    break
                raise
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                data = {"type": "message", "content": raw}

            if data.get("type") == "cancel":
                continue

            # Direct rerun — no LLM involved
            if data.get("type") == "rerun":
                ticker = data.get("ticker", "").strip()
                if not ticker:
                    await websocket.send_json(ErrorEvent(message="No ticker provided").to_dict())
                    await websocket.send_json(DoneEvent().to_dict())
                    continue

                param_overrides = data.get("param_overrides")
                if param_overrides is not None and not isinstance(param_overrides, dict):
                    param_overrides = None

                version_id = data.get("version_id")
                if version_id is not None and not isinstance(version_id, str):
                    version_id = None
                if version_id is not None and not version_id.strip():
                    version_id = None
                elif version_id is not None:
                    version_id = version_id.strip()

                # Start/end date for this rerun (default: session's initial range)
                rerun_start = (data.get("start_date") or "").strip() or (session.start_date or "")
                rerun_end = (data.get("end_date") or "").strip() or (session.end_date or "")

                async def on_rerun_event(event):
                    try:
                        await websocket.send_json(event.to_dict())
                    except Exception:
                        pass

                try:
                    await handle_rerun_on_ticker(
                        session=session,
                        on_event=on_rerun_event,
                        ticker=ticker,
                        start=rerun_start,
                        end=rerun_end,
                        param_overrides=param_overrides,
                        version_id=version_id,
                    )
                except Exception as exc:
                    log.exception("Rerun error")
                    await websocket.send_json(ErrorEvent(message=str(exc)).to_dict())
                await websocket.send_json(DoneEvent().to_dict())
                session.save()
                continue

            # Client submitting selected date range (after request_date_range)
            if data.get("type") == "date_range":
                start_date = (data.get("start_date") or "").strip()
                end_date = (data.get("end_date") or "").strip()
                pending = getattr(session, "_pending_user_message", None)
                session._pending_user_message = None
                if not start_date or not end_date:
                    await websocket.send_json(ErrorEvent(message="Please provide both start_date and end_date (YYYY-MM-DD).").to_dict())
                    await websocket.send_json(DoneEvent().to_dict())
                    continue
                session.start_date = start_date
                session.end_date = end_date
                session.save()
                if pending:
                    content = pending
                else:
                    await websocket.send_json(DoneEvent().to_dict())
                    continue
            else:
                content = data.get("content", "").strip()
                if not content:
                    continue

            # Store chart screenshot from frontend (if provided) for fix/refine tools
            chart_image = data.get("chart_image")
            if chart_image:
                session.pending_chart_image = chart_image
            else:
                session.pending_chart_image = None

            if data.get("model") and data["model"] != session.model:
                session.model = data["model"]
                provider = None

            if provider is None:
                try:
                    provider = get_provider(session.model)
                except Exception as exc:
                    await websocket.send_json(ErrorEvent(message=f"LLM init failed: {exc}").to_dict())
                    await websocket.send_json(DoneEvent().to_dict())
                    continue

            # Title: generate once, as soon as the first user message arrives
            if not (session.title and session.title.strip()) and len(session.messages) == 0:
                session.title = _generate_session_title(provider, content)
                session.save()

            # On first real message, if session has no date range, ask for it via calendar
            if not session.start_date or not session.end_date:
                session._pending_user_message = content
                sug_start: str | None = None
                sug_end: str | None = None
                try:
                    sug_start, sug_end = infer_suggested_backtest_dates(provider, content)
                except Exception:
                    log.exception("Date inference from user message failed")
                msg = RequestDateRangeEvent().message
                if sug_start and sug_end:
                    msg = (
                        f"{msg} Suggested from your message: {sug_start} to {sug_end}. "
                        "Adjust if needed, then confirm."
                    )
                await websocket.send_json(
                    RequestDateRangeEvent(
                        message=msg,
                        suggested_start_date=sug_start,
                        suggested_end_date=sug_end,
                    ).to_dict()
                )
                await websocket.send_json(DoneEvent().to_dict())
                session.save()
                continue

            async def on_event(event):
                try:
                    await websocket.send_json(event.to_dict())
                except Exception:
                    pass

            try:
                await agent_loop(session, content, provider, on_event)
            except Exception as exc:
                log.exception("Agent loop error")
                await websocket.send_json(ErrorEvent(message=str(exc)).to_dict())
                await websocket.send_json(DoneEvent().to_dict())

            session.save()

    except WebSocketDisconnect:
        log.info("Client disconnected: %s", session_id)
        if session_id in _sessions:
            _sessions[session_id].save()
    except Exception as exc:
        log.exception("WebSocket error: %s", exc)
        if session_id in _sessions:
            _sessions[session_id].save()
    finally:
        if session_id in _sessions:
            _sessions[session_id].save()

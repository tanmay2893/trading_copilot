"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLlmSettings } from "@/context/LlmSettingsContext";
import type {
  ChatMessage,
  DoneEvent,
  MessageBlock,
  RequestDateRangeEvent,
  ServerEvent,
} from "@/lib/types";
import { fetchSessionMessages } from "@/lib/api";

/** Backend port for WebSockets in local dev (must match uvicorn and next.config rewrites target). */
const DEFAULT_LOCAL_WS = "ws://localhost:6700";

function getWsBase() {
  if (process.env.NEXT_PUBLIC_WS_URL) {
    return process.env.NEXT_PUBLIC_WS_URL;
  }
  if (typeof window !== "undefined") {
    const hostname = window.location.hostname;
    const isLocal = hostname === "localhost" || hostname === "127.0.0.1";
    if (!isLocal) {
      const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
      return `${proto}//${window.location.host}`;
    }
    // Localhost: Next.js rewrites /api to the backend but does not proxy /ws — connect to API server directly.
    return DEFAULT_LOCAL_WS;
  }
  return DEFAULT_LOCAL_WS;
}
const RECONNECT_DELAY_MS = 3000;
const MAX_RECONNECT_ATTEMPTS = 10;

let msgCounter = 0;
function nextId() {
  return `msg-${Date.now()}-${++msgCounter}`;
}

export interface UseChatOptions {
  /** When set, the ref's callback is invoked on the next "done" event (e.g. open chart after rerun), then cleared. */
  onDoneRef?: React.MutableRefObject<(() => void) | null>;
  /** Session model: openai | opus | deepseek — which API key Settings expects. */
  sessionModel?: string;
}

export function useChat(sessionId: string, options?: UseChatOptions) {
  const onDoneRef = options?.onDoneRef;
  const sessionModel = (options?.sessionModel || "openai").toLowerCase();
  const { hasKeysForModel, openSettings } = useLlmSettings();

  const guardLlmKeys = useCallback(() => {
    if (sessionId.startsWith("local-")) return true;
    if (hasKeysForModel(sessionModel)) return true;
    openSettings("Add an API key to use chat. Keys apply to all sessions.");
    return false;
  }, [sessionId, sessionModel, hasKeysForModel, openSettings]);

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const assistantBlocksRef = useRef<MessageBlock[]>([]);
  const assistantIdRef = useRef<string>("");
  const reconnectAttempts = useRef(0);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);

  const flushAssistant = useCallback(() => {
    const id = assistantIdRef.current || nextId();
    if (!assistantIdRef.current) {
      assistantIdRef.current = id;
    }
    const blocks = [...assistantBlocksRef.current];
    setMessages((prev) => {
      const idx = prev.findIndex((m) => m.id === id);
      const msg: ChatMessage = {
        id,
        role: "assistant",
        blocks,
        timestamp: Date.now(),
      };
      if (idx >= 0) {
        const updated = [...prev];
        updated[idx] = msg;
        return updated;
      }
      return [...prev, msg];
    });
  }, []);

  const [showDateRangePicker, setShowDateRangePicker] = useState(false);
  const [dateRangeMessage, setDateRangeMessage] = useState<string>("");
  const [dateRangeSuggestedStart, setDateRangeSuggestedStart] = useState<string | null>(null);
  const [dateRangeSuggestedEnd, setDateRangeSuggestedEnd] = useState<string | null>(null);
  const [sessionDateRange, setSessionDateRange] = useState<{ start_date: string; end_date: string } | null>(null);

  /** Cumulative token usage for this chat session (updated on each "done" with usage). */
  const [usage, setUsage] = useState<{
    inputTokens: number;
    outputTokens: number;
    model: string | null;
  }>({ inputTokens: 0, outputTokens: 0, model: null });

  const handleServerEvent = useCallback((event: ServerEvent) => {
    switch (event.type) {
      case "request_date_range": {
        const dr = event as RequestDateRangeEvent;
        setShowDateRangePicker(true);
        setDateRangeMessage(dr.message ?? "Select start and end dates for backtesting.");
        const ss = dr.suggested_start_date?.trim() || null;
        const se = dr.suggested_end_date?.trim() || null;
        setDateRangeSuggestedStart(ss && /^\d{4}-\d{2}-\d{2}$/.test(ss) ? ss : null);
        setDateRangeSuggestedEnd(se && /^\d{4}-\d{2}-\d{2}$/.test(se) ? se : null);
        setIsLoading(false);
        break;
      }
      case "text": {
        assistantBlocksRef.current.push({ type: "text", content: event.content });
        flushAssistant();
        break;
      }
      case "progress": {
        const existing = assistantBlocksRef.current.findIndex(
          (b) => b.type === "progress" && (b as { step: string }).step === event.step
        );
        const block: MessageBlock = {
          type: "progress",
          step: event.step,
          status: event.status,
          detail: event.detail,
        };
        if (existing >= 0) {
          assistantBlocksRef.current[existing] = block;
        } else {
          assistantBlocksRef.current.push(block);
        }
        flushAssistant();
        break;
      }
      case "code": {
        assistantBlocksRef.current.push({
          type: "code",
          code: event.code,
          language: event.language || "python",
        });
        flushAssistant();
        break;
      }
      case "strategy_version": {
        assistantBlocksRef.current.push({
          type: "strategy_version",
          versionId: event.version_id,
        });
        flushAssistant();
        break;
      }
      case "table": {
        assistantBlocksRef.current.push({
          type: "table",
          title: event.title,
          headers: event.headers,
          rows: event.rows,
          ...(event.formula ? { formula: event.formula } : {}),
        });
        flushAssistant();
        break;
      }
      case "image": {
        assistantBlocksRef.current.push({
          type: "image",
          url: event.url,
          alt: event.alt || "Chart screenshot",
        });
        flushAssistant();
        break;
      }
      case "error": {
        assistantBlocksRef.current.push({ type: "error", message: event.message });
        flushAssistant();
        break;
      }
      case "tool_start":
      case "tool_end":
        break;
      case "done": {
        setIsLoading(false);
        const doneEv = event as DoneEvent;
        if (
          typeof doneEv.input_tokens === "number" &&
          typeof doneEv.output_tokens === "number"
        ) {
          setUsage((prev) => ({
            inputTokens: prev.inputTokens + doneEv.input_tokens!,
            outputTokens: prev.outputTokens + doneEv.output_tokens!,
            model: doneEv.model ?? prev.model,
          }));
        }
        assistantBlocksRef.current = [];
        assistantIdRef.current = "";
        if (onDoneRef?.current) {
          const fn = onDoneRef.current;
          onDoneRef.current = null;
          fn();
        }
        if (typeof window !== "undefined") {
          window.dispatchEvent(new CustomEvent("backtester:sessions-updated", { detail: { sessionId } }));
        }
        break;
      }
    }
  }, [flushAssistant, sessionId, onDoneRef]);

  const handleEventRef = useRef(handleServerEvent);
  handleEventRef.current = handleServerEvent;

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN || wsRef.current?.readyState === WebSocket.CONNECTING) {
      return;
    }

    const ws = new WebSocket(`${getWsBase()}/ws/chat/${sessionId}`);

    ws.onopen = () => {
      if (!mountedRef.current) return;
      setIsConnected(true);
      reconnectAttempts.current = 0;
    };

    ws.onclose = () => {
      if (!mountedRef.current) return;
      setIsConnected(false);
      wsRef.current = null;
      if (reconnectAttempts.current < MAX_RECONNECT_ATTEMPTS) {
        reconnectAttempts.current += 1;
        reconnectTimer.current = setTimeout(() => {
          if (mountedRef.current) connect();
        }, RECONNECT_DELAY_MS);
      }
    };

    ws.onerror = () => {
      // onclose will fire after this, which handles reconnect
    };

    ws.onmessage = (event) => {
      let data: ServerEvent;
      try {
        data = JSON.parse(event.data);
      } catch {
        return;
      }
      handleEventRef.current(data);
    };

    wsRef.current = ws;
  }, [sessionId]);

  useEffect(() => {
    mountedRef.current = true;
    connect();
    return () => {
      mountedRef.current = false;
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [connect]);

  // Load conversation history from the server on first mount
  const [hasChartDataFromServer, setHasChartDataFromServer] = useState(false);
  const [hasSuccessfulRunFromServer, setHasSuccessfulRunFromServer] = useState(false);
  useEffect(() => {
    let cancelled = false;
    fetchSessionMessages(sessionId)
      .then((data) => {
        if (cancelled || !data.messages) return;
        const history: ChatMessage[] = [];
        for (const msg of data.messages) {
          if (msg.tool_calls?.length && !msg.content?.trim()) continue;
          if (!msg.content?.trim()) continue;
          const blocks: MessageBlock[] = [{ type: "text", content: msg.content }];
          if (msg.strategy_version_id) {
            blocks.push({ type: "strategy_version", versionId: msg.strategy_version_id });
          }
          history.push({
            id: nextId(),
            role: msg.role as "user" | "assistant",
            blocks,
            timestamp: new Date(msg.timestamp).getTime(),
          });
        }
        if (history.length > 0 && !cancelled) {
          setMessages((prev) => (prev.length > 0 ? prev : history));
        }
        if (!cancelled) {
          setHistoryLoaded(true);
          if (data.has_chart_data) setHasChartDataFromServer(true);
          if (data.has_successful_run) setHasSuccessfulRunFromServer(true);
          if (data.start_date && data.end_date) {
            setSessionDateRange({ start_date: data.start_date, end_date: data.end_date });
          }
        }
      })
      .catch(() => {
        if (!cancelled) setHistoryLoaded(true);
      });
    return () => { cancelled = true; };
  }, [sessionId]);

  const sendDateRange = useCallback(
    (startDate: string, endDate: string) => {
      if (!guardLlmKeys()) return;
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
        connect();
        setTimeout(() => sendDateRange(startDate, endDate), 1000);
        return;
      }
      setShowDateRangePicker(false);
      setDateRangeMessage("");
      setDateRangeSuggestedStart(null);
      setDateRangeSuggestedEnd(null);
      setSessionDateRange({ start_date: startDate, end_date: endDate });
      setIsLoading(true);
      wsRef.current.send(
        JSON.stringify({ type: "date_range", start_date: startDate, end_date: endDate })
      );
    },
    [connect, guardLlmKeys]
  );

  const dismissDateRangePicker = useCallback(() => {
    setShowDateRangePicker(false);
    setDateRangeMessage("");
    setDateRangeSuggestedStart(null);
    setDateRangeSuggestedEnd(null);
  }, []);

  const sendMessage = useCallback(
    (content: string, chartImage?: string | null) => {
      if (!guardLlmKeys()) return;
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
        connect();
        setTimeout(() => sendMessage(content, chartImage), 1000);
        return;
      }

      const userBlocks: MessageBlock[] = [{ type: "text", content }];
      if (chartImage) {
        userBlocks.push({ type: "image", url: chartImage, alt: "Chart screenshot attached" });
      }

      const userMsg: ChatMessage = {
        id: nextId(),
        role: "user",
        blocks: userBlocks,
        timestamp: Date.now(),
      };
      setMessages((prev) => [...prev, userMsg]);
      setIsLoading(true);
      assistantBlocksRef.current = [];
      assistantIdRef.current = "";

      const payload: Record<string, string> = { type: "message", content };
      if (chartImage) {
        const base64 = chartImage.startsWith("data:") ? chartImage.split(",")[1] : chartImage;
        payload.chart_image = base64;
      }
      wsRef.current.send(JSON.stringify(payload));
    },
    [connect, guardLlmKeys]
  );

  const rerunOnTicker = useCallback(
    (
      ticker: string,
      paramOverrides?: Record<string, string>,
      versionId?: string | null,
      startDate?: string,
      endDate?: string
    ) => {
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
        connect();
        setTimeout(() => rerunOnTicker(ticker, paramOverrides, versionId, startDate, endDate), 1000);
        return;
      }

      const userMsg: ChatMessage = {
        id: nextId(),
        role: "user",
        blocks: [{ type: "text", content: `Run the same strategy on ${ticker}` }],
        timestamp: Date.now(),
      };
      setMessages((prev) => [...prev, userMsg]);
      setIsLoading(true);
      assistantBlocksRef.current = [];
      assistantIdRef.current = "";

      const payload: {
        type: "rerun";
        ticker: string;
        param_overrides?: Record<string, string>;
        version_id?: string;
        start_date?: string;
        end_date?: string;
      } = {
        type: "rerun",
        ticker,
      };
      if (paramOverrides && Object.keys(paramOverrides).length > 0) {
        payload.param_overrides = paramOverrides;
      }
      if (versionId != null && versionId !== "") {
        payload.version_id = versionId;
      }
      if (startDate?.trim()) {
        payload.start_date = startDate.trim();
      }
      if (endDate?.trim()) {
        payload.end_date = endDate.trim();
      }
      wsRef.current.send(JSON.stringify(payload));
    },
    [connect]
  );

  const disconnect = useCallback(() => {
    if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
    reconnectAttempts.current = MAX_RECONNECT_ATTEMPTS;
    wsRef.current?.close();
    wsRef.current = null;
  }, []);

  /** Latest strategy code from the last code block in messages (so "Latest" params match what the user sees). */
  const latestStrategyCode = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      const msg = messages[i];
      for (let j = (msg.blocks?.length ?? 0) - 1; j >= 0; j--) {
        const block = msg.blocks[j];
        if (block.type === "code" && block.code?.trim()) {
          return block.code.trim();
        }
      }
    }
    return undefined;
  }, [messages]);

  return {
    messages,
    isConnected,
    isLoading,
    historyLoaded,
    hasChartDataFromServer,
    hasSuccessfulRunFromServer,
    usage,
    connect,
    disconnect,
    sendMessage,
    rerunOnTicker,
    showDateRangePicker,
    dateRangeMessage,
    dateRangeSuggestedStart,
    dateRangeSuggestedEnd,
    sendDateRange,
    dismissDateRangePicker,
    sessionDateRange,
    latestStrategyCode,
  };
}

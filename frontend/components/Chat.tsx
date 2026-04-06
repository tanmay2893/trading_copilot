"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLlmSettings } from "@/context/LlmSettingsContext";
import { useChat } from "@/hooks/useChat";
import { estimateUsageCost, formatUsageCost } from "@/lib/usageCost";
import {
  fetchCodeVersions,
  fetchLlmModelOptions,
  fetchSession,
  fetchStrategyVersionsAll,
  getBatchRerunStatus,
  setChatBase,
  startBatchRerun,
  type LlmModelOption,
} from "@/lib/api";
import type { VersionTagsMap } from "./MessageList";

const BATCH_STORAGE_KEY = (sid: string) => `backtester_batch_${sid}`;
import { BatchProgressModal } from "./BatchProgressModal";
import { ChatInput } from "./ChatInput";
import { DateRangePicker } from "./DateRangePicker";
import { MessageList } from "./MessageList";
import { StrategyFollowUpSuggestions } from "./StrategyFollowUpSuggestions";

interface ChatProps {
  sessionId: string;
  onOpenChart?: () => void;
  getChartScreenshot?: () => string | null;
  onChartDataUpdated?: () => void;
  /** Number of strategy versions in this session that passed compliance (only those can be paper traded). */
  readyForPaperTradingCount?: number;
  /** Ref to run a callback on next "done" (e.g. open chart after rerun from batch modal). */
  openChartOnDoneRef?: React.MutableRefObject<(() => void) | null>;
  /** Called when this chat's loading state changes (strategy/refinement/question running). Passes sessionId so parent can track which chat is loading. */
  onLoadingChange?: (sessionId: string, loading: boolean) => void;
  /** Called when user tags a strategy version (so right panel can refresh). */
  onStrategyVersionTagged?: () => void;
}

export function Chat({ sessionId, onOpenChart, getChartScreenshot, onChartDataUpdated, readyForPaperTradingCount = 0, openChartOnDoneRef, onLoadingChange, onStrategyVersionTagged }: ChatProps) {
  const [batchJob, setBatchJob] = useState<{
    jobId: string;
    country: "US" | "INDIA";
    paramOverrides?: Record<string, string>;
    versionId?: string | null;
    startDate?: string;
    endDate?: string;
  } | null>(null);
  /** When modal is closed, which country has a reopenable job (so only that button stays active). */
  const [storedBatchCountry, setStoredBatchCountry] = useState<"US" | "INDIA" | null>(null);
  /** version_id -> tag (null if not set). Used to require tagging before continuing chat. */
  const [versionTags, setVersionTags] = useState<VersionTagsMap>({});
  /** version_id -> source (run_backtest | refine_strategy | fix_strategy | rerun). Rerun versions do not require naming. */
  const [versionSources, setVersionSources] = useState<Record<string, string>>({});
  /** Chat base version (selected in strategies panel): show as attachment above input. */
  const [chatBaseVersionId, setChatBaseVersionId] = useState<string | null>(null);
  const [chatBaseVersionLabel, setChatBaseVersionLabel] = useState<string | null>(null);
  const [sessionModel, setSessionModel] = useState("openai");
  const [llmModelId, setLlmModelId] = useState("");
  const [llmModelOptions, setLlmModelOptions] = useState<LlmModelOption[]>([]);
  const { status: llmKeyStatus } = useLlmSettings();

  const {
    messages,
    isConnected,
    isLoading,
    hasChartDataFromServer,
    hasSuccessfulRunFromServer,
    usage,
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
    followUpSuggestions,
  } = useChat(sessionId, {
    onDoneRef: openChartOnDoneRef ?? undefined,
    sessionModel,
    llmModelId,
  });

  const onLoadingChangeRef = useRef(onLoadingChange);
  onLoadingChangeRef.current = onLoadingChange;
  useEffect(() => {
    onLoadingChangeRef.current?.(sessionId, isLoading);
    return () => {
      onLoadingChangeRef.current?.(sessionId, false);
    };
  }, [sessionId, isLoading]);

  const loadChatBase = useCallback(() => {
    if (!sessionId) return;
    fetchSession(sessionId)
      .then((s) => {
        const id = s.chat_base_version_id ?? null;
        setChatBaseVersionId(id);
        if (!id) {
          setChatBaseVersionLabel(null);
          return;
        }
        return fetchStrategyVersionsAll(sessionId).then((data) => {
          const v = data.versions?.find((x) => x.version_id === id);
          setChatBaseVersionLabel(v?.label ?? id);
        });
      })
      .catch(() => {
        setChatBaseVersionId(null);
        setChatBaseVersionLabel(null);
      });
  }, [sessionId]);

  useEffect(() => {
    loadChatBase();
  }, [loadChatBase]);

  useEffect(() => {
    if (sessionId.startsWith("local-")) return;
    fetchSession(sessionId)
      .then((s) => {
        setSessionModel((s.model || "openai").toLowerCase());
        setLlmModelId((s.llm_model_id ?? "").trim());
      })
      .catch(() => {});
  }, [sessionId]);

  useEffect(() => {
    if (sessionId.startsWith("local-")) {
      setLlmModelOptions([]);
      return;
    }
    fetchLlmModelOptions()
      .then((r) => setLlmModelOptions(Array.isArray(r.all) ? r.all : []))
      .catch(() => setLlmModelOptions([]));
  }, [
    sessionId,
    llmKeyStatus?.openai_configured,
    llmKeyStatus?.anthropic_configured,
    llmKeyStatus?.deepseek_configured,
  ]);

  const handleLlmModelChange = useCallback(
    (id: string) => {
      setLlmModelId(id);
      if (id) {
        const opt = llmModelOptions.find((o) => o.id === id);
        if (opt) setSessionModel(opt.alias);
      }
    },
    [llmModelOptions]
  );

  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<{ sessionId?: string }>).detail;
      if (detail?.sessionId === sessionId) loadChatBase();
    };
    window.addEventListener("chat-base-changed", handler);
    return () => window.removeEventListener("chat-base-changed", handler);
  }, [sessionId, loadChatBase]);

  const handleClearChatBase = useCallback(async () => {
    if (!sessionId) return;
    try {
      await setChatBase(sessionId, null);
      setChatBaseVersionId(null);
      setChatBaseVersionLabel(null);
      window.dispatchEvent(new CustomEvent("chat-base-changed", { detail: { sessionId } }));
    } catch {
      // keep state on error
    }
  }, [sessionId]);

  // Collect version IDs from strategy_version blocks (for fetch) and from the last message only (for blocking)
  const versionIdsInMessages = useMemo(() => {
    const ids: string[] = [];
    for (const msg of messages) {
      for (const block of msg.blocks) {
        if (block.type === "strategy_version") ids.push(block.versionId);
      }
    }
    return ids;
  }, [messages]);

  const versionIdsInLastMessage = useMemo(() => {
    if (messages.length === 0) return [];
    const last = messages[messages.length - 1];
    const ids: string[] = [];
    for (const block of last.blocks ?? []) {
      if (block.type === "strategy_version") ids.push(block.versionId);
    }
    return ids;
  }, [messages]);

  useEffect(() => {
    if (!sessionId || versionIdsInMessages.length === 0) return;
    let cancelled = false;
    fetchCodeVersions(sessionId)
      .then((data) => {
        if (cancelled || !data.versions) return;
        const nextTags: VersionTagsMap = {};
        const nextSources: Record<string, string> = {};
        for (const v of data.versions) {
          if (v.version_id != null) {
            nextTags[v.version_id] = v.tag ?? null;
            if (v.source != null) nextSources[v.version_id] = String(v.source);
          }
        }
        setVersionTags((prev) => ({ ...prev, ...nextTags }));
        setVersionSources((prev) => ({ ...prev, ...nextSources }));
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [sessionId, versionIdsInMessages.join(",")]);

  // Require naming only when a strategy was created or refined (run_backtest / refine_strategy / fix_strategy). Never when a previously created strategy was rerun.
  const REQUIRED_TAG_SOURCES = ["run_backtest", "refine_strategy", "fix_strategy"];
  const hasUntaggedVersion =
    versionIdsInLastMessage.length > 0 &&
    versionIdsInLastMessage.some(
      (id) =>
        (versionTags[id] === null || versionTags[id] === undefined) &&
        REQUIRED_TAG_SOURCES.includes(versionSources[id])
    );

  const handleVersionTagged = useCallback(
    (versionId: string, tag: string) => {
      setVersionTags((prev) => ({ ...prev, [versionId]: tag }));
      onStrategyVersionTagged?.();
    },
    [onStrategyVersionTagged]
  );

  // Restore batch modal when returning to this session (job keeps running on server)
  useEffect(() => {
    const key = BATCH_STORAGE_KEY(sessionId);
    const raw = typeof sessionStorage !== "undefined" ? sessionStorage.getItem(key) : null;
    if (!raw) return;
    try {
      const stored = JSON.parse(raw) as {
        jobId: string;
        country: "US" | "INDIA";
        paramOverrides?: Record<string, string>;
        versionId?: string | null;
        startDate?: string;
        endDate?: string;
      };
      getBatchRerunStatus(sessionId, stored.jobId).then((data) => {
        if (data.status === "running" || data.status === "done") {
          setBatchJob({
            jobId: stored.jobId,
            country: stored.country ?? data.country ?? "US",
            paramOverrides: stored.paramOverrides,
            versionId: stored.versionId,
            startDate: stored.startDate,
            endDate: stored.endDate,
          });
        } else {
          sessionStorage.removeItem(key);
        }
      }).catch(() => sessionStorage.removeItem(key));
    } catch {
      sessionStorage.removeItem(key);
    }
  }, [sessionId]);

  const estimatedCost =
    usage.inputTokens > 0 || usage.outputTokens > 0
      ? estimateUsageCost(
          usage.inputTokens,
          usage.outputTokens,
          usage.model ?? null
        )
      : null;
  const bottomRef = useRef<HTMLDivElement>(null);
  const [hasChartData, setHasChartData] = useState(false);
  const [hasSuccessfulRun, setHasSuccessfulRun] = useState(false);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const backtestCountRef = useRef(0);

  useEffect(() => {
    const completedCount = messages.filter((m) => m.role === "assistant")
      .reduce((n, m) => n + (m.blocks.some(
        (b) => b.type === "progress" && b.step === "Backtest complete" && b.status === "success"
      ) ? 1 : 0), 0);

    if (completedCount > 0) {
      setHasChartData(true);
      setHasSuccessfulRun(true);
    }

    if (completedCount > backtestCountRef.current) {
      backtestCountRef.current = completedCount;
      onChartDataUpdated?.();
    }
  }, [messages]);

  // Also activate from server-reported data (session loaded from history)
  useEffect(() => {
    if (hasChartDataFromServer) setHasChartData(true);
  }, [hasChartDataFromServer]);

  useEffect(() => {
    if (hasSuccessfulRunFromServer) setHasSuccessfulRun(true);
  }, [hasSuccessfulRunFromServer]);

  const handleBatchRerunConfirm = async (
    country: "US" | "INDIA",
    paramOverrides: Record<string, string> | undefined,
    versionId: string | null | undefined,
    startDate: string | undefined,
    endDate: string | undefined
  ) => {
    try {
      const { job_id } = await startBatchRerun(sessionId, {
        country,
        param_overrides: paramOverrides,
        version_id: versionId ?? null,
        start_date: startDate ?? "",
        end_date: endDate ?? "",
      });
      const job = {
        jobId: job_id,
        country,
        paramOverrides,
        versionId: versionId ?? null,
        startDate: startDate ?? undefined,
        endDate: endDate ?? undefined,
      };
      setBatchJob(job);
      if (typeof sessionStorage !== "undefined") {
        sessionStorage.setItem(BATCH_STORAGE_KEY(sessionId), JSON.stringify(job));
      }
    } catch (err) {
      console.error("Batch rerun start failed:", err);
    }
  };

  const handleBatchModalClose = (finalStatus?: string) => {
    setBatchJob(null);
    const key = BATCH_STORAGE_KEY(sessionId);
    if (finalStatus === "done" || finalStatus === "cancelled") {
      if (typeof sessionStorage !== "undefined") sessionStorage.removeItem(key);
      setStoredBatchCountry(null);
      return;
    }
    const raw = typeof sessionStorage !== "undefined" ? sessionStorage.getItem(key) : null;
    if (raw) {
      try {
        const stored = JSON.parse(raw) as { country?: string };
        setStoredBatchCountry(
          stored.country === "INDIA" || stored.country === "US" ? stored.country : null
        );
      } catch {
        setStoredBatchCountry(null);
      }
    } else {
      setStoredBatchCountry(null);
    }
  };

  const handleBatchRerunOpenRequest = useCallback(
    async (country: "US" | "INDIA"): Promise<boolean> => {
      const key = BATCH_STORAGE_KEY(sessionId);
      const raw = typeof sessionStorage !== "undefined" ? sessionStorage.getItem(key) : null;
      if (!raw) return false;
      try {
        const stored = JSON.parse(raw) as {
          jobId: string;
          country: string;
          paramOverrides?: Record<string, string>;
          versionId?: string | null;
          startDate?: string;
          endDate?: string;
        };
        if (stored.country !== country) return false;
        const data = await getBatchRerunStatus(sessionId, stored.jobId);
        if (data.status === "running" || data.status === "done") {
          setBatchJob({
            jobId: stored.jobId,
            country: stored.country as "US" | "INDIA",
            paramOverrides: stored.paramOverrides,
            versionId: stored.versionId,
            startDate: stored.startDate,
            endDate: stored.endDate,
          });
          return true;
        }
      } catch {
        // Job may be gone or network error
      }
      return false;
    },
    [sessionId]
  );

  const handleBatchCompanyClick = (symbol: string) => {
    if (!batchJob) return;
    if (openChartOnDoneRef && onOpenChart) {
      openChartOnDoneRef.current = onOpenChart;
    }
    rerunOnTicker(
      symbol,
      batchJob.paramOverrides,
      batchJob.versionId ?? undefined,
      batchJob.startDate,
      batchJob.endDate
    );
  };

  const handleSendMessage = useCallback(
    (msg: string) => {
      const screenshot = hasChartData && getChartScreenshot ? getChartScreenshot() : null;
      sendMessage(msg, screenshot);
    },
    [hasChartData, getChartScreenshot, sendMessage]
  );

  const showStrategyFollowUps = useMemo(() => {
    if (followUpSuggestions.length === 0 || isLoading || hasUntaggedVersion) return false;
    return true;
  }, [followUpSuggestions, isLoading, hasUntaggedVersion]);

  return (
    <div className="flex-1 flex flex-col h-full">
      {/* Header */}
      <header className="flex-shrink-0 border-b border-[var(--border)] px-6 py-3 flex items-center justify-between bg-[var(--bg-secondary)]">
        <div className="flex items-center gap-3">
          <div
            className={`w-2 h-2 rounded-full ${
              isConnected ? "bg-[var(--success)]" : "bg-[var(--error)]"
            }`}
          />
          <span className="text-sm text-[var(--text-secondary)]">
            {isConnected ? "Connected" : "Disconnected"}
          </span>
        </div>
        <div className="flex items-center gap-3">
          {(usage.inputTokens > 0 || usage.outputTokens > 0) && (
            <div
              className="flex items-center gap-2 text-xs text-[var(--text-muted)] font-mono"
              title={`Tokens used in this chat. Model: ${usage.model ?? "—"}. Cost is estimated.`}
            >
              <span>
                {usage.inputTokens.toLocaleString()} in / {usage.outputTokens.toLocaleString()} out
              </span>
              {usage.model && (
                <span className="opacity-75">· {usage.model}</span>
              )}
              {estimatedCost != null && (
                <span className="text-[var(--text-secondary)]">
                  {formatUsageCost(estimatedCost)}
                </span>
              )}
            </div>
          )}
          {readyForPaperTradingCount > 0 && (
            <div
              className="flex items-center gap-1.5 text-xs text-[var(--success)]"
              title="Only these strategy version(s) have passed reproducibility and quiz; only they can be paper traded."
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
              </svg>
              <span>{readyForPaperTradingCount} version{readyForPaperTradingCount !== 1 ? "s" : ""} ready to paper trade</span>
            </div>
          )}
          {onOpenChart && (
            <button
              onClick={() => hasChartData && onOpenChart()}
              disabled={!hasChartData}
              title={hasChartData ? "View chart" : "Run a backtest to see the chart"}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                hasChartData
                  ? "bg-[var(--accent)] text-white hover:bg-[var(--accent-hover)] cursor-pointer"
                  : "bg-[var(--bg-tertiary)] text-[var(--text-muted)] cursor-not-allowed opacity-50"
              }`}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M3 3v18h18" />
                <path d="M7 16l4-8 4 4 4-6" />
              </svg>
              Chart
            </button>
          )}
          {sessionDateRange && (
            <span className="text-xs text-[var(--text-muted)]" title="Date range for this conversation">
              {sessionDateRange.start_date} → {sessionDateRange.end_date}
            </span>
          )}
          <span className="text-xs text-[var(--text-muted)] font-mono">
            {sessionId.slice(0, 8)}
          </span>
        </div>
      </header>

      {/* Date range picker (after first command when session has no dates) */}
      {showDateRangePicker && (
        <div className="flex-shrink-0 border-b border-[var(--border)] bg-[var(--bg-primary)] px-6 py-4">
          <DateRangePicker
            message={dateRangeMessage}
            suggestedStartDate={dateRangeSuggestedStart}
            suggestedEndDate={dateRangeSuggestedEnd}
            onConfirm={sendDateRange}
            onDismiss={dismissDateRangePicker}
          />
        </div>
      )}

      {/* Messages area */}
      <div className="flex-1 overflow-y-auto">
        {messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-center px-8">
            <div className="text-4xl mb-4 opacity-20">&#x1F4C8;</div>
            <h2 className="text-xl font-semibold text-[var(--text-secondary)] mb-2">
              Backtester Agent
            </h2>
            <p className="text-sm text-[var(--text-muted)] max-w-md leading-relaxed">
              Describe a trading strategy in plain English and I&apos;ll backtest it
              for you. Try something like:
            </p>
            <div className="mt-4 space-y-2">
              {[
                "Backtest RSI crossover on AAPL for 2024",
                "Buy when MACD crosses above signal line, sell on cross below. Use TSLA 2023-2024",
                "Test a Bollinger Band mean-reversion strategy on SPY",
              ].map((example) => (
                <button
                  key={example}
                  onClick={() => sendMessage(example)}
                  className="block w-full text-left px-4 py-2.5 rounded-lg border border-[var(--border)] text-sm text-[var(--text-secondary)] hover:border-[var(--accent)] hover:text-[var(--accent)] transition-colors"
                >
                  {example}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <MessageList
            messages={messages}
            sessionId={sessionId}
            versionTags={versionTags}
            versionSources={versionSources}
            onVersionTagged={handleVersionTagged}
          />
        )}
        <div ref={bottomRef} />
      </div>

      {showStrategyFollowUps && (
        <StrategyFollowUpSuggestions
          items={followUpSuggestions}
          onPick={handleSendMessage}
          disabled={isLoading}
        />
      )}

      {/* Input */}
      <ChatInput
        sessionId={sessionId}
        latestStrategyCode={latestStrategyCode}
        sessionDateRange={sessionDateRange}
        llmModelOptions={llmModelOptions}
        llmModelId={llmModelId}
        onLlmModelChange={handleLlmModelChange}
        onSend={handleSendMessage}
        isLoading={isLoading}
        hasSuccessfulRun={hasSuccessfulRun}
        onRerunTicker={rerunOnTicker}
        onBatchRerunConfirm={handleBatchRerunConfirm}
        onBatchRerunOpenRequest={handleBatchRerunOpenRequest}
        activeBatchCountry={batchJob?.country ?? storedBatchCountry}
        inputDisabled={hasUntaggedVersion}
        inputDisabledReason="Name the strategy version above before continuing."
        chatBaseVersionId={chatBaseVersionId}
        chatBaseVersionLabel={chatBaseVersionLabel}
        onClearChatBase={handleClearChatBase}
      />

      {/* Batch rerun progress modal (runs in background; persists when user switches chat) */}
      {batchJob && (
        <BatchProgressModal
          sessionId={sessionId}
          jobId={batchJob.jobId}
          country={batchJob.country}
          onCompanyClick={handleBatchCompanyClick}
          onClose={handleBatchModalClose}
        />
      )}
    </div>
  );
}

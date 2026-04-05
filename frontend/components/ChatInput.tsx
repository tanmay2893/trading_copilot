"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import { fetchTickers, type Ticker } from "@/lib/api";
import { ParameterModal } from "./ParameterModal";
import { ComplianceModal } from "./ComplianceModal";

interface ChatInputProps {
  onSend: (message: string) => void;
  isLoading: boolean;
  hasSuccessfulRun?: boolean;
  sessionId?: string;
  /** Latest strategy code from chat (last code block). When provided, rerun param modal uses it for "Latest" so params match what user sees. */
  latestStrategyCode?: string | null;
  /** Session date range (initial run). Used as default start/end in rerun modal. */
  sessionDateRange?: { start_date: string; end_date: string } | null;
  onRerunTicker?: (
    ticker: string,
    paramOverrides?: Record<string, string>,
    versionId?: string | null,
    startDate?: string,
    endDate?: string
  ) => void;
  /** Called when user confirms batch rerun (all Indian or all US stocks) with params. Parent starts job and shows progress modal. */
  onBatchRerunConfirm?: (
    country: "US" | "INDIA",
    paramOverrides: Record<string, string> | undefined,
    versionId: string | null | undefined,
    startDate: string | undefined,
    endDate: string | undefined
  ) => void;
  /** When user clicks "Rerun on all Indian/US stocks", parent tries to reopen existing batch for that country. Returns true if modal was reopened, false to show param modal. */
  onBatchRerunOpenRequest?: (country: "US" | "INDIA") => Promise<boolean>;
  /** When set, only this country's batch button is active (reopen); the other is disabled. */
  activeBatchCountry?: "US" | "INDIA" | null;
  /** When true, send is disabled (e.g. until user tags the latest strategy version). */
  inputDisabled?: boolean;
  /** Shown when inputDisabled is true. */
  inputDisabledReason?: string;
  /** Version ID currently in chat (shown as attachment above input). */
  chatBaseVersionId?: string | null;
  /** Label for the version in chat (e.g. tag or date). */
  chatBaseVersionLabel?: string | null;
  /** Called when user clears the chat-base attachment. */
  onClearChatBase?: () => void;
}

export function ChatInput({
  onSend,
  isLoading,
  hasSuccessfulRun,
  sessionId,
  latestStrategyCode,
  sessionDateRange,
  onRerunTicker,
  onBatchRerunConfirm,
  onBatchRerunOpenRequest,
  activeBatchCountry = null,
  inputDisabled = false,
  inputDisabledReason = "Name the strategy version above before continuing.",
  chatBaseVersionId = null,
  chatBaseVersionLabel = null,
  onClearChatBase,
}: ChatInputProps) {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const [showTickerPicker, setShowTickerPicker] = useState(false);
  const [tickerSearch, setTickerSearch] = useState("");
  const [tickers, setTickers] = useState<Ticker[]>([]);
  const [filteredTickers, setFilteredTickers] = useState<Ticker[]>([]);
  const [pendingRerunTicker, setPendingRerunTicker] = useState<Ticker | null>(null);
  const [pendingBatchCountry, setPendingBatchCountry] = useState<"US" | "INDIA" | null>(null);
  const [showComplianceModal, setShowComplianceModal] = useState(false);
  const pickerRef = useRef<HTMLDivElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!showTickerPicker) return;
    fetchTickers()
      .then(setTickers)
      .catch(() => {});
  }, [showTickerPicker]);

  useEffect(() => {
    if (!tickerSearch.trim()) {
      setFilteredTickers(tickers.slice(0, 50));
      return;
    }
    const q = tickerSearch.toLowerCase();
    setFilteredTickers(
      tickers
        .filter((t) => t.symbol.toLowerCase().includes(q) || t.name.toLowerCase().includes(q))
        .slice(0, 50)
    );
  }, [tickerSearch, tickers]);

  useEffect(() => {
    if (showTickerPicker) {
      setTimeout(() => searchInputRef.current?.focus(), 50);
    }
  }, [showTickerPicker]);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (pickerRef.current && !pickerRef.current.contains(e.target as Node)) {
        setShowTickerPicker(false);
        setTickerSearch("");
      }
    }
    if (showTickerPicker) {
      document.addEventListener("mousedown", handleClickOutside);
      return () => document.removeEventListener("mousedown", handleClickOutside);
    }
  }, [showTickerPicker]);

  const handleSelectTicker = (ticker: Ticker) => {
    setShowTickerPicker(false);
    setTickerSearch("");
    if (onRerunTicker && sessionId) {
      setPendingRerunTicker(ticker);
    } else if (onRerunTicker) {
      onRerunTicker(ticker.symbol);
    } else {
      onSend(`Run the same strategy on ${ticker.symbol}`);
    }
  };

  const handleParamModalConfirm = useCallback(
    (
      paramOverrides: Record<string, string>,
      versionId?: string | null,
      startDate?: string,
      endDate?: string
    ) => {
      if (pendingRerunTicker && onRerunTicker) {
        onRerunTicker(
          pendingRerunTicker.symbol,
          Object.keys(paramOverrides).length > 0 ? paramOverrides : undefined,
          versionId,
          startDate,
          endDate
        );
      }
      setPendingRerunTicker(null);
    },
    [pendingRerunTicker, onRerunTicker]
  );

  const handleParamModalCancel = useCallback(() => {
    setPendingRerunTicker(null);
    setPendingBatchCountry(null);
  }, []);

  const handleBatchParamConfirm = useCallback(
    (
      paramOverrides: Record<string, string>,
      versionId?: string | null,
      startDate?: string,
      endDate?: string
    ) => {
      if (pendingBatchCountry && onBatchRerunConfirm) {
        onBatchRerunConfirm(
          pendingBatchCountry,
          Object.keys(paramOverrides || {}).length > 0 ? paramOverrides : undefined,
          versionId,
          startDate,
          endDate
        );
      }
      setPendingBatchCountry(null);
    },
    [pendingBatchCountry, onBatchRerunConfirm]
  );

  const handleSubmit = useCallback(() => {
    const trimmed = value.trim();
    if (!trimmed || isLoading) return;
    onSend(trimmed);
    setValue("");
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  }, [value, isLoading, onSend]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleInput = () => {
    const el = textareaRef.current;
    if (el) {
      el.style.height = "auto";
      el.style.height = Math.min(el.scrollHeight, 200) + "px";
    }
  };

  return (
    <div className="flex-shrink-0 border-t border-[var(--border)] bg-[var(--bg-secondary)] px-4 py-3">
      <div className="max-w-3xl mx-auto">
        {/* Quick actions row */}
        {hasSuccessfulRun && !isLoading && (
          <div className="flex items-center gap-2 mb-2 relative" ref={pickerRef}>
            <button
              onClick={() => setShowTickerPicker(!showTickerPicker)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border border-[var(--border)] text-[var(--text-secondary)] hover:border-[var(--accent)] hover:text-[var(--accent)] transition-colors"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
                <circle cx="9" cy="7" r="4" />
                <line x1="19" y1="8" x2="19" y2="14" />
                <line x1="22" y1="11" x2="16" y2="11" />
              </svg>
              Run on other stocks
            </button>
            <button
              onClick={() => sessionId && setShowComplianceModal(true)}
              disabled={!sessionId}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border border-[var(--border)] text-[var(--text-secondary)] hover:border-[var(--accent)] hover:text-[var(--accent)] transition-colors"
              title="Complete reproducibility check and understanding quiz before paper trading"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
              </svg>
              Prepare for paper trade
            </button>
            {onBatchRerunConfirm && sessionId && (
              <>
                <button
                  onClick={async () => {
                    if (onBatchRerunOpenRequest) {
                      const reopened = await onBatchRerunOpenRequest("INDIA");
                      if (reopened) return;
                    }
                    setPendingBatchCountry("INDIA");
                  }}
                  disabled={activeBatchCountry === "US"}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border border-[var(--border)] text-[var(--text-secondary)] hover:border-[var(--accent)] hover:text-[var(--accent)] transition-colors disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:border-[var(--border)] disabled:hover:text-[var(--text-secondary)]"
                  title={
                    activeBatchCountry === "US"
                      ? "A US batch is running or reopenable. Close or finish it first."
                      : activeBatchCountry === "INDIA"
                        ? "Reopen Indian batch"
                        : "Rerun same strategy on all Indian stocks (parameters, date, code version)"
                  }
                >
                  Rerun on all Indian stocks
                </button>
                <button
                  onClick={async () => {
                    if (onBatchRerunOpenRequest) {
                      const reopened = await onBatchRerunOpenRequest("US");
                      if (reopened) return;
                    }
                    setPendingBatchCountry("US");
                  }}
                  disabled={activeBatchCountry === "INDIA"}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border border-[var(--border)] text-[var(--text-secondary)] hover:border-[var(--accent)] hover:text-[var(--accent)] transition-colors disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:border-[var(--border)] disabled:hover:text-[var(--text-secondary)]"
                  title={
                    activeBatchCountry === "INDIA"
                      ? "An Indian batch is running or reopenable. Close or finish it first."
                      : activeBatchCountry === "US"
                        ? "Reopen US batch"
                        : "Rerun same strategy on all US stocks (parameters, date, code version)"
                  }
                >
                  Rerun on all US stocks
                </button>
              </>
            )}

            {showTickerPicker && (
              <div className="absolute bottom-full left-0 mb-2 w-80 bg-[var(--bg-secondary)] border border-[var(--border)] rounded-xl shadow-2xl z-50 overflow-hidden">
                <div className="p-3 border-b border-[var(--border)]">
                  <input
                    ref={searchInputRef}
                    type="text"
                    value={tickerSearch}
                    onChange={(e) => setTickerSearch(e.target.value)}
                    placeholder="Search ticker or company..."
                    className="w-full bg-[var(--bg-tertiary)] border border-[var(--border)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--accent)]"
                  />
                </div>
                <div className="max-h-64 overflow-y-auto">
                  {filteredTickers.length === 0 ? (
                    <div className="px-4 py-6 text-center text-sm text-[var(--text-muted)]">
                      {tickers.length === 0 ? "Loading tickers..." : "No matches found"}
                    </div>
                  ) : (
                    filteredTickers.map((t) => (
                      <button
                        key={`${t.country ?? "US"}-${t.symbol}`}
                        onClick={() => handleSelectTicker(t)}
                        className="w-full text-left px-4 py-2.5 flex items-center gap-3 hover:bg-[var(--bg-tertiary)] transition-colors border-b border-[var(--border)] last:border-b-0"
                      >
                        <span className="font-mono text-sm font-semibold text-[var(--accent)] w-16 flex-shrink-0">
                          {t.symbol}
                        </span>
                        <span className="text-xs text-[var(--text-secondary)] truncate">
                          {t.country === "INDIA" ? "(INDIA) " : "(US) "}
                          {t.name}
                        </span>
                      </button>
                    ))
                  )}
                </div>
              </div>
            )}
          </div>
        )}

        {((pendingRerunTicker || pendingBatchCountry) && sessionId) && (
          <ParameterModal
            sessionId={sessionId}
            ticker={
              pendingRerunTicker
                ? { symbol: pendingRerunTicker.symbol, name: pendingRerunTicker.name, country: pendingRerunTicker.country }
                : {
                    symbol: "ALL",
                    name: `All ${pendingBatchCountry === "INDIA" ? "Indian" : "US"} stocks`,
                    country: pendingBatchCountry ?? "US",
                  }
            }
            latestStrategyCode={latestStrategyCode ?? undefined}
            defaultStartDate={sessionDateRange?.start_date ?? ""}
            defaultEndDate={sessionDateRange?.end_date ?? ""}
            onConfirm={
              pendingRerunTicker
                ? handleParamModalConfirm
                : handleBatchParamConfirm
            }
            onCancel={handleParamModalCancel}
          />
        )}

        {showComplianceModal && sessionId && (
          <ComplianceModal sessionId={sessionId} onClose={() => setShowComplianceModal(false)} />
        )}

        {chatBaseVersionId && (
          <div className="flex items-center gap-2 mb-2 flex-wrap">
            <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-[var(--bg-tertiary)] border border-[var(--border)] text-[var(--text-secondary)]">
              <span className="truncate max-w-[12rem]" title={chatBaseVersionLabel ?? undefined}>
                Strategy: {chatBaseVersionLabel ?? chatBaseVersionId}
              </span>
              {onClearChatBase && (
                <button
                  type="button"
                  onClick={onClearChatBase}
                  className="flex-shrink-0 p-0.5 rounded hover:bg-[var(--bg-primary)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
                  aria-label="Remove from chat"
                  title="Remove strategy from chat"
                >
                  <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M18 6L6 18M6 6l12 12" />
                  </svg>
                </button>
              )}
            </span>
          </div>
        )}

        {inputDisabled && inputDisabledReason && (
          <p className="text-xs text-amber-600 dark:text-amber-400 mb-1">
            {inputDisabledReason}
          </p>
        )}
        {/* Input row */}
        <div className="flex items-end gap-3">
          <textarea
            ref={textareaRef}
            value={value}
            onChange={(e) => { setValue(e.target.value); handleInput(); }}
            onKeyDown={handleKeyDown}
            placeholder={
              inputDisabled
                ? "Tag the version above first..."
                : isLoading
                  ? "Agent is working..."
                  : "Describe a strategy or ask a question..."
            }
            disabled={isLoading || inputDisabled}
            rows={1}
            className="flex-1 resize-none bg-[var(--bg-tertiary)] border border-[var(--border)] rounded-xl px-4 py-3 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--accent)] transition-colors disabled:opacity-50"
          />
          <button
            onClick={handleSubmit}
            disabled={!value.trim() || isLoading || inputDisabled}
            className="flex-shrink-0 w-10 h-10 rounded-xl bg-[var(--accent)] text-white flex items-center justify-center hover:bg-[var(--accent-hover)] transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
          >
            {isLoading ? (
              <svg className="animate-spin w-4 h-4" viewBox="0 0 24 24" fill="none">
                <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" strokeDasharray="31.4 31.4" strokeLinecap="round" />
              </svg>
            ) : (
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <line x1="22" y1="2" x2="11" y2="13" />
                <polygon points="22 2 15 22 11 13 2 9 22 2" />
              </svg>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}

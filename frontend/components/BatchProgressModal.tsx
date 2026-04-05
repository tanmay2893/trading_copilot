"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  cancelBatchRerun,
  getBatchRerunStatus,
  type BatchRerunResult,
  type BatchRerunStatus,
} from "@/lib/api";

const POLL_INTERVAL_MS = 2000;

export type BatchTableSortKey = "company" | "profit_factor" | "risk_reward" | "max_loss_pct";

export interface BatchProgressModalProps {
  sessionId: string;
  jobId: string;
  country: "US" | "INDIA";
  onCompanyClick: (symbol: string) => void;
  onClose: (finalStatus?: string) => void;
}

function formatMetric(value: number | null | undefined): string {
  if (value == null) return "—";
  if (typeof value === "number" && !Number.isFinite(value)) return "∞";
  return typeof value === "number" ? value.toFixed(2) : "—";
}

function formatPct(value: number | null | undefined): string {
  if (value == null) return "—";
  if (typeof value === "number" && !Number.isFinite(value)) return "—";
  return typeof value === "number" ? `${value.toFixed(2)}%` : "—";
}

export function BatchProgressModal({
  sessionId,
  jobId,
  country,
  onCompanyClick,
  onClose,
}: BatchProgressModalProps) {
  const [status, setStatus] = useState<BatchRerunStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<BatchTableSortKey>("company");
  const [sortAsc, setSortAsc] = useState(true);
  const [stopping, setStopping] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const mountedRef = useRef(true);

  const poll = useCallback(() => {
    if (!mountedRef.current) return;
    getBatchRerunStatus(sessionId, jobId)
      .then((data) => {
        if (!mountedRef.current) return;
        setStatus(data);
        setError(null);
        if (data.status !== "running") {
          if (pollRef.current) {
            clearInterval(pollRef.current);
            pollRef.current = null;
          }
        }
      })
      .catch((err) => {
        if (mountedRef.current) setError(err instanceof Error ? err.message : "Failed to fetch status");
      });
  }, [sessionId, jobId]);

  useEffect(() => {
    mountedRef.current = true;
    poll();
    pollRef.current = setInterval(poll, POLL_INTERVAL_MS);
    return () => {
      mountedRef.current = false;
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [poll]);

  const isRunning = status?.status === "running";
  const isCancelled = status?.status === "cancelled";
  const total = status?.total ?? 0;

  const handleStop = useCallback(() => {
    if (!isRunning || stopping) return;
    setStopping(true);
    cancelBatchRerun(sessionId, jobId).then(() => {
      setStopping(false);
      poll();
    }).catch(() => setStopping(false));
  }, [sessionId, jobId, isRunning, stopping, poll]);
  const completed = status?.completed ?? 0;
  const rawResults = status?.results ?? [];

  const sortedResults = useMemo(() => {
    const rows = [...rawResults];
    rows.sort((a, b) => {
      let va: string | number | null;
      let vb: string | number | null;
      switch (sortKey) {
        case "company":
          va = `${a.name} ${a.ticker}`.toLowerCase();
          vb = `${b.name} ${b.ticker}`.toLowerCase();
          break;
        case "profit_factor":
          va = a.profit_factor;
          vb = b.profit_factor;
          break;
        case "risk_reward":
          va = a.risk_reward;
          vb = b.risk_reward;
          break;
        case "max_loss_pct":
          va = a.max_loss_pct;
          vb = b.max_loss_pct;
          break;
        default:
          return 0;
      }
      const nullsLast = (x: string | number | null, y: string | number | null) => {
        const xNull = x == null;
        const yNull = y == null;
        if (xNull && yNull) return 0;
        if (xNull) return 1;
        if (yNull) return -1;
        return 0;
      };
      const cmp = nullsLast(va, vb);
      if (cmp !== 0) return sortAsc ? cmp : -cmp;
      if (va == null || vb == null) return 0;
      let out = 0;
      if (typeof va === "string" && typeof vb === "string") out = va.localeCompare(vb);
      else if (typeof va === "number" && typeof vb === "number") out = va < vb ? -1 : va > vb ? 1 : 0;
      return sortAsc ? out : -out;
    });
    return rows;
  }, [rawResults, sortKey, sortAsc]);

  const handleSort = useCallback((key: BatchTableSortKey) => {
    setSortKey((prev) => {
      if (prev === key) {
        setSortAsc((a) => !a);
        return prev;
      }
      setSortAsc(true);
      return key;
    });
  }, []);

  const progressPct = total > 0 ? Math.round((completed / total) * 100) : 0;

  const SortIcon = ({ column }: { column: BatchTableSortKey }) => {
    if (sortKey !== column) return <span className="opacity-30 ml-0.5">↕</span>;
    return <span className="ml-0.5">{sortAsc ? "↑" : "↓"}</span>;
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      role="dialog"
      aria-modal="true"
      aria-labelledby="batch-modal-title"
    >
      <div className="w-full max-w-3xl max-h-[85vh] rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] shadow-2xl flex flex-col overflow-hidden">
        <div className="px-5 py-4 border-b border-[var(--border)] flex items-center justify-between flex-shrink-0">
          <div>
            <h2 id="batch-modal-title" className="text-base font-semibold text-[var(--text-primary)]">
              Rerun on all {country === "INDIA" ? "Indian" : "US"} stocks
            </h2>
            <p className="text-xs text-[var(--text-muted)] mt-0.5">
            {isRunning
              ? `Running… ${completed} of ${total} completed`
              : isCancelled
                ? `Stopped: ${completed} of ${total} processed`
                : status?.status === "done"
                  ? `Completed: ${completed} of ${total}`
                  : status?.status === "failed"
                    ? "Job failed"
                    : "Loading…"}
            </p>
          </div>
          <button
            type="button"
            onClick={() => onClose(status?.status)}
            className="p-2 rounded-lg text-[var(--text-muted)] hover:bg-[var(--bg-tertiary)] hover:text-[var(--text-primary)] transition-colors"
            aria-label="Close"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        {/* Progress bar */}
        <div className="px-5 py-3 border-b border-[var(--border)] flex-shrink-0">
          <div className="h-2 w-full bg-[var(--bg-tertiary)] rounded-full overflow-hidden">
            <div
              className="h-full bg-[var(--accent)] transition-all duration-300"
              style={{ width: `${progressPct}%` }}
            />
          </div>
        </div>

        {error && (
          <div className="px-5 py-2 text-sm text-[var(--error)] flex-shrink-0">
            {error}
          </div>
        )}

        {/* Table */}
        <div className="flex-1 overflow-auto min-h-0">
          <table className="w-full text-sm border-collapse">
            <thead className="sticky top-0 bg-[var(--bg-secondary)] border-b border-[var(--border)] z-10">
              <tr>
                <th className="text-left py-3 px-4 font-medium text-[var(--text-secondary)]">
                  <button
                    type="button"
                    onClick={() => handleSort("company")}
                    className="flex items-center hover:text-[var(--text-primary)] transition-colors"
                  >
                    Company
                    <SortIcon column="company" />
                  </button>
                </th>
                <th className="text-right py-3 px-4 font-medium text-[var(--text-secondary)]">
                  <button
                    type="button"
                    onClick={() => handleSort("profit_factor")}
                    className="inline-flex items-center justify-end w-full hover:text-[var(--text-primary)] transition-colors"
                  >
                    Profit factor
                    <SortIcon column="profit_factor" />
                  </button>
                </th>
                <th className="text-right py-3 px-4 font-medium text-[var(--text-secondary)]">
                  <button
                    type="button"
                    onClick={() => handleSort("risk_reward")}
                    className="inline-flex items-center justify-end w-full hover:text-[var(--text-primary)] transition-colors"
                  >
                    Risk/Reward
                    <SortIcon column="risk_reward" />
                  </button>
                </th>
                <th className="text-right py-3 px-4 font-medium text-[var(--text-secondary)]">
                  <button
                    type="button"
                    onClick={() => handleSort("max_loss_pct")}
                    className="inline-flex items-center justify-end w-full hover:text-[var(--text-primary)] transition-colors"
                  >
                    Max loss %
                    <SortIcon column="max_loss_pct" />
                  </button>
                </th>
              </tr>
            </thead>
            <tbody>
              {sortedResults.map((row: BatchRerunResult, idx: number) => (
                <tr
                  key={`${row.ticker}-${idx}`}
                  className="border-b border-[var(--border)] last:border-b-0 hover:bg-[var(--bg-tertiary)]"
                >
                  <td className="py-2.5 px-4">
                    <button
                      type="button"
                      onClick={() => onCompanyClick(row.ticker)}
                      className="text-left font-medium text-[var(--accent)] hover:underline cursor-pointer"
                    >
                      {row.name} ({row.ticker})
                    </button>
                  </td>
                  <td className="text-right py-2.5 px-4 tabular-nums text-[var(--text-primary)]">
                    {formatMetric(row.profit_factor)}
                  </td>
                  <td className="text-right py-2.5 px-4 tabular-nums text-[var(--text-primary)]">
                    {formatMetric(row.risk_reward)}
                  </td>
                  <td className="text-right py-2.5 px-4 tabular-nums text-[var(--text-primary)]">
                    {formatPct(row.max_loss_pct)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {sortedResults.length === 0 && !error && (
            <div className="px-5 py-8 text-center text-[var(--text-muted)]">
              {isRunning ? "Processing first companies…" : "No results yet."}
            </div>
          )}
        </div>

        <div className="px-5 py-4 border-t border-[var(--border)] flex justify-end gap-2 flex-shrink-0">
          {isRunning && (
            <button
              type="button"
              onClick={handleStop}
              disabled={stopping}
              className="px-4 py-2 rounded-lg text-sm font-medium border border-[var(--error)] text-[var(--error)] hover:bg-[var(--error)]/10 transition-colors disabled:opacity-50"
            >
              {stopping ? "Stopping…" : "Stop processing"}
            </button>
          )}
          <button
            type="button"
            onClick={() => onClose(status?.status)}
            className="px-4 py-2 rounded-lg text-sm font-medium bg-[var(--accent)] text-white hover:bg-[var(--accent-hover)]"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

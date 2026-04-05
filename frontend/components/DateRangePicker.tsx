"use client";

import { useState } from "react";

const DEFAULT_START = "2020-01-01";
const DEFAULT_END = "2025-01-01";

function getDefaultEnd(): string {
  const today = new Date();
  return today.toISOString().slice(0, 10);
}

function coercePickerDate(value: string | null | undefined, fallback: string): string {
  const s = (value || "").trim().slice(0, 10);
  return /^\d{4}-\d{2}-\d{2}$/.test(s) ? s : fallback;
}

interface DateRangePickerProps {
  message: string;
  /** When set (YYYY-MM-DD), pre-fills start; otherwise 2020-01-01. */
  suggestedStartDate?: string | null;
  suggestedEndDate?: string | null;
  onConfirm: (startDate: string, endDate: string) => void;
  onDismiss?: () => void;
}

export function DateRangePicker({
  message,
  suggestedStartDate,
  suggestedEndDate,
  onConfirm,
  onDismiss,
}: DateRangePickerProps) {
  let initialStart = coercePickerDate(suggestedStartDate, DEFAULT_START);
  let initialEnd = coercePickerDate(suggestedEndDate, getDefaultEnd());
  if (initialStart > initialEnd) {
    const t = initialStart;
    initialStart = initialEnd;
    initialEnd = t;
  }
  const [startDate, setStartDate] = useState(initialStart);
  const [endDate, setEndDate] = useState(initialEnd);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const s = startDate.trim();
    const e_ = endDate.trim();
    if (!s || !e_) return;
    if (new Date(s) > new Date(e_)) {
      setEndDate(s);
      onConfirm(s, s);
    } else {
      onConfirm(s, e_);
    }
  };

  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] p-5 shadow-lg">
      <p className="text-sm text-[var(--text-secondary)] mb-4">{message}</p>
      <p className="text-xs text-[var(--text-muted)] mb-4">
        These dates will be used for all backtests in this conversation.
      </p>
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label htmlFor="start-date" className="block text-xs font-medium text-[var(--text-muted)] mb-1.5">
              Start date
            </label>
            <input
              id="start-date"
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className="w-full px-3 py-2 rounded-lg border border-[var(--border)] bg-[var(--bg-primary)] text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
              max={endDate}
            />
          </div>
          <div>
            <label htmlFor="end-date" className="block text-xs font-medium text-[var(--text-muted)] mb-1.5">
              End date
            </label>
            <input
              id="end-date"
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              min={startDate}
              className="w-full px-3 py-2 rounded-lg border border-[var(--border)] bg-[var(--bg-primary)] text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-transparent"
            />
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="submit"
            className="px-4 py-2 rounded-lg bg-[var(--accent)] text-white text-sm font-medium hover:bg-[var(--accent-hover)] transition-colors"
          >
            Confirm dates
          </button>
          {onDismiss && (
            <button
              type="button"
              onClick={onDismiss}
              className="px-4 py-2 rounded-lg border border-[var(--border)] text-[var(--text-secondary)] text-sm hover:bg-[var(--bg-tertiary)] transition-colors"
            >
              Cancel
            </button>
          )}
        </div>
      </form>
    </div>
  );
}

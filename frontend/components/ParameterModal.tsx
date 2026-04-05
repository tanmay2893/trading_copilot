"use client";

import { useCallback, useEffect, useState } from "react";
import {
  fetchCodeVersions,
  fetchRunParameters,
  type CodeVersionOption,
  type RunParameter,
} from "@/lib/api";

export interface TickerOption {
  symbol: string;
  name: string;
  country?: "US" | "INDIA";
}

interface ParameterModalProps {
  sessionId: string;
  ticker: TickerOption;
  /** Unused when using GET-only for params; kept for API compatibility. */
  latestStrategyCode?: string;
  /** Default date range for this rerun (same as initial run). */
  defaultStartDate?: string;
  defaultEndDate?: string;
  onConfirm: (
    paramOverrides: Record<string, string>,
    versionId?: string | null,
    startDate?: string,
    endDate?: string
  ) => void;
  onCancel: () => void;
}

export function ParameterModal({
  sessionId,
  ticker,
  defaultStartDate = "",
  defaultEndDate = "",
  onConfirm,
  onCancel,
}: ParameterModalProps) {
  const [versions, setVersions] = useState<CodeVersionOption[]>([]);
  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(null);
  const [parameters, setParameters] = useState<RunParameter[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [startDate, setStartDate] = useState(defaultStartDate);
  const [endDate, setEndDate] = useState(defaultEndDate);

  useEffect(() => {
    setStartDate(defaultStartDate);
    setEndDate(defaultEndDate);
  }, [defaultStartDate, defaultEndDate]);

  // Load code versions when modal opens
  useEffect(() => {
    let cancelled = false;
    fetchCodeVersions(sessionId)
      .then((data) => {
        if (cancelled) return;
        setVersions(data.versions || []);
        setSelectedVersionId(null);
      })
      .catch(() => {
        if (!cancelled) setVersions([{ version_id: null, label: "Latest (current)" }]);
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  // Load parameters when version selection changes (null = latest). Use GET only so proxies/rewrites (e.g. ngrok) don't return 405; backend uses in-memory session for latest code.
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchRunParameters(sessionId, selectedVersionId ?? undefined)
      .then((data) => {
        if (cancelled) return;
        const params = data.parameters || [];
        setParameters(params);
        const initial: Record<string, string> = {};
        params.forEach((p) => {
          initial[p.name] = String(p.value ?? "");
        });
        setValues(initial);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load parameters");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId, selectedVersionId]);

  const setParam = useCallback((name: string, value: string) => {
    setValues((prev) => ({ ...prev, [name]: value }));
  }, []);

  const handleSubmit = useCallback(() => {
    const overrides: Record<string, string> = {};
    parameters.forEach((p) => {
      const current = values[p.name];
      if (current !== undefined && String(p.value) !== current) {
        overrides[p.name] = current;
      }
    });
    onConfirm(
      overrides,
      selectedVersionId ?? undefined,
      startDate.trim() || undefined,
      endDate.trim() || undefined
    );
  }, [parameters, values, onConfirm, selectedVersionId, startDate, endDate]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      role="dialog"
      aria-modal="true"
      aria-labelledby="param-modal-title"
    >
      <div className="w-full max-w-md rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] shadow-2xl overflow-hidden">
        <div className="px-5 py-4 border-b border-[var(--border)]">
          <h2 id="param-modal-title" className="text-base font-semibold text-[var(--text-primary)]">
            Run strategy on {ticker.symbol === "ALL" ? ticker.name : ticker.symbol}
          </h2>
          <p className="text-xs text-[var(--text-muted)] mt-0.5 truncate" title={ticker.name}>
            {ticker.country === "INDIA" ? "(INDIA) " : "(US) "}
            {ticker.name}
          </p>
        </div>

        <div className="px-5 py-4 max-h-80 overflow-y-auto">
          <div className="mb-4 grid grid-cols-2 gap-3">
            <div>
              <label
                htmlFor="rerun-start-date"
                className="block text-xs font-medium text-[var(--text-secondary)] mb-1.5"
              >
                Start date
              </label>
              <input
                id="rerun-start-date"
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
                className="w-full bg-[var(--bg-tertiary)] border border-[var(--border)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
              />
            </div>
            <div>
              <label
                htmlFor="rerun-end-date"
                className="block text-xs font-medium text-[var(--text-secondary)] mb-1.5"
              >
                End date
              </label>
              <input
                id="rerun-end-date"
                type="date"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
                className="w-full bg-[var(--bg-tertiary)] border border-[var(--border)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
              />
            </div>
          </div>
          {versions.length > 1 && (
            <div className="mb-4">
              <label htmlFor="code-version" className="block text-xs font-medium text-[var(--text-secondary)] mb-1.5">
                Code version
              </label>
              <select
                id="code-version"
                value={selectedVersionId ?? ""}
                onChange={(e) => setSelectedVersionId(e.target.value === "" ? null : e.target.value)}
                className="w-full bg-[var(--bg-tertiary)] border border-[var(--border)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
              >
                {versions.map((v) => (
                  <option key={v.version_id ?? "latest"} value={v.version_id ?? ""}>
                    {v.label}
                  </option>
                ))}
              </select>
            </div>
          )}
          {loading && (
            <p className="text-sm text-[var(--text-muted)]">Loading parameters…</p>
          )}
          {error && (
            <p className="text-sm text-[var(--error)]">{error}</p>
          )}
          {!loading && !error && parameters.length === 0 && (
            <p className="text-sm text-[var(--text-muted)]">
              No tunable parameters. Click OK to run with default settings.
            </p>
          )}
          {!loading && !error && parameters.length > 0 && (
            <div className="space-y-3">
              <p className="text-xs text-[var(--text-muted)] mb-2">
                Edit values to override defaults for this run.
              </p>
              {parameters.map((p) => (
                <div key={p.name} className="flex flex-col gap-1">
                  <label
                    htmlFor={`param-${p.name}`}
                    className="text-xs font-medium text-[var(--text-secondary)]"
                  >
                    {p.name}
                    {p.description && (
                      <span className="font-normal text-[var(--text-muted)] ml-1">
                        — {p.description}
                      </span>
                    )}
                  </label>
                  <input
                    id={`param-${p.name}`}
                    type="text"
                    value={values[p.name] ?? ""}
                    onChange={(e) => setParam(p.name, e.target.value)}
                    className="w-full bg-[var(--bg-tertiary)] border border-[var(--border)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--accent)]"
                    placeholder={String(p.value)}
                  />
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="px-5 py-4 border-t border-[var(--border)] flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="px-4 py-2 rounded-lg text-sm font-medium border border-[var(--border)] text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)] transition-colors"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            className="px-4 py-2 rounded-lg text-sm font-medium bg-[var(--accent)] text-white hover:bg-[var(--accent-hover)] transition-colors"
          >
            OK
          </button>
        </div>
      </div>
    </div>
  );
}

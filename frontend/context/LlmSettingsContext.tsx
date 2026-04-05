"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  fetchLlmKeysStatus,
  LLM_KEYS_STORAGE_KEY,
  postGlobalLlmKeys,
  type LlmKeysStatus,
} from "@/lib/api";

type LlmSettingsContextValue = {
  status: LlmKeysStatus | null;
  refreshStatus: () => Promise<void>;
  settingsOpen: boolean;
  openSettings: (reason?: string) => void;
  closeSettings: () => void;
  settingsReason: string | null;
  hasKeysForModel: (model: string) => boolean;
  /** True if the session's model can run using any configured key (same fallback as the API). */
  hasUsableLlmForSession: (model: string) => boolean;
};

const LlmSettingsContext = createContext<LlmSettingsContextValue | null>(null);

export function LlmSettingsProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<LlmKeysStatus | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsReason, setSettingsReason] = useState<string | null>(null);

  const refreshStatus = useCallback(async () => {
    try {
      const s = await fetchLlmKeysStatus();
      setStatus(s);
    } catch {
      setStatus({
        openai_configured: false,
        anthropic_configured: false,
        deepseek_configured: false,
      });
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      await refreshStatus();
      if (cancelled) return;
      let raw: string | null = null;
      try {
        raw = localStorage.getItem(LLM_KEYS_STORAGE_KEY);
      } catch {
        return;
      }
      if (!raw) return;
      try {
        const p = JSON.parse(raw) as { openai?: string; anthropic?: string; deepseek?: string };
        await postGlobalLlmKeys({
          openai_api_key: p.openai ?? "",
          anthropic_api_key: p.anthropic ?? "",
          deepseek_api_key: p.deepseek ?? "",
        });
        if (!cancelled) await refreshStatus();
      } catch {
        /* ignore */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [refreshStatus]);

  const openSettings = useCallback((reason?: string) => {
    setSettingsReason(reason ?? null);
    setSettingsOpen(true);
  }, []);

  const closeSettings = useCallback(() => {
    setSettingsOpen(false);
    setSettingsReason(null);
  }, []);

  const hasKeysForModel = useCallback(
    (model: string) => {
      if (!status) return false;
      const m = model.toLowerCase();
      if (m === "openai") return status.openai_configured;
      if (m === "opus") return status.anthropic_configured;
      if (m === "deepseek") return status.deepseek_configured;
      return false;
    },
    [status]
  );

  const hasUsableLlmForSession = useCallback(
    (model: string) => {
      if (!status) return false;
      const m = model.toLowerCase();
      const chain: ("openai" | "opus" | "deepseek")[] =
        m === "openai"
          ? ["openai", "opus", "deepseek"]
          : m === "opus"
            ? ["opus", "openai", "deepseek"]
            : m === "deepseek"
              ? ["deepseek", "openai", "opus"]
              : [];
      for (const x of chain) {
        if (x === "openai" && status.openai_configured) return true;
        if (x === "opus" && status.anthropic_configured) return true;
        if (x === "deepseek" && status.deepseek_configured) return true;
      }
      return false;
    },
    [status]
  );

  const value = useMemo(
    () => ({
      status,
      refreshStatus,
      settingsOpen,
      openSettings,
      closeSettings,
      settingsReason,
      hasKeysForModel,
      hasUsableLlmForSession,
    }),
    [
      status,
      refreshStatus,
      settingsOpen,
      openSettings,
      closeSettings,
      settingsReason,
      hasKeysForModel,
      hasUsableLlmForSession,
    ]
  );

  return (
    <LlmSettingsContext.Provider value={value}>
      {children}
      <LlmSettingsModal />
    </LlmSettingsContext.Provider>
  );
}

export function useLlmSettings() {
  const ctx = useContext(LlmSettingsContext);
  if (!ctx) {
    throw new Error("useLlmSettings must be used within LlmSettingsProvider");
  }
  return ctx;
}

function LlmSettingsModal() {
  const { settingsOpen, closeSettings, settingsReason, refreshStatus } = useLlmSettings();
  const [openai, setOpenai] = useState("");
  const [anthropic, setAnthropic] = useState("");
  const [deepseek, setDeepseek] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!settingsOpen) return;
    setError(null);
    try {
      const raw = localStorage.getItem(LLM_KEYS_STORAGE_KEY);
      if (raw) {
        const p = JSON.parse(raw) as { openai?: string; anthropic?: string; deepseek?: string };
        setOpenai(p.openai ?? "");
        setAnthropic(p.anthropic ?? "");
        setDeepseek(p.deepseek ?? "");
      } else {
        setOpenai("");
        setAnthropic("");
        setDeepseek("");
      }
    } catch {
      setOpenai("");
      setAnthropic("");
      setDeepseek("");
    }
  }, [settingsOpen]);

  if (!settingsOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const res = await postGlobalLlmKeys({
        openai_api_key: openai,
        anthropic_api_key: anthropic,
        deepseek_api_key: deepseek,
      });
      const failed = [res.openai, res.anthropic, res.deepseek].filter((x) => x.status === "failed");
      if (failed.length > 0) {
        const parts = failed.map((x) => x.error).filter(Boolean);
        setError(parts.join(" · ") || "Verification failed");
        setSubmitting(false);
        return;
      }
      try {
        localStorage.setItem(
          LLM_KEYS_STORAGE_KEY,
          JSON.stringify({ openai, anthropic, deepseek })
        );
      } catch {
        /* ignore */
      }
      await refreshStatus();
      closeSettings();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-[200] flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="llm-settings-title"
      onMouseDown={(ev) => {
        if (ev.target === ev.currentTarget) closeSettings();
      }}
    >
      <div
        className="w-full max-w-lg rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] shadow-xl max-h-[90vh] overflow-y-auto"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="p-5 border-b border-[var(--border)] flex items-start justify-between gap-3">
          <div>
            <h2 id="llm-settings-title" className="text-lg font-semibold text-[var(--text-primary)]">
              Settings — API keys
            </h2>
            <p className="text-sm text-[var(--text-muted)] mt-1">
              Keys are stored in this browser and sent to the running API server (memory only). They apply to all chats.
              The CLI still uses <code className="text-xs opacity-80">.env</code> on your machine.
            </p>
            {settingsReason && (
              <p className="text-sm text-[var(--accent)] mt-2">{settingsReason}</p>
            )}
          </div>
          <button
            type="button"
            onClick={closeSettings}
            className="p-1 rounded-lg hover:bg-[var(--bg-tertiary)] text-[var(--text-muted)]"
            aria-label="Close"
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>
        <form onSubmit={(e) => void handleSubmit(e)} className="p-5 space-y-4">
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-[var(--text-secondary)]">OpenAI</label>
            <input
              type="password"
              autoComplete="off"
              value={openai}
              onChange={(e) => setOpenai(e.target.value)}
              placeholder="sk-… (required for OpenAI / gpt-4o chats)"
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg-primary)] px-3 py-2 text-sm"
            />
          </div>
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-[var(--text-secondary)]">Anthropic</label>
            <input
              type="password"
              autoComplete="off"
              value={anthropic}
              onChange={(e) => setAnthropic(e.target.value)}
              placeholder="sk-ant-… (required for Anthropic / opus)"
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg-primary)] px-3 py-2 text-sm"
            />
          </div>
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-[var(--text-secondary)]">DeepSeek</label>
            <input
              type="password"
              autoComplete="off"
              value={deepseek}
              onChange={(e) => setDeepseek(e.target.value)}
              placeholder="sk-… (if you use deepseek model)"
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg-primary)] px-3 py-2 text-sm"
            />
          </div>
          {error && <p className="text-sm text-[var(--error)]">{error}</p>}
          <div className="flex flex-wrap gap-2 pt-2">
            <button
              type="submit"
              disabled={submitting}
              className="px-4 py-2 rounded-lg text-sm font-medium bg-[var(--accent)] text-white hover:bg-[var(--accent-hover)] disabled:opacity-50"
            >
              {submitting ? "Verifying…" : "Save & verify"}
            </button>
            <button
              type="button"
              onClick={closeSettings}
              className="px-4 py-2 rounded-lg text-sm border border-[var(--border)] text-[var(--text-secondary)]"
            >
              Cancel
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

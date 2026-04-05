"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Chat } from "@/components/Chat";
import { ChartView, type ChartViewHandle } from "@/components/ChartView";
import { Sidebar } from "@/components/Sidebar";
import { StrategyVersionsPanel } from "@/components/StrategyVersionsPanel";
import { LlmSettingsProvider, useLlmSettings } from "@/context/LlmSettingsContext";
import { createSession, deleteSession, fetchSessions } from "@/lib/api";
import type { SessionSummary } from "@/lib/types";

export default function Home() {
  return (
    <LlmSettingsProvider>
      <HomeContent />
    </LlmSettingsProvider>
  );
}

function HomeContent() {
  const { openSettings } = useLlmSettings();
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [activeSession, setActiveSession] = useState<string>("");
  /** Session IDs that have a strategy/refinement/question running (kept mounted in background). */
  const [runningSessionIds, setRunningSessionIds] = useState<string[]>([]);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [view, setView] = useState<"chat" | "chart">("chat");
  const [chartEverOpened, setChartEverOpened] = useState(false);
  const [chartDataVersion, setChartDataVersion] = useState(0);
  const [strategiesPanelOpen, setStrategiesPanelOpen] = useState(true);
  const [strategiesRefreshKey, setStrategiesRefreshKey] = useState(0);
  const chartRef = useRef<ChartViewHandle>(null);
  const openChartOnDoneRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<{ sessionId?: string }>).detail;
      if (!detail?.sessionId || detail.sessionId === activeSession) {
        setStrategiesRefreshKey((k) => k + 1);
      }
    };
    window.addEventListener("strategy-versions-changed", handler);
    return () => window.removeEventListener("strategy-versions-changed", handler);
  }, [activeSession]);

  const handleLoadingChange = useCallback((sessionId: string, loading: boolean) => {
    setRunningSessionIds((prev) =>
      loading
        ? prev.includes(sessionId)
          ? prev
          : [...prev, sessionId]
        : prev.filter((id) => id !== sessionId)
    );
  }, []);

  /** Sessions to keep mounted: active + any that are still running (so they keep receiving responses). */
  const sessionIdsToMount = useMemo(
    () => Array.from(new Set([activeSession, ...runningSessionIds].filter(Boolean))),
    [activeSession, runningSessionIds]
  );

  useEffect(() => {
    fetchSessions()
      .then(setSessions)
      .catch(() => {});
  }, []);

  useEffect(() => {
    const handler = () => {
      fetchSessions()
        .then(setSessions)
        .catch(() => {});
    };
    window.addEventListener("backtester:sessions-updated", handler as EventListener);
    return () => window.removeEventListener("backtester:sessions-updated", handler as EventListener);
  }, []);

  // Refetch sessions when tab becomes visible so titles stay in sync
  useEffect(() => {
    const onVisibility = () => {
      if (document.visibilityState === "visible") {
        fetchSessions().then(setSessions).catch(() => {});
      }
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, []);

  const handleNewSession = async () => {
    const useLocalFallback = () => {
      const id = `local-${Date.now().toString(36)}`;
      setActiveSession(id);
      setView("chat");
      setChartEverOpened(false);
    };
    try {
      const { session_id } = await createSession("openai");
      if (typeof session_id !== "string" || !session_id) {
        useLocalFallback();
        return;
      }
      setActiveSession(session_id);
      setView("chat");
      setChartEverOpened(false);
      // Do not block UI on session list refresh (can hang on flaky tunnels).
      void fetchSessions().then(setSessions).catch(() => {});
    } catch {
      useLocalFallback();
    }
  };

  const handleSelectSession = (id: string) => {
    setActiveSession(id);
    setView("chat");
    setChartEverOpened(false);
  };

  const handleDeleteSession = async (id: string) => {
    try {
      await deleteSession(id);
      setSessions((prev) => prev.filter((s) => s.session_id !== id));
      if (activeSession === id) {
        const remaining = sessions.filter((s) => s.session_id !== id);
        if (remaining.length > 0) {
          setActiveSession(remaining[0].session_id);
        } else {
          setActiveSession("");
          handleNewSession();
        }
      }
    } catch {
      // Optionally show toast or error state
    }
  };

  useEffect(() => {
    if (activeSession) return;
    const timeoutId = setTimeout(() => {
      setActiveSession((current) => current || `local-${Date.now().toString(36)}`);
    }, 2500);
    handleNewSession().finally(() => clearTimeout(timeoutId));
    return () => clearTimeout(timeoutId);
  }, []);

  return (
    <div className="flex h-screen overflow-hidden">
      {sidebarOpen && view === "chat" && (
        <Sidebar
          sessions={[...sessions]
            .filter((s) => s.messages > 0 || s.runs > 0 || (s.title != null && String(s.title).trim().length > 0))
            .sort((a, b) => (b.updated_at || "").localeCompare(a.updated_at || "", undefined, { numeric: true }))}
          activeSession={activeSession}
          runningSessionIds={runningSessionIds}
          onSelect={handleSelectSession}
          onNew={handleNewSession}
          onClose={() => setSidebarOpen(false)}
          onDelete={handleDeleteSession}
          onOpenSettings={() => openSettings()}
        />
      )}
      <main className="flex-1 flex flex-col min-w-0">
        {!sidebarOpen && view === "chat" && (
          <div className="absolute top-4 left-4 z-10 flex items-center gap-1">
            <button
              onClick={() => setSidebarOpen(true)}
              className="p-2 rounded-lg hover:bg-[var(--bg-tertiary)] transition-colors"
              title="Open sidebar"
              type="button"
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <line x1="3" y1="6" x2="21" y2="6" />
                <line x1="3" y1="12" x2="21" y2="12" />
                <line x1="3" y1="18" x2="21" y2="18" />
              </svg>
            </button>
            <button
              type="button"
              onClick={() => openSettings()}
              className="p-2 rounded-lg hover:bg-[var(--bg-tertiary)] transition-colors text-[var(--text-muted)]"
              title="Settings — API keys"
              aria-label="Open settings"
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="12" cy="12" r="3" />
                <path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42" />
              </svg>
            </button>
          </div>
        )}

        {activeSession && chartEverOpened && (
          <div className={`flex-1 flex flex-col min-h-0 ${view !== "chart" ? "hidden" : ""}`}>
            <ChartView
              ref={chartRef}
              sessionId={activeSession}
              onBack={() => setView("chat")}
              dataVersion={chartDataVersion}
            />
          </div>
        )}

        {activeSession ? (
          <div className={`flex-1 flex min-h-0 ${view === "chart" ? "hidden" : ""}`}>
            <div className="flex-1 flex flex-col min-h-0 min-w-0">
              {sessionIdsToMount.map((sessionId) => (
                <div
                  key={sessionId}
                  className={
                    sessionId === activeSession
                      ? "flex-1 flex flex-col min-h-0 min-w-0"
                      : "hidden"
                  }
                  aria-hidden={sessionId !== activeSession}
                >
                  <Chat
                    sessionId={sessionId}
                    onOpenChart={() => { setChartEverOpened(true); setView("chart"); }}
                    getChartScreenshot={() => chartRef.current?.takeScreenshot() ?? null}
                    onChartDataUpdated={() => setChartDataVersion((v) => v + 1)}
                    readyForPaperTradingCount={sessions.find((s) => s.session_id === sessionId)?.ready_for_paper_trading_count ?? 0}
                    openChartOnDoneRef={sessionId === activeSession ? openChartOnDoneRef : undefined}
                    onLoadingChange={handleLoadingChange}
                    onStrategyVersionTagged={sessionId === activeSession ? () => window.dispatchEvent(new CustomEvent("strategy-versions-changed", { detail: { sessionId } })) : undefined}
                  />
                </div>
              ))}
            </div>
            {view === "chat" && (
              <StrategyVersionsPanel
                sessionId={activeSession}
                open={strategiesPanelOpen}
                onToggle={() => setStrategiesPanelOpen((o) => !o)}
                refreshKey={strategiesRefreshKey}
              />
            )}
          </div>
        ) : (
          <div className="flex-1 flex items-center justify-center text-[var(--text-muted)]">
            Loading...
          </div>
        )}
      </main>
    </div>
  );
}

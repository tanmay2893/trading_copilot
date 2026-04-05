"use client";

import type { SessionSummary } from "@/lib/types";

interface SidebarProps {
  sessions: SessionSummary[];
  activeSession: string;
  /** Session IDs that currently have a strategy/refinement/question running (shows spinner). */
  runningSessionIds?: string[];
  onSelect: (id: string) => void;
  onNew: () => void;
  onClose: () => void;
  onDelete?: (id: string) => void;
  onOpenSettings?: () => void;
}

export function Sidebar({
  sessions,
  activeSession,
  runningSessionIds = [],
  onSelect,
  onNew,
  onClose,
  onDelete,
  onOpenSettings,
}: SidebarProps) {
  return (
    <aside className="w-64 flex-shrink-0 border-r border-[var(--border)] bg-[var(--bg-secondary)] flex flex-col">
      <div className="p-4 border-b border-[var(--border)] flex items-center justify-between gap-2">
        <h1 className="text-sm font-semibold tracking-wide uppercase text-[var(--text-secondary)] min-w-0">
          Backtester
        </h1>
        <div className="flex items-center gap-1 shrink-0">
          {onOpenSettings && (
            <button
              type="button"
              onClick={onOpenSettings}
              className="p-1 rounded hover:bg-[var(--bg-tertiary)] transition-colors text-[var(--text-muted)]"
              title="Settings — API keys"
              aria-label="Open settings"
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="12" cy="12" r="3" />
                <path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42" />
              </svg>
            </button>
          )}
          <button
            type="button"
            onClick={onClose}
            className="p-1 rounded hover:bg-[var(--bg-tertiary)] transition-colors text-[var(--text-muted)]"
            aria-label="Close sidebar"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>
      </div>

      <div className="p-3">
        <button
          onClick={onNew}
          className="w-full px-3 py-2.5 rounded-lg border border-dashed border-[var(--border)] text-sm text-[var(--text-secondary)] hover:border-[var(--accent)] hover:text-[var(--accent)] transition-colors"
        >
          + New Chat
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-2 pb-4">
        {sessions.map((s) => (
          <div
            key={s.session_id}
            className={`group flex items-center gap-1 rounded-lg mb-1 text-sm transition-colors ${
              activeSession === s.session_id
                ? "bg-[var(--bg-tertiary)]"
                : "hover:bg-[var(--bg-tertiary)]"
            }`}
          >
            <span className="shrink-0 w-3 h-3 flex items-center justify-center" aria-hidden>
              {runningSessionIds.includes(s.session_id) ? (
                <span
                  className="w-3 h-3 border-2 border-[var(--accent)] border-t-transparent rounded-full animate-spin"
                  title="Running..."
                />
              ) : null}
            </span>
            <button
              onClick={() => onSelect(s.session_id)}
              className={`flex-1 min-w-0 text-left px-3 py-2.5 ${
                activeSession === s.session_id
                  ? "text-[var(--text-primary)]"
                  : "text-[var(--text-secondary)]"
              }`}
            >
              <div className="truncate font-medium flex items-center gap-1.5 flex-wrap">
                <span className="min-w-0 truncate">
                  {s.title?.trim()
                    ? s.title
                    : s.active_strategy?.trim()
                      ? s.active_strategy
                      : `Session ${s.session_id.slice(0, 6)}`}
                </span>
                {(s.ready_for_paper_trading_count ?? 0) > 0 && (
                  <span
                    className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full bg-[var(--success)]/15 text-[var(--success)] text-[10px] font-semibold uppercase tracking-wide shrink-0"
                    title={`${s.ready_for_paper_trading_count} strategy version(s) passed compliance and can be paper traded`}
                  >
                    ● {s.ready_for_paper_trading_count} ready
                  </span>
                )}
              </div>
              <div className="text-xs text-[var(--text-muted)] mt-0.5">
                {s.messages} messages · {s.runs} runs
              </div>
            </button>
            {onDelete && (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  onDelete(s.session_id);
                }}
                className="p-1.5 rounded opacity-0 group-hover:opacity-100 hover:bg-[var(--bg-tertiary)] text-[var(--text-muted)] hover:text-red-500 transition-all shrink-0"
                title="Delete session"
                aria-label="Delete session"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M3 6h18M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6M8 6V4a2 2 0 012-2h4a2 2 0 012 2v2" />
                  <line x1="10" y1="11" x2="10" y2="17" />
                  <line x1="14" y1="11" x2="14" y2="17" />
                </svg>
              </button>
            )}
          </div>
        ))}
        {sessions.length === 0 && (
          <p className="text-xs text-[var(--text-muted)] text-center mt-8">
            No previous sessions
          </p>
        )}
      </div>
    </aside>
  );
}

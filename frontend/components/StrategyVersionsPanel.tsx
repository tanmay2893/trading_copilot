"use client";

import { useCallback, useEffect, useState } from "react";
import {
  fetchSession,
  fetchStrategyVersionCode,
  fetchStrategyVersionsAll,
  setChatBase,
  setVersionDeleted,
  setVersionTag,
  type StrategyVersionItem,
} from "@/lib/api";
import { CodeBlock } from "./CodeBlock";

interface StrategyVersionsPanelProps {
  sessionId: string;
  /** When true, panel is expanded. */
  open: boolean;
  onToggle: () => void;
  /** Optional: refetch when this changes (e.g. after tagging a new version). */
  refreshKey?: string | number;
}

export function StrategyVersionsPanel({
  sessionId,
  open,
  onToggle,
  refreshKey,
}: StrategyVersionsPanelProps) {
  const [versions, setVersions] = useState<StrategyVersionItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [chatBaseVersionId, setChatBaseVersionId] = useState<string | null>(null);

  const load = useCallback(() => {
    if (!sessionId) return;
    setLoading(true);
    setError(null);
    fetchStrategyVersionsAll(sessionId)
      .then((data) => {
        setVersions(data.versions ?? []);
      })
      .catch((e) => {
        setError(e instanceof Error ? e.message : "Failed to load");
      })
      .finally(() => setLoading(false));
  }, [sessionId]);

  useEffect(() => {
    if (open && sessionId) load();
  }, [open, sessionId, refreshKey, load]);

  useEffect(() => {
    if (!open || !sessionId) return;
    fetchSession(sessionId)
      .then((s) => setChatBaseVersionId(s.chat_base_version_id ?? null))
      .catch(() => setChatBaseVersionId(null));
  }, [open, sessionId, refreshKey]);

  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<{ sessionId?: string }>).detail;
      if (detail?.sessionId === sessionId) {
        fetchSession(sessionId)
          .then((s) => setChatBaseVersionId(s.chat_base_version_id ?? null))
          .catch(() => setChatBaseVersionId(null));
      }
    };
    window.addEventListener("chat-base-changed", handler);
    return () => window.removeEventListener("chat-base-changed", handler);
  }, [sessionId]);

  const handleSetChatBase = useCallback(
    async (versionId: string | null) => {
      try {
        const res = await setChatBase(sessionId, versionId);
        setChatBaseVersionId(res.chat_base_version_id ?? null);
        window.dispatchEvent(new CustomEvent("chat-base-changed", { detail: { sessionId } }));
      } catch {
        // Keep UI unchanged on error
      }
    },
    [sessionId]
  );

  const handleSetDeleted = useCallback(
    async (versionId: string, deleted: boolean) => {
      try {
        await setVersionDeleted(sessionId, versionId, deleted);
        setVersions((prev) =>
          prev.map((v) =>
            v.version_id === versionId ? { ...v, deleted } : v
          )
        );
      } catch {
        // Keep UI unchanged on error
      }
    },
    [sessionId]
  );

  const handleTagUpdated = useCallback(
    (versionId: string, tag: string) => {
      setVersions((prev) =>
        prev.map((v) =>
          v.version_id === versionId ? { ...v, tag, label: tag } : v
        )
      );
    },
    []
  );

  return (
    <div
      className={`flex flex-col h-full border-l border-[var(--border)] bg-[var(--bg-secondary)] flex-shrink-0 transition-[width] ${
        open ? "w-64" : "w-10"
      }`}
    >
      <button
        type="button"
        onClick={onToggle}
        className={`flex items-center border-b border-[var(--border)] bg-[var(--bg-tertiary)] text-[var(--text-primary)] hover:bg-[var(--bg-primary)] transition-colors ${
          open ? "justify-between gap-2 px-3 py-2.5 text-left text-sm font-medium" : "justify-center p-2 w-full"
        }`}
        aria-expanded={open}
        title={open ? "Collapse strategies" : "Strategies"}
      >
        {open ? (
          <>
            <span>Strategies</span>
            <svg className="w-4 h-4 text-[var(--text-muted)]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M9 18l6-6-6-6" />
            </svg>
          </>
        ) : (
          <svg className="w-5 h-5 text-[var(--text-muted)]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
            <path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3" />
          </svg>
        )}
      </button>
      {open && (
        <div className="flex-1 overflow-y-auto min-h-0">
          {loading && (
            <p className="px-3 py-2 text-xs text-[var(--text-muted)]">
              Loading…
            </p>
          )}
          {error && (
            <p className="px-3 py-2 text-xs text-red-400">{error}</p>
          )}
          {!loading && !error && versions.length === 0 && (
            <p className="px-3 py-2 text-xs text-[var(--text-muted)]">
              No saved strategies yet. Run or refine a strategy and tag it.
            </p>
          )}
          {!loading && versions.length > 0 && (
            <ul className="py-1">
              {versions.map((v) => (
                <StrategyVersionRow
                  key={v.version_id}
                  sessionId={sessionId}
                  item={v}
                  isInChat={chatBaseVersionId === v.version_id}
                  onAddToChat={() => handleSetChatBase(v.version_id)}
                  onClearFromChat={() => handleSetChatBase(null)}
                  onDelete={() => handleSetDeleted(v.version_id, true)}
                  onRestore={() => handleSetDeleted(v.version_id, false)}
                  onTagUpdated={handleTagUpdated}
                />
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

function StrategyVersionRow({
  sessionId,
  item,
  isInChat,
  onAddToChat,
  onClearFromChat,
  onDelete,
  onRestore,
  onTagUpdated,
}: {
  sessionId: string;
  item: StrategyVersionItem;
  isInChat: boolean;
  onAddToChat: () => void;
  onClearFromChat: () => void;
  onDelete: () => void;
  onRestore: () => void;
  onTagUpdated: (versionId: string, tag: string) => void;
}) {
  const [modalOpen, setModalOpen] = useState(false);
  const [code, setCode] = useState<string | null>(null);
  const [codeLoading, setCodeLoading] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editValue, setEditValue] = useState("");
  const [savingTag, setSavingTag] = useState(false);
  const [tagError, setTagError] = useState<string | null>(null);
  const editInputRef = useCallback((el: HTMLInputElement | null) => {
    el?.focus();
    el?.select();
  }, []);

  const startEdit = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation();
      setEditValue(item.label || item.version_id);
      setTagError(null);
      setEditing(true);
    },
    [item.label, item.version_id]
  );

  const saveEdit = useCallback(async () => {
    const value = editValue.trim();
    if (!value) {
      setTagError("Name is required");
      return;
    }
    setTagError(null);
    setSavingTag(true);
    try {
      await setVersionTag(sessionId, item.version_id, value);
      onTagUpdated(item.version_id, value);
      setEditing(false);
    } catch {
      setTagError("Failed to update");
    } finally {
      setSavingTag(false);
    }
  }, [sessionId, item.version_id, editValue, onTagUpdated]);

  const cancelEdit = useCallback((e: React.MouseEvent) => {
    e?.stopPropagation();
    setEditing(false);
    setTagError(null);
  }, []);

  const openModal = useCallback(async () => {
    setModalOpen(true);
    if (code !== null) return;
    setCodeLoading(true);
    try {
      const res = await fetchStrategyVersionCode(sessionId, item.version_id);
      setCode(res.code);
    } catch {
      setCode("Failed to load code.");
    } finally {
      setCodeLoading(false);
    }
  }, [sessionId, item.version_id, code]);

  const closeModal = useCallback(() => setModalOpen(false), []);

  useEffect(() => {
    if (!modalOpen) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeModal();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [modalOpen, closeModal]);

  return (
    <>
      <li className="group border-b border-[var(--border)] last:border-b-0">
        <div className="flex items-center gap-1 px-2 py-1.5">
          {editing ? (
            <div className="flex-1 min-w-0 flex flex-col gap-1">
              <input
                ref={editInputRef}
                type="text"
                value={editValue}
                onChange={(e) => setEditValue(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") saveEdit();
                  if (e.key === "Escape") setEditing(false);
                }}
                className="w-full bg-[var(--bg-primary)] border border-[var(--border)] rounded px-1.5 py-1 text-xs text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
                placeholder="Version name"
                disabled={savingTag}
              />
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  onClick={saveEdit}
                  disabled={savingTag || !editValue.trim()}
                  className="px-2 py-0.5 text-xs rounded bg-[var(--accent)] text-white hover:bg-[var(--accent-hover)] disabled:opacity-50"
                >
                  {savingTag ? "Saving…" : "Save"}
                </button>
                <button
                  type="button"
                  onClick={cancelEdit}
                  className="px-2 py-0.5 text-xs rounded border border-[var(--border)] text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)]"
                >
                  Cancel
                </button>
              </div>
              {tagError && <p className="text-xs text-red-400">{tagError}</p>}
            </div>
          ) : (
            <>
              <button
                type="button"
                onClick={openModal}
                className={`flex-1 min-w-0 text-left text-xs truncate rounded px-1.5 py-1 hover:bg-[var(--bg-tertiary)] transition-colors ${
                  item.deleted
                    ? "line-through text-[var(--text-muted)]"
                    : "text-[var(--text-primary)]"
                }`}
                title={item.label}
              >
                {item.label || item.version_id}
              </button>
              {!item.deleted && (
                isInChat ? (
                  <button
                    type="button"
                    onClick={(e) => { e.stopPropagation(); onClearFromChat(); }}
                    className="flex-shrink-0 p-1 rounded text-[var(--text-muted)] opacity-0 group-hover:opacity-100 hover:text-[var(--accent)] hover:bg-[var(--bg-tertiary)] transition-all"
                    title="Clear from chat"
                  >
                    <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M18 6L6 18M6 6l12 12" />
                    </svg>
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={(e) => { e.stopPropagation(); onAddToChat(); }}
                    className="flex-shrink-0 p-1 rounded text-[var(--text-muted)] opacity-0 group-hover:opacity-100 hover:text-[var(--accent)] hover:bg-[var(--bg-tertiary)] transition-all"
                    title="Add to chat (use this version as base for next refine)"
                  >
                    <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M12 5v14M5 12h14" />
                    </svg>
                  </button>
                )
              )}
              <button
                type="button"
                onClick={startEdit}
                className="flex-shrink-0 p-1 rounded text-[var(--text-muted)] opacity-0 group-hover:opacity-100 hover:text-[var(--accent)] hover:bg-[var(--bg-tertiary)] transition-all"
                title="Change name"
              >
                <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
                  <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
                </svg>
              </button>
            </>
          )}
          {!editing && (item.deleted ? (
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); onRestore(); }}
              className="flex-shrink-0 p-1 rounded text-[var(--text-muted)] hover:text-[var(--accent)] hover:bg-[var(--bg-tertiary)] transition-colors"
              title="Restore (show in rerun options)"
            >
              <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
                <path d="M3 3v5h5" />
              </svg>
            </button>
          ) : (
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); onDelete(); }}
              className="flex-shrink-0 p-1 rounded text-[var(--text-muted)] hover:text-red-400 hover:bg-red-500/10 transition-colors"
              title="Remove from rerun options (keep in list)"
            >
              <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m3 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6h14z" />
                <line x1="10" y1="11" x2="10" y2="17" />
                <line x1="14" y1="11" x2="14" y2="17" />
              </svg>
            </button>
          ))}
        </div>
      </li>

      {modalOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="code-modal-title"
          onClick={closeModal}
        >
          <div
            className="w-full max-w-2xl max-h-[85vh] flex flex-col rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] shadow-2xl overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--border)] bg-[var(--bg-tertiary)]">
              <h2 id="code-modal-title" className="text-sm font-medium text-[var(--text-primary)] truncate">
                {item.label || item.version_id}
              </h2>
              <button
                type="button"
                onClick={closeModal}
                className="p-1.5 rounded-lg text-[var(--text-muted)] hover:text-white hover:bg-[var(--bg-primary)] transition-colors"
                aria-label="Close"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
            <div className="flex-1 overflow-auto p-3 min-h-0">
              {codeLoading && (
                <p className="text-sm text-[var(--text-muted)]">Loading code…</p>
              )}
              {!codeLoading && code !== null && (
                <CodeBlock code={code} language="python" />
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}

"use client";

import { useState } from "react";
import type { ChatMessage, MessageBlock } from "@/lib/types";
import { fetchStrategyVersionCode, setVersionTag } from "@/lib/api";
import { extractMarkdownTable } from "@/lib/parseMarkdownTable";
import { CodeBlock } from "./CodeBlock";
import { ProgressStep } from "./ProgressStep";
import { SignalTable } from "./SignalTable";
import { TextWithMath } from "./TextWithMath";
import type { VersionTagsMap } from "./MessageList";

interface MessageBubbleProps {
  message: ChatMessage;
  sessionId: string;
  versionTags?: VersionTagsMap;
  versionSources?: Record<string, string>;
  onVersionTagged?: (versionId: string, tag: string) => void;
}

export function MessageBubble({
  message,
  sessionId,
  versionTags = {},
  versionSources = {},
  onVersionTagged,
}: MessageBubbleProps) {
  const isUser = message.role === "user";

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[85%] rounded-2xl px-4 py-3 ${
          isUser
            ? "bg-[var(--accent)] text-white"
            : "bg-[var(--bg-secondary)] border border-[var(--border)]"
        }`}
      >
        {message.blocks.map((block, i) => (
          <BlockRenderer
            key={i}
            block={block}
            isUser={isUser}
            sessionId={sessionId}
            versionTags={versionTags}
            versionSources={versionSources}
            onVersionTagged={onVersionTagged}
          />
        ))}
      </div>
    </div>
  );
}

function TextWithTables({ content, isUser }: { content: string; isUser: boolean }) {
  const textClass = `text-sm leading-relaxed ${
    isUser ? "" : "text-[var(--text-primary)]"
  }`;
  const safeContent = content ?? "";
  const match = extractMarkdownTable(safeContent);
  if (!match) {
    return (
      <div className={textClass}>
        <TextWithMath content={safeContent} className={textClass} />
      </div>
    );
  }
  const { before, table, after } = match;
  return (
    <div className="space-y-2">
      {before ? (
        <div className={textClass}>
          <TextWithMath content={before} className={textClass} />
        </div>
      ) : null}
      <div className="my-2">
        <SignalTable headers={table.headers} rows={table.rows} />
      </div>
      {after ? <TextWithTables content={after} isUser={isUser} /> : null}
    </div>
  );
}

function BlockRenderer({
  block,
  isUser,
  sessionId,
  versionTags,
  versionSources,
  onVersionTagged,
}: {
  block: MessageBlock;
  isUser: boolean;
  sessionId: string;
  versionTags: VersionTagsMap;
  versionSources: Record<string, string>;
  onVersionTagged?: (versionId: string, tag: string) => void;
}) {
  switch (block.type) {
    case "text":
      return (
        <TextWithTables content={block.content} isUser={isUser} />
      );

    case "code":
      return (
        <div className="my-2">
          <CodeBlock code={block.code} language={block.language} />
        </div>
      );

    case "progress":
      return (
        <div className="my-1">
          <ProgressStep step={block.step} status={block.status} detail={block.detail} />
        </div>
      );

    case "table":
      return (
        <div className="my-2">
          <SignalTable
            title={block.title}
            headers={block.headers}
            rows={block.rows}
            formula={"formula" in block ? block.formula : undefined}
          />
        </div>
      );

    case "image":
      return <ImageThumbnail url={block.url} alt={block.alt} />;

    case "error":
      return (
        <div className="my-2 px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/30 text-sm text-red-400">
          {block.message}
        </div>
      );

    case "strategy_version":
      return (
        <div className="mt-2">
          <StrategyVersionBlock
            sessionId={sessionId}
            versionId={block.versionId}
            tag={versionTags[block.versionId] ?? null}
            tagOptional={versionSources[block.versionId] === "rerun"}
            onVersionTagged={onVersionTagged}
          />
        </div>
      );

    default:
      return null;
  }
}

function ImageThumbnail({ url, alt }: { url: string; alt: string }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <>
      <div className="my-2 cursor-pointer group" onClick={() => setExpanded(true)}>
        <div className="relative inline-block rounded-lg overflow-hidden border border-[var(--border)] hover:border-[var(--accent)] transition-colors">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={url}
            alt={alt}
            className="block w-48 h-auto object-contain"
          />
          <div className="absolute inset-0 flex items-center justify-center bg-black/0 group-hover:bg-black/30 transition-colors">
            <svg
              className="w-6 h-6 text-white opacity-0 group-hover:opacity-100 transition-opacity"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0zM10 7v3m0 0v3m0-3h3m-3 0H7"
              />
            </svg>
          </div>
        </div>
        <p className="text-xs text-[var(--text-secondary)] mt-1">{alt}</p>
      </div>

      {expanded && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm cursor-pointer"
          onClick={() => setExpanded(false)}
        >
          <div className="relative max-w-[90vw] max-h-[90vh]" onClick={(e) => e.stopPropagation()}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={url}
              alt={alt}
              className="max-w-full max-h-[90vh] object-contain rounded-lg shadow-2xl"
            />
            <button
              onClick={() => setExpanded(false)}
              className="absolute -top-3 -right-3 w-8 h-8 rounded-full bg-[var(--bg-primary)] border border-[var(--border)] flex items-center justify-center text-[var(--text-secondary)] hover:text-white hover:bg-red-500/80 transition-colors"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>
      )}
    </>
  );
}

function StrategyVersionBlock({
  sessionId,
  versionId,
  tag,
  tagOptional = false,
  onVersionTagged,
}: {
  sessionId: string;
  versionId: string;
  tag: string | null;
  /** When true (e.g. rerun), naming is not required and the form is hidden */
  tagOptional?: boolean;
  onVersionTagged?: (versionId: string, tag: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [code, setCode] = useState<string | null>(null);
  const [tagInput, setTagInput] = useState("");
  const [savingTag, setSavingTag] = useState(false);
  const [tagError, setTagError] = useState<string | null>(null);

  const needsTag = !tagOptional && (tag === null || tag === undefined);

  const handleClick = async () => {
    if (open) {
      setOpen(false);
      return;
    }
    if (code) {
      setOpen(true);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await fetchStrategyVersionCode(sessionId, versionId);
      setCode(res.code);
      setOpen(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load strategy code");
    } finally {
      setLoading(false);
    }
  };

  const handleSaveTag = async () => {
    const value = tagInput.trim();
    if (!value) {
      setTagError("Tag is required");
      return;
    }
    if (!onVersionTagged) return;
    setTagError(null);
    setSavingTag(true);
    try {
      await setVersionTag(sessionId, versionId, value);
      onVersionTagged(versionId, value);
    } catch (e) {
      setTagError(e instanceof Error ? e.message : "Failed to save tag");
    } finally {
      setSavingTag(false);
    }
  };

  return (
    <div className="space-y-2">
      {needsTag ? (
        <div className="rounded-md border border-amber-500/50 bg-amber-500/10 px-3 py-2 space-y-2">
          <p className="text-xs font-medium text-amber-600 dark:text-amber-400">
            Name this version (required before continuing)
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <input
              type="text"
              value={tagInput}
              onChange={(e) => {
                setTagInput(e.target.value);
                setTagError(null);
              }}
              onKeyDown={(e) => e.key === "Enter" && handleSaveTag()}
              placeholder="e.g. RSI v1, MACD crossover"
              className="flex-1 min-w-[160px] bg-[var(--bg-primary)] border border-[var(--border)] rounded-lg px-2.5 py-1.5 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--accent)]"
              disabled={savingTag}
            />
            <button
              type="button"
              onClick={handleSaveTag}
              disabled={savingTag || !tagInput.trim()}
              className="px-3 py-1.5 text-xs font-medium rounded-lg bg-[var(--accent)] text-white hover:bg-[var(--accent-hover)] disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {savingTag ? "Saving…" : "Save tag"}
            </button>
          </div>
          {tagError && <p className="text-xs text-red-400">{tagError}</p>}
        </div>
      ) : (
        <span className="text-xs text-[var(--text-muted)]" title="Version name">
          Version: {tag}
        </span>
      )}
      <button
        type="button"
        onClick={handleClick}
        className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs rounded-md border border-[var(--border)] text-[var(--text-secondary)] hover:border-[var(--accent)] hover:text-[var(--accent)] bg-[var(--bg-primary)] transition-colors"
      >
        <svg
          className="w-3 h-3"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M3 5h18" />
          <path d="M8 3h8v4H8z" />
          <path d="M5 9h14v11H5z" />
        </svg>
        {loading ? "Loading code..." : open ? "Hide code for this version" : "View code for this version"}
      </button>
      {error && (
        <div className="text-xs text-red-400">
          {error}
        </div>
      )}
      {open && code && (
        <CodeBlock code={code} language="python" />
      )}
    </div>
  );
}

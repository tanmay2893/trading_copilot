"use client";

import React from "react";
import katex from "katex";
import "katex/dist/katex.min.css";
import { parseMathSegments, type MathSegment } from "@/lib/parseMath";

interface TextWithMathProps {
  content: string;
  className?: string;
}

function renderMathSegment(seg: MathSegment, key: number): React.ReactNode {
  if (seg.type === "text") {
    return (
      <span key={key} className="whitespace-pre-wrap">
        {seg.content}
      </span>
    );
  }
  if (seg.type === "inline") {
    try {
      const html = katex.renderToString(seg.content.trim(), {
        displayMode: false,
        throwOnError: false,
        output: "html",
      });
      return (
        <span
          key={key}
          className="katex-inline align-baseline"
          dangerouslySetInnerHTML={{ __html: html }}
        />
      );
    } catch {
      return (
        <span key={key} className="opacity-80">
          \({seg.content}\)
        </span>
      );
    }
  }
  try {
    const html = katex.renderToString(seg.content.trim(), {
      displayMode: true,
      throwOnError: false,
      output: "html",
    });
    return (
      <div
        key={key}
        className="my-2 flex justify-center overflow-x-auto katex-display text-[var(--text-primary)]"
        dangerouslySetInnerHTML={{ __html: html }}
      />
    );
  } catch {
    return (
      <div key={key} className="my-2 text-center opacity-80">
        \[{seg.content}\]
      </div>
    );
  }
}

/** Renders a single line (may contain inline math). */
function renderLineWithMath(line: string, lineKey: number): React.ReactNode {
  const segments = parseMathSegments(line);
  if (segments.length === 0) return <div key={lineKey} />;
  if (segments.length === 1 && segments[0].type === "text") {
    return (
      <div key={lineKey} className="whitespace-pre-wrap">
        {segments[0].content}
      </div>
    );
  }
  return (
    <div key={lineKey} className="whitespace-pre-wrap">
      {segments.map((seg, i) => renderMathSegment(seg, i))}
    </div>
  );
}

/** Renders text with block structure: newlines → blocks, "- " / "* " → list. */
function renderTextWithBlocks(text: string, baseKey: number): React.ReactNode[] {
  const lines = text.split("\n");
  const nodes: React.ReactNode[] = [];
  let listItems: string[] = [];
  let key = baseKey;

  const flushList = () => {
    if (listItems.length > 0) {
      nodes.push(
        <ul
          key={key++}
          className="list-disc list-inside pl-4 my-1 space-y-0.5 text-[inherit]"
        >
          {listItems.map((item, j) => (
            <li key={j}>{parseMathSegments(item).map((seg, i) => renderMathSegment(seg, i))}</li>
          ))}
        </ul>
      );
      listItems = [];
    }
  };

  for (const line of lines) {
    const listMatch = line.match(/^\s*[-*]\s+(.*)$/);
    if (listMatch) {
      flushList();
      listItems.push(listMatch[1]);
    } else {
      flushList();
      if (line.trim() === "") {
        nodes.push(<div key={key++} className="h-2" aria-hidden />);
      } else {
        nodes.push(renderLineWithMath(line, key++));
      }
    }
  }
  flushList();
  return nodes;
}

export function TextWithMath({ content, className = "" }: TextWithMathProps) {
  const segments = parseMathSegments(content ?? "");

  if (segments.length === 0) return null;
  if (segments.length === 1 && segments[0].type === "text") {
    const text = segments[0].content;
    if (!text.includes("\n") && !/^\s*[-*]\s+/m.test(text)) {
      return <span className={className}>{text}</span>;
    }
    return (
      <div className={`${className} space-y-1`}>
        {renderTextWithBlocks(text, 0)}
      </div>
    );
  }

  const hasDisplay = segments.some((s) => s.type === "display");

  return (
    <div className={`${className} space-y-1`}>
      {segments.map((seg, i) => {
        if (seg.type === "text") {
          if (seg.content.includes("\n") || /^\s*[-*]\s+/m.test(seg.content)) {
            return <React.Fragment key={i}>{renderTextWithBlocks(seg.content, i * 1000)}</React.Fragment>;
          }
          return (
            <span key={i} className="whitespace-pre-wrap block">
              {seg.content}
            </span>
          );
        }
        return renderMathSegment(seg, i);
      })}
    </div>
  );
}

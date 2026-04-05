"use client";

import { useState } from "react";
import katex from "katex";
import "katex/dist/katex.min.css";

interface SignalTableProps {
  title?: string;
  headers: string[];
  rows: string[][];
  formula?: string;
}

function tableToTSV(headers: string[], rows: string[][]): string {
  const escape = (cell: string) => {
    const s = String(cell);
    if (s.includes("\t") || s.includes("\n") || s.includes('"')) {
      return `"${s.replace(/"/g, '""')}"`;
    }
    return s;
  };
  const headerLine = headers.map(escape).join("\t");
  const dataLines = rows.map((row) => row.map(escape).join("\t")).join("\n");
  return headers.length ? [headerLine, dataLines].filter(Boolean).join("\n") : dataLines;
}

function tableToCSV(headers: string[], rows: string[][]): string {
  const escape = (cell: string) => {
    const s = String(cell);
    if (s.includes(",") || s.includes("\n") || s.includes('"')) {
      return `"${s.replace(/"/g, '""')}"`;
    }
    return s;
  };
  const headerLine = headers.map(escape).join(",");
  const dataLines = rows.map((row) => row.map(escape).join(",")).join("\n");
  return headers.length ? [headerLine, dataLines].filter(Boolean).join("\n") : dataLines;
}

export function SignalTable({ title = "", headers, rows, formula }: SignalTableProps) {
  const [copied, setCopied] = useState(false);
  const hasData = headers.length > 0 || rows.length > 0;

  let formulaHtml: string | null = null;
  if (formula && formula.trim()) {
    try {
      formulaHtml = katex.renderToString(formula.trim(), {
        displayMode: true,
        throwOnError: false,
        output: "html",
      });
    } catch {
      formulaHtml = null;
    }
  }

  if (!hasData && !formulaHtml) return null;

  const handleCopy = async () => {
    const tsv = tableToTSV(headers, rows);
    await navigator.clipboard.writeText(tsv);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDownloadCSV = () => {
    const csv = tableToCSV(headers, rows);
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = title ? `${title.replace(/\s+/g, "_")}.csv` : "table.csv";
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="rounded-xl border border-[var(--border)] overflow-hidden bg-[var(--bg-secondary)] shadow-sm">
      <div className="flex items-center justify-between gap-2 px-3 py-2 border-b border-[var(--border)] bg-[var(--bg-tertiary)]">
        {title ? (
          <span className="text-sm font-medium text-[var(--text-primary)] truncate">{title}</span>
        ) : (
          <span />
        )}
        <div className="flex items-center gap-1 shrink-0">
          <button
            type="button"
            onClick={handleCopy}
            className="px-2 py-1 text-xs font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-secondary)] rounded-md transition-colors"
          >
            {copied ? "Copied!" : "Copy"}
          </button>
          <button
            type="button"
            onClick={handleDownloadCSV}
            className="px-2 py-1 text-xs font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-secondary)] rounded-md transition-colors"
          >
            Download CSV
          </button>
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm border-collapse">
          {headers.length > 0 && (
            <thead>
              <tr className="border-b border-[var(--border)]">
                {headers.map((h, i) => (
                  <th
                    key={i}
                    className="px-4 py-2.5 text-left font-semibold text-[var(--text-primary)] bg-[var(--bg-tertiary)]/80 whitespace-nowrap"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
          )}
          <tbody>
            {rows.map((row, ri) => (
              <tr
                key={ri}
                className="border-b border-[var(--border)]/60 last:border-0 hover:bg-[var(--bg-tertiary)]/50 transition-colors"
              >
                {row.map((cell, ci) => (
                  <td
                    key={ci}
                    className="px-4 py-2.5 text-[var(--text-primary)] font-mono text-xs tabular-nums"
                  >
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {formulaHtml && (
        <div
          className="px-4 py-3 border-t border-[var(--border)] bg-[var(--bg-tertiary)]/50 flex items-center justify-center overflow-x-auto"
          aria-label="Risk/Reward formula"
        >
          <div
            className="katex-display text-[var(--text-primary)]"
            dangerouslySetInnerHTML={{ __html: formulaHtml }}
          />
        </div>
      )}
    </div>
  );
}

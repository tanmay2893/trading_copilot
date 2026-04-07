/**
 * Parse a markdown table from text.
 * Supports format:
 *   | Col1 | Col2 |
 *   |------|------|
 *   | a    | b    |
 * Returns null if no valid table is found.
 */
export interface ParsedTable {
  headers: string[];
  rows: string[][];
}

export interface MarkdownTableMatch {
  /** Text before the table */
  before: string;
  /** The parsed table */
  table: ParsedTable;
  /** Text after the table */
  after: string;
}

function parseTableLines(lines: string[]): ParsedTable | null {
  if (lines.length < 2) return null;

  const trimCell = (s: string) => s.trim().replace(/^\|?\s*|\s*\|?$/g, "").trim();
  const splitRow = (line: string): string[] =>
    line
      .split("|")
      .map((c) => c.trim())
      .filter((_, i, arr) => i > 0 && i < arr.length - 1);

  const firstLine = lines[0];
  const secondLine = lines[1];

  // Second line should be separator (e.g. |---|---| or |:---|:---|)
  const isSeparator = /^\s*\|[\s\-:]+\|/.test(secondLine) || /^[\s\-:|]+$/.test(secondLine.trim());
  if (!isSeparator) return null;

  const headers = splitRow(firstLine).map(trimCell);
  if (headers.length === 0 || headers.some((h) => !h)) return null;

  const rows: string[][] = [];
  for (let i = 2; i < lines.length; i++) {
    const line = lines[i];
    if (!line.trim().startsWith("|")) break;
    const cells = splitRow(line).map(trimCell);
    if (cells.length !== headers.length) break;
    rows.push(cells);
  }

  return { headers, rows };
}

/**
 * Find the first markdown table in content and return segments (before, table, after).
 * If no table is found, returns null.
 */
export function extractMarkdownTable(content: string): MarkdownTableMatch | null {
  if (content == null || typeof content !== "string") return null;
  const lines = content.split("\n");
  for (let start = 0; start < lines.length; start++) {
    const line = lines[start];
    if (!line.trim().startsWith("|")) continue;

    const tableLines: string[] = [];
    let i = start;
    while (i < lines.length && lines[i].trim().startsWith("|")) {
      tableLines.push(lines[i]);
      i++;
    }

    const table = parseTableLines(tableLines);
    if (table && table.headers.length > 0) {
      const before = lines.slice(0, start).join("\n").trimEnd();
      const after = lines.slice(i).join("\n").trimStart();
      return { before, table, after };
    }
  }
  return null;
}

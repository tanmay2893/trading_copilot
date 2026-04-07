/**
 * Parse a string into segments of plain text and LaTeX.
 * Supports:
 *   - Display: \[ ... \] or $$ ... $$
 *   - Inline: \( ... \)
 * Used to render mathematical formulas in chat messages.
 */
export type MathSegment =
  | { type: "text"; content: string }
  | { type: "inline"; content: string }
  | { type: "display"; content: string };

export function parseMathSegments(str: string): MathSegment[] {
  if (!str) return [];
  const segments: MathSegment[] = [];
  let i = 0;
  const len = str.length;

  while (i < len) {
    const displayBracket = str.indexOf("\\[", i);
    const displayDollar = str.indexOf("$$", i);
    const inlineOpen = str.indexOf("\\(", i);

    let next = -1;
    let mode: "display" | "display$$" | "inline" | null = null;
    const candidates: { pos: number; mode: "display" | "display$$" | "inline" }[] = [];
    if (displayBracket !== -1) candidates.push({ pos: displayBracket, mode: "display" });
    if (displayDollar !== -1) candidates.push({ pos: displayDollar, mode: "display$$" });
    if (inlineOpen !== -1) candidates.push({ pos: inlineOpen, mode: "inline" });
    candidates.sort((a, b) => a.pos - b.pos);
    const first = candidates[0];
    if (!first) {
      segments.push({ type: "text", content: str.slice(i) });
      break;
    }
    next = first.pos;
    mode = first.mode;

    segments.push({ type: "text", content: str.slice(i, next) });

    if (mode === "display") {
      const close = str.indexOf("\\]", next + 2);
      const content = close === -1 ? str.slice(next + 2) : str.slice(next + 2, close);
      segments.push({ type: "display", content });
      i = close === -1 ? len : close + 2;
    } else if (mode === "display$$") {
      const close = str.indexOf("$$", next + 2);
      const content = close === -1 ? str.slice(next + 2) : str.slice(next + 2, close);
      segments.push({ type: "display", content });
      i = close === -1 ? len : close + 2;
    } else {
      const close = str.indexOf("\\)", next + 2);
      const content = close === -1 ? str.slice(next + 2) : str.slice(next + 2, close);
      segments.push({ type: "inline", content });
      i = close === -1 ? len : close + 2;
    }
  }

  return segments;
}

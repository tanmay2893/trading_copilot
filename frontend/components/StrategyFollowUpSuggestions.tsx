"use client";

interface StrategyFollowUpSuggestionsProps {
  /** LLM-generated label + full prompt (from server `follow_up_suggestions` event). */
  items: { label: string; prompt: string }[];
  onPick: (prompt: string) => void;
  disabled?: boolean;
  /**
   * `panel` — full-width strip (standalone). `inline` — inside the composer column, below messages
   * and above “Run on other stocks” so chips do not overlap or misalign with quick actions.
   */
  variant?: "panel" | "inline";
}

export function StrategyFollowUpSuggestions({
  items,
  onPick,
  disabled = false,
  variant = "panel",
}: StrategyFollowUpSuggestionsProps) {
  if (items.length === 0) return null;

  const wrapperClass =
    variant === "inline"
      ? "w-full mb-3 pb-3 border-b border-[var(--border)]"
      : "flex-shrink-0 border-t border-[var(--border)] bg-[var(--bg-secondary)] px-4 py-2.5";

  return (
    <div className={wrapperClass}>
      <p className="text-[10px] uppercase tracking-wide text-[var(--text-muted)] mb-2">
        Suggested next steps
      </p>
      <div className="flex flex-wrap gap-2">
        {items.map(({ label, prompt }, index) => (
          <button
            key={`followup-${index}-${prompt.length}-${label.slice(0, 32)}`}
            type="button"
            disabled={disabled}
            onClick={() => onPick(prompt)}
            className="text-left px-3 py-1.5 rounded-lg border border-[var(--border)] text-xs text-[var(--text-secondary)] hover:border-[var(--accent)] hover:text-[var(--accent)] hover:bg-[var(--bg-primary)] transition-colors disabled:opacity-40 disabled:pointer-events-none max-w-full"
          >
            {label}
          </button>
        ))}
      </div>
    </div>
  );
}

"use client";

interface StrategyFollowUpSuggestionsProps {
  /** LLM-generated label + full prompt (from server `follow_up_suggestions` event). */
  items: { label: string; prompt: string }[];
  onPick: (prompt: string) => void;
  disabled?: boolean;
}

export function StrategyFollowUpSuggestions({
  items,
  onPick,
  disabled = false,
}: StrategyFollowUpSuggestionsProps) {
  if (items.length === 0) return null;

  return (
    <div className="flex-shrink-0 border-t border-[var(--border)] bg-[var(--bg-secondary)] px-4 py-2.5">
      <p className="text-[10px] uppercase tracking-wide text-[var(--text-muted)] mb-2">
        Suggested next steps
      </p>
      <div className="flex flex-wrap gap-2">
        {items.map(({ label, prompt }) => (
          <button
            key={`${label}-${prompt.slice(0, 24)}`}
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

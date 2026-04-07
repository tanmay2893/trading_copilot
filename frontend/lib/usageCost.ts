/**
 * Estimated cost per 1M tokens (USD). Used for chat usage display.
 * OpenAI: https://openai.com/api/pricing/
 * Others: best-effort for display only.
 */
const PRICING_PER_MILLION: Record<
  string,
  { input: number; output: number }
> = {
  "gpt-4o": { input: 2.5, output: 10 },
  "gpt-4o-mini": { input: 0.15, output: 0.6 },
  "deepseek-chat": { input: 0.14, output: 0.28 },
  "claude-sonnet-4-20250514": { input: 3, output: 15 },
};

/** Normalize model string for lookup (e.g. strip date suffixes). */
function normalizeModel(model: string): string {
  const lower = model.toLowerCase();
  if (lower.includes("gpt-4o-mini")) return "gpt-4o-mini";
  if (lower.includes("gpt-4o")) return "gpt-4o";
  if (lower.includes("deepseek")) return "deepseek-chat";
  if (lower.includes("claude-sonnet") || lower.includes("claude-3-5-sonnet"))
    return "claude-sonnet-4-20250514";
  return lower;
}

/** Default model for cost when backend doesn't send one (e.g. OpenAI). */
const DEFAULT_MODEL_FOR_COST = "gpt-4o";

export function estimateUsageCost(
  inputTokens: number,
  outputTokens: number,
  model: string | null
): number | null {
  if (inputTokens <= 0 && outputTokens <= 0) return null;
  const modelKey = (model?.trim() || DEFAULT_MODEL_FOR_COST).toLowerCase();
  const key = normalizeModel(modelKey);
  const pricing = PRICING_PER_MILLION[key];
  if (!pricing) {
    // Unknown model: use OpenAI gpt-4o as fallback so cost still shows
    const fallback = PRICING_PER_MILLION[DEFAULT_MODEL_FOR_COST];
    if (!fallback) return null;
    const inputCost = (inputTokens / 1_000_000) * fallback.input;
    const outputCost = (outputTokens / 1_000_000) * fallback.output;
    return inputCost + outputCost;
  }
  const inputCost = (inputTokens / 1_000_000) * pricing.input;
  const outputCost = (outputTokens / 1_000_000) * pricing.output;
  return inputCost + outputCost;
}

export function formatUsageCost(cost: number): string {
  if (cost >= 0.01) return `~$${cost.toFixed(2)}`;
  if (cost >= 0.001) return `~$${cost.toFixed(3)}`;
  return `~$${cost.toFixed(4)}`;
}

/* REST API client for session management. */

/** REST routes live under `/api` on the FastAPI app; relative default matches Next rewrites. */
function apiBaseFromEnv(): string {
  const v = process.env.NEXT_PUBLIC_API_URL?.trim();
  if (!v) return "/api";
  if (v.startsWith("http://") || v.startsWith("https://")) {
    const base = v.replace(/\/+$/, "");
    return base.endsWith("/api") ? base : `${base}/api`;
  }
  return v;
}

const API_BASE = apiBaseFromEnv();

/** Ngrok free tier may return an interstitial HTML page unless this header is sent. */
function ngrokHeaders(): HeadersInit | undefined {
  if (typeof window === "undefined") return undefined;
  const h = window.location.hostname;
  if (!h.includes("ngrok")) return undefined;
  return {
    "ngrok-skip-browser-warning": "true",
    // Some ngrok builds honor a second hint; harmless if ignored.
    "bypass-tunnel-reminder": "true",
  };
}

function isNgrokPage(): boolean {
  return typeof window !== "undefined" && window.location.hostname.includes("ngrok");
}

function apiFetch(input: string, init?: RequestInit): Promise<Response> {
  const extra = ngrokHeaders();
  if (!extra) return fetch(input, init);
  const headers = new Headers(init?.headers);
  for (const [k, v] of Object.entries(extra)) {
    headers.set(k, v);
  }
  return fetch(input, { ...init, headers });
}

/** Parse JSON; fail clearly if the tunnel returned HTML (e.g. ngrok interstitial). */
async function parseJsonResponse<T>(res: Response): Promise<T> {
  const text = await res.text();
  const t = text.trim();
  if (t.startsWith("<") || t.startsWith("<!")) {
    throw new Error("API returned HTML instead of JSON (ngrok warning page or proxy error).");
  }
  try {
    return JSON.parse(text) as T;
  } catch {
    throw new Error("Invalid JSON from API");
  }
}

export async function fetchSessions() {
  const res = await apiFetch(`${API_BASE}/sessions`);
  if (!res.ok) throw new Error("Failed to fetch sessions");
  const data = await parseJsonResponse<unknown>(res);
  if (!Array.isArray(data)) {
    throw new Error("Expected sessions list from API");
  }
  return data;
}

export async function createSession(model: string = "openai") {
  const init: RequestInit = {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model }),
  };
  if (isNgrokPage() && typeof AbortSignal !== "undefined" && typeof AbortSignal.timeout === "function") {
    init.signal = AbortSignal.timeout(25_000);
  }
  const res = await apiFetch(`${API_BASE}/sessions`, init);
  if (!res.ok) throw new Error("Failed to create session");
  const data = await parseJsonResponse<{ session_id?: unknown }>(res);
  if (typeof data.session_id !== "string" || data.session_id.length === 0) {
    throw new Error("Create session response missing session_id");
  }
  return data as { session_id: string; model?: string };
}

export async function deleteSession(sessionId: string) {
  const res = await apiFetch(`${API_BASE}/sessions/${sessionId}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error("Failed to delete session");
  return res.json();
}

export interface SessionDetail {
  session_id: string;
  model: string;
  /** Specific API model when user picked one in the UI; omit or null = auto (alias default). */
  llm_model_id?: string | null;
  title: string | null;
  active_ticker: string | null;
  active_strategy: string | null;
  active_interval: string | null;
  has_code: boolean;
  messages: number;
  runs: number;
  run_history: unknown[];
  created_at: string;
  updated_at: string;
  chat_base_version_id: string | null;
  ready_for_paper_trading_count: number;
  ready_for_paper_trading_versions: unknown[];
}

export async function fetchSession(sessionId: string): Promise<SessionDetail> {
  const res = await apiFetch(`${API_BASE}/sessions/${sessionId}`);
  if (!res.ok) throw new Error("Failed to fetch session");
  return res.json();
}

export const LLM_KEYS_STORAGE_KEY = "backtester_global_llm_v1";

export type LlmCredentialSideResult = {
  status: "ok" | "cleared" | "failed";
  error?: string;
};

export interface LlmKeysStatus {
  openai_configured: boolean;
  anthropic_configured: boolean;
  deepseek_configured: boolean;
  nvidia_qwen_configured: boolean;
}

export async function fetchLlmKeysStatus(): Promise<LlmKeysStatus> {
  const res = await apiFetch(`${API_BASE}/settings/llm-keys`);
  if (!res.ok) throw new Error("Failed to fetch API key status");
  return parseJsonResponse(res);
}

export interface LlmModelOption {
  id: string;
  label: string;
  alias: "openai" | "opus" | "deepseek";
}

export async function fetchLlmModelOptions(): Promise<{
  all: LlmModelOption[];
  by_provider: Record<string, LlmModelOption[]>;
}> {
  const res = await apiFetch(`${API_BASE}/settings/llm-model-options`);
  if (!res.ok) throw new Error("Failed to fetch model options");
  return parseJsonResponse(res);
}

/** Global LLM keys for the web app (server memory). Empty string clears that provider. */
export async function postGlobalLlmKeys(body: {
  openai_api_key: string;
  anthropic_api_key: string;
  deepseek_api_key: string;
  nvidia_qwen_api_key: string;
}): Promise<{
  openai: LlmCredentialSideResult;
  anthropic: LlmCredentialSideResult;
  deepseek: LlmCredentialSideResult;
  nvidia_qwen: LlmCredentialSideResult;
}> {
  const res = await apiFetch(`${API_BASE}/settings/llm-keys`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(err.detail ?? "Failed to update API keys");
  }
  return parseJsonResponse(res);
}

/** Set or clear the strategy version used as chat base for refine. Pass null to clear. */
export async function setChatBase(
  sessionId: string,
  versionId: string | null
): Promise<{ chat_base_version_id: string | null }> {
  const res = await apiFetch(`${API_BASE}/sessions/${sessionId}/chat-base`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ version_id: versionId }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail ?? "Failed to set chat base");
  }
  return res.json();
}

export async function fetchSessionMessages(sessionId: string) {
  const res = await apiFetch(`${API_BASE}/sessions/${sessionId}/messages`);
  if (!res.ok) throw new Error("Failed to fetch messages");
  return res.json();
}

export async function fetchChartData(sessionId: string) {
  const res = await apiFetch(`${API_BASE}/sessions/${sessionId}/chart-data`);
  if (!res.ok) throw new Error("No chart data available");
  return res.json();
}

export async function fetchStrategyVersionCode(sessionId: string, versionId: string) {
  const res = await apiFetch(`${API_BASE}/sessions/${sessionId}/code/${versionId}`);
  if (!res.ok) {
    throw new Error("Failed to fetch strategy code for this version");
  }
  return res.json() as Promise<{ code: string; version_id: string }>;
}

export interface RunParameter {
  name: string;
  value: string;
  description: string;
}

export interface CodeVersionOption {
  version_id: string | null;
  label: string;
  /** User-set tag for this version; null if not tagged yet. When set, label equals tag. */
  tag?: string | null;
  /** run_backtest | refine_strategy | fix_strategy | rerun. Rerun versions do not require naming. */
  source?: string | null;
}

export async function fetchCodeVersions(sessionId: string): Promise<{ versions: CodeVersionOption[] }> {
  const res = await apiFetch(`${API_BASE}/sessions/${sessionId}/code-versions`);
  if (!res.ok) throw new Error("Failed to fetch code versions");
  return res.json();
}

/** Set the mandatory tag (name) for a strategy version. Required before continuing chat. */
export async function setVersionTag(
  sessionId: string,
  versionId: string,
  tag: string
): Promise<{ version_id: string; tag: string }> {
  const res = await apiFetch(
    `${API_BASE}/sessions/${sessionId}/code/${encodeURIComponent(versionId)}/tag`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tag: tag.trim() }),
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail ?? "Failed to set version tag");
  }
  return res.json();
}

/** One strategy version for the right panel (includes soft-deleted). */
export interface StrategyVersionItem {
  version_id: string;
  label: string;
  tag: string | null;
  deleted: boolean;
}

/** Fetch all strategy versions for the session (including soft-deleted, for the right panel). */
export async function fetchStrategyVersionsAll(
  sessionId: string
): Promise<{ versions: StrategyVersionItem[] }> {
  const res = await apiFetch(`${API_BASE}/sessions/${sessionId}/strategy-versions`);
  if (!res.ok) throw new Error("Failed to fetch strategy versions");
  return res.json();
}

/** Soft-delete or restore a version. Deleted versions stay in the panel but are excluded from rerun options. */
export async function setVersionDeleted(
  sessionId: string,
  versionId: string,
  deleted: boolean
): Promise<{ version_id: string; deleted: boolean }> {
  const res = await apiFetch(
    `${API_BASE}/sessions/${sessionId}/code/${encodeURIComponent(versionId)}/deleted`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ deleted }),
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail ?? "Failed to update version");
  }
  return res.json();
}

/** Fetch current (latest) strategy code for the session. Uses in-memory session on the server when available. */
export async function fetchSessionCode(sessionId: string): Promise<{ code: string; ticker: string | null }> {
  const res = await apiFetch(`${API_BASE}/sessions/${sessionId}/code`);
  if (!res.ok) throw new Error("Failed to fetch session code");
  return res.json();
}

export async function fetchRunParameters(
  sessionId: string,
  versionId?: string | null,
  code?: string | null
): Promise<{ parameters: RunParameter[] }> {
  // When current code is provided (e.g. from editor), POST it so params match what user sees
  if (code != null && code.trim() !== "") {
    const res = await apiFetch(`${API_BASE}/sessions/${sessionId}/run-parameters`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code: code.trim() }),
    });
    if (!res.ok) throw new Error("Failed to fetch run parameters");
    return res.json();
  }
  const url =
    versionId != null && versionId !== ""
      ? `${API_BASE}/sessions/${sessionId}/run-parameters?version_id=${encodeURIComponent(versionId)}`
      : `${API_BASE}/sessions/${sessionId}/run-parameters`;
  const res = await apiFetch(url);
  if (!res.ok) throw new Error("Failed to fetch run parameters");
  return res.json();
}

export interface Ticker {
  symbol: string;
  name: string;
  country?: "US" | "INDIA";
}

// ---------------------------------------------------------------------------
// Compliance (paper-trading pre-requisites)
// ---------------------------------------------------------------------------

export interface ComplianceStatus {
  version_id: string;
  reproducibility_passed: boolean;
  reproducibility_choice?: string;
  quiz_passed: boolean;
  paper_trading_unlocked_at?: string;
  ready_for_paper_trading: boolean;
  updated_at?: string;
}

/** Versions that are in the manifest and can be used for compliance (reproducibility + quiz). */
export interface ComplianceVersionOption {
  version_id: string;
  label: string;
}

export async function fetchComplianceVersions(
  sessionId: string
): Promise<{ versions: ComplianceVersionOption[] }> {
  const res = await apiFetch(`${API_BASE}/sessions/${sessionId}/compliance/versions`);
  if (!res.ok) throw new Error("Failed to fetch compliance versions");
  return res.json();
}

/** Only versions that have passed both reproducibility and quiz; only these may be paper traded. */
export async function fetchReadyForPaperTradingVersions(
  sessionId: string
): Promise<{ versions: ComplianceVersionOption[] }> {
  const res = await apiFetch(`${API_BASE}/sessions/${sessionId}/compliance/ready-versions`);
  if (!res.ok) throw new Error("Failed to fetch ready-for-paper-trading versions");
  return res.json();
}

export async function fetchComplianceStatus(
  sessionId: string,
  versionId: string
): Promise<ComplianceStatus> {
  const res = await apiFetch(
    `${API_BASE}/sessions/${sessionId}/compliance/status?version_id=${encodeURIComponent(versionId)}`
  );
  if (!res.ok) throw new Error("Failed to fetch compliance status");
  return res.json();
}

export interface ReproducibilityResult {
  success: boolean;
  passed?: boolean;
  error?: string;
  summary?: string;
  choice_required?: boolean;
  summary_bullets?: string[];
  options?: { id: string; label: string; description: string }[];
}

export async function runReproducibilityCheck(
  sessionId: string,
  versionId: string
): Promise<ReproducibilityResult> {
  const res = await apiFetch(
    `${API_BASE}/sessions/${sessionId}/compliance/reproducibility`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ version_id: versionId }),
    }
  );
  if (!res.ok) throw new Error("Reproducibility check failed");
  return res.json();
}

export async function chooseReproducibility(
  sessionId: string,
  versionId: string,
  choice: "original" | "rebuild_1" | "rebuild_2"
): Promise<{ success: boolean; choice: string; message: string }> {
  const res = await apiFetch(
    `${API_BASE}/sessions/${sessionId}/compliance/reproducibility/choose`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ version_id: versionId, choice }),
    }
  );
  if (!res.ok) throw new Error("Failed to save choice");
  return res.json();
}

export interface QuizQuestion {
  id: string;
  question: string;
  options: string[];
}

export async function generateComplianceQuiz(
  sessionId: string,
  versionId: string
): Promise<{ success: boolean; questions: QuizQuestion[] }> {
  const res = await apiFetch(
    `${API_BASE}/sessions/${sessionId}/compliance/quiz/generate`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ version_id: versionId }),
    }
  );
  if (!res.ok) throw new Error("Failed to generate quiz");
  return res.json();
}

export async function submitComplianceQuiz(
  sessionId: string,
  versionId: string,
  answers: number[]
): Promise<{ success: boolean; passed: boolean; score: string; message: string }> {
  const res = await apiFetch(
    `${API_BASE}/sessions/${sessionId}/compliance/quiz/submit`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ version_id: versionId, answers }),
    }
  );
  if (!res.ok) throw new Error("Failed to submit quiz");
  return res.json();
}

// ---------------------------------------------------------------------------

let tickerCache: Ticker[] | null = null;

export async function fetchTickers(): Promise<Ticker[]> {
  if (tickerCache) return tickerCache;
  const res = await apiFetch(`${API_BASE}/tickers`);
  if (!res.ok) throw new Error("Failed to fetch tickers");
  tickerCache = await res.json();
  return tickerCache!;
}

/** Fetch stocks for batch rerun (US or INDIA). */
export async function fetchStocksByCountry(
  sessionId: string,
  country: "US" | "INDIA"
): Promise<{ symbol: string; name: string }[]> {
  const res = await apiFetch(
    `${API_BASE}/sessions/${sessionId}/stocks?country=${encodeURIComponent(country)}`
  );
  if (!res.ok) throw new Error("Failed to fetch stocks");
  return res.json();
}

export interface BatchRerunResult {
  ticker: string;
  name: string;
  profit_factor: number | null;
  risk_reward: number | null;
  /** Worst trade as percentage (e.g. -10.5 for -10.5%). */
  max_loss_pct: number | null;
  success: boolean;
  error?: string;
}

export interface BatchRerunStatus {
  job_id: string;
  status: "running" | "done" | "failed" | "cancelled";
  total: number;
  completed: number;
  results: BatchRerunResult[];
  country?: string;
  error?: string;
}

export async function cancelBatchRerun(
  sessionId: string,
  jobId: string
): Promise<{ job_id: string; status: string }> {
  const res = await apiFetch(
    `${API_BASE}/sessions/${sessionId}/batch_rerun/${encodeURIComponent(jobId)}/cancel`,
    { method: "POST" }
  );
  if (!res.ok) throw new Error("Failed to cancel batch");
  return res.json();
}

export async function startBatchRerun(
  sessionId: string,
  params: {
    country: "US" | "INDIA";
    param_overrides?: Record<string, string>;
    version_id?: string | null;
    start_date?: string;
    end_date?: string;
  }
): Promise<{ job_id: string }> {
  const res = await apiFetch(`${API_BASE}/sessions/${sessionId}/batch_rerun`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      country: params.country,
      param_overrides: params.param_overrides ?? null,
      version_id: params.version_id ?? null,
      start_date: params.start_date ?? "",
      end_date: params.end_date ?? "",
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? "Failed to start batch");
  }
  return res.json();
}

export async function getBatchRerunStatus(
  sessionId: string,
  jobId: string
): Promise<BatchRerunStatus> {
  const res = await apiFetch(
    `${API_BASE}/sessions/${sessionId}/batch_rerun/${encodeURIComponent(jobId)}`
  );
  if (!res.ok) throw new Error("Failed to fetch batch status");
  return res.json();
}

export interface ParameterSearchRange {
  start: number;
  end: number;
  step: number;
}

export interface ParameterSearchRow {
  [paramName: string]: string | number | boolean | null | undefined;
  success: boolean;
  error?: string | null;
  win_rate_pct?: number | null;
  total_return_pct?: number | null;
  profit_factor?: number | null;
  risk_reward?: number | null;
  max_loss_pct?: number | null;
  train_win_rate_pct?: number | null;
  train_total_return_pct?: number | null;
  train_profit_factor?: number | null;
  train_risk_reward?: number | null;
  train_max_loss_pct?: number | null;
  test_win_rate_pct?: number | null;
  test_total_return_pct?: number | null;
  train_total_return_pct_period?: number | null;
  test_total_return_pct_period?: number | null;
  test_profit_factor?: number | null;
  test_risk_reward?: number | null;
  test_max_loss_pct?: number | null;
  annual_return_gap?: number | null;
  overfitting_risk?: boolean;
}

export interface ParameterSearchResponse {
  ticker: string;
  version_id?: string | null;
  total_combinations: number;
  rows: ParameterSearchRow[];
  optimization_note?: string;
  interval?: string;
  history_start?: string;
  history_end?: string;
  date_range_was_clamped?: boolean;
  train_end_date?: string;
  test_start_date?: string;
  train_bars?: number;
  test_bars?: number;
  profit_annualization?: string;
  train_period_calendar_days?: number;
  test_period_calendar_days?: number;
}

export async function runParameterSearch(
  sessionId: string,
  params: {
    ticker: string;
    parameter_ranges: Record<string, ParameterSearchRange>;
    version_id?: string | null;
    start_date?: string;
    end_date?: string;
    max_combinations?: number;
  }
): Promise<ParameterSearchResponse> {
  const res = await apiFetch(`${API_BASE}/sessions/${sessionId}/parameter-search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      ticker: params.ticker,
      parameter_ranges: params.parameter_ranges,
      version_id: params.version_id ?? null,
      start_date: params.start_date ?? "",
      end_date: params.end_date ?? "",
      max_combinations: params.max_combinations ?? 200,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? "Failed to run parameter search");
  }
  return res.json();
}

export async function applyParameterSearchSelection(
  sessionId: string,
  params: {
    ticker: string;
    selected_parameters: Record<string, string>;
    version_id?: string | null;
    start_date?: string;
    end_date?: string;
  }
): Promise<{ success: boolean; strategy_version_id: string; ticker: string; selected_parameters: Record<string, string> }> {
  const res = await apiFetch(`${API_BASE}/sessions/${sessionId}/parameter-search/apply`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      ticker: params.ticker,
      selected_parameters: params.selected_parameters,
      version_id: params.version_id ?? null,
      start_date: params.start_date ?? "",
      end_date: params.end_date ?? "",
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail ?? "Failed to apply selected parameters");
  }
  return res.json();
}

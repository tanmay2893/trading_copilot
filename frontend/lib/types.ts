/* Wire protocol types matching the backend WebSocket messages. */

export interface TextEvent {
  type: "text";
  content: string;
}

export interface ProgressEvent {
  type: "progress";
  step: string;
  status: "running" | "success" | "failed";
  detail: string;
}

export interface ToolStartEvent {
  type: "tool_start";
  tool_name: string;
  arguments: Record<string, unknown>;
}

export interface ToolEndEvent {
  type: "tool_end";
  tool_name: string;
  result: Record<string, unknown>;
}

export interface CodeEvent {
  type: "code";
  code: string;
  language: string;
}

export interface TableEvent {
  type: "table";
  title: string;
  headers: string[];
  rows: string[][];
  formula?: string;
}

export interface ImageServerEvent {
  type: "image";
  url: string;
  alt: string;
}

export interface ErrorEvent {
  type: "error";
  message: string;
}

export interface DoneEvent {
  type: "done";
  /** Token usage for this turn (cumulative for the turn). */
  input_tokens?: number;
  output_tokens?: number;
  /** Model used, e.g. gpt-4o, for cost estimation. */
  model?: string;
}

export interface RequestDateRangeEvent {
  type: "request_date_range";
  message?: string;
  /** YYYY-MM-DD from LLM parse of user message; pre-fills the date picker when set. */
  suggested_start_date?: string | null;
  suggested_end_date?: string | null;
}

export interface StrategyVersionEvent {
  type: "strategy_version";
  version_id: string;
}

export interface FollowUpSuggestionsEvent {
  type: "follow_up_suggestions";
  suggestions: { label: string; prompt: string }[];
}

export type ServerEvent =
  | TextEvent
  | ProgressEvent
  | ToolStartEvent
  | ToolEndEvent
  | CodeEvent
  | TableEvent
  | ImageServerEvent
  | ErrorEvent
  | DoneEvent
  | RequestDateRangeEvent
  | StrategyVersionEvent
  | FollowUpSuggestionsEvent;

/* Chat message model for the UI. */

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  blocks: MessageBlock[];
  timestamp: number;
}

export type MessageBlock =
  | { type: "text"; content: string }
  | { type: "code"; code: string; language: string }
  | { type: "progress"; step: string; status: string; detail: string }
  | { type: "table"; title: string; headers: string[]; rows: string[][]; formula?: string }
  | { type: "image"; url: string; alt: string }
  | { type: "error"; message: string }
  | { type: "strategy_version"; versionId: string };

/* Session summary from REST API. */

export interface SessionSummary {
  session_id: string;
  model: string;
  title?: string | null;
  active_ticker: string | null;
  active_strategy: string | null;
  messages: number;
  runs: number;
  updated_at: string;
  /** Number of strategy versions in this session that passed compliance (only those can be paper traded). */
  ready_for_paper_trading_count?: number;
}

/* Chart data from REST API. */

export interface OHLCVBar {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface SignalMarker {
  time: string;
  signal: "BUY" | "SELL";
  price: number;
}

/** Cumulative equity index (starts at 100; each closed trade adds its return %). From backtest signals. */
export interface EquityPoint {
  time: string;
  equity: number;
}

export interface ChartData {
  ticker: string;
  interval: string;
  ohlcv: OHLCVBar[];
  signals: SignalMarker[];
  indicators: Record<string, { time: string; value: number }[]>;
  /** Present after a backtest with signals in memory; drives equity/summary toggle. */
  equity_curve?: EquityPoint[] | null;
  backtest_summary?: Record<string, string> | null;
}

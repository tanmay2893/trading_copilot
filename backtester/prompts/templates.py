"""Prompt templates for code generation, debugging, and fixing."""

from __future__ import annotations

SYSTEM_PROMPT = """\
You are an expert quantitative finance Python developer. You implement whatever trading logic \
the user describes. The data may be any timeframe (1-minute, 5-minute, hourly, daily, weekly, monthly, etc.). \
Reason from the description: use pre-built or ta for standard indicators; \
for any other logic (derivatives, percentiles, custom formulas, filters) implement it in setup() \
and generate_signals() with pandas, numpy, and ta. If the user does not specify a parameter \
(e.g. RSI period, SMA length), use a standard default and expose it as an __init__ keyword argument with that default. \
IMPORTANT: Never use fillna(method=...) — it was removed in pandas 2. Use .ffill() or .bfill() instead. \
You ONLY output a Python class that subclasses BaseStrategy. No explanations, no markdown - just the code."""

PARAMETERS_RULE = """\
Parameters (required): Define ALL configurable parameters as keyword-only arguments in __init__ with sensible defaults, \
so the runner can pass overrides when rerunning. Override __init__ like this:

  def __init__(self, df, *, RSI_PERIOD=14, RSI_OVERSOLD=30, SMA_FAST=20, SMA_SLOW=50, **kwargs):
      super().__init__(df)
      self.RSI_PERIOD = RSI_PERIOD
      self.RSI_OVERSOLD = RSI_OVERSOLD
      self.SMA_FAST = SMA_FAST
      self.SMA_SLOW = SMA_SLOW

Use self.RSI_PERIOD, self.SMA_FAST, etc. in setup() and generate_signals(); do not hardcode numbers. \
If the user did not specify a value, choose a common default (e.g. RSI 14, SMA 20/50). \
The runner will pass user overrides as keyword arguments to __init__, so parameter names must match."""

AVAILABLE_INDICATORS = """\
Pre-built - use EXACT signatures (parameter names matter). All add_* functions modify df in place; call add_sma(self.df, 20) do NOT assign return value:
  add_sma(df, period, col="Close") -> column "SMA_{period}"
  add_ema(df, period, col="Close") -> column "EMA_{period}"
  add_rsi(df, period=14, col="Close") -> column "RSI"
  add_macd(df, fast=12, slow=26, signal=9) -> columns "MACD", "MACD_Signal", "MACD_Hist"
  add_bollinger(df, period=20, std_dev=2) -> "BB_Upper", "BB_Middle", "BB_Lower"
  add_atr(df, period=14, suffix=None) -> "ATR"; for multiple periods use suffix: add_atr(df, 5, suffix="5") -> "ATR_5"
  add_stochastic(df, k_period=14, d_period=3) -> "Stoch_K", "Stoch_D"
  add_williams_r(df, period=14) -> "Williams_R"
  add_cci(df, period=20) -> "CCI"
  add_adx(df, period=14) -> "ADX", "ADX_Pos", "ADX_Neg"
  add_vwap(df), add_obv(df) -> "VWAP", "OBV"
Pre-built functions have fixed semantics (e.g. add_rsi uses Close). If the user specifies a custom or named indicator with different inputs or formula (e.g. a variant on another price series, or with smoothing), implement it manually in setup() using pandas/ta—do NOT use the pre-built add_* when its semantics differ from what the user asked for.
Other indicators: use ta (ta.trend for CCI/ADX, ta.momentum for RSI/Stochastic); .ffill() then assign to self.df. Import from backtester.harness, not backtester.indicators.
"""

CORPORATE_DATA_GUIDANCE = """\
Corporate event columns available in self.df (present because the strategy involves corporate events):
  Dividends: "Dividend_Amount" (float, 0 on non-dividend days), "Is_Ex_Dividend" (bool)
  Splits: "Split_Ratio" (float, 1.0 on non-split days), "Is_Split_Day" (bool)
  Earnings: "Is_Earnings_Day" (bool, True on the date of an earnings report),
            "Days_To_Earnings" (int — distance in **trading days** (rows) to the nearest earnings date.
              Positive means earnings is N trading days ahead, negative means N trading days behind, 0 = earnings day.
              e.g. Days_To_Earnings==5 means "5 trading days before earnings", Days_To_Earnings==-1 means "1 trading day after earnings"),
            "EPS_Estimate" (float), "EPS_Actual" (float), "EPS_Surprise_Pct" (float, NaN if no data)
Use these columns directly in setup() and generate_signals(). They are already merged into self.df by date.
For example: self.df["Is_Earnings_Day"], self.df["Days_To_Earnings"], self.df["Dividend_Amount"], etc.
Do NOT try to fetch corporate data yourself — it is pre-loaded.
"""

CUSTOM_LOGIC_GUIDANCE = """\
Any other logic: implement in setup() with pandas/numpy. You have full pandas, numpy, ta.
- Derivatives: rate of change = .diff(); acceleration = .diff().diff()
- Percentiles: top 20% = .quantile(0.80); bottom 20% = .quantile(0.20)
- Fill NaN: use .ffill() or .fillna(0), never fillna(method='ffill') (deprecated in pandas 2).
- For "N consecutive bars then current bar expands": require the expansion (e.g. range > 1.5*ATR) on the same bar where the consecutive condition first holds, or use .shift(1) on the streak so you trigger one bar after the streak (expansion bar).
- For "close above highest high of the last N days": use .rolling(N).max().shift(1) so the highest high is from the previous N days (otherwise close cannot exceed today's high).
- Skip NaN rows in generate_signals() as needed.
"""

BASE_CLASS_DEF = """\
from abc import ABC, abstractmethod
import pandas as pd

class BaseStrategy(ABC):
    def __init__(self, df: pd.DataFrame):
        self.df = df.copy()
        self.signals: list[dict] = []

    @abstractmethod
    def setup(self) -> None:
        \"\"\"Compute indicators. Store as new self.df columns.\"\"\"
        ...

    @abstractmethod
    def generate_signals(self) -> None:
        \"\"\"Iterate self.df rows and append dicts to self.signals.
        Each dict MUST have EXACTLY 3 keys: {"date": <value>, "signal": "BUY"/"SELL", "price": <float>}
        Do NOT include extra keys (no target, stop_loss, etc.).
        \"\"\"
        ...

    def run(self) -> pd.DataFrame:
        self.setup()
        self.generate_signals()
        if not self.signals:
            return pd.DataFrame(columns=["Date", "Signal", "Price"])
        result = pd.DataFrame(self.signals)
        # Extracts only Date, Signal, Price — extra keys are ignored
        rename_map = {}
        for col in result.columns:
            lc = col.lower().strip()
            if lc == "date" and "Date" not in rename_map.values():
                rename_map[col] = "Date"
            elif lc == "signal" and "Signal" not in rename_map.values():
                rename_map[col] = "Signal"
            elif lc == "price" and "Price" not in rename_map.values():
                rename_map[col] = "Price"
        result = result.rename(columns=rename_map)
        if {"Date", "Signal", "Price"}.issubset(result.columns):
            return result[["Date", "Signal", "Price"]]
        result = result.iloc[:, :3]
        result.columns = ["Date", "Signal", "Price"]
        return result
"""


def _build_timeframe_section(data_interval: str) -> str:
    """Build a prompt section explaining the data timeframe to the LLM."""
    from backtester.data.interval import INTERVAL_LABELS, is_intraday

    label = INTERVAL_LABELS.get(data_interval, data_interval)
    section = f"Data timeframe: **{data_interval}** ({label})."

    if is_intraday(data_interval):
        section += (
            " Each row is one intraday bar. The Date column contains full datetime values (not just dates)."
            " Indicator periods apply to bars, not days — e.g. RSI(14) on 5m data covers 70 minutes."
            " Choose indicator periods appropriate for this timeframe."
        )
    elif data_interval in ("1wk", "1mo", "3mo"):
        section += (
            f" Each row represents one {label} bar."
            " Indicator periods apply to bars — e.g. SMA(20) on weekly data covers ~20 weeks."
            " Choose indicator periods appropriate for this longer timeframe."
        )
    else:
        section += " Each row is one trading day."

    return section


def _corporate_section(has_corporate_data: bool) -> str:
    if not has_corporate_data:
        return ""
    return f"\n## Corporate Event Data\n{CORPORATE_DATA_GUIDANCE}\n"


def build_codegen_prompt(
    strategy_description: str,
    data_columns: list[str],
    data_dtypes: dict[str, str],
    sample_rows: str,
    row_count: int,
    data_interval: str = "1d",
    has_corporate_data: bool = False,
) -> str:
    timeframe_section = _build_timeframe_section(data_interval)
    corporate_section = _corporate_section(has_corporate_data)
    return f"""\
Write a Python class called `Strategy` that subclasses `BaseStrategy`.

## User's Trading Strategy
{strategy_description}

## DataFrame Schema
self.df has {row_count} rows. Columns: {data_columns}. Dtypes: {data_dtypes}.
First 3 rows:
{sample_rows}

## Data Timeframe
{timeframe_section}

## BaseStrategy (do NOT redefine)
{BASE_CLASS_DEF}

## Parameters (required)
{PARAMETERS_RULE}

## Indicators and custom logic
{AVAILABLE_INDICATORS}
{CUSTOM_LOGIC_GUIDANCE}
{corporate_section}
## Rules
- **Completeness**: Implement every condition and concept from the user's description. Do not omit or merge distinct rules they state. If they name a custom indicator or define one with specific inputs (e.g. a different price series, smoothing, or formula), implement that in setup() using pandas/ta—do NOT use a pre-built add_* whose semantics differ (e.g. do not use add_rsi when the user asked for RSI on EMA or a custom-named variant). If they specify multiple entry filters, exit rules, or risk rules, implement all of them.
- Implement the strategy exactly as described. Use pre-built or ta for standard indicators; use pandas/numpy for any other logic (derivatives, percentiles, custom conditions). Reason about the user's words and implement accordingly.
- Put all tunable parameters as __init__ keyword-only arguments with defaults; assign to self and use them in setup() and generate_signals().
- In setup(): add all columns needed. In generate_signals(): iterate rows chronologically; track a single position (holding True/False). Only append BUY when not holding; only append SELL when holding; then flip position. Each signal dict must have EXACTLY 3 keys: {{"date": <value>, "signal": "BUY"/"SELL", "price": <float>}}. Do NOT include extra keys like target, stop_loss, reason, etc. Skip NaN rows where needed.
- Always import pandas as pd and use it for isna(), to_datetime(), etc. Import BaseStrategy and indicators from backtester.harness. No plotting, no file I/O. Output ONLY the Python code, no markdown."""


def build_fix_prompt(
    strategy_description: str,
    current_code: str,
    error_type: str,
    error_message: str,
    traceback_str: str,
    attempt_history: list[dict],
    data_columns: list[str],
    sample_rows: str = "",
    data_interval: str = "1d",
    has_corporate_data: bool = False,
) -> str:
    history_text = ""
    if attempt_history:
        history_text = "\n## Previous Attempts\n"
        for h in attempt_history:
            history_text += f"- Attempt {h['attempt']}: [{h['error_type']}] {h['message'][:150]}\n"

    sample_section = ""
    if sample_rows:
        sample_section = f"\n## Data Sample\n{sample_rows}\n"

    timeframe_section = _build_timeframe_section(data_interval)
    corporate_section = _corporate_section(has_corporate_data)

    return f"""\
Fix the following strategy code. It failed with an error.

## User's Strategy Description
{strategy_description}

## Data Timeframe
{timeframe_section}

## Current Code (BROKEN)
```python
{current_code}
```

## Error
Type: {error_type}
Message: {error_message}

Traceback:
{traceback_str}
{history_text}{sample_section}
## Available Indicators
{AVAILABLE_INDICATORS}

## Custom Logic
{CUSTOM_LOGIC_GUIDANCE}
{corporate_section}
## Parameters
{PARAMETERS_RULE}

## DataFrame Columns
{data_columns}

## Rules
- Output ONLY the complete fixed Python code. Keep tunable parameters as __init__ keyword-only arguments with defaults.
- If the error mentions fillna(method=...) or 'unexpected keyword argument', use .ffill() instead of fillna(method='ffill').
- If the error mentions "Length mismatch" in column assignment, ensure each signal dict has EXACTLY 3 keys: {{"date": ..., "signal": "BUY"/"SELL", "price": <float>}}. Do NOT include extra keys.
- Fix the specific error. No markdown, no explanation."""


def build_anti_loop_prompt(
    strategy_description: str,
    current_code: str,
    repeated_error: str,
    repeat_count: int,
    data_columns: list[str],
    sample_rows: str,
    data_interval: str = "1d",
    has_corporate_data: bool = False,
) -> str:
    timeframe_section = _build_timeframe_section(data_interval)
    corporate_section = _corporate_section(has_corporate_data)
    return f"""\
The previous approach has FAILED {repeat_count} times with the same error.
You MUST take a COMPLETELY DIFFERENT approach to implementing this strategy.

## User's Strategy Description
{strategy_description}

## Data Timeframe
{timeframe_section}

## Failing Code (DO NOT use this approach again)
```python
{current_code}
```

## Repeated Error ({repeat_count} times)
{repeated_error}

## Data Sample
{sample_rows}

## DataFrame Columns
{data_columns}

## Available Indicators
{AVAILABLE_INDICATORS}

## Custom Logic
{CUSTOM_LOGIC_GUIDANCE}
{corporate_section}
## Parameters
{PARAMETERS_RULE}

## Instructions
- Take a COMPLETELY DIFFERENT approach. Keep parameters as __init__ keyword-only arguments with defaults.
- Each signal dict must have EXACTLY 3 keys: {{"date": ..., "signal": "BUY"/"SELL", "price": <float>}}. No extra keys.
- Output ONLY the Python code."""


PARAMETER_EXTRACTION_PROMPT = """\
Below is a Python Strategy class for backtesting. List every configurable parameter (__init__ keyword argument with default, or class-level constant) that the user might want to see or change.

For each parameter output exactly one line in this format:
  NAME = value  # short description

Use the parameter name and default value as in the code. Add a brief description (e.g. "RSI period", "oversold threshold"). Output only these lines, no other text. If there are no such parameters, output: (none)
"""


REFINE_SYSTEM_PROMPT = """\
You are an expert quantitative finance Python developer. You modify existing trading strategies \
based on user requests. Preserve all existing logic unless the change explicitly contradicts it. \
You ONLY output a Python class that subclasses BaseStrategy. No explanations, no markdown - just the code."""


def build_refine_prompt(
    current_code: str,
    change_request: str,
    strategy_description: str,
    conversation_history: str,
    data_columns: list[str],
    data_dtypes: dict[str, str],
    sample_rows: str,
    row_count: int,
    data_interval: str = "1d",
    has_corporate_data: bool = False,
    baseline_buy_count: int | None = None,
    baseline_sell_count: int | None = None,
    is_selected_version: bool = False,
) -> str:
    timeframe_section = _build_timeframe_section(data_interval)
    corporate_section = _corporate_section(has_corporate_data)

    history_section = ""
    if conversation_history:
        history_section = f"""
## Conversation History (previous modifications)
{conversation_history}
"""

    baseline_section = ""
    if isinstance(baseline_buy_count, int) and isinstance(baseline_sell_count, int):
        baseline_section = f"""
## Previous Run Summary
Before this change, the strategy produced BUY={baseline_buy_count}, SELL={baseline_sell_count} signals.
If the requested change is a restriction or filter on when to buy, your refinement should
not increase the number of BUY signals (it may decrease them)."""

    selected_version_section = ""
    if is_selected_version:
        selected_version_section = """
## Important: Selected version
The code below is the strategy version the user selected in the strategies panel. You MUST modify this code according to the user's message to create a new version. Do not use any other code as the base.

"""

    return f"""\
Modify the existing strategy code to incorporate the requested change.
Preserve all existing logic unless the change explicitly contradicts it.

## Original Strategy Description
{strategy_description}
{history_section}
{baseline_section}
{selected_version_section}## Current Working Code
```python
{current_code}
```

## Requested Change
{change_request}

## DataFrame Schema
self.df has {row_count} rows. Columns: {data_columns}. Dtypes: {data_dtypes}.
First 3 rows:
{sample_rows}

## Data Timeframe
{timeframe_section}

## BaseStrategy (do NOT redefine)
{BASE_CLASS_DEF}

## Parameters (required)
{PARAMETERS_RULE}

## Indicators and custom logic
{AVAILABLE_INDICATORS}
{CUSTOM_LOGIC_GUIDANCE}
{corporate_section}
## Rules
- Apply the requested change while preserving the rest of the strategy logic.
- Keep all tunable parameters as __init__ keyword-only arguments with defaults.
- In generate_signals(): track a single position (holding True/False). Only BUY when not holding; only SELL when holding.
- Import BaseStrategy and indicators from backtester.harness. No plotting, no file I/O.
- Output ONLY the complete modified Python code, no markdown."""


def build_refine_fix_prompt(
    current_code: str,
    change_request: str,
    strategy_description: str,
    error_type: str,
    error_message: str,
    traceback_str: str,
    data_columns: list[str],
    data_interval: str = "1d",
    has_corporate_data: bool = False,
    is_selected_version: bool = False,
) -> str:
    timeframe_section = _build_timeframe_section(data_interval)
    corporate_section = _corporate_section(has_corporate_data)

    selected_note = ""
    if is_selected_version:
        selected_note = " The code below is the selected version; fix it while still applying the user's change.\n\n"

    return f"""\
The strategy modification attempt failed with an error.
Fix the error while still incorporating the requested change.{selected_note}
## Original Strategy Description
{strategy_description}

## Requested Change
{change_request}

## Data Timeframe
{timeframe_section}

## Current Code (BROKEN)
```python
{current_code}
```

## Error
Type: {error_type}
Message: {error_message}

Traceback:
{traceback_str}

## Available Indicators
{AVAILABLE_INDICATORS}

## Custom Logic
{CUSTOM_LOGIC_GUIDANCE}
{corporate_section}
## Parameters
{PARAMETERS_RULE}

## DataFrame Columns
{data_columns}

## Rules
- Fix the specific error while keeping the requested change intact.
- Keep tunable parameters as __init__ keyword-only arguments with defaults; assign in __init__ and use self.param in setup/generate_signals.
- If the error mentions fillna(method=...), use .ffill() instead.
- Output ONLY the complete fixed Python code. No markdown, no explanation."""


CHANGE_SUMMARY_PROMPT = """\
Below is a before/after diff of a Python trading strategy. The user requested this change:
"{change_request}"

Summarize what was actually changed in 1-2 short bullet points. Be specific about parameter values, \
indicators added/removed, or logic changes. No preamble, just the bullets."""


def build_change_summary_prompt(
    code_before: str,
    code_after: str,
    change_request: str,
) -> str:
    return f"""\
{CHANGE_SUMMARY_PROMPT.format(change_request=change_request)}

## Before
```python
{code_before}
```

## After
```python
{code_after}
```"""


# ---------------------------------------------------------------------------
# Post-execution code review
# ---------------------------------------------------------------------------

REVIEW_SYSTEM_PROMPT = """\
You are an expert code reviewer specializing in quantitative trading strategies. \
You compare generated Python code against the user's original strategy description \
to verify correctness. \
Verify that every condition, indicator definition, and rule from the description is \
present in the code: if the user specified a custom or named indicator (or one with \
specific inputs), the code must implement that—not a standard substitute. If they \
specified multiple entry filters, exit rules, or risk rules, all must be implemented. \
Flag as "fix" when any specified element is missing or replaced by a different rule. \
Do NOT flag stylistic preferences or minor implementation choices. Approve only when \
the code faithfully implements the full strategy as described."""


def build_review_prompt(
    strategy_description: str,
    generated_code: str,
    signal_count: int,
    buy_count: int,
    sell_count: int,
    sample_signals: str,
    data_interval: str = "1d",
    has_corporate_data: bool = False,
    data_row_count: int | None = None,
    data_date_range_str: str | None = None,
    signal_date_range_str: str | None = None,
) -> str:
    """Build a prompt that asks the LLM to review generated code for correctness.

    Optional data_row_count, data_date_range_str, and signal_date_range_str
    give the LLM context to judge whether signal count and distribution are
    plausible given the user's strategy (e.g. few bars vs many signals).
    """
    timeframe_section = _build_timeframe_section(data_interval)
    corporate_section = _corporate_section(has_corporate_data)

    execution_context = ""
    if data_row_count is not None or data_date_range_str or signal_date_range_str:
        parts = []
        if data_row_count is not None:
            parts.append(f"Data: {data_row_count} rows.")
        if data_date_range_str:
            parts.append(f"Data date range: {data_date_range_str}.")
        if signal_date_range_str:
            parts.append(f"Signals span: {signal_date_range_str}.")
        execution_context = (
            "\n## Signal and data context\n"
            + " ".join(parts)
            + "\nUse this to judge whether the number and distribution of signals are plausible "
            "for the described strategy (e.g. a very selective rule may yield few signals; "
            "a per-bar condition may yield many). Flag if the output seems inconsistent with "
            "the user's description (e.g. user asked to restrict or filter but the signal count "
            "or pattern suggests the condition was not applied correctly).\n"
        )

    return f"""\
Review the generated strategy code below. Your job is to check whether it
correctly and faithfully implements the user's described trading strategy.

## User's Original Strategy Description
{strategy_description}

## Data Timeframe
{timeframe_section}
{corporate_section}
## Generated Code
```python
{generated_code}
```

## Execution Results
The code ran successfully and produced:
- Total signals: {signal_count} ({buy_count} BUY, {sell_count} SELL)
- Sample signals (first 10):
{sample_signals}
{execution_context}
## Available Indicators (for reference)
{AVAILABLE_INDICATORS}

## Your Task
Compare the code against the user's strategy description. Check for:
- **Completeness**: Is every condition, indicator, and rule from the description present in the code? If the user specified a custom or named indicator (or one with specific inputs, e.g. a different price series or smoothing), the code must implement that exact formulation in setup()—using a pre-built add_* that has different semantics (e.g. add_rsi which uses Close when the user asked for the indicator on EMA, or a custom-named variant) is wrong; return "fix" and list it as an issue. If they specified multiple entry filters, exit rules, or risk rules, are all of them implemented?
- Logical correctness: Are the BUY/SELL conditions fundamentally wrong (e.g., buying when should sell)?
- Parameter alignment: Are indicator parameters wildly off from what the user specified?
- Position tracking: Can we buy twice without selling, or is alternation broken?
- Plausibility of output: Given the strategy text and the data/signal context above, could there reasonably be this many or this few signals? If the user described a restrictive condition and the signal count or pattern suggests that restriction was not applied, flag it.

Return "ok" (approve) only when the code faithfully implements the full strategy as described. Return "fix" when any specified element is missing or replaced by a different rule, or when there are clear material errors. Do not flag stylistic or minor implementation choices. The code already passed execution and validation.

Respond with this JSON structure ONLY (no other text):
{{
  "verdict": "ok or fix",
  "issues": ["list of specific issues found, empty array if ok"],
  "fix_instructions": "specific instructions for fixing the code, null if ok"
}}"""


def build_review_fix_prompt(
    strategy_description: str,
    current_code: str,
    review_issues: list[str],
    fix_instructions: str,
    data_columns: list[str],
    sample_rows: str,
    data_interval: str = "1d",
    has_corporate_data: bool = False,
) -> str:
    """Build a prompt to fix code based on review feedback."""
    timeframe_section = _build_timeframe_section(data_interval)
    corporate_section = _corporate_section(has_corporate_data)

    issues_text = "\n".join(f"  {i+1}. {issue}" for i, issue in enumerate(review_issues))

    return f"""\
The strategy code below was reviewed and found to have issues.
Fix the code according to the review feedback.

## User's Strategy Description
{strategy_description}

## Data Timeframe
{timeframe_section}

## Current Code (needs fixing)
```python
{current_code}
```

## Review Issues Found
{issues_text}

## Fix Instructions
{fix_instructions}

## DataFrame Columns
{data_columns}

## Data Sample
{sample_rows}

## Available Indicators
{AVAILABLE_INDICATORS}

## Custom Logic
{CUSTOM_LOGIC_GUIDANCE}
{corporate_section}
## Parameters
{PARAMETERS_RULE}

## Rules
- Fix the specific review issues while keeping the rest of the strategy intact.
- The BUY and SELL conditions must faithfully match the user's strategy description.
- Keep tunable parameters as __init__ keyword-only arguments with defaults; assign in __init__ and use self.param in setup/generate_signals.
- In generate_signals(): track a single position (holding True/False). Only BUY when not holding; only SELL when holding.
- Each signal dict must have EXACTLY 3 keys: {{"date": ..., "signal": "BUY"/"SELL", "price": <float>}}. No extra keys.
- Output ONLY the complete fixed Python code. No markdown, no explanation."""


# ---------------------------------------------------------------------------
# Mid-loop stuck diagnosis
# ---------------------------------------------------------------------------

DIAGNOSIS_SYSTEM_PROMPT = """\
You are a senior quantitative trading strategy analyst debugging a backtesting \
pipeline that is stuck. You diagnose why the strategy cannot produce valid \
trading signals and, when the strategy description itself is the problem, \
propose a minimal relaxation that preserves the original intent."""


def build_diagnosis_prompt(
    strategy_description: str,
    error_history: list[dict],
    last_code: str,
    row_count: int,
    interval: str,
    columns: list[str],
    has_corporate_data: bool = False,
) -> str:
    """Build a context-dump prompt for diagnosing why the iteration loop is stuck."""
    from backtester.data.interval import INTERVAL_LABELS

    interval_label = INTERVAL_LABELS.get(interval, interval)

    error_lines = []
    for e in error_history[-8:]:
        error_lines.append(
            f"  Attempt {e.get('attempt', '?')}: [{e.get('error_type', '?')}] "
            f"{e.get('message', '')[:200]}"
        )
    error_section = "\n".join(error_lines) if error_lines else "  (no errors recorded)"

    corporate_note = ""
    if has_corporate_data:
        corp_cols = [c for c in columns if c in (
            "Dividend_Amount", "Is_Ex_Dividend", "Split_Ratio", "Is_Split_Day",
            "Is_Earnings_Day", "Days_To_Earnings", "EPS_Estimate", "EPS_Actual",
            "EPS_Surprise_Pct",
        )]
        if corp_cols:
            corporate_note = f"\nCorporate event columns present: {', '.join(corp_cols)}"

    code_section = last_code[:3000] if last_code else "(no code generated yet)"

    return f"""\
The backtesting pipeline has been stuck for multiple iterations. It keeps
failing to produce valid trading signals (at least 1 BUY and 1 SELL).
Diagnose the root cause and, if the strategy description itself is the
problem, propose a minimal relaxation.

## Original Strategy Description
{strategy_description}

## Data Context
- Interval: {interval} ({interval_label})
- Total data rows: {row_count}
- Available columns: {', '.join(columns)}{corporate_note}

## Error History (recent attempts)
{error_section}

## Last Generated Code
```python
{code_section}
```

## Your Task
1. Diagnose WHY the strategy is not producing signals.
2. Determine the root cause:
   - "strategy_too_restrictive": the buy/sell conditions are too strict for this data
   - "code_bug": the code has a bug that could be fixed without changing the strategy
   - "data_issue": the data does not contain what the strategy needs
   - "other": something else
3. If root_cause is "strategy_too_restrictive" or "data_issue", propose a
   MINIMAL relaxation that preserves the original intent but will actually
   produce signals. Make the fewest changes possible.

Respond with this JSON structure ONLY (no other text):
{{
  "diagnosis": "explanation of why it is stuck",
  "root_cause": "strategy_too_restrictive | code_bug | data_issue | other",
  "revised_strategy": "relaxed strategy text preserving original intent, or null if not applicable",
  "explanation": "what was changed and why, or null"
}}"""


# ---------------------------------------------------------------------------
# Strategy pre-flight analysis
# ---------------------------------------------------------------------------

ANALYSIS_SYSTEM_PROMPT = """\
You are a senior quantitative trading strategy analyst. You review strategies \
before they get coded and flag anything that would prevent the strategy from \
producing valid trading signals. Be practical, concise, and constructive. \
When you suggest a revision, keep the spirit of the original strategy intact \
while making the minimum changes needed for it to work."""


def build_analysis_prompt(
    strategy_text: str,
    ticker: str,
    interval: str,
    start: str,
    end: str,
    was_clamped: bool,
    row_count: int,
    columns: list[str],
    corporate_needs: set[str],
    corporate_summary: dict[str, int],
) -> str:
    """Assemble a context-dump prompt for the LLM to analyze the strategy."""
    from backtester.data.interval import INTERVAL_LABELS, INTERVAL_MAX_DAYS

    interval_label = INTERVAL_LABELS.get(interval, interval)

    clamp_note = ""
    if was_clamped:
        max_d = INTERVAL_MAX_DAYS.get(interval, 0)
        clamp_note = (
            f" (date range was CLAMPED from the user's original request "
            f"because yfinance limits {interval} data to the last ~{max_d} days)"
        )

    if corporate_needs and corporate_summary:
        event_lines = []
        for key, count in corporate_summary.items():
            event_lines.append(f"  - {key}: {count} found in data")
        event_section = "Corporate events detected and fetched:\n" + "\n".join(event_lines)
    elif corporate_needs:
        event_section = (
            "Corporate events detected in strategy keywords: "
            + ", ".join(sorted(corporate_needs))
            + " (but no events found in the data range)"
        )
    else:
        event_section = "No corporate event data needed for this strategy."

    interval_table = "\n".join(
        f"  {k}: max {v} days of history"
        for k, v in sorted(INTERVAL_MAX_DAYS.items(), key=lambda x: x[1])
        if v < 100_000
    )

    return f"""\
You are reviewing a trading strategy before it gets coded and backtested.
Your job is to identify any issues that would prevent it from producing valid
trading signals, and if needed, propose a revised version that fixes the problems.

## Strategy
{strategy_text}

## Data Context
- Ticker: {ticker}
- Interval: {interval} ({interval_label}){clamp_note}
- Date range: {start} -> {end}
- Total data rows: {row_count}
- Available columns: {', '.join(columns)}

## Corporate Event Summary
{event_section}

## Platform Constraints
yfinance intraday data limits (max history from today):
{interval_table}
  Daily/weekly/monthly: unlimited history

General facts:
- Corporate events are sparse: typically ~4 earnings/year, ~4 dividends/year, stock splits are very rare (0-2 per decade).
- The backtesting engine requires at least 1 BUY and 1 SELL signal to pass validation.
- Indicators need sufficient rows for warm-up (e.g. SMA 200 needs 200+ rows).

## Available Technical Indicators
{AVAILABLE_INDICATORS}

## Your Task
Analyze this strategy given the context above. Think about whether it will
actually produce trading signals with this data. Consider everything you think
is relevant — timeframe compatibility, data availability, condition feasibility,
event frequency, indicator warm-up, logical contradictions, or anything else.

If the strategy looks fine, return verdict "ok".
If you see issues, return verdict "revise" with a corrected strategy that
preserves the original intent but fixes the problems. Make minimal changes.

Respond with this JSON structure ONLY (no other text):
{{
  "verdict": "ok or revise",
  "issues": ["list of issues found, empty array if ok"],
  "revised_strategy": "improved strategy text if revise, null if ok",
  "explanation": "brief explanation of changes if revise, null if ok"
}}"""


def build_reanalysis_prompt(
    strategy_text: str,
    issues: list[str],
    previous_revision: str,
    user_feedback: str,
    ticker: str,
    interval: str,
    start: str,
    end: str,
    row_count: int,
    columns: list[str],
    revision_history: list[dict] | None = None,
) -> str:
    """Build a prompt for re-analyzing a strategy with user feedback on why they rejected the revision."""
    from backtester.data.interval import INTERVAL_LABELS

    interval_label = INTERVAL_LABELS.get(interval, interval)

    history_section = ""
    if revision_history:
        history_section = "\n## Previous Revision Attempts (user rejected all of these)\n"
        for i, entry in enumerate(revision_history, 1):
            history_section += f"  {i}. Suggested: \"{entry['revision'][:200]}\"\n"
            history_section += f"     User feedback: \"{entry['feedback']}\"\n"

    issues_text = "\n".join(f"  - {issue}" for issue in issues) if issues else "  (none)"

    return f"""\
You previously analyzed a trading strategy and suggested a revision, but the
user was not satisfied. Generate a NEW alternative revision that addresses
their feedback while still fixing the original issues.

## Original Strategy
{strategy_text}

## Issues Found
{issues_text}

## Your Previous Revision (rejected by user)
{previous_revision}

## User's Feedback
"{user_feedback}"
{history_section}
## Data Context
- Ticker: {ticker}
- Interval: {interval} ({interval_label})
- Date range: {start} -> {end}
- Total data rows: {row_count}
- Available columns: {', '.join(columns)}

## Available Technical Indicators
{AVAILABLE_INDICATORS}

## Instructions
- Address the user's feedback while still fixing any genuine issues.
- If the user wants to keep something from the original, preserve it.
- If the user's feedback contradicts the issues, prioritize the user's intent.
- Make the minimum changes needed. Preserve the spirit of the original strategy.
- Produce a strategy that will generate at least 1 BUY and 1 SELL signal.

Respond with this JSON structure ONLY (no other text):
{{
  "verdict": "revise",
  "issues": ["updated list of issues, incorporating user feedback"],
  "revised_strategy": "new revised strategy text",
  "explanation": "brief explanation of what changed and why, addressing the user's feedback"
}}"""


REANALYSIS_SYSTEM_PROMPT = """\
You are a senior quantitative trading strategy analyst. A user rejected your \
previous strategy revision and gave feedback. Generate a better alternative \
that addresses their concerns while still ensuring the strategy is practical \
and will produce valid trading signals. Be responsive to the user's intent."""


def build_parameter_extraction_prompt(strategy_code: str) -> str:
    return f"""\
{PARAMETER_EXTRACTION_PROMPT}

## Strategy code
```python
{strategy_code}
```"""


# ---------------------------------------------------------------------------
# Chart indicator selection (two-phase: classify + review)
# ---------------------------------------------------------------------------

INDICATOR_SELECTION_SYSTEM_PROMPT = """\
You are an expert quantitative finance analyst specializing in technical analysis visualization. \
You analyze trading strategy code and classify computed indicator columns for chart overlay purposes. \
Be precise: only include columns that are meaningful for end-user visualization."""


def build_indicator_selection_prompt(
    strategy_code: str,
    indicator_columns: list[str],
    original_columns: list[str],
) -> str:
    return f"""\
Analyze the following trading strategy code and classify the computed indicator columns
for chart visualization.

## Strategy Code
```python
{strategy_code}
```

## Original Data Columns (OHLCV)
{original_columns}

## Computed Indicator Columns (added by the strategy in setup())
{indicator_columns}

## Classification Rules
Classify each computed column into exactly ONE category:

1. **overlay**: Continuous indicators on the SAME SCALE as price — overlay directly on the
   OHLCV candlestick chart. Examples: SMA, EMA, Bollinger Bands (Upper/Middle/Lower), VWAP,
   Parabolic SAR, Ichimoku cloud lines, Keltner Channel, Donchian Channel.

2. **oscillator**: Continuous indicators on a DIFFERENT SCALE — shown in a sub-panel below
   the price chart. Examples: RSI, MACD, MACD_Signal, MACD_Hist, Stochastic K/D, CCI,
   Williams %R, ADX, OBV, ATR (if used as a standalone indicator, not just internally).

3. **internal**: Boolean flags, intermediate calculations, temporary helper columns, or
   values that are NOT meaningful for end-user visualization. Examples: position tracking
   booleans, streak counters used only in signal logic, threshold flags, NaN masks.

## Important
- Only classify columns that exist in the "Computed Indicator Columns" list above.
- If a column is used ONLY as an intermediate step for computing other indicators and
  has no standalone visual meaning, classify it as "internal".
- ATR used as a volatility measure visible to the user = oscillator.
  ATR used only to compute stop-loss levels internally = internal.
- When in doubt, prefer including a column (overlay/oscillator) over excluding it.

Respond with this JSON structure ONLY (no other text):
{{
  "overlay": ["col1", "col2"],
  "oscillator": ["col3", "col4"],
  "internal": ["col5", "col6"],
  "reasoning": "brief explanation of the classification decisions"
}}"""


def build_indicator_review_prompt(
    strategy_description: str,
    strategy_code: str,
    overlay_cols: list[str],
    oscillator_cols: list[str],
    internal_cols: list[str],
    reasoning: str,
) -> str:
    return f"""\
Review the following indicator classification for a trading strategy's chart output.
Your job is to catch any mistakes and finalize the selection.

## User's Strategy Description
{strategy_description}

## Strategy Code
```python
{strategy_code}
```

## Proposed Classification
- **Overlay** (on price chart, same scale): {overlay_cols}
- **Oscillator** (sub-panel, different scale): {oscillator_cols}
- **Internal** (excluded from output): {internal_cols}

## Classification Reasoning
{reasoning}

## Review Checklist
1. Are ALL overlay indicators truly on the same scale as price? (e.g., SMA/EMA of price = yes;
   RSI = no, it's 0-100)
2. Are oscillators correctly identified? (different scale, but still meaningful to visualize)
3. Were any useful continuous indicators mistakenly classified as internal?
4. Were any temporary/boolean columns mistakenly included as overlay or oscillator?
5. Does the selection align with what the user's strategy description would expect to see?

If the classification is correct, return it unchanged.
If there are issues, fix them and explain what you changed.

Respond with this JSON structure ONLY (no other text):
{{
  "overlay": ["col1", "col2"],
  "oscillator": ["col3", "col4"],
  "reasoning": "what was changed and why, or 'classification confirmed — no changes needed'"
}}"""


INDICATOR_REVIEW_SYSTEM_PROMPT = """\
You are a senior quantitative analyst reviewing indicator classifications for chart output. \
Verify that overlay indicators share the price scale, oscillators are on their own scale, \
and no useful indicators were excluded. Be concise and precise."""

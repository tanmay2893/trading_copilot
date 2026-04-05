# Paper-Trading Compliance (Pre-requisites)

Before a user can paper-trade a strategy version, they must pass two checks. The UI should gate "Paper trade" on these.

## 1. Reproducibility check

- **When**: User selects a strategy **version** to paper-trade and starts the flow.
- **What**: Only commands **before** that version are used:
  - Initial strategy text (from the first `run_backtest`)
  - Ordered list of refinement/fix requests that produced versions up to the selected one (from the version manifest).
- **How**:
  1. Rebuild the strategy from scratch: generate code from the initial strategy, then apply each change request in order (same pipeline as the agent: iterate then refine/fix).
  2. Run the **original** version code and the **rebuilt** code on the **same** data (same ticker, date range, interval as stored in the manifest).
  3. Compare signals (BUY/SELL dates). If identical → **pass**.
  4. If **not** identical: run the rebuild **again** from the beginning. Compare all three: original, rebuild 1, rebuild 2. The system shows:
     - Structured diagnostics: signal count changes (BUY/SELL) and likely causes (e.g. different indicator parameters, date/bar handling, floating-point comparison, ambiguous refinement wording).
     - An LLM summary and bullets tied to the actual diffs.
  5. User must **choose** which to use: **original**, **rebuild_1**, or **rebuild_2**. That choice is stored and counts as reproducibility passed for that version.
  6. On the choice screen, user can **Run reproducibility check again** to retry (fresh rebuilds). Results can differ each run; use this to verify before choosing a version for paper trading.

**API**

- `POST /api/sessions/{session_id}/compliance/reproducibility`  
  Body: `{ "version_id": "..." }`  
  Returns: `passed` (true/false), or `choice_required: true` with `summary`, `summary_bullets`, `options` (original, rebuild_1, rebuild_2).
- `POST /api/sessions/{session_id}/compliance/reproducibility/choose`  
  Body: `{ "version_id": "...", "choice": "original" | "rebuild_1" | "rebuild_2" }`  
  Records the choice and marks reproducibility as passed.

## 2. Strategy understanding quiz

- **When**: After reproducibility is passed (or after user has chosen an option).
- **What**: AI-generated questions (yes/no or multiple choice) about the strategy (triggers, exits, indicators, and at least one risk-awareness question). Correct answers are stored server-side.
- **How**: User answers; backend grades. **Pass** = all correct. On pass, compliance status is updated; if reproducibility was already passed, `paper_trading_unlocked_at` is set.

**API**

- `POST /api/sessions/{session_id}/compliance/quiz/generate`  
  Body: `{ "version_id": "..." }`  
  Returns: `questions` (array of `{ id, question, options }`). Correct indices are stored under `compliance/quiz_{version_id}.json`.
- `POST /api/sessions/{session_id}/compliance/quiz/submit`  
  Body: `{ "version_id": "...", "answers": [0, 1, ...] }`  
  Returns: `passed`, `score`, `message`. On pass, updates compliance and may set `paper_trading_unlocked_at`.

## 3. Compliance status

- **When**: Before showing "Paper trade" or after each step.
- **What**: Stored per session per version under `sessions/{session_id}/compliance/{version_id}.json`:  
  `reproducibility_passed`, `reproducibility_choice` (if any), `quiz_passed`, `paper_trading_unlocked_at`, `updated_at`.
- **Ready for paper trading**: `reproducibility_passed` and `quiz_passed` are both true **for that version**. Only strategy version(s) that have passed both checks may be paper traded; other versions in the same session are not eligible until they pass compliance.

**API**

- `GET /api/sessions/{session_id}/compliance/status?version_id=...`  
  Returns: `reproducibility_passed`, `reproducibility_choice`, `quiz_passed`, `paper_trading_unlocked_at`, `ready_for_paper_trading`, `updated_at`.
- `GET /api/sessions/{session_id}/compliance/ready-versions`  
  Returns: `versions` — only strategy versions in this session that have passed both reproducibility and quiz. **Only these versions may be paper traded.** Use this list when implementing the paper-trade version selector.

Session list and session detail include `ready_for_paper_trading_count` (and session detail includes `ready_for_paper_trading_versions`) so the UI can show how many versions in that session are eligible for paper trading.

## Version manifest

Every time a strategy version is saved (after `run_backtest`, `refine_strategy`, or `fix_strategy`), an entry is appended to `sessions/{session_id}/strategy_versions/manifest.json`:

- `version_id`, `created_at`, `source` (`run_backtest` | `refine` | `fix`)
- For `run_backtest`: `strategy_text`, `ticker`, `start_date`, `end_date`, `interval`
- For `refine` / `fix`: `change_request`

This allows "commands up to version X" to be reconstructed for reproducibility.

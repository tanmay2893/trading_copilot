"""Strategy understanding quiz: generate questions and grade answers."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backtester.agent.session import AGENT_SESSIONS_DIR
from backtester.llm.base import BaseLLMProvider


@dataclass
class QuizQuestion:
    id: str
    question: str
    options: list[str]
    correct_index: int


def _compliance_dir(session_id: str) -> Path:
    return AGENT_SESSIONS_DIR / session_id / "compliance"


def _quiz_state_path(session_id: str, version_id: str) -> Path:
    return _compliance_dir(session_id) / f"quiz_{version_id}.json"


def generate_quiz_questions(
    provider: BaseLLMProvider,
    strategy_code: str,
    strategy_description: str,
    session_id: str,
    version_id: str,
    num_questions: int = 5,
) -> dict[str, Any]:
    """
    Generate multiple-choice and yes/no questions about the strategy.
    Persists correct indices server-side for grading. Returns questions without correct answer.
    """
    prompt = f"""You are creating a short quiz to verify that a user understands their trading strategy before they paper trade it.

Strategy description (natural language):
{strategy_description[:2000]}

Strategy code (Python):
```python
{strategy_code[:4000]}
```

Generate exactly {num_questions} questions. Mix of:
- What triggers a BUY / what triggers a SELL
- Which indicators or conditions are used
- One risk-awareness question: e.g. "Backtest results do not guarantee future performance. Yes or No?" or "Paper trading can still result in losses. True or False?"
- What market conditions might make this strategy underperform

For each question, provide 2-4 short options. One option must be correct.

Format your response as JSON only, no markdown:
{{
  "questions": [
    {{ "question": "...", "options": ["A", "B", "C"], "correct_index": 0 }},
    ...
  ]
}}
Use correct_index 0-based (0 = first option). Output only valid JSON."""

    resp = provider.generate(prompt, "You output only valid JSON. No explanation.")
    text = resp.content.strip()
    # Strip markdown code block if present
    if "```" in text:
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if match:
            text = match.group(1).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {"questions": [], "error": "Failed to parse quiz from model"}

    questions_data = data.get("questions", [])
    if not isinstance(questions_data, list):
        return {"questions": [], "error": "Invalid quiz format"}

    questions_out: list[dict] = []
    correct_indices: list[int] = []

    for i, q in enumerate(questions_data[:num_questions]):
        if not isinstance(q, dict):
            continue
        opts = q.get("options") or []
        if not opts or not isinstance(opts, list):
            continue
        correct_index = int(q.get("correct_index", 0))
        if correct_index < 0 or correct_index >= len(opts):
            correct_index = 0
        qid = f"q{i}"
        questions_out.append({
            "id": qid,
            "question": str(q.get("question", "")).strip() or f"Question {i+1}",
            "options": [str(o) for o in opts],
        })
        correct_indices.append(correct_index)

    _compliance_dir(session_id).mkdir(parents=True, exist_ok=True)
    state_path = _quiz_state_path(session_id, version_id)
    state_path.write_text(
        json.dumps({"correct_indices": correct_indices}, indent=2),
        encoding="utf-8",
    )

    return {"questions": questions_out}


def grade_quiz(
    session_id: str,
    version_id: str,
    answers: list[int],
) -> dict[str, Any]:
    """
    Grade submitted answers. answers[i] is the selected option index for question i.
    Returns { "passed": bool, "score": str, "message": str }.
    """
    state_path = _quiz_state_path(session_id, version_id)
    if not state_path.exists():
        return {"passed": False, "score": "0/0", "message": "No quiz generated for this version. Generate quiz first."}

    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        correct_indices = state.get("correct_indices", [])
    except (json.JSONDecodeError, OSError):
        return {"passed": False, "score": "0/0", "message": "Quiz state invalid."}

    if len(answers) != len(correct_indices):
        return {
            "passed": False,
            "score": f"{sum(1 for a, c in zip(answers, correct_indices) if a == c)}/{len(correct_indices)}",
            "message": "Number of answers does not match number of questions.",
        }

    correct = sum(1 for a, c in zip(answers, correct_indices) if a == c)
    total = len(correct_indices)
    passed = correct == total

    return {
        "passed": passed,
        "score": f"{correct}/{total}",
        "message": "All correct. You can proceed to paper trading (when available)." if passed else f"Please review the strategy and try again. Score: {correct}/{total}.",
    }

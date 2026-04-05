"""Paper-trading compliance: reproducibility check and strategy understanding quiz."""

from __future__ import annotations

from backtester.compliance.manifest import (
    get_commands_up_to_version,
    load_manifest,
)
from backtester.compliance.reproducibility import run_reproducibility
from backtester.compliance.quiz import generate_quiz_questions, grade_quiz
from backtester.compliance.status import (
    compliance_ready_for_paper_trading,
    load_compliance_status,
    save_compliance_status,
)

__all__ = [
    "compliance_ready_for_paper_trading",
    "get_commands_up_to_version",
    "load_manifest",
    "run_reproducibility",
    "generate_quiz_questions",
    "grade_quiz",
    "load_compliance_status",
    "save_compliance_status",
]

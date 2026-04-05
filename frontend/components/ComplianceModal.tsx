"use client";

import { useCallback, useEffect, useState } from "react";
import { fetchComplianceVersions, type ComplianceVersionOption } from "@/lib/api";
import {
  fetchComplianceStatus,
  runReproducibilityCheck,
  chooseReproducibility,
  generateComplianceQuiz,
  submitComplianceQuiz,
  type QuizQuestion,
} from "@/lib/api";

interface ComplianceModalProps {
  sessionId: string;
  onClose: () => void;
}

type Step = "version" | "reproducibility" | "repro_choice" | "quiz" | "done";

export function ComplianceModal({ sessionId, onClose }: ComplianceModalProps) {
  const [versions, setVersions] = useState<ComplianceVersionOption[]>([]);
  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(null);
  const [step, setStep] = useState<Step>("version");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Reproducibility
  const [reproResult, setReproResult] = useState<Awaited<ReturnType<typeof runReproducibilityCheck>> | null>(null);
  const [reproChoice, setReproChoice] = useState<"original" | "rebuild_1" | "rebuild_2" | "">("");

  // Quiz
  const [questions, setQuestions] = useState<QuizQuestion[]>([]);
  const [answers, setAnswers] = useState<number[]>([]);
  const [quizResult, setQuizResult] = useState<{ passed: boolean; score: string; message: string } | null>(null);

  // Status (after load or after steps)
  const [status, setStatus] = useState<Awaited<ReturnType<typeof fetchComplianceStatus>> | null>(null);

  // All versions from compliance/versions are eligible (version_id is always set)

  useEffect(() => {
    fetchComplianceVersions(sessionId)
      .then((data) => setVersions(data.versions || []))
      .catch(() => setError("Failed to load versions"));
  }, [sessionId]);

  const loadStatus = useCallback(() => {
    if (!selectedVersionId) return;
    fetchComplianceStatus(sessionId, selectedVersionId)
      .then(setStatus)
      .catch(() => setStatus(null));
  }, [sessionId, selectedVersionId]);

  useEffect(() => {
    if (selectedVersionId) loadStatus();
  }, [selectedVersionId, loadStatus]);

  const handleStartCompliance = () => {
    if (!selectedVersionId) return;
    setError(null);
    setStep("reproducibility");
    setReproResult(null);
    setReproChoice("");
    setQuestions([]);
    setAnswers([]);
    setQuizResult(null);
  };

  const handleRunReproducibility = async () => {
    if (!selectedVersionId) return;
    setLoading(true);
    setError(null);
    try {
      const result = await runReproducibilityCheck(sessionId, selectedVersionId);
      setReproResult(result);
      if (result.error) {
        setError(result.error);
      } else if (result.passed) {
        loadStatus();
        setStep("quiz");
      } else if (result.choice_required) {
        setStep("repro_choice");
      } else {
        setStep("quiz");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Reproducibility check failed");
    } finally {
      setLoading(false);
    }
  };

  const handleConfirmChoice = async () => {
    if (!selectedVersionId || !reproChoice) return;
    setLoading(true);
    setError(null);
    try {
      await chooseReproducibility(sessionId, selectedVersionId, reproChoice);
      loadStatus();
      setStep("quiz");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save choice");
    } finally {
      setLoading(false);
    }
  };

  const handleRunReproducibilityAgain = async () => {
    if (!selectedVersionId) return;
    setLoading(true);
    setError(null);
    setReproChoice("");
    try {
      const result = await runReproducibilityCheck(sessionId, selectedVersionId);
      setReproResult(result);
      if (result.error) {
        setError(result.error);
      } else if (result.passed) {
        loadStatus();
        setStep("quiz");
      }
      // If choice_required, stay on repro_choice with new result/options
    } catch (e) {
      setError(e instanceof Error ? e.message : "Reproducibility check failed");
    } finally {
      setLoading(false);
    }
  };

  const handleGenerateQuiz = async () => {
    if (!selectedVersionId) return;
    setLoading(true);
    setError(null);
    try {
      const data = await generateComplianceQuiz(sessionId, selectedVersionId);
      setQuestions(data.questions || []);
      setAnswers((data.questions || []).map(() => -1));
      setQuizResult(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to generate quiz");
    } finally {
      setLoading(false);
    }
  };

  const handleSubmitQuiz = async () => {
    if (!selectedVersionId) return;
    setLoading(true);
    setError(null);
    try {
      const result = await submitComplianceQuiz(sessionId, selectedVersionId, answers);
      setQuizResult({ passed: result.passed, score: result.score, message: result.message });
      if (result.passed) {
        loadStatus();
        setStep("done");
        if (typeof window !== "undefined") {
          window.dispatchEvent(
            new CustomEvent("backtester:sessions-updated", { detail: { sessionId } })
          );
        }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to submit quiz");
    } finally {
      setLoading(false);
    }
  };

  const allQuizAnswersSelected =
    questions.length > 0 && answers.length === questions.length && answers.every((a) => a >= 0);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="bg-[var(--bg-secondary)] border border-[var(--border)] rounded-2xl shadow-2xl max-w-lg w-full max-h-[90vh] overflow-hidden flex flex-col">
        <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--border)]">
          <h2 className="text-lg font-semibold text-[var(--text-primary)]">
            Prepare for paper trading
          </h2>
          <button
            onClick={onClose}
            className="p-2 rounded-lg text-[var(--text-muted)] hover:bg-[var(--bg-tertiary)] hover:text-[var(--text-primary)]"
            aria-label="Close"
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M18 6L6 18M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
          {error && (
            <div className="rounded-lg bg-[var(--error)]/10 border border-[var(--error)]/30 text-[var(--error)] text-sm px-4 py-2">
              {error}
            </div>
          )}

          {/* Step: Select version — show when on version step or when a version is selected (later steps) */}
          {(step === "version" || selectedVersionId) && (
            <div>
              <label className="block text-sm font-medium text-[var(--text-secondary)] mb-2">
                Strategy version to prepare
              </label>
              <select
                value={selectedVersionId ?? ""}
                onChange={(e) => {
                  const v = e.target.value || null;
                  setSelectedVersionId(v);
                  setStatus(null);
                }}
                disabled={step !== "version"}
                className="w-full bg-[var(--bg-tertiary)] border border-[var(--border)] rounded-lg px-3 py-2 text-sm text-[var(--text-primary)]"
              >
                <option value="">Select a version</option>
                {versions.map((v) => (
                  <option key={v.version_id} value={v.version_id}>
                    {v.label}
                  </option>
                ))}
              </select>
              {versions.length === 0 && (
                <p className="text-xs text-[var(--text-muted)] mt-1">
                  No compliance-eligible versions yet. Run a new backtest (or refine) in this session to create a version that can be used for paper trading. Versions from before compliance tracking are not listed here.
                </p>
              )}
            </div>
          )}

          {step === "version" && (
            <button
              onClick={handleStartCompliance}
              disabled={!selectedVersionId || versions.length === 0 || loading}
              className="w-full py-2.5 rounded-lg bg-[var(--accent)] text-white text-sm font-medium hover:bg-[var(--accent-hover)] disabled:opacity-50"
            >
              Start compliance steps
            </button>
          )}

          {/* Step: Reproducibility */}
          {step === "reproducibility" && selectedVersionId && (
            <div className="space-y-3">
              <p className="text-sm text-[var(--text-secondary)]">
                We will rebuild your strategy from your commands and compare signals. This may take a minute.
              </p>
              {!reproResult ? (
                <button
                  onClick={handleRunReproducibility}
                  disabled={loading}
                  className="w-full py-2.5 rounded-lg bg-[var(--accent)] text-white text-sm font-medium hover:bg-[var(--accent-hover)] disabled:opacity-50"
                >
                  {loading ? "Running…" : "Run reproducibility check"}
                </button>
              ) : reproResult.passed ? (
                <div className="rounded-lg bg-[var(--success)]/10 border border-[var(--success)]/30 text-[var(--success)] text-sm px-4 py-2">
                  {reproResult.summary}
                </div>
              ) : reproResult.choice_required ? null : (
                <p className="text-sm text-[var(--text-muted)]">{reproResult.summary}</p>
              )}
            </div>
          )}

          {/* Step: Choose after failed reproducibility */}
          {step === "repro_choice" && reproResult?.choice_required && (
            <div className="space-y-3">
              <p className="text-sm text-[var(--text-secondary)]">{reproResult.summary}</p>
              {reproResult.summary_bullets && reproResult.summary_bullets.length > 0 && (
                <ul className="list-disc list-inside text-sm text-[var(--text-secondary)] space-y-1">
                  {reproResult.summary_bullets.map((b, i) => (
                    <li key={i}>{b}</li>
                  ))}
                </ul>
              )}
              <div className="space-y-2">
                <span className="block text-sm font-medium text-[var(--text-primary)]">Choose which version to use:</span>
                {(reproResult.options || []).map((opt) => (
                  <label key={opt.id} className="flex items-start gap-3 p-3 rounded-lg border border-[var(--border)] cursor-pointer hover:bg-[var(--bg-tertiary)]">
                    <input
                      type="radio"
                      name="repro_choice"
                      value={opt.id}
                      checked={reproChoice === opt.id}
                      onChange={() => setReproChoice(opt.id as "original" | "rebuild_1" | "rebuild_2")}
                      className="mt-1"
                    />
                    <div>
                      <span className="text-sm font-medium text-[var(--text-primary)]">{opt.label}</span>
                      <p className="text-xs text-[var(--text-muted)]">{opt.description}</p>
                    </div>
                  </label>
                ))}
              </div>
              <div className="flex flex-col gap-2">
                <button
                  onClick={handleConfirmChoice}
                  disabled={!reproChoice || loading}
                  className="w-full py-2.5 rounded-lg bg-[var(--accent)] text-white text-sm font-medium hover:bg-[var(--accent-hover)] disabled:opacity-50"
                >
                  {loading ? "Saving…" : "Confirm choice"}
                </button>
                <button
                  type="button"
                  onClick={handleRunReproducibilityAgain}
                  disabled={loading}
                  className="w-full py-2 rounded-lg border border-[var(--border)] text-sm text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)] disabled:opacity-50"
                >
                  {loading ? "Running…" : "Run reproducibility check again"}
                </button>
              </div>
              <p className="text-xs text-[var(--text-muted)]">
                Run again to get a fresh rebuild and compare signals once more. Results can differ each time (e.g. different generated code). Use this to verify before choosing a version for paper trading.
              </p>
            </div>
          )}

          {/* Step: Quiz */}
          {(step === "quiz" || step === "done") && selectedVersionId && (
            <div className="space-y-3">
              <h3 className="text-sm font-medium text-[var(--text-primary)]">Strategy understanding quiz</h3>
              {questions.length === 0 && !quizResult && (
                <>
                  <p className="text-sm text-[var(--text-secondary)]">
                    Answer a few questions about your strategy to confirm you understand it.
                  </p>
                  <button
                    onClick={handleGenerateQuiz}
                    disabled={loading}
                    className="w-full py-2.5 rounded-lg bg-[var(--accent)] text-white text-sm font-medium hover:bg-[var(--accent-hover)] disabled:opacity-50"
                  >
                    {loading ? "Generating…" : "Generate quiz"}
                  </button>
                </>
              )}
              {questions.length > 0 && !quizResult && (
                <div className="space-y-4">
                  {questions.map((q, i) => (
                    <div key={q.id}>
                      <p className="text-sm font-medium text-[var(--text-primary)] mb-2">{i + 1}. {q.question}</p>
                      <div className="space-y-1.5">
                        {q.options.map((opt, j) => (
                          <label key={j} className="flex items-center gap-2 cursor-pointer">
                            <input
                              type="radio"
                              name={q.id}
                              checked={answers[i] === j}
                              onChange={() => {
                                setAnswers((prev) => {
                                  const next = [...prev];
                                  next[i] = j;
                                  return next;
                                });
                              }}
                            />
                            <span className="text-sm text-[var(--text-secondary)]">{opt}</span>
                          </label>
                        ))}
                      </div>
                    </div>
                  ))}
                  <button
                    onClick={handleSubmitQuiz}
                    disabled={loading || !allQuizAnswersSelected}
                    className="w-full py-2.5 rounded-lg bg-[var(--accent)] text-white text-sm font-medium hover:bg-[var(--accent-hover)] disabled:opacity-50"
                  >
                    {loading ? "Submitting…" : allQuizAnswersSelected ? "Submit answers" : "Answer all questions to submit"}
                  </button>
                </div>
              )}
              {quizResult && (
                <div
                  className={`rounded-lg border px-4 py-2 text-sm ${
                    quizResult.passed
                      ? "bg-[var(--success)]/10 border-[var(--success)]/30 text-[var(--success)]"
                      : "bg-[var(--error)]/10 border-[var(--error)]/30 text-[var(--error)]"
                  }`}
                >
                  {quizResult.message} {!quizResult.passed && `(${quizResult.score})`}
                </div>
              )}
            </div>
          )}

          {/* Status summary */}
          {status && (step === "quiz" || step === "done") && (
            <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-tertiary)] p-4 space-y-2 text-sm">
              <p className="font-medium text-[var(--text-primary)]">Compliance status</p>
              <p className="text-[var(--text-secondary)]">
                Reproducibility: {status.reproducibility_passed ? "✓ Passed" : "Not passed"}
              </p>
              <p className="text-[var(--text-secondary)]">
                Quiz: {status.quiz_passed ? "✓ Passed" : "Not passed"}
              </p>
              {status.ready_for_paper_trading && (
                <p className="text-[var(--success)] font-medium">
                  This strategy version is ready for paper trading (feature coming soon). Only versions that pass both checks can be paper traded.
                </p>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

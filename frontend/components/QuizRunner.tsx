"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { AnswerResult, PublicQuiz } from "@/lib/types";
import { ExplanationPanel } from "./ExplanationPanel";

/** One question per screen, keyboard navigable: 1–4 to select, Enter to submit (§14). */
export function QuizRunner({
  quiz,
  attemptId,
  onFinish,
}: {
  quiz: PublicQuiz;
  attemptId: string;
  onFinish: () => void;
}) {
  const [index, setIndex] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const [result, setResult] = useState<AnswerResult | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [startedAt, setStartedAt] = useState(() => Date.now());

  const question = quiz.questions[index];
  const isLast = index === quiz.questions.length - 1;

  const submit = useCallback(async () => {
    if (!selected || result || submitting) return;
    setSubmitting(true);
    try {
      setResult(await api.answer(attemptId, question.id, selected, Date.now() - startedAt));
    } finally {
      setSubmitting(false);
    }
  }, [selected, result, submitting, attemptId, question, startedAt]);

  const next = useCallback(() => {
    if (isLast) return onFinish();
    setIndex((i) => i + 1);
    setSelected(null);
    setResult(null);
    setStartedAt(Date.now());
  }, [isLast, onFinish]);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key >= "1" && event.key <= "4") {
        const option = question.options[Number(event.key) - 1];
        if (option && !result) setSelected(option.id);
        return;
      }
      if (event.key === "Enter") {
        event.preventDefault();
        result ? next() : void submit();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [question, result, submit, next]);

  function optionClass(id: string) {
    if (!result) {
      return selected === id
        ? "border-accent bg-accent-soft"
        : "border-line bg-paper-raised hover:border-line-strong";
    }
    if (id === result.correct_option_id) return "border-good bg-good-soft";
    if (id === result.selected_option_id) return "border-bad bg-bad-soft";
    return "border-line bg-paper-raised opacity-60";
  }

  return (
    <div>
      <div className="mb-6 h-[3px] overflow-hidden rounded-sm bg-line">
        <div
          className="h-full bg-accent transition-all duration-300"
          style={{ width: `${(index / quiz.questions.length) * 100}%` }}
        />
      </div>

      <div className="mb-3.5 flex items-center justify-between gap-3">
        <span className="text-small text-ink-muted">
          Question {index + 1} of {quiz.questions.length}
        </span>
        {question.section_path.length > 0 && (
          <span className="rounded-full border border-line bg-paper px-2.5 py-0.5 text-small text-ink-muted">
            {question.section_path.join(" › ")}
          </span>
        )}
      </div>

      <section className="card">
        <h1 className="text-title font-medium">{question.stem}</h1>

        <div className="mt-4 space-y-2">
          {question.options.map((option, i) => (
            <button
              key={option.id}
              disabled={!!result}
              onClick={() => setSelected(option.id)}
              className={`flex w-full items-start gap-3 rounded-[9px] border px-4 py-3 text-left transition-colors ${optionClass(option.id)}`}
            >
              <kbd className="mt-0.5 grid h-[21px] w-[21px] flex-none place-items-center rounded-[5px] border border-line bg-paper font-mono text-[11px] font-semibold text-ink-muted">
                {i + 1}
              </kbd>
              <span
                className={
                  result && option.id === result.selected_option_id && !result.is_correct
                    ? "line-through decoration-bad/40"
                    : ""
                }
              >
                {option.text}
              </span>
            </button>
          ))}
        </div>

        {/* The misconception sits with the option the student actually chose, not in a
            paragraph below — that is what makes it land (§14). */}
        {result?.why_wrong && (
          <p className="mt-3 rounded-control bg-bad-soft px-4 py-2.5 text-small text-bad">
            {result.why_wrong}
          </p>
        )}

        {!result && (
          <div className="mt-4 flex items-center gap-2.5">
            <button
              className="btn btn-primary"
              disabled={!selected || submitting}
              onClick={() => void submit()}
            >
              {submitting ? "Checking…" : "Submit"}
            </button>
            <span className="text-small text-ink-muted">
              press 1–4 to choose, Enter to submit
            </span>
          </div>
        )}
      </section>

      {result && (
        <ExplanationPanel
          result={result}
          question={question}
          onNext={next}
          isLast={isLast}
        />
      )}
    </div>
  );
}

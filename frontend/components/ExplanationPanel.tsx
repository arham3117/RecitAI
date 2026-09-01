"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import type { AnswerResult, PublicQuestion } from "@/lib/types";
import { SkeletonLines } from "./Skeleton";

/**
 * §14: "The explanation panel deserves more design attention than everything else
 * combined — it is where the product's value actually lands."
 *
 * The whole payload arrives with the answer, so nothing here waits on a second request.
 * The one thing that does stream is the optional follow-up, which the student chose to
 * wait for.
 */
export function ExplanationPanel({
  result,
  question,
  onNext,
  isLast,
}: {
  result: AnswerResult;
  question: PublicQuestion;
  onNext: () => void;
  isLast: boolean;
}) {
  const [stream, setStream] = useState<string | null>(null);
  const [streaming, setStreaming] = useState(false);

  async function followUp(prompt: string) {
    setStream("");
    setStreaming(true);
    try {
      for await (const piece of api.explain(question.id, prompt)) {
        setStream((prev) => (prev ?? "") + piece);
      }
    } finally {
      setStreaming(false);
    }
  }

  return (
    <section className="card mt-4" aria-live="polite">
      <p
        className={`font-semibold mb-1 ${result.is_correct ? "text-good" : "text-bad"}`}
      >
        {result.is_correct ? "Correct" : "Not quite"}
      </p>
      <p>{result.explanation}</p>

      {result.source && (
        <>
          <blockquote className="mt-4 max-h-52 overflow-auto whitespace-pre-wrap rounded-r-control border-l-[3px] border-line bg-paper px-4 py-3 text-small">
            {result.source.text}
          </blockquote>
          <p className="mt-2 text-small text-ink-muted">
            From <b className="text-ink">{result.source.document_name}</b>, slide{" "}
            <b className="text-ink">{result.source.page}</b>
            {result.source.section_path.length > 0 && (
              <> — {result.source.section_path.join(" › ")}</>
            )}
          </p>
        </>
      )}

      <div className="mt-5 flex flex-wrap items-center gap-2.5">
        <button
          className="btn"
          disabled={streaming}
          onClick={() => followUp("Explain this differently, more simply.")}
        >
          Explain differently
        </button>
        <button
          className="btn"
          disabled={streaming}
          onClick={() => followUp("Why is the answer I chose wrong?")}
        >
          Ask a question
        </button>
        <button className="btn btn-primary ml-auto" onClick={onNext}>
          {isLast ? "See results" : "Next question"}
        </button>
      </div>

      {stream !== null && (
        <div className="mt-3 rounded-control bg-paper px-4 py-3 text-body">
          {stream === "" && streaming ? (
            <SkeletonLines count={2} />
          ) : (
            <p className="whitespace-pre-wrap">{stream}</p>
          )}
        </div>
      )}
    </section>
  );
}

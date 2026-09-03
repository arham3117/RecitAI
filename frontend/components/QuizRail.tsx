"use client";

import { useRef, useState } from "react";
import { uploadDocument } from "@/lib/api";
import type { Course, DeckStats, QuizSummary } from "@/lib/types";

/** The quiz controls, alongside the chat rather than instead of it. Chat is for
 *  understanding something now; a quiz is for finding out what you do not know — they are
 *  different jobs and belong side by side. */
export function QuizRail({
  course,
  quizzes,
  deck,
  selectedCount,
  busy,
  onGenerate,
  onStart,
  onReview,
  onUploaded,
}: {
  course: Course;
  quizzes: QuizSummary[];
  deck: DeckStats | null;
  selectedCount: number;
  busy: boolean;
  onGenerate: (n: number) => void;
  onStart: (quizId: string) => void;
  onReview: () => void;
  onUploaded: () => void;
}) {
  const [n, setN] = useState(5);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  async function upload(file: File) {
    setError(null);
    try {
      await uploadDocument(course.id, file);
      onUploaded();
    } catch (e) {
      setError(e instanceof Error ? e.message : "upload failed");
    }
  }

  return (
    <aside className="space-y-3 lg:sticky lg:top-6">
      <section className="card">
        <h2 className="label">Practice</h2>
        <p className="mt-2 text-small text-ink-muted">
          {selectedCount > 0
            ? `${selectedCount} topic${selectedCount > 1 ? "s" : ""} selected`
            : "Whole course — pick topics on the left to narrow it"}
        </p>
        <div className="mt-3 flex items-center gap-2">
          <input
            type="number"
            min={1}
            max={20}
            value={n}
            onChange={(e) => setN(Number(e.target.value))}
            aria-label="Number of questions"
            className="w-16 rounded-control border border-line bg-paper px-2 py-1.5"
          />
          <button className="btn btn-primary flex-1" disabled={busy} onClick={() => onGenerate(n)}>
            {busy ? "Generating…" : "Generate quiz"}
          </button>
        </div>
        <p className="mt-2.5 text-small text-ink-muted">
          Roughly 20 seconds per question, generated locally.
        </p>
      </section>

      {quizzes.length > 0 && (
        <section className="card">
          <h2 className="label">Ready now</h2>
          <p className="mt-2">
            <b>{quizzes[0].question_count} questions</b>
          </p>
          <p className="text-small text-ink-muted">
            {new Date(quizzes[0].created_at).toLocaleDateString()}
            {typeof quizzes[0].generation_meta?.validator_pass_rate === "number" && (
              <>
                {" · "}
                {Math.round((quizzes[0].generation_meta.validator_pass_rate as number) * 100)}%
                passed the validator
              </>
            )}
          </p>
          <button className="btn mt-3 w-full" onClick={() => onStart(quizzes[0].id)}>
            Start quiz
          </button>
        </section>
      )}

      {deck && deck.due > 0 && (
        <section className="card">
          <h2 className="label">Review</h2>
          <p className="mt-2 text-small text-ink-muted">
            {deck.due} card{deck.due > 1 ? "s" : ""} due — questions you missed, coming back
            on a schedule.
          </p>
          <button className="btn mt-3 w-full" onClick={onReview}>
            Review {deck.due} card{deck.due > 1 ? "s" : ""}
          </button>
        </section>
      )}

      <section className="card">
        <h2 className="label">Material</h2>
        <button className="btn mt-3 w-full" onClick={() => fileRef.current?.click()}>
          Add slides or a PDF
        </button>
        <input
          ref={fileRef}
          type="file"
          accept=".pptx,.pdf"
          hidden
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) void upload(file);
            e.target.value = "";
          }}
        />
        {error && <p className="mt-2 text-small text-bad">{error}</p>}
      </section>
    </aside>
  );
}

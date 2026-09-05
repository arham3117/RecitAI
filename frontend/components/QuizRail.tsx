"use client";

import { useRef, useState } from "react";
import { uploadDocument } from "@/lib/api";
import type { Coverage, Course, DeckStats, QuizSummary } from "@/lib/types";

/** The quiz controls, alongside the chat rather than instead of it. Chat is for
 *  understanding something now; a quiz is for finding out what you do not know — they are
 *  different jobs and belong side by side. */
export function QuizRail({
  course,
  quizzes,
  deck,
  selectedCount,
  coverage,
  progress,
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
  coverage: Coverage | null;
  progress: { answered: number; total: number } | null;
  busy: boolean;
  onGenerate: () => void;
  onStart: (quizId: string, restart?: boolean) => void;
  onReview: () => void;
  onUploaded: () => void;
}) {
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
    // Sticky, but scrollable within the viewport: the rail used to run past the bottom of
    // the window and the last card was simply unreachable.
    <aside className="space-y-3 lg:sticky lg:top-9 lg:max-h-[calc(100vh-5rem)] lg:overflow-y-auto lg:pb-2">
      <section className="card !p-4">
        <h2 className="label">Practice</h2>

        {/* A quiz covers the concepts in the selected material — its length follows the
            material rather than a number the student had to invent. Showing what will be
            covered before generating keeps that from being a surprise. */}
        {coverage === null ? (
          <div className="mt-3 space-y-2">
            <div className="skeleton h-4 w-32" />
            <div className="skeleton h-4 w-24" />
          </div>
        ) : coverage.concepts === 0 ? (
          <p className="mt-2 text-small text-ink-muted">
            Nothing to quiz on in this selection yet.
          </p>
        ) : (
          <>
            <p className="mt-2">
              <b>
                {coverage.concepts} concept{coverage.concepts === 1 ? "" : "s"}
              </b>
              <span className="text-ink-muted">
                {" "}
                in {selectedCount > 0 ? "your selection" : "this course"}
              </span>
            </p>
            <p className="text-small text-ink-muted">
              across {coverage.topics} topic{coverage.topics === 1 ? "" : "s"} · about{" "}
              {Math.max(1, Math.round(coverage.estimated_seconds / 60))} min to generate
            </p>
          </>
        )}

        <button
          className="btn btn-primary mt-3 w-full"
          disabled={busy || !coverage || coverage.concepts === 0}
          onClick={onGenerate}
        >
          {busy ? "Generating…" : "Quiz me on this"}
        </button>
        <p className="mt-2.5 text-small text-ink-muted">
          One question per concept, generated locally. Pick topics on the left to narrow it.
        </p>
      </section>

      {/* Secondary actions are compact rows, not full cards. Four stacked cards ran past
          the bottom of the window, which put "add material" somewhere nobody would find. */}
      {quizzes.length > 0 && (
        <div
          className="rounded-card border border-line bg-paper-raised
                     hover:border-line-strong"
        >
          <button
            onClick={() => onStart(quizzes[0].id)}
            className="flex w-full items-center gap-3 p-3 text-left"
          >
            <span className="min-w-0 flex-1">
              <span className="block text-small font-medium">
                {progress
                  ? `Resume quiz · ${progress.answered} of ${progress.total} answered`
                  : `Start ready quiz · ${quizzes[0].question_count} questions`}
              </span>
              <span className="block text-[11.5px] text-ink-muted">
                {new Date(quizzes[0].created_at).toLocaleDateString()}
                {typeof quizzes[0].generation_meta?.validator_pass_rate === "number" && (
                  <>
                    {" · "}
                    {Math.round(
                      (quizzes[0].generation_meta.validator_pass_rate as number) * 100,
                    )}
                    % passed the validator
                  </>
                )}
              </span>
            </span>
          </button>
          {/* Resuming is the default, so starting again has to be reachable — but quietly,
              since it throws away answers already given. */}
          {progress && (
            <button
              onClick={() => onStart(quizzes[0].id, true)}
              className="w-full border-t border-line px-3 py-2 text-left text-[11.5px]
                         text-ink-muted hover:text-ink"
            >
              Start over from the first question
            </button>
          )}
        </div>
      )}

      {deck && deck.due > 0 && (
        <button
          onClick={onReview}
          className="flex w-full items-center gap-3 rounded-card border border-line
                     bg-paper-raised p-3 text-left hover:border-line-strong"
        >
          <span className="min-w-0 flex-1">
            <span className="block text-small font-medium">
              Review {deck.due} due card{deck.due > 1 ? "s" : ""}
            </span>
            <span className="block text-[11.5px] text-ink-muted">
              questions you missed, coming back on a schedule
            </span>
          </span>
        </button>
      )}

      <button
        onClick={() => fileRef.current?.click()}
        className="flex w-full items-center gap-3 rounded-card border border-dashed
                   border-line bg-transparent p-3 text-left text-small text-ink-muted
                   hover:border-line-strong hover:text-ink"
      >
        + Add slides or a PDF
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
      {error && <p className="text-small text-bad">{error}</p>}
    </aside>
  );
}

"use client";

import { useRef, useState } from "react";
import { uploadDocument } from "@/lib/api";
import { IconArrow, IconCards, IconPlus, IconQuiz } from "./icons";
import type { Coverage, Course, DeckStats, QuizSummary } from "@/lib/types";

/** One action row: tinted tile, label, sub-label, affordance arrow. */
function ActionRow({
  tone,
  icon,
  title,
  detail,
  onClick,
}: {
  tone: "accent" | "good";
  icon: React.ReactNode;
  title: string;
  detail: React.ReactNode;
  onClick: () => void;
}) {
  const tile = tone === "good" ? "bg-good-soft text-good" : "bg-accent-soft text-accent";
  return (
    <button onClick={onClick} className="row group w-full items-start hover:bg-paper">
      <span className={`tile mt-px ${tile}`}>{icon}</span>
      <span className="min-w-0 flex-1">
        <span className="block text-small font-medium">{title}</span>
        <span className="block text-[11.5px] leading-snug text-ink-muted">{detail}</span>
      </span>
      <IconArrow className="mt-1.5 h-3 w-3 flex-none text-ink-faint transition-transform group-hover:translate-x-0.5 group-hover:text-ink-muted" />
    </button>
  );
}

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
  const [dragging, setDragging] = useState(false);
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

  const ready = coverage && coverage.concepts > 0;

  return (
    // Sticky, but scrollable within the viewport: the rail used to run past the bottom of
    // the window and the last card was simply unreachable.
    <aside className="space-y-2.5 lg:sticky lg:top-6 lg:max-h-[calc(100vh-4rem)] lg:overflow-y-auto lg:pb-2">
      {/* The generator is the one thing on this rail with a primary action, so it is the
          only one that gets a filled card. */}
      <section className="panel overflow-hidden">
        <div className="border-b border-line bg-paper px-4 py-2">
          <h2 className="label">Build a quiz</h2>
        </div>
        <div className="p-4">
          {/* A quiz covers the concepts in the selected material — its length follows the
              material rather than a number the student had to invent. Showing what will be
              covered before generating keeps that from being a surprise. */}
          {coverage === null ? (
            <div className="space-y-2">
              <div className="skeleton h-5 w-28" />
              <div className="skeleton h-3.5 w-36" />
            </div>
          ) : coverage.concepts === 0 ? (
            <p className="text-small text-ink-muted">
              Nothing to quiz on in this selection yet.
            </p>
          ) : (
            <>
              <div className="flex items-baseline gap-1.5">
                <span className="text-[26px] font-semibold leading-none tracking-tight">
                  {coverage.concepts}
                </span>
                <span className="text-small text-ink-muted">
                  concept{coverage.concepts === 1 ? "" : "s"} found
                </span>
              </div>
              <p className="mt-1.5 text-[11.5px] leading-relaxed text-ink-muted">
                in {selectedCount > 0 ? "your selected topics" : "this whole course"} · across{" "}
                {coverage.topics} topic{coverage.topics === 1 ? "" : "s"} · about{" "}
                {Math.max(1, Math.round(coverage.estimated_seconds / 60))} min to write
              </p>
            </>
          )}

          <button
            className="btn btn-primary mt-3 w-full"
            disabled={busy || !ready}
            onClick={onGenerate}
          >
            {busy ? "Generating…" : "Quiz me on this"}
          </button>
          <p className="mt-2 text-[11.5px] leading-relaxed text-ink-muted">
            One question per concept — pick topics on the left to narrow it.
          </p>
        </div>
      </section>

      {/* Everything else is a compact row inside one panel. Four stacked cards ran past
          the bottom of the window, which put "add material" somewhere nobody would find. */}
      {(quizzes.length > 0 || (deck && deck.due > 0)) && (
        <section className="panel overflow-hidden">
          <div className="border-b border-line bg-paper px-4 py-2">
            <h2 className="label">Continue</h2>
          </div>
          <div className="space-y-0.5 p-1.5">
            {quizzes.length > 0 && (
              <>
                <ActionRow
                  tone="accent"
                  icon={<IconQuiz />}
                  title={progress ? "Resume your quiz" : "Ready quiz"}
                  detail={
                    <>
                      {progress
                        ? `${progress.answered} of ${progress.total} answered · `
                        : `${quizzes[0].question_count} questions · `}
                      {new Date(quizzes[0].created_at).toLocaleDateString()}
                      {typeof quizzes[0].generation_meta?.validator_pass_rate === "number" && (
                        <>
                          {" · "}
                          {Math.round(
                            (quizzes[0].generation_meta.validator_pass_rate as number) * 100,
                          )}
                          % passed
                        </>
                      )}
                    </>
                  }
                  onClick={() => onStart(quizzes[0].id)}
                />
                {/* Resuming is the default, so starting again has to be reachable — but
                    quietly, since it throws away answers already given. */}
                {progress && (
                  <button
                    onClick={() => onStart(quizzes[0].id, true)}
                    className="ml-[42px] block px-2.5 pb-1 text-[11.5px] text-ink-muted
                               hover:text-ink"
                  >
                    Start over from the first question
                  </button>
                )}
              </>
            )}

            {deck && deck.due > 0 && (
              <ActionRow
                tone="good"
                icon={<IconCards />}
                title="Review your flashcards"
                detail={`${deck.due} due · questions you missed, on a schedule`}
                onClick={onReview}
              />
            )}
          </div>
        </section>
      )}

      {/* Also a drop target, not just a button — dragging a deck onto it is the gesture
          people try first. */}
      <button
        onClick={() => fileRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          const file = e.dataTransfer.files?.[0];
          if (file) void upload(file);
        }}
        className={`row w-full justify-center border border-dashed text-small transition-colors ${
          dragging
            ? "border-accent bg-accent-soft text-accent"
            : "border-line text-ink-muted hover:border-line-strong hover:text-ink"
        }`}
      >
        <IconPlus />
        {dragging ? "Drop to add it" : "Add slides or a PDF"}
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
      {error && (
        <p className="rounded-control bg-bad-soft px-3 py-2 text-small text-bad">{error}</p>
      )}
    </aside>
  );
}

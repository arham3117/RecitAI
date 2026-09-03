"use client";

import { useCallback, useEffect, useState } from "react";
import { Chat } from "@/components/Chat";
import { FlashcardReviewer } from "@/components/FlashcardReviewer";
import { QuizRail } from "@/components/QuizRail";
import { QuizRunner } from "@/components/QuizRunner";
import { Sidebar } from "@/components/Sidebar";
import { SkeletonQuestion } from "@/components/Skeleton";
import { api } from "@/lib/api";
import type {
  AttemptResults,
  Course,
  DeckStats,
  DocumentSummary,
  Flashcard,
  PublicQuiz,
  QuizSummary,
  Topic,
} from "@/lib/types";

type View =
  | { name: "library" }
  | { name: "generating"; detail: string; progress: number; total: number }
  | { name: "quiz"; quiz: PublicQuiz; attemptId: string }
  | { name: "results"; results: AttemptResults; cardsAdded: number }
  | { name: "review"; cards: Flashcard[] }
  | { name: "error"; message: string };

export default function Page() {
  const [course, setCourse] = useState<Course | null>(null);
  const [topics, setTopics] = useState<Topic[]>([]);
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [quizzes, setQuizzes] = useState<QuizSummary[]>([]);
  const [deck, setDeck] = useState<DeckStats | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [view, setView] = useState<View>({ name: "library" });
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    const courses = await api.courses();
    if (courses.length === 0) {
      setLoading(false);
      return;
    }
    const active = courses[0];
    setCourse(active);
    const [t, d, q, s] = await Promise.all([
      api.topics(active.id),
      api.documents(active.id),
      api.quizzes(active.id),
      api.deckStats(active.id),
    ]);
    setTopics(t);
    setDocuments(d);
    setQuizzes(q);
    setDeck(s);
    setLoading(false);
  }, []);

  useEffect(() => {
    void refresh().catch((e) => setView({ name: "error", message: String(e) }));
  }, [refresh]);

  const startQuiz = useCallback(async (quizId: string) => {
    const [quiz, attempt] = await Promise.all([api.quiz(quizId), api.startAttempt(quizId)]);
    setView({ name: "quiz", quiz, attemptId: attempt.id });
  }, []);

  const generate = useCallback(
    async (n: number, query: string) => {
      if (!course) return;
      setView({ name: "generating", detail: "starting…", progress: 0, total: n });
      try {
        const job = await api.createQuiz({
          course_id: course.id,
          n,
          topic_ids: selected.size ? [...selected] : undefined,
          query: !selected.size && query.trim() ? query.trim() : undefined,
        });
        // Poll rather than hold a connection open for minutes (§12).
        for (;;) {
          await new Promise((r) => setTimeout(r, 1500));
          const status = await api.job(job.job_id);
          setView({
            name: "generating",
            detail: status.detail || status.status,
            progress: status.progress,
            total: status.total || n,
          });
          if (status.status === "complete" && status.result_id) {
            await startQuiz(status.result_id);
            return;
          }
          if (status.status === "failed") {
            setView({ name: "error", message: status.error ?? "generation failed" });
            return;
          }
        }
      } catch (e) {
        setView({ name: "error", message: e instanceof Error ? e.message : String(e) });
      }
    },
    [course, selected, startQuiz],
  );

  const finishQuiz = useCallback(
    async (attemptId: string) => {
      if (!course) return;
      const before = deck?.total ?? 0;
      const [results, stats] = await Promise.all([
        api.results(attemptId),
        api.deckStats(course.id),
      ]);
      setDeck(stats);
      void refresh();
      setView({ name: "results", results, cardsAdded: Math.max(0, stats.total - before) });
    },
    [course, deck, refresh],
  );

  const review = useCallback(async () => {
    if (!course) return;
    const cards = await api.dueCards(course.id);
    if (cards.length) setView({ name: "review", cards });
  }, [course]);

  if (!loading && !course) {
    return (
      <main className="mx-auto max-w-canvas px-10 py-9">
        <h1 className="text-display font-semibold">No course yet</h1>
        <p className="mt-1.5 text-ink-muted">
          Ingest material with <code className="rounded bg-line/50 px-1">make ingest</code>.
        </p>
      </main>
    );
  }

  return (
    <div className="grid min-h-screen grid-cols-[260px_1fr]">
      <Sidebar
        course={course}
        topics={topics}
        documents={documents}
        deck={deck}
        selected={selected}
        onToggleTopic={(id) =>
          setSelected((prev) => {
            const next = new Set(prev);
            next.has(id) ? next.delete(id) : next.add(id);
            return next;
          })
        }
        onReview={() => void review()}
      />

      <main className="max-w-[1180px] px-10 py-9">
        {view.name === "library" && course && (
          <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_268px]">
            <Chat
              courseId={course.id}
              topicIds={[...selected]}
              scopeLabel={
                selected.size
                  ? `${selected.size} selected topic${selected.size > 1 ? "s" : ""}`
                  : "your course material"
              }
            />
            <QuizRail
              course={course}
              quizzes={quizzes}
              deck={deck}
              selectedCount={selected.size}
              busy={false}
              onGenerate={(n) => void generate(n, "")}
              onStart={(id) => void startQuiz(id)}
              onReview={() => void review()}
              onUploaded={() => void refresh()}
            />
          </div>
        )}

        {view.name === "library" && !course && (
          <div className="pt-4">
            <div className="skeleton h-8 w-72" />
            <div className="skeleton mt-3 h-4 w-96" />
          </div>
        )}

        {view.name === "generating" && (
          <>
            <h1 className="text-display font-semibold">Generating</h1>
            <p className="mt-1.5 mb-6 text-ink-muted">{view.detail}</p>
            <div className="mb-6 h-[3px] overflow-hidden rounded-sm bg-line">
              <div
                className="h-full bg-accent transition-all duration-300"
                style={{ width: `${Math.max(4, (view.progress / Math.max(1, view.total)) * 100)}%` }}
              />
            </div>
            <SkeletonQuestion />
            <p className="mt-4 text-small text-ink-muted">
              Each question is generated from a passage, then checked for length bias,
              near-duplicate options, answer leakage and groundedness. Rejected questions are
              regenerated.
            </p>
          </>
        )}

        {view.name === "quiz" && (
          <QuizRunner
            quiz={view.quiz}
            attemptId={view.attemptId}
            onFinish={() => void finishQuiz(view.attemptId)}
          />
        )}

        {view.name === "results" && (
          <>
            <h1 className="text-display font-semibold">Results</h1>
            <section className="card mt-4">
              <div className="text-[40px] font-semibold tracking-tight">
                {Math.round(view.results.score * 100)}%
              </div>
              <p className="text-ink-muted">
                {view.results.correct} of {view.results.answered} correct
              </p>
            </section>
            {view.cardsAdded > 0 && (
              <section className="card mt-3.5">
                <b>
                  {view.cardsAdded} card{view.cardsAdded > 1 ? "s" : ""} added to your deck
                </b>
                <p className="mt-1 text-small text-ink-muted">
                  Questions you missed become flashcards, so you meet them again on a schedule
                  rather than once.
                </p>
              </section>
            )}
            <div className="mt-4 flex gap-2.5">
              <button className="btn btn-primary" onClick={() => setView({ name: "library" })}>
                Back to practice
              </button>
              {deck && deck.due > 0 && (
                <button className="btn" onClick={() => void review()}>
                  Review {deck.due} due card{deck.due > 1 ? "s" : ""}
                </button>
              )}
            </div>
          </>
        )}

        {view.name === "review" && (
          <FlashcardReviewer
            cards={view.cards}
            onDone={() => {
              void refresh();
              setView({ name: "library" });
            }}
          />
        )}

        {view.name === "error" && (
          <>
            <h1 className="text-display font-semibold">Something went wrong</h1>
            <p className="mt-1.5 text-ink-muted">{view.message}</p>
            <button className="btn mt-4" onClick={() => setView({ name: "library" })}>
              Back
            </button>
          </>
        )}
      </main>
    </div>
  );
}

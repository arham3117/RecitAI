"use client";

import { useCallback, useEffect, useState } from "react";
import { Chat } from "@/components/Chat";
import { CourseSwitcher } from "@/components/CourseSwitcher";
import { EmptyCourse } from "@/components/EmptyCourse";
import { FlashcardReviewer } from "@/components/FlashcardReviewer";
import { QuizRail } from "@/components/QuizRail";
import { QuizRunner } from "@/components/QuizRunner";
import { CanvasHeader } from "@/components/CanvasHeader";
import { IconCards } from "@/components/icons";
import { Sidebar } from "@/components/Sidebar";
import { SkeletonQuestion } from "@/components/Skeleton";
import { api } from "@/lib/api";
import type {
  AttemptResults,
  Coverage,
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
  | { name: "quiz"; quiz: PublicQuiz; attemptId: string; startIndex: number }
  | { name: "results"; results: AttemptResults; cardsAdded: number }
  | { name: "review"; cards: Flashcard[] }
  | { name: "error"; message: string };

export default function Page() {
  const [courses, setCourses] = useState<Course[]>([]);
  const [course, setCourse] = useState<Course | null>(null);
  const [topics, setTopics] = useState<Topic[]>([]);
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [quizzes, setQuizzes] = useState<QuizSummary[]>([]);
  /** An unfinished attempt on the newest quiz, so the rail can offer to resume it. */
  const [progress, setProgress] = useState<{ answered: number; total: number } | null>(null);
  const [deck, setDeck] = useState<DeckStats | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [view, setView] = useState<View>({ name: "library" });
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async (preferId?: string) => {
    const all = await api.courses();
    setCourses(all);
    if (all.length === 0) {
      setCourse(null);
      setLoading(false);
      return;
    }
    // Keep whatever the student picked; fall back to the first only on a cold start.
    const wanted = preferId ?? course?.id;
    const active = all.find((c) => c.id === wanted) ?? all[0];
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
    setProgress(
      q.length ? await api.quizProgress(q[0].id).then((p) => (p.in_progress ? p : null)) : null,
    );
    setLoading(false);
  }, [course?.id]);

  useEffect(() => {
    void refresh().catch((e) => setView({ name: "error", message: String(e) }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Ingestion runs in the background, so poll until it settles. Without this the sidebar
  // says "processing" until the student reloads, and a finished upload looks stuck.
  const ingesting = documents.some((d) => d.ingest_status === "pending" || d.ingest_status === "processing");
  useEffect(() => {
    if (!ingesting || !course) return;
    const timer = setInterval(() => void refresh(course.id), 2500);
    return () => clearInterval(timer);
  }, [ingesting, course, refresh]);

  // What a quiz over the current selection would cover. Refetched when the scope changes,
  // so the rail always describes what the button will actually do.
  const [coverage, setCoverage] = useState<Coverage | null>(null);
  useEffect(() => {
    if (!course) return;
    let cancelled = false;
    setCoverage(null);
    api
      .coverage(course.id, [...selected])
      .then((c) => !cancelled && setCoverage(c))
      .catch(() => !cancelled && setCoverage({ concepts: 0, topics: 0, estimated_seconds: 0 }));
    return () => {
      cancelled = true;
    };
  }, [course, selected]);

  const startQuiz = useCallback(async (quizId: string, restart = false) => {
    const [quiz, attempt] = await Promise.all([
      api.quiz(quizId),
      api.startAttempt(quizId, restart),
    ]);
    // Resume where they stopped: the first question with no answer on record. Answering
    // a question twice would count it twice against topic mastery.
    const done = new Set(attempt.answered_question_ids);
    const first = quiz.questions.findIndex((q) => !done.has(q.id));
    setView({
      name: "quiz",
      quiz,
      attemptId: attempt.id,
      startIndex: first < 0 ? 0 : first,
    });
    setProgress(null);
  }, []);

  const generate = useCallback(
    async () => {
      if (!course) return;
      // No question count: the quiz covers the concepts in the selection, so its length
      // follows the material.
      const total = coverage?.concepts ?? 0;
      setView({ name: "generating", detail: "starting…", progress: 0, total });
      try {
        const job = await api.createQuiz({
          course_id: course.id,
          topic_ids: selected.size ? [...selected] : undefined,
        });
        // Poll rather than hold a connection open for minutes (§12).
        for (;;) {
          await new Promise((r) => setTimeout(r, 1500));
          const status = await api.job(job.job_id);
          setView({
            name: "generating",
            detail: status.detail || status.status,
            progress: status.progress,
            total: status.total || total,
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
    [course, selected, startQuiz, coverage],
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

  const scopeLabel = selected.size
    ? `${selected.size} selected topic${selected.size > 1 ? "s" : ""}`
    : "all material";

  return (
    <div className="grid min-h-screen grid-cols-[264px_1fr]">
      <Sidebar
        header={
          <CourseSwitcher
            courses={courses}
            active={course}
            onSelect={(c) => {
              setCourse(c);
              setSelected(new Set());
              void refresh(c.id);
            }}
            onCreated={(c) => {
              setCourse(c);
              setSelected(new Set());
              void refresh(c.id);
            }}
            onDeleted={(id) => {
              // Deleting the course you are looking at leaves nothing selected, so fall
              // back to whatever remains rather than rendering an empty shell.
              const next = courses.find((c) => c.id !== id) ?? null;
              setSelected(new Set());
              setView({ name: "library" });
              void refresh(course?.id === id ? next?.id : course?.id);
            }}
          />
        }
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
        onClearTopics={() => setSelected(new Set())}
        onReview={() => void review()}
      />

      {/* Only the library needs the wide measure — it carries chat plus the rail.
          Everything else is a single column of reading, and a long measure makes
          options, explanations and a score card all harder to scan. */}
      <main className={`px-8 pb-10 ${view.name === "library" ? "max-w-7xl" : "max-w-3xl"}`}>
        {view.name === "library" && (!course || course.chunk_count === 0) && !loading && (
          <EmptyCourse course={course} onUploaded={() => void refresh(course?.id)} />
        )}

        {view.name === "library" && course && course.chunk_count > 0 && (
          <>
            <CanvasHeader
              course={course}
              scopeLabel={scopeLabel}
              narrowed={selected.size > 0}
              onClearScope={() => setSelected(new Set())}
            />
            <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_272px]">
              <Chat
                courseId={course.id}
                topicIds={[...selected]}
                scopeLabel={scopeLabel === "all material" ? "your course material" : scopeLabel}
              />
              <QuizRail
                course={course}
                quizzes={quizzes}
                deck={deck}
                selectedCount={selected.size}
                busy={false}
                coverage={coverage}
                onGenerate={() => void generate()}
                progress={progress}
                onStart={(id, restart) => void startQuiz(id, restart)}
                onReview={() => void review()}
                onUploaded={() => void refresh(course.id)}
              />
            </div>
          </>
        )}

        {view.name === "library" && loading && (
          <div className="pt-8">
            <div className="skeleton h-8 w-72" />
            <div className="skeleton mt-3 h-4 w-96" />
          </div>
        )}

        {view.name === "generating" && (
          <div className="pt-8">
            <div className="flex items-baseline justify-between gap-4">
              <h1 className="text-display font-semibold">Writing your quiz</h1>
              <span className="text-small tabular-nums text-ink-muted">
                {view.progress} / {view.total || "…"}
              </span>
            </div>
            <p className="mt-1.5 mb-5 text-ink-muted">{view.detail}</p>
            <div className="mb-7 h-1.5 overflow-hidden rounded-full bg-line">
              <div
                className="h-full rounded-full bg-accent transition-all duration-300"
                style={{ width: `${Math.max(3, (view.progress / Math.max(1, view.total)) * 100)}%` }}
              />
            </div>
            <SkeletonQuestion />
            <p className="mt-5 max-w-[62ch] text-small text-ink-muted">
              Each question is written from one passage, then checked for length bias,
              near-duplicate options, answer leakage and groundedness. Rejected questions are
              regenerated, which is why this takes a moment.
            </p>
          </div>
        )}

        {view.name === "quiz" && (
          <div className="pt-8">
            <QuizRunner
              quiz={view.quiz}
              attemptId={view.attemptId}
              startIndex={view.startIndex}
              onFinish={() => void finishQuiz(view.attemptId)}
              onExit={() => setView({ name: "library" })}
            />
          </div>
        )}

        {view.name === "results" && (
          <div className="pt-8">
            <h1 className="text-display font-semibold">How you did</h1>
            {/* The score is the one number worth a large, coloured treatment — and the
                colour is the grade, so it has to be earned rather than chosen. */}
            <section className="panel mt-4 flex flex-wrap items-center gap-5 p-6">
              <ScoreDial score={view.results.score} />
              <div className="min-w-0">
                <p className="text-title font-medium">
                  {view.results.correct} of {view.results.answered} correct
                </p>
                <p className="mt-0.5 text-small text-ink-muted">
                  {view.results.score >= 0.8
                    ? "Strong. The misses below are worth a second look."
                    : view.results.score >= 0.5
                      ? "A reasonable start — the gaps are now on a schedule."
                      : "Plenty to work on. Every miss became a flashcard."}
                </p>
              </div>
            </section>

            {view.cardsAdded > 0 && (
              <section className="panel mt-2.5 flex items-start gap-3 p-4">
                <span className="tile bg-good-soft text-good">
                  <IconCards />
                </span>
                <div>
                  <p className="text-small font-medium">
                    {view.cardsAdded} card{view.cardsAdded > 1 ? "s" : ""} added to your deck
                  </p>
                  <p className="mt-0.5 text-small text-ink-muted">
                    Questions you missed become flashcards, so you meet them again on a
                    schedule rather than once.
                  </p>
                </div>
              </section>
            )}

            <div className="mt-5 flex flex-wrap gap-2.5">
              <button className="btn btn-primary" onClick={() => setView({ name: "library" })}>
                Back to practice
              </button>
              {deck && deck.due > 0 && (
                <button className="btn" onClick={() => void review()}>
                  Review {deck.due} due card{deck.due > 1 ? "s" : ""}
                </button>
              )}
            </div>
          </div>
        )}

        {view.name === "review" && (
          <div className="pt-8">
            <FlashcardReviewer
              cards={view.cards}
              onDone={() => {
                void refresh();
                setView({ name: "library" });
              }}
            />
          </div>
        )}

        {view.name === "error" && (
          <div className="pt-8">
            <span className="tile bg-bad-soft text-bad">!</span>
            <h1 className="mt-3 text-display font-semibold">Something went wrong</h1>
            <p className="mt-1.5 max-w-[62ch] text-ink-muted">{view.message}</p>
            <button className="btn mt-5" onClick={() => setView({ name: "library" })}>
              Back to practice
            </button>
          </div>
        )}

      </main>
    </div>
  );
}

/** Score as a ring rather than a number alone: the colour is the grade, and an arc is
 *  read before a percentage is. Green at 80, amber at 50, red below. */
function ScoreDial({ score }: { score: number }) {
  const tone = score >= 0.8 ? "good" : score >= 0.5 ? "warn" : "bad";
  const stroke = { good: "#0f7b52", warn: "#a15c07", bad: "#b42318" }[tone];
  const r = 34;
  const circumference = 2 * Math.PI * r;

  return (
    <div className="relative h-[92px] w-[92px] flex-none">
      <svg viewBox="0 0 80 80" className="h-full w-full -rotate-90">
        <circle cx="40" cy="40" r={r} fill="none" stroke="#e5e3de" strokeWidth="7" />
        <circle
          cx="40"
          cy="40"
          r={r}
          fill="none"
          stroke={stroke}
          strokeWidth="7"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - score)}
        />
      </svg>
      <span
        className="absolute inset-0 grid place-items-center text-[22px] font-semibold
                   tabular-nums tracking-tight"
        style={{ color: stroke }}
      >
        {Math.round(score * 100)}%
      </span>
    </div>
  );
}

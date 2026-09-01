import type {
  AnswerResult,
  AttemptResults,
  Course,
  DeckStats,
  DocumentSummary,
  Flashcard,
  Job,
  PublicQuiz,
  QuizSummary,
  Topic,
} from "./types";

/** Requests go to the same origin; next.config.mjs proxies /api to the backend, so no
 *  API URL is baked into the bundle and there is no CORS surface. */
async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
    cache: "no-store",
  });
  if (!res.ok) {
    // The API returns structured errors (§12); surface the detail rather than a status.
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? body.error ?? `${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  courses: () => req<Course[]>("/courses"),
  topics: (courseId: string) => req<Topic[]>(`/courses/${courseId}/topics`),
  documents: (courseId: string) => req<DocumentSummary[]>(`/courses/${courseId}/documents`),
  quizzes: (courseId: string) => req<QuizSummary[]>(`/courses/${courseId}/quizzes`),
  quiz: (quizId: string) => req<PublicQuiz>(`/quizzes/${quizId}`),

  createQuiz: (body: {
    course_id: string;
    topic_ids?: string[];
    query?: string;
    n: number;
    difficulty?: string;
  }) => req<Job>("/quizzes", { method: "POST", body: JSON.stringify(body) }),
  job: (jobId: string) => req<Job>(`/jobs/${jobId}`),

  startAttempt: (quizId: string) =>
    req<{ id: string }>("/attempts", { method: "POST", body: JSON.stringify({ quiz_id: quizId }) }),
  answer: (attemptId: string, questionId: string, optionId: string, timeTakenMs?: number) =>
    req<AnswerResult>(`/attempts/${attemptId}/answers`, {
      method: "POST",
      body: JSON.stringify({
        question_id: questionId,
        selected_option_id: optionId,
        time_taken_ms: timeTakenMs,
      }),
    }),
  results: (attemptId: string) => req<AttemptResults>(`/attempts/${attemptId}/results`),

  dueCards: (courseId: string) => req<Flashcard[]>(`/courses/${courseId}/flashcards/due`),
  deckStats: (courseId: string) => req<DeckStats>(`/courses/${courseId}/flashcards/stats`),
  reviewCard: (cardId: string, rating: 1 | 2 | 3 | 4) =>
    req<{ interval_days: number; state: string }>(`/flashcards/${cardId}/review`, {
      method: "POST",
      body: JSON.stringify({ rating }),
    }),

  /** SSE follow-up (§12). Yields text as it arrives rather than buffering — on a local
   *  model the difference between 0.9s and 8s to first visible word. */
  async *explain(questionId: string, followup: string): AsyncGenerator<string> {
    const res = await fetch(`/api/questions/${questionId}/explain`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ followup }),
    });
    if (!res.body) return;
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      for (const line of decoder.decode(value, { stream: true }).split("\n")) {
        if (line.startsWith("data:")) yield line.slice(5);
      }
    }
  },
};

export async function uploadDocument(courseId: string, file: File): Promise<DocumentSummary> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`/api/courses/${courseId}/documents`, { method: "POST", body: form });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? `upload failed: ${res.status}`);
  }
  return res.json();
}

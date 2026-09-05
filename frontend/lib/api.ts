import type {
  AnswerResult,
  ChatSource,
  Coverage,
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
  createCourse: (name: string) =>
    req<Course>("/courses", { method: "POST", body: JSON.stringify({ name }) }),
  documentStatus: (documentId: string) => req<DocumentSummary>(`/documents/${documentId}/status`),
  topics: (courseId: string) => req<Topic[]>(`/courses/${courseId}/topics`),
  documents: (courseId: string) => req<DocumentSummary[]>(`/courses/${courseId}/documents`),
  quizzes: (courseId: string) => req<QuizSummary[]>(`/courses/${courseId}/quizzes`),
  quiz: (quizId: string) => req<PublicQuiz>(`/quizzes/${quizId}`),

  /** What a quiz over this selection would cover, before committing to generating it. */
  coverage: (courseId: string, topicIds: string[] = []) =>
    req<Coverage>(`/courses/${courseId}/coverage?topic_ids=${topicIds.join(",")}`),

  /** `n` omitted means "cover the scope" — the length follows the material. */
  createQuiz: (body: {
    course_id: string;
    topic_ids?: string[];
    query?: string;
    n?: number;
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

  /** Ask about the material. Yields the cited passages first, then the answer as it is
   *  written — the citations arrive before a word of the answer, so a claim can be traced
   *  the moment it appears. */
  async *chat(
    courseId: string,
    message: string,
    topicIds: string[] = [],
  ): AsyncGenerator<{ sources?: ChatSource[]; text?: string }> {
    const res = await fetch(`/api/courses/${courseId}/chat`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ message, topic_ids: topicIds }),
    });
    if (!res.body) return;
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let sawSources = false;
    let buffer = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";
      for (const line of lines) {
        if (!line.startsWith("data:")) continue;
        const payload = line.slice(5).replace(/^ /, "");
        if (!sawSources && payload.startsWith("[")) {
          sawSources = true;
          try {
            yield { sources: JSON.parse(payload) as ChatSource[] };
          } catch {
            /* a passage list that will not parse is not worth failing the answer over */
          }
          continue;
        }
        yield { text: payload };
      }
    }
  },

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
        // Exactly one space after "data:" is framing; anything more is content.
        if (line.startsWith("data:")) yield line.slice(5).replace(/^ /, "");
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

export type Course = {
  id: string;
  name: string;
  code: string | null;
  document_count: number;
  chunk_count: number;
};

export type Topic = {
  id: string;
  name: string;
  chunk_count: number;
  parent_topic_id: string | null;
};

export type DocumentSummary = {
  id: string;
  filename: string;
  ingest_status: "pending" | "processing" | "complete" | "failed";
  page_count: number | null;
  chunk_count: number;
  ingest_error: string | null;
};

/** Deliberately has no `is_correct` and no `why_wrong`: the server never sends them
 *  before an answer is submitted (plan/ISSUES.md I-010). */
export type PublicOption = { id: "A" | "B" | "C" | "D"; text: string };

export type PublicQuestion = {
  id: string;
  stem: string;
  options: PublicOption[];
  difficulty: string | null;
  page_refs: number[];
  section_path: string[];
};

export type PublicQuiz = {
  id: string;
  course_id: string;
  question_count: number;
  difficulty: string | null;
  questions: PublicQuestion[];
};

export type QuizSummary = {
  id: string;
  question_count: number;
  difficulty: string | null;
  created_at: string;
  generation_meta: Record<string, unknown>;
};

export type Source = {
  text: string;
  page: number;
  section_path: string[];
  document_name: string;
};

/** §12's core payload: everything the explanation panel needs, in one response. */
export type AnswerResult = {
  is_correct: boolean;
  correct_option_id: string;
  selected_option_id: string | null;
  why_wrong: string | null;
  explanation: string;
  source: Source | null;
};

export type Job = {
  job_id: string;
  status: "queued" | "running" | "complete" | "failed";
  detail: string;
  progress: number;
  total: number;
  result_id: string | null;
  error: string | null;
};

export type Flashcard = {
  id: string;
  front: string;
  back: string;
  origin: "generated" | "missed_question";
  page_refs: number[];
  topic_id: string | null;
};

export type DeckStats = {
  total: number;
  new: number;
  learning: number;
  review: number;
  mature: number;
  due: number;
};

export type AttemptResults = {
  attempt_id: string;
  answered: number;
  correct: number;
  score: number;
  per_topic: Record<string, { answered: number; correct: number }>;
};

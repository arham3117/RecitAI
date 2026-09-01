"use client";

import type { Course, DeckStats, DocumentSummary, Topic } from "@/lib/types";

/** §14 design language: sidebar-left, canvas-right. */
export function Sidebar({
  course,
  topics,
  documents,
  deck,
  selected,
  onToggleTopic,
  onReview,
}: {
  course: Course | null;
  topics: Topic[];
  documents: DocumentSummary[];
  deck: DeckStats | null;
  selected: Set<string>;
  onToggleTopic: (id: string) => void;
  onReview: () => void;
}) {
  return (
    <aside className="border-r border-line bg-paper-raised px-[18px] py-[22px]">
      <div className="font-semibold tracking-tight">
        RecitAI
        <span className="block text-small font-normal tracking-normal text-ink-muted">
          practice from your own material
        </span>
      </div>

      <h2 className="label mt-7 mb-2">Course</h2>
      <p className="text-small text-ink-muted">
        {course ? `${course.name} · ${course.chunk_count} passages` : "—"}
      </p>

      <h2 className="label mt-7 mb-2">Topics</h2>
      <div>
        {topics.map((topic) => {
          const on = selected.has(topic.id);
          return (
            <button
              key={topic.id}
              onClick={() => onToggleTopic(topic.id)}
              aria-pressed={on}
              className={`flex w-full items-center justify-between gap-2 rounded-[7px] px-2 py-1.5 text-left text-small ${
                on ? "bg-accent-soft font-medium text-accent" : "hover:bg-paper"
              }`}
            >
              <span className="truncate">{topic.name}</span>
              <span className={`tabular-nums text-[12px] ${on ? "text-accent" : "text-ink-muted"}`}>
                {topic.chunk_count}
              </span>
            </button>
          );
        })}
      </div>

      <h2 className="label mt-7 mb-2">Material</h2>
      <div className="text-[12.5px] text-ink-muted">
        {documents.map((doc) => (
          <div key={doc.id} className="flex items-center justify-between gap-2 px-2 py-[3px]">
            <span className="truncate">{doc.filename}</span>
            {doc.ingest_status !== "complete" && (
              <span className="flex-none text-[11px] text-accent">{doc.ingest_status}</span>
            )}
          </div>
        ))}
      </div>

      {deck && (
        <>
          <h2 className="label mt-7 mb-2">Flashcards</h2>
          <div className="px-2 text-[12.5px] text-ink-muted">
            <div>
              {deck.due} due · {deck.new} new
            </div>
            <div>
              {deck.learning} learning · {deck.mature} mature
            </div>
          </div>
          {deck.due > 0 && (
            <button className="btn mt-2.5 w-full text-small" onClick={onReview}>
              Review due cards
            </button>
          )}
        </>
      )}
    </aside>
  );
}

"use client";

import type { Course, DeckStats, DocumentSummary, Topic } from "@/lib/types";

/** A collapsible sidebar group.
 *
 *  Native <details> rather than a state hook: it is keyboard-operable and screen-reader
 *  announced without any work, and because the sidebar is never unmounted, open/closed
 *  survives moving between screens on its own.
 *
 *  The count stays in the summary so a collapsed group still tells you what is inside —
 *  collapsing should cost space, not information.
 */
function Group({
  label,
  count,
  badge,
  defaultOpen = false,
  children,
}: {
  label: string;
  count?: number;
  badge?: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  return (
    <details className="group mt-5 first:mt-7" open={defaultOpen}>
      <summary
        className="flex cursor-pointer list-none items-center gap-1.5 rounded-[6px] px-1 py-1
                   text-micro font-semibold uppercase text-ink-muted
                   hover:text-ink focus-visible:outline focus-visible:outline-2
                   focus-visible:outline-accent [&::-webkit-details-marker]:hidden"
      >
        <svg
          viewBox="0 0 10 10"
          aria-hidden="true"
          className="h-2.5 w-2.5 flex-none transition-transform duration-150 group-open:rotate-90"
        >
          <path d="M3 1.5 L7 5 L3 8.5" fill="none" stroke="currentColor" strokeWidth="1.6"
                strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        <span>{label}</span>
        {badge ? (
          <span className="ml-auto rounded-full bg-accent-soft px-1.5 py-px text-[10px]
                           font-semibold normal-case tracking-normal text-accent">
            {badge}
          </span>
        ) : count !== undefined ? (
          <span className="ml-auto tabular-nums text-[11px] font-normal text-ink-faint">
            {count}
          </span>
        ) : null}
      </summary>
      <div className="mt-1.5">{children}</div>
    </details>
  );
}

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
  const ingesting = documents.filter((d) => d.ingest_status !== "complete").length;

  return (
    <aside className="border-r border-line bg-paper-raised px-[18px] py-[22px]">
      <div className="font-semibold tracking-tight">
        RecitAI
        <span className="block text-small font-normal tracking-normal text-ink-muted">
          practice from your own material
        </span>
      </div>

      <p className="mt-6 text-small text-ink-muted">
        {course ? course.name : "—"}
        {course && (
          <span className="block text-ink-faint">{course.chunk_count} passages</span>
        )}
      </p>

      <Group
        label="Topics"
        count={topics.length}
        badge={selected.size ? `${selected.size} selected` : undefined}
      >
        {topics.map((topic) => {
          const on = selected.has(topic.id);
          return (
            <button
              key={topic.id}
              onClick={() => onToggleTopic(topic.id)}
              aria-pressed={on}
              className={`flex w-full items-center justify-between gap-2 rounded-[7px] px-2 py-1.5
                          text-left text-small ${
                            on
                              ? "bg-accent-soft font-medium text-accent"
                              : "hover:bg-paper"
                          }`}
            >
              <span className="truncate">{topic.name}</span>
              <span
                className={`tabular-nums text-[12px] ${on ? "text-accent" : "text-ink-muted"}`}
              >
                {topic.chunk_count}
              </span>
            </button>
          );
        })}
      </Group>

      <Group
        label="Material"
        count={documents.length}
        badge={ingesting ? `${ingesting} processing` : undefined}
      >
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
      </Group>

      {deck && (
        <Group label="Flashcards" badge={deck.due ? `${deck.due} due` : undefined} count={deck.total}>
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
        </Group>
      )}
    </aside>
  );
}

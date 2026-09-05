"use client";

import { IconCards, IconChevron, IconFile, IconLocal, IconTopics } from "./icons";
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
  icon,
  tone,
  count,
  badge,
  defaultOpen = false,
  children,
}: {
  label: string;
  icon: React.ReactNode;
  /** Which of the four meanings this group carries; picks the tile tint. */
  tone: "accent" | "good" | "ink";
  count?: number;
  badge?: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const tile = {
    accent: "bg-accent-soft text-accent",
    good: "bg-good-soft text-good",
    ink: "bg-line/60 text-ink-muted",
  }[tone];

  return (
    <details className="group mt-1.5" open={defaultOpen}>
      <summary
        className="row cursor-pointer list-none hover:bg-paper
                   focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent
                   [&::-webkit-details-marker]:hidden"
      >
        <span className={`tile ${tile}`}>{icon}</span>
        <span className="flex-1 text-small font-medium">{label}</span>
        {badge ? (
          <span
            className={`chip ${
              tone === "good" ? "bg-warn-soft text-warn" : "bg-accent-soft text-accent"
            }`}
          >
            {badge}
          </span>
        ) : count !== undefined ? (
          <span className="tabular-nums text-[12px] text-ink-faint">{count}</span>
        ) : null}
        <IconChevron className="h-3 w-3 flex-none text-ink-faint transition-transform duration-150 group-open:rotate-90" />
      </summary>
      {/* Indented to the tile's edge, so a list reads as belonging to its heading. */}
      <div className="ml-[38px] mt-1 border-l border-line pl-2">{children}</div>
    </details>
  );
}

/** §14 design language: sidebar-left, canvas-right. */
export function Sidebar({
  header,
  course,
  topics,
  documents,
  deck,
  selected,
  onToggleTopic,
  onClearTopics,
  onReview,
}: {
  header?: React.ReactNode;
  course: Course | null;
  topics: Topic[];
  documents: DocumentSummary[];
  deck: DeckStats | null;
  selected: Set<string>;
  onToggleTopic: (id: string) => void;
  onClearTopics: () => void;
  onReview: () => void;
}) {
  const ingesting = documents.filter((d) => d.ingest_status !== "complete").length;

  return (
    // Its own scroll region: the sidebar must never push the canvas or lose its footer.
    <aside className="flex h-screen flex-col border-r border-line bg-paper-raised">
      <div className="flex items-center gap-2 px-4 pb-3 pt-5">
        <span className="tile bg-ink text-white">
          <span className="text-[13px] font-semibold leading-none">R</span>
        </span>
        <span className="leading-tight">
          <span className="block text-small font-semibold tracking-tight">RecitAI</span>
          <span className="block text-[11.5px] text-ink-muted">
            practice from your own material
          </span>
        </span>
      </div>

      <div className="px-3">{header}</div>

      <nav className="mt-3 flex-1 overflow-y-auto px-3 pb-3">
        <Group
          label="Topics"
          icon={<IconTopics />}
          tone="accent"
          count={topics.length}
          badge={selected.size ? `${selected.size} selected` : undefined}
          defaultOpen
        >
          {topics.map((topic) => {
            const on = selected.has(topic.id);
            return (
              <button
                key={topic.id}
                onClick={() => onToggleTopic(topic.id)}
                aria-pressed={on}
                className={`flex w-full items-center justify-between gap-2 rounded-[7px]
                            px-2 py-1.5 text-left text-small transition-colors ${
                              on
                                ? "bg-accent-soft font-medium text-accent"
                                : "text-ink-muted hover:bg-paper hover:text-ink"
                            }`}
              >
                <span className="truncate">{topic.name}</span>
                <span className={`tabular-nums text-[12px] ${on ? "text-accent" : "text-ink-faint"}`}>
                  {topic.chunk_count}
                </span>
              </button>
            );
          })}
          {selected.size > 0 && (
            <button
              onClick={onClearTopics}
              className="mt-1 px-2 py-1 text-[11.5px] text-ink-muted hover:text-ink"
            >
              Clear selection
            </button>
          )}
        </Group>

        <Group
          label="Material"
          icon={<IconFile />}
          tone="ink"
          count={documents.length}
          badge={ingesting ? `${ingesting} processing` : undefined}
        >
          {documents.map((doc) => (
            <div
              key={doc.id}
              className="flex items-center justify-between gap-2 px-2 py-1 text-[12.5px]
                         text-ink-muted"
            >
              <span className="truncate">{doc.filename}</span>
              {doc.ingest_status !== "complete" && (
                <span className="chip flex-none bg-accent-soft text-accent">
                  {doc.ingest_status}
                </span>
              )}
            </div>
          ))}
        </Group>

        {deck && (
          <Group
            label="Flashcards"
            icon={<IconCards />}
            tone="good"
            count={deck.total}
            badge={deck.due ? `${deck.due} due` : undefined}
          >
            {/* A four-way split of the deck, as a bar rather than four numbers: the shape
                of what you know is the thing worth seeing at a glance. */}
            <DeckBar deck={deck} />
            {deck.due > 0 && (
              <button className="btn mt-2 w-full !py-1.5 text-small" onClick={onReview}>
                Review {deck.due} due
              </button>
            )}
          </Group>
        )}
      </nav>

      <div className="flex items-center gap-1.5 border-t border-line px-4 py-2.5
                      text-[11px] text-ink-faint">
        <IconLocal className="h-3 w-3 flex-none" />
        <span>Runs on your machine · nothing leaves it</span>
      </div>
    </aside>
  );
}

/** Deck composition as a single stacked bar. */
function DeckBar({ deck }: { deck: DeckStats }) {
  const parts = [
    { n: deck.due, cls: "bg-warn", label: "due" },
    { n: deck.learning, cls: "bg-accent", label: "learning" },
    { n: deck.mature, cls: "bg-good", label: "mature" },
    { n: deck.new, cls: "bg-line-strong", label: "new" },
  ].filter((p) => p.n > 0);
  const total = parts.reduce((a, p) => a + p.n, 0) || 1;

  return (
    <div className="px-2 py-1">
      <div className="flex h-1.5 overflow-hidden rounded-full bg-line">
        {parts.map((p) => (
          <div key={p.label} className={p.cls} style={{ width: `${(p.n / total) * 100}%` }} />
        ))}
      </div>
      <div className="mt-1.5 flex flex-wrap gap-x-2.5 gap-y-0.5 text-[11.5px] text-ink-muted">
        {parts.map((p) => (
          <span key={p.label} className="inline-flex items-center gap-1">
            <span className={`h-1.5 w-1.5 rounded-full ${p.cls}`} />
            {p.n} {p.label}
          </span>
        ))}
      </div>
    </div>
  );
}

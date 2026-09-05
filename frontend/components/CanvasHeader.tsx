"use client";

import { IconAsk } from "./icons";
import type { Course } from "@/lib/types";

/** The bar above the canvas.
 *
 *  Before this the chat's own <h1> was the only page heading, so the course you were
 *  working in and the scope your questions were answered from were both invisible —
 *  the scope in particular changes every answer, and it was only legible from which
 *  sidebar rows happened to be highlighted.
 */
export function CanvasHeader({
  course,
  scopeLabel,
  narrowed,
  onClearScope,
}: {
  course: Course;
  scopeLabel: string;
  narrowed: boolean;
  onClearScope: () => void;
}) {
  return (
    <header className="sticky top-0 z-10 -mx-8 mb-6 border-b border-line bg-paper/90 px-8 py-3 backdrop-blur">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <span className="tile bg-accent-soft text-accent">
          <IconAsk />
        </span>
        <h1 className="truncate text-body font-semibold tracking-tight">{course.name}</h1>
        <span className="whitespace-nowrap text-[11.5px] text-ink-muted">
          {course.document_count} file{course.document_count === 1 ? "" : "s"} ·{" "}
          {course.chunk_count} passages
        </span>

        <div className="ml-auto flex items-center gap-2">
          <span className="text-[11.5px] text-ink-muted">Answering from</span>
          {narrowed ? (
            <button
              onClick={onClearScope}
              title="Clear the topic selection"
              className="chip border border-accent-line bg-accent-soft text-accent
                         hover:border-accent"
            >
              {scopeLabel}
              <span aria-hidden className="text-[13px] leading-none">×</span>
            </button>
          ) : (
            <span className="chip border border-line bg-paper-raised text-ink-muted">
              {scopeLabel}
            </span>
          )}
        </div>
      </div>
    </header>
  );
}

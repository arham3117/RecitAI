"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import type { Course } from "@/lib/types";

/** Pick a course, or start a new one.
 *
 *  The app previously used whichever course happened to be first, which made it a demo of
 *  one dataset rather than something a person could bring their own material to.
 */
export function CourseSwitcher({
  courses,
  active,
  onSelect,
  onCreated,
}: {
  courses: Course[];
  active: Course | null;
  onSelect: (course: Course) => void;
  onCreated: (course: Course) => void;
}) {
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function create() {
    const trimmed = name.trim();
    if (!trimmed) return;
    setError(null);
    try {
      const course = await api.createCourse(trimmed);
      setName("");
      setCreating(false);
      setOpen(false);
      onCreated(course);
    } catch (e) {
      setError(e instanceof Error ? e.message : "could not create the course");
    }
  }

  return (
    <div className="relative mt-6">
      <button
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center gap-1.5 rounded-control border border-line
                   bg-paper px-2.5 py-2 text-left hover:border-line-strong"
      >
        <span className="min-w-0 flex-1">
          <span className="block truncate text-small font-medium">
            {active ? active.name : "No course yet"}
          </span>
          {active && (
            <span className="block text-[11.5px] text-ink-muted">
              {active.document_count} file{active.document_count === 1 ? "" : "s"} ·{" "}
              {active.chunk_count} passages
            </span>
          )}
        </span>
        <svg viewBox="0 0 10 10" aria-hidden="true" className="h-2.5 w-2.5 flex-none text-ink-muted">
          <path d="M2 3.5 L5 6.5 L8 3.5" fill="none" stroke="currentColor" strokeWidth="1.6"
                strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>

      {open && (
        <div className="absolute left-0 right-0 top-full z-10 mt-1 rounded-control border
                        border-line bg-paper-raised p-1 shadow-lg">
          {courses.map((course) => (
            <button
              key={course.id}
              onClick={() => {
                onSelect(course);
                setOpen(false);
              }}
              className={`block w-full truncate rounded-[6px] px-2 py-1.5 text-left text-small
                          hover:bg-paper ${course.id === active?.id ? "text-accent" : ""}`}
            >
              {course.name}
            </button>
          ))}

          {creating ? (
            <div className="border-t border-line p-1.5">
              <input
                autoFocus
                value={name}
                onChange={(e) => setName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void create();
                  if (e.key === "Escape") setCreating(false);
                }}
                placeholder="Course name"
                className="w-full rounded-[6px] border border-line bg-paper px-2 py-1.5 text-small
                           outline-none focus:border-accent"
              />
              <button className="btn mt-1.5 w-full text-small" onClick={() => void create()}>
                Create
              </button>
              {error && <p className="mt-1 text-small text-bad">{error}</p>}
            </div>
          ) : (
            <button
              onClick={() => setCreating(true)}
              className="mt-1 block w-full rounded-[6px] border-t border-line px-2 py-1.5
                         text-left text-small text-ink-muted hover:bg-paper hover:text-ink"
            >
              + New course
            </button>
          )}
        </div>
      )}
    </div>
  );
}

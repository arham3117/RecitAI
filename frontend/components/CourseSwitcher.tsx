"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { IconPlus } from "./icons";
import type { Course } from "@/lib/types";

/** Pick a course, start a new one, or remove one.
 *
 *  The app previously used whichever course happened to be first, which made it a demo of
 *  one dataset rather than something a person could bring their own material to.
 */
export function CourseSwitcher({
  courses,
  active,
  onSelect,
  onCreated,
  onDeleted,
}: {
  courses: Course[];
  active: Course | null;
  onSelect: (course: Course) => void;
  onCreated: (course: Course) => void;
  onDeleted: (courseId: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);

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

  async function remove(courseId: string) {
    setError(null);
    try {
      await api.deleteCourse(courseId);
      setConfirming(null);
      onDeleted(courseId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "could not delete the course");
    }
  }

  function startCreating() {
    setCreating(true);
    setOpen(true);
  }

  return (
    <div className="relative mt-4">
      {/* A split control. "New course" used to live only at the foot of a dropdown you
          had to know to open, in muted grey — so the one action a first-time user needs
          was the hardest thing on the screen to find. It is now always visible. */}
      <div className="flex items-stretch gap-1">
        <button
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          className="flex min-w-0 flex-1 items-center gap-1.5 rounded-control border
                     border-line bg-paper px-2.5 py-2 text-left hover:border-line-strong"
        >
          <span className="min-w-0 flex-1">
            <span className="block truncate text-small font-medium leading-snug" title={active?.name}>
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

        <button
          onClick={startCreating}
          title="Add a new course"
          aria-label="Add a new course"
          className="grid w-9 flex-none place-items-center rounded-control border
                     border-accent-line bg-accent-soft text-accent transition-colors
                     hover:border-accent hover:bg-accent hover:text-white"
        >
          <IconPlus className="h-4 w-4" />
        </button>
      </div>

      {open && (
        <div className="absolute left-0 right-0 top-full z-20 mt-1 rounded-control border
                        border-line bg-paper-raised p-1 shadow-lg">
          {/* Capped and scrollable: a long list used to run off the bottom of the panel,
              taking the create action with it. */}
          <div className="max-h-[248px] overflow-y-auto">
            {courses.map((course) => (
              <div key={course.id} className="group flex items-center gap-1">
                <button
                  onClick={() => {
                    onSelect(course);
                    setOpen(false);
                  }}
                  className={`min-w-0 flex-1 truncate rounded-[6px] px-2 py-1.5 text-left
                              text-small hover:bg-paper ${
                                course.id === active?.id ? "font-medium text-accent" : ""
                              }`}
                >
                  {course.name}
                </button>

                {confirming === course.id ? (
                  <span className="flex flex-none items-center gap-1 pr-1">
                    <button
                      onClick={() => void remove(course.id)}
                      className="rounded-[5px] bg-bad px-1.5 py-0.5 text-[11px] font-medium text-white"
                    >
                      Delete
                    </button>
                    <button
                      onClick={() => setConfirming(null)}
                      className="text-[11px] text-ink-muted hover:text-ink"
                    >
                      Cancel
                    </button>
                  </span>
                ) : (
                  <button
                    onClick={() => setConfirming(course.id)}
                    title={`Delete ${course.name}`}
                    aria-label={`Delete ${course.name}`}
                    className="mr-1 grid h-6 w-6 flex-none place-items-center rounded-[5px]
                               text-ink-faint opacity-0 hover:bg-bad-soft hover:text-bad
                               focus:opacity-100 group-hover:opacity-100"
                  >
                    <svg viewBox="0 0 16 16" aria-hidden className="h-3.5 w-3.5">
                      <path d="M3 4.5h10M6.5 4.5V3.2h3v1.3M5 4.5l.6 8h4.8l.6-8M7 7v3.5M9 7v3.5"
                            fill="none" stroke="currentColor" strokeWidth="1.4"
                            strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  </button>
                )}
              </div>
            ))}
          </div>

          {creating ? (
            <div className="mt-1 border-t border-line p-1.5">
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
              <button className="btn btn-primary mt-1.5 w-full !py-1.5 text-small" onClick={() => void create()}>
                Create course
              </button>
            </div>
          ) : (
            <button
              onClick={() => setCreating(true)}
              className="mt-1 flex w-full items-center gap-2 rounded-[6px] border-t border-line
                         px-2 py-2 text-left text-small font-medium text-accent hover:bg-accent-soft"
            >
              <IconPlus className="h-3.5 w-3.5" />
              New course
            </button>
          )}
          {error && <p className="px-2 py-1 text-[11.5px] text-bad">{error}</p>}
        </div>
      )}
    </div>
  );
}

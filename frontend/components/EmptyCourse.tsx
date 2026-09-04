"use client";

import { useRef, useState } from "react";
import { uploadDocument } from "@/lib/api";
import type { Course } from "@/lib/types";

/** First run. The previous empty state told the reader to run `make ingest`, which is an
 *  instruction to whoever built the thing, not to whoever is using it. */
export function EmptyCourse({
  course,
  onUploaded,
}: {
  course: Course | null;
  onUploaded: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  async function upload(file: File) {
    if (!course) return;
    setError(null);
    setBusy(true);
    try {
      await uploadDocument(course.id, file);
      onUploaded();
    } catch (e) {
      setError(e instanceof Error ? e.message : "upload failed");
    } finally {
      setBusy(false);
    }
  }

  if (!course) {
    return (
      <div className="pt-4">
        <h1 className="text-display font-semibold">Start with a course</h1>
        <p className="mt-1.5 max-w-[58ch] text-ink-muted">
          Create one in the sidebar, then add your lecture slides. Everything stays on this
          machine.
        </p>
      </div>
    );
  }

  return (
    <div className="pt-4">
      <h1 className="text-display font-semibold">Add your material</h1>
      <p className="mt-1.5 max-w-[58ch] text-ink-muted">
        Drop in the slides for <b className="text-ink">{course.name}</b>. RecitAI reads them,
        then answers questions and writes practice quizzes using only what is in them.
      </p>

      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          const file = e.dataTransfer.files?.[0];
          if (file) void upload(file);
        }}
        className={`mt-6 rounded-card border-2 border-dashed p-10 text-center transition-colors ${
          dragging ? "border-accent bg-accent-soft" : "border-line bg-paper-raised"
        }`}
      >
        <p className="font-medium">{busy ? "Uploading…" : "Drop a .pptx or .pdf here"}</p>
        <p className="mt-1 text-small text-ink-muted">or</p>
        <button className="btn btn-primary mt-2" disabled={busy} onClick={() => fileRef.current?.click()}>
          Choose a file
        </button>
        <input
          ref={fileRef}
          type="file"
          accept=".pptx,.pdf"
          hidden
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) void upload(file);
            e.target.value = "";
          }}
        />
        {error && <p className="mt-3 text-small text-bad">{error}</p>}
      </div>

      <p className="mt-4 max-w-[58ch] text-small text-ink-muted">
        PowerPoint decks work best — RecitAI keeps each slide&rsquo;s number so it can show
        you the source of every answer. Scanned PDFs are not supported, since there is no
        text to read.
      </p>
    </div>
  );
}

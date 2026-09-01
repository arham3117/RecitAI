"use client";

import { useRef, useState } from "react";
import { uploadDocument } from "@/lib/api";
import type { Course } from "@/lib/types";

/**
 * §14's dual-mode hero. The mockup's input is a paste-notes textarea; the architecture is
 * a persistent indexed library. The layout is kept identical and the input does both:
 * choose a scope and start, or add material.
 */
export function Hero({
  course,
  selectedCount,
  onGenerate,
  onUploaded,
  busy,
}: {
  course: Course | null;
  selectedCount: number;
  onGenerate: (n: number, query: string) => void;
  onUploaded: () => void;
  busy: boolean;
}) {
  const [n, setN] = useState(5);
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  async function upload(file: File) {
    setError(null);
    try {
      await uploadDocument(course!.id, file);
      onUploaded();
    } catch (e) {
      setError(e instanceof Error ? e.message : "upload failed");
    }
  }

  return (
    <>
      <h1 className="text-display font-semibold">What do you want to practice today?</h1>
      <p className="mt-1.5 mb-6 text-ink-muted">
        Questions are drawn only from your material, and every answer cites the slide it
        came from.
      </p>

      <section className="card">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && !busy && onGenerate(n, query)}
          placeholder={
            selectedCount > 0
              ? `${selectedCount} topic${selectedCount > 1 ? "s" : ""} selected — press Enter`
              : "Type what you want to study, or pick topics on the left…"
          }
          className="w-full rounded-control border border-line bg-paper px-4 py-3 outline-none placeholder:text-ink-faint focus:border-accent"
        />

        <div className="mt-3.5 flex flex-wrap items-center gap-2.5">
          <label className="text-small text-ink-muted">Questions</label>
          <input
            type="number"
            min={1}
            max={20}
            value={n}
            onChange={(e) => setN(Number(e.target.value))}
            className="w-16 rounded-control border border-line px-2 py-1.5"
          />
          <button className="btn btn-primary" disabled={busy} onClick={() => onGenerate(n, query)}>
            Generate
          </button>
          <button className="btn" onClick={() => fileRef.current?.click()}>
            Add material
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
        </div>

        {error && <p className="mt-3 text-small text-bad">{error}</p>}
        <p className="mt-3.5 text-small text-ink-muted">
          Generation runs locally and takes roughly 20 seconds per question.
        </p>
      </section>
    </>
  );
}

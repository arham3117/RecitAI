"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Flashcard } from "@/lib/types";

const RATINGS = [
  { label: "Again", value: 1 as const },
  { label: "Hard", value: 2 as const },
  { label: "Good", value: 3 as const },
  { label: "Easy", value: 4 as const },
];

export function FlashcardReviewer({
  cards,
  onDone,
}: {
  cards: Flashcard[];
  onDone: () => void;
}) {
  const [index, setIndex] = useState(0);
  const [revealed, setRevealed] = useState(false);
  const card = cards[index];

  const grade = useCallback(
    async (rating: 1 | 2 | 3 | 4) => {
      if (!card) return;
      await api.reviewCard(card.id, rating);
      if (index + 1 >= cards.length) return onDone();
      setIndex((i) => i + 1);
      setRevealed(false);
    },
    [card, index, cards.length, onDone],
  );

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (!revealed && (event.key === " " || event.key === "Enter")) {
        event.preventDefault();
        setRevealed(true);
        return;
      }
      if (revealed && event.key >= "1" && event.key <= "4") {
        void grade(Number(event.key) as 1 | 2 | 3 | 4);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [revealed, grade]);

  if (!card) return null;

  return (
    <div>
      <div className="mb-4 flex items-center justify-between gap-3">
        <button
          onClick={onDone}
          className="-ml-1 flex items-center gap-1.5 rounded-control px-1.5 py-1 text-small
                     text-ink-muted hover:bg-paper-raised hover:text-ink"
        >
          <svg viewBox="0 0 10 10" aria-hidden="true" className="h-2.5 w-2.5">
            <path d="M6.5 1.5 L3 5 L6.5 8.5" fill="none" stroke="currentColor" strokeWidth="1.6"
                  strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          Done for now
        </button>
        <span className="text-small tabular-nums text-ink-muted">
          {index + 1} of {cards.length}
        </span>
      </div>
      <div className="mb-5 flex gap-1" aria-hidden="true">
        {cards.map((_, i) => (
          <div
            key={i}
            className={`h-[3px] flex-1 rounded-sm ${
              i < index ? "bg-accent" : i === index ? "bg-accent/45" : "bg-line"
            }`}
          />
        ))}
      </div>
      <div className="mb-3.5 flex items-center justify-end gap-3">
        <span className="rounded-full border border-line bg-paper px-2.5 py-0.5 text-small text-ink-muted">
          {card.origin === "missed_question" ? "from a question you missed" : "generated"}
        </span>
      </div>

      <section className="card">
        <h1 className="text-title font-medium">{card.front}</h1>

        {revealed ? (
          <>
            <blockquote className="mt-4 rounded-r-control border-l-[3px] border-accent bg-paper px-4 py-3">
              {card.back}
            </blockquote>
            {card.page_refs.length > 0 && (
              <p className="mt-2 text-small text-ink-muted">slide {card.page_refs[0]}</p>
            )}
            <div className="mt-5 flex flex-wrap items-center gap-2">
              {RATINGS.map((r) => (
                <button
                  key={r.value}
                  className={`btn ${r.value === 3 ? "btn-primary" : ""}`}
                  onClick={() => void grade(r.value)}
                >
                  {r.label} <span className="opacity-60">{r.value}</span>
                </button>
              ))}
              <span className="text-small text-ink-muted">press 1–4</span>
            </div>
          </>
        ) : (
          <div className="mt-5 flex items-center gap-2.5">
            <button className="btn btn-primary" onClick={() => setRevealed(true)}>
              Show answer
            </button>
            <span className="text-small text-ink-muted">space to reveal</span>
          </div>
        )}
      </section>
    </div>
  );
}

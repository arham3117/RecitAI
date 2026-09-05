"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import type { AnswerResult, PublicQuestion, Source } from "@/lib/types";
import { SkeletonLines } from "./Skeleton";

/**
 * §14: "The explanation panel deserves more design attention than everything else
 * combined — it is where the product's value actually lands."
 *
 * The whole payload arrives with the answer, so nothing here waits on a second request.
 * The one thing that does stream is the optional follow-up, which the student chose to
 * wait for.
 */
/** The passage a question came from usually spans several merged slides, so it is shown
 *  slide by slide — with a picture of each where one can be produced. Text says what a
 *  slide states; only the image shows a diagram, and 12% of slides here are diagram-only. */
function SourcePanel({ source }: { source: Source }) {
  // A merged passage can span several slides, and rendering them all at full size buried
  // the "Next question" button under two screens of scrolling. The first slide is the
  // evidence you look at; the rest are there if you want them.
  const [expanded, setExpanded] = useState(false);
  const shown = expanded ? source.slides : source.slides.slice(0, 1);
  const hidden = source.slides.length - shown.length;

  const range =
    source.page === source.page_end
      ? `slide ${source.page}`
      : `slides ${source.page}–${source.page_end}`;

  return (
    <div className="mt-4">
      <p className="mb-2 text-small text-ink-muted">
        From <b className="text-ink">{source.document_name}</b>, {range}
        {source.section_path.length > 0 && <> — {source.section_path.join(" › ")}</>}
      </p>

      <div className="space-y-3">
        {shown.map((slide, i) => (
          <figure key={i} className="overflow-hidden rounded-control border border-line bg-paper">
            {slide.image_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              // Capped so a tall slide cannot push the controls off the screen; the
              // full-size original is one click away.
              <a href={slide.image_url} target="_blank" rel="noreferrer" className="block">
                <img
                  src={slide.image_url}
                  alt={`Slide ${slide.page}${slide.heading ? `: ${slide.heading}` : ""}`}
                  className="mx-auto block max-h-[330px] max-w-full"
                  loading="lazy"
                />
              </a>
            ) : (
              <div className="px-4 py-3">
                {slide.heading && <p className="mb-1 font-medium">{slide.heading}</p>}
                <p className="whitespace-pre-wrap text-small text-ink-muted">{slide.text}</p>
              </div>
            )}
            <figcaption className="flex items-center justify-between gap-3 border-t
                                   border-line px-4 py-1.5 text-small text-ink-muted">
              <span>
                slide {slide.page}
                {slide.heading && !slide.image_url ? "" : slide.heading ? ` — ${slide.heading}` : ""}
              </span>
              {slide.image_url && (
                <a
                  href={slide.image_url}
                  target="_blank"
                  rel="noreferrer"
                  className="flex-none text-[11.5px] text-accent hover:underline"
                >
                  open full size
                </a>
              )}
            </figcaption>
          </figure>
        ))}
      </div>

      {hidden > 0 && (
        <button
          onClick={() => setExpanded(true)}
          className="mt-2 w-full rounded-control border border-dashed border-line py-2
                     text-small text-ink-muted hover:border-line-strong hover:text-ink"
        >
          Show {hidden} more slide{hidden > 1 ? "s" : ""} from this passage
        </button>
      )}

      {source.images === "unavailable" && (
        <p className="mt-2 text-small text-ink-faint">
          Showing the extracted text. To see the actual slides, save a PDF copy of the deck
          next to it (File → Save as PDF), or install LibreOffice.
        </p>
      )}
    </div>
  );
}

export function ExplanationPanel({
  result,
  question,
  onNext,
  isLast,
}: {
  result: AnswerResult;
  question: PublicQuestion;
  onNext: () => void;
  isLast: boolean;
}) {
  const [stream, setStream] = useState<string | null>(null);
  const [streaming, setStreaming] = useState(false);

  async function followUp(prompt: string) {
    setStream("");
    setStreaming(true);
    try {
      for await (const piece of api.explain(question.id, prompt)) {
        setStream((prev) => (prev ?? "") + piece);
      }
    } finally {
      setStreaming(false);
    }
  }

  return (
    <section className="card mt-4" aria-live="polite">
      {/* The verdict is the first thing the eye needs, so it gets the tile and the
          colour; the explanation follows in ordinary ink. */}
      <div className="mb-2 flex items-center gap-2">
        <span
          className={`tile ${
            result.is_correct ? "bg-good-soft text-good" : "bg-bad-soft text-bad"
          }`}
        >
          {result.is_correct ? (
            <svg viewBox="0 0 16 16" aria-hidden className="h-3.5 w-3.5">
              <path d="M3.5 8.5 6.5 11.5 12.5 5" fill="none" stroke="currentColor"
                    strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          ) : (
            <svg viewBox="0 0 16 16" aria-hidden className="h-3.5 w-3.5">
              <path d="M5 5l6 6M11 5l-6 6" fill="none" stroke="currentColor"
                    strokeWidth="1.9" strokeLinecap="round" />
            </svg>
          )}
        </span>
        <p className={`font-semibold ${result.is_correct ? "text-good" : "text-bad"}`}>
          {result.is_correct ? "Correct" : "Not quite"}
        </p>
      </div>
      <p>{result.explanation}</p>

      {result.source && <SourcePanel source={result.source} />}

      <div className="sticky bottom-0 -mx-6 -mb-6 mt-5 flex flex-wrap items-center gap-2.5
                      border-t border-line bg-paper-raised/95 px-6 py-3 backdrop-blur">
        <button
          className="btn"
          disabled={streaming}
          onClick={() => followUp("Explain this differently, more simply.")}
        >
          Explain differently
        </button>
        <button
          className="btn"
          disabled={streaming}
          onClick={() => followUp("Why is the answer I chose wrong?")}
        >
          Ask a question
        </button>
        <button className="btn btn-primary ml-auto" onClick={onNext}>
          {isLast ? "See results" : "Next question"}
        </button>
      </div>

      {stream !== null && (
        <div className="mt-3 rounded-control bg-paper px-4 py-3 text-body">
          {stream === "" && streaming ? (
            <SkeletonLines count={2} />
          ) : (
            <p className="whitespace-pre-wrap">{stream}</p>
          )}
        </div>
      )}
    </section>
  );
}

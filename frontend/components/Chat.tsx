"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { ChatSource, ChatTurn } from "@/lib/types";

/** Passages an answer was built from. Shown above the answer, because they arrive first:
 *  you can see what the tutor is working from before it has written a word. */
function Sources({ sources }: { sources: ChatSource[] }) {
  const [open, setOpen] = useState(false);
  if (sources.length === 0) return null;

  return (
    <details
      className="mt-2 rounded-control border border-line bg-paper"
      open={open}
      onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}
    >
      <summary className="cursor-pointer list-none px-3 py-2 text-small text-ink-muted hover:text-ink [&::-webkit-details-marker]:hidden">
        {open ? "▾" : "▸"} {sources.length} passage{sources.length > 1 ? "s" : ""} used
      </summary>
      <div className="space-y-2 px-3 pb-3">
        {sources.map((s) => (
          <div key={s.n} className="overflow-hidden rounded-[7px] border border-line bg-paper-raised">
            {s.image_url && (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={s.image_url} alt={`Slide ${s.page_start}`} className="block w-full" loading="lazy" />
            )}
            <p className="px-3 py-1.5 text-small text-ink-muted">
              <b className="text-accent">[{s.n}]</b> {s.document_name}, slide{" "}
              {s.page_start === s.page_end ? s.page_start : `${s.page_start}–${s.page_end}`}
              {s.section_path.length > 0 && <> — {s.section_path.join(" › ")}</>}
            </p>
          </div>
        ))}
      </div>
    </details>
  );
}

export function Chat({
  courseId,
  topicIds,
  scopeLabel,
}: {
  courseId: string;
  topicIds: string[];
  scopeLabel: string;
}) {
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns]);

  async function send() {
    const message = draft.trim();
    if (!message || busy) return;
    setDraft("");
    setBusy(true);
    setTurns((t) => [...t, { role: "you", text: message }, { role: "tutor", text: "", streaming: true }]);

    try {
      for await (const part of api.chat(courseId, message, topicIds)) {
        setTurns((t) => {
          const next = [...t];
          const last = { ...next[next.length - 1] };
          if (part.sources) last.sources = part.sources;
          if (part.text !== undefined) last.text += part.text;
          next[next.length - 1] = last;
          return next;
        });
      }
    } catch (e) {
      setTurns((t) => {
        const next = [...t];
        next[next.length - 1] = {
          role: "tutor",
          text: e instanceof Error ? e.message : "Something went wrong.",
        };
        return next;
      });
    } finally {
      setBusy(false);
      setTurns((t) => {
        const next = [...t];
        next[next.length - 1] = { ...next[next.length - 1], streaming: false };
        return next;
      });
    }
  }

  return (
    <div className="flex min-h-[calc(100vh-9rem)] flex-col">
      <div className={turns.length === 0 ? "" : "flex-1"}>
        {turns.length === 0 ? (
          <div className="pt-4">
            <h1 className="text-[1.6rem] font-semibold leading-tight tracking-tight">
              Ask about your material
            </h1>
            <p className="mt-1.5 max-w-[60ch] text-ink-muted">
              Answers come only from your own slides, with the passage and slide number
              they came from. If your material does not cover something, it will say so
              rather than guess.
            </p>
            <div className="mt-6 flex flex-wrap gap-2">
              {[
                "What is vertical fragmentation?",
                "How does a semijoin work?",
                "Explain the allocation model",
              ].map((q) => (
                <button
                  key={q}
                  className="btn text-small"
                  onClick={() => setDraft(q)}
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="space-y-5 pt-2">
            {turns.map((turn, i) =>
              turn.role === "you" ? (
                <div key={i} className="flex justify-end">
                  <p className="max-w-[80%] rounded-[14px] rounded-br-[4px] bg-accent-soft px-4 py-2.5 text-accent">
                    {turn.text}
                  </p>
                </div>
              ) : (
                <div key={i}>
                  {turn.sources && <Sources sources={turn.sources} />}
                  <p className="mt-2 whitespace-pre-wrap">
                    {turn.text}
                    {turn.streaming && (
                      <span className="ml-0.5 inline-block h-[1.05em] w-[2px] translate-y-[3px] animate-pulse bg-ink-muted" />
                    )}
                  </p>
                </div>
              ),
            )}
          </div>
        )}
        <div ref={endRef} />
      </div>

      {/* When the conversation is empty the composer sits under the prompts rather than
          being pushed to the bottom of an empty screen. */}
      <div
        className={`sticky bottom-0 -mx-2 px-2 pb-5 pt-3 ${
          turns.length === 0 ? "mt-6" : "mt-6 bg-paper/85 backdrop-blur"
        }`}
      >
        <div className="flex items-end gap-2 rounded-[14px] border border-line bg-paper-raised p-2 focus-within:border-accent">
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void send();
              }
            }}
            rows={1}
            placeholder={`Ask about ${scopeLabel}…`}
            className="max-h-40 flex-1 resize-none bg-transparent px-2 py-1.5 outline-none placeholder:text-ink-faint"
          />
          <button className="btn btn-primary" disabled={busy || !draft.trim()} onClick={() => void send()}>
            {busy ? "…" : "Ask"}
          </button>
        </div>
        <p className="mt-2 text-small text-ink-muted">
          Answers are drawn only from {scopeLabel}. RecitAI can make mistakes — check the
          cited slide.
        </p>
      </div>
    </div>
  );
}

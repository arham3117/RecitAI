/** A small stroke-icon set.
 *
 *  Inline rather than an icon package: nine glyphs at one weight is not worth a
 *  dependency, and keeping them here means they inherit `currentColor` and the
 *  surrounding type size without any configuration.
 */
type P = { className?: string };

const base = "h-3.5 w-3.5 flex-none";
const stroke = {
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.7,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

export const IconAsk = ({ className = base }: P) => (
  <svg viewBox="0 0 16 16" aria-hidden className={className}>
    <path d="M2.5 3.5h11v7h-6l-3.5 3v-3h-1.5z" {...stroke} />
  </svg>
);

export const IconQuiz = ({ className = base }: P) => (
  <svg viewBox="0 0 16 16" aria-hidden className={className}>
    <path d="M6 6a2 2 0 1 1 2.6 1.9c-.4.15-.6.5-.6.9v.4" {...stroke} />
    <path d="M8 12.2v.1" {...stroke} />
    <circle cx="8" cy="8" r="6.2" {...stroke} />
  </svg>
);

export const IconCards = ({ className = base }: P) => (
  <svg viewBox="0 0 16 16" aria-hidden className={className}>
    <rect x="2" y="4.5" width="9" height="7.5" rx="1.4" {...stroke} />
    <path d="M5 2.8h7.2a1.4 1.4 0 0 1 1.4 1.4v6.4" {...stroke} />
  </svg>
);

export const IconTopics = ({ className = base }: P) => (
  <svg viewBox="0 0 16 16" aria-hidden className={className}>
    <circle cx="4" cy="4" r="1.9" {...stroke} />
    <circle cx="12" cy="5" r="1.6" {...stroke} />
    <circle cx="7" cy="12" r="1.7" {...stroke} />
    <path d="M5.6 5.3 6.4 10.4M10.6 6.3 8.3 10.7" {...stroke} />
  </svg>
);

export const IconFile = ({ className = base }: P) => (
  <svg viewBox="0 0 16 16" aria-hidden className={className}>
    <path d="M9 2H4.5A1.5 1.5 0 0 0 3 3.5v9A1.5 1.5 0 0 0 4.5 14h7a1.5 1.5 0 0 0 1.5-1.5V6z" {...stroke} />
    <path d="M9 2v3.2c0 .5.3.8.8.8H13" {...stroke} />
  </svg>
);

export const IconPlus = ({ className = base }: P) => (
  <svg viewBox="0 0 16 16" aria-hidden className={className}>
    <path d="M8 3.5v9M3.5 8h9" {...stroke} />
  </svg>
);

export const IconLocal = ({ className = base }: P) => (
  <svg viewBox="0 0 16 16" aria-hidden className={className}>
    <rect x="2.2" y="3" width="11.6" height="4.2" rx="1.2" {...stroke} />
    <rect x="2.2" y="8.8" width="11.6" height="4.2" rx="1.2" {...stroke} />
    <path d="M4.6 5.1h.01M4.6 10.9h.01" {...stroke} />
  </svg>
);

export const IconArrow = ({ className = base }: P) => (
  <svg viewBox="0 0 16 16" aria-hidden className={className}>
    <path d="M3.5 8h9M9 4.5 12.5 8 9 11.5" {...stroke} />
  </svg>
);

export const IconChevron = ({ className = base }: P) => (
  <svg viewBox="0 0 16 16" aria-hidden className={className}>
    <path d="M6 3.5 10.5 8 6 12.5" {...stroke} />
  </svg>
);

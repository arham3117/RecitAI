import type { Config } from "tailwindcss";

// §14: extract the palette and type scale into tokens BEFORE building components.
// Near-black on off-white, one accent, generous whitespace.
export default {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: { DEFAULT: "#16181d", muted: "#6b7280", faint: "#9ca3af" },
        paper: { DEFAULT: "#faf9f7", raised: "#ffffff" },
        line: { DEFAULT: "#e5e3de", strong: "#cfcbc3" },
        accent: { DEFAULT: "#2f5bea", soft: "#eef2fe" },
        good: { DEFAULT: "#0f7b52", soft: "#e8f5ee" },
        bad: { DEFAULT: "#b42318", soft: "#fdecea" },
      },
      fontFamily: {
        sans: ["ui-sans-serif", "-apple-system", "Segoe UI", "Roboto", "sans-serif"],
      },
      fontSize: {
        // A restrained scale: display for the hero, then three body sizes.
        display: ["1.75rem", { lineHeight: "1.25", letterSpacing: "-0.02em" }],
        title: ["1.19rem", { lineHeight: "1.45", letterSpacing: "-0.01em" }],
        body: ["0.9375rem", { lineHeight: "1.55" }],
        small: ["0.8125rem", { lineHeight: "1.5" }],
        micro: ["0.6875rem", { lineHeight: "1.4", letterSpacing: "0.09em" }],
      },
      borderRadius: { card: "10px", control: "8px" },
      maxWidth: { canvas: "54rem" },
    },
  },
  plugins: [],
} satisfies Config;

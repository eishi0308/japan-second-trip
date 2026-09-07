import type { Config } from "tailwindcss";

/**
 * The palette is deliberately narrow: an ink-on-paper base with a single
 * restrained accent. A verification product loses credibility the moment it
 * looks like a toy, so colour is used to mean something (severity, freshness)
 * rather than to decorate.
 */
const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          50: "#f7f7f6",
          100: "#e9e9e6",
          200: "#d3d3ce",
          300: "#b0b0a8",
          400: "#87877e",
          500: "#6a6a62",
          600: "#54544e",
          700: "#454540",
          800: "#3a3a36",
          900: "#1c1c1a",
          950: "#121211",
        },
        paper: "#fbfaf8",
        accent: {
          50: "#f2f6f4",
          100: "#dfeae5",
          200: "#c1d6cd",
          300: "#98baad",
          400: "#6d9a89",
          500: "#4f7f6d",
          600: "#3c6656",
          700: "#325347",
          800: "#2b433b",
          900: "#253932",
        },
        signal: {
          critical: "#a13d33",
          warning: "#9a6b23",
          good: "#3c6656",
          info: "#3f5b73",
        },
      },
      fontFamily: {
        sans: ["var(--font-sans)", "ui-sans-serif", "system-ui", "sans-serif"],
        serif: ["var(--font-serif)", "ui-serif", "Georgia", "serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      fontSize: {
        display: ["clamp(2.5rem, 6vw, 4.5rem)", { lineHeight: "1.02", letterSpacing: "-0.03em" }],
        headline: ["clamp(1.75rem, 3.5vw, 2.75rem)", { lineHeight: "1.1", letterSpacing: "-0.02em" }],
        title: ["clamp(1.25rem, 2vw, 1.6rem)", { lineHeight: "1.2", letterSpacing: "-0.01em" }],
      },
      maxWidth: { measure: "68ch", wide: "1180px" },
      keyframes: {
        "fade-up": {
          from: { opacity: "0", transform: "translateY(6px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        shimmer: { "100%": { transform: "translateX(100%)" } },
      },
      animation: { "fade-up": "fade-up 320ms cubic-bezier(0.22,0.61,0.36,1) both" },
    },
  },
  plugins: [],
};

export default config;

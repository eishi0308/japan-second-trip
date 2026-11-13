import type { Config } from "tailwindcss";

/**
 * The palette is deliberately narrow (PRODUCT_AMENDMENTS.md §8): white, ink and
 * indigo, with green, amber and red kept for status alone. A verification product loses credibility the moment it
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
        paper: "#ffffff",
        // Indigo: the one accent. Used for actions and focus, never for status.
        accent: {
          50: "#f1f3fa",
          100: "#e2e6f4",
          200: "#c5cce8",
          300: "#9ea9d6",
          400: "#7180bf",
          500: "#4f5fa6",
          600: "#3d4b8c",
          700: "#323d72",
          800: "#29325c",
          900: "#1f2647",
        },
        // Status only, always paired with an icon and words (WCAG AA on white).
        signal: {
          critical: "#b42318",
          warning: "#8a5a00",
          good: "#1f7a4d",
          info: "#3d4b8c",
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

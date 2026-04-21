import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // AWS-ish palette tuned for a dark console look
        bg: {
          DEFAULT: "#0b1220",
          panel: "#111a2e",
          raised: "#17223b",
        },
        ink: {
          DEFAULT: "#e8ecf5",
          muted: "#8a95b2",
        },
        accent: {
          DEFAULT: "#ff9900",
          blue: "#3b82f6",
          green: "#22c55e",
          yellow: "#eab308",
          red: "#ef4444",
        },
      },
      fontFamily: {
        mono: ['"JetBrains Mono"', '"SF Mono"', "ui-monospace", "monospace"],
      },
      keyframes: {
        caret: {
          "0%, 45%": { opacity: "1" },
          "50%, 100%": { opacity: "0" },
        },
        pulseDot: {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.3" },
        },
      },
      animation: {
        caret: "caret 1s steps(1) infinite",
        pulseDot: "pulseDot 1.2s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};

export default config;

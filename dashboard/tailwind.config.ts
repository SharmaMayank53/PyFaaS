import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        bg: {
          base: "#080B10",
          panel: "#0D131C",
          surface: "#121A26",
          raised: "#182232",
          overlay: "#101824",
        },
        border: {
          DEFAULT: "#223043",
          soft: "rgba(255,255,255,0.06)",
        },
        text: {
          primary: "#F6F8FB",
          secondary: "#B7C2D2",
          muted: "#7F8DA3",
          faint: "#566276",
        },
        accent: {
          DEFAULT: "#38BDF8",
          hover: "#0EA5E9",
          soft: "rgba(56,189,248,0.12)",
        },
        success: "#34D399",
        warning: "#FBBF24",
        error: "#FB7185",
      },
      boxShadow: {
        card: "0 16px 40px rgba(0,0,0,0.20)",
        panel: "0 18px 60px rgba(0,0,0,0.28)",
        drawer: "-28px 0 80px rgba(0,0,0,0.45)",
        "inner-soft": "inset 0 1px 0 rgba(255,255,255,0.04)",
      },
      borderRadius: {
        xl: "0.9rem",
        "2xl": "1.15rem",
      },
      fontFamily: {
        mono: ["JetBrains Mono", "Fira Code", "Consolas", "monospace"],
        sans: ["Inter", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
};

export default config;

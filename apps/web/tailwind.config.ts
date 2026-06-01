import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        border: "hsl(214 32% 91%)",
        background: "hsl(0 0% 100%)",
        foreground: "hsl(222 47% 11%)",
        muted: { DEFAULT: "hsl(210 40% 96%)", foreground: "hsl(215 16% 47%)" },
        primary: { DEFAULT: "hsl(222 47% 11%)", foreground: "hsl(210 40% 98%)" },
        destructive: { DEFAULT: "hsl(0 84% 60%)", foreground: "hsl(210 40% 98%)" },
        accent: { DEFAULT: "hsl(210 40% 96%)", foreground: "hsl(222 47% 11%)" },
      },
      borderRadius: { lg: "0.5rem", md: "0.375rem", sm: "0.25rem" },
    },
  },
  plugins: [],
};
export default config;

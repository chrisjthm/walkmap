/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        display: ["Fraunces", "serif"],
        body: ["Chivo", "sans-serif"],
      },
      colors: {
        ink: "#0f1e1b",
        moss: "#3f5b4a",
        clay: "#d9b99b",
        sun: "#f3c063",
        river: "#6cb1a6",
        paper: "#f7f1e6",
        mist: "#eef2ed",
      },
      boxShadow: {
        soft: "0 18px 50px -24px rgba(15, 30, 27, 0.45)",
        edge: "0 0 0 1px rgba(15, 30, 27, 0.18)",
      },
      keyframes: {
        floatIn: {
          "0%": { opacity: "0", transform: "translateY(14px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        shimmer: {
          "0%": { backgroundPosition: "0% 50%" },
          "100%": { backgroundPosition: "100% 50%" },
        },
      },
      animation: {
        floatIn: "floatIn 0.7s ease-out forwards",
        shimmer: "shimmer 12s ease-in-out infinite alternate",
      },
    },
  },
  plugins: [],
};

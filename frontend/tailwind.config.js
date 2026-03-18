/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      fontFamily: {
        mono: ["JetBrains Mono", "Fira Code", "ui-monospace", "monospace"],
      },
      colors: {
        surface: {
          DEFAULT: "#0d1117",
          1: "#161b22",
          2: "#21262d",
          3: "#30363d",
        },
        accent: {
          green:  "#3fb950",
          red:    "#f85149",
          yellow: "#d29922",
          blue:   "#58a6ff",
          purple: "#bc8cff",
          orange: "#ffa657",
        },
        border: "#30363d",
      },
    },
  },
  plugins: [],
};

/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: "class",
  content: [
    "./frontend/templates/**/*.html",
    "./admin/templates/**/*.html",
    "./frontend/static/js/**/*.js",
  ],
  theme: {
    extend: {
      colors: {
        ink: {
          DEFAULT: "rgb(var(--c-ink) / <alpha-value>)",
          soft: "rgb(var(--c-ink-soft) / <alpha-value>)",
        },
        muted: "rgb(var(--c-muted) / <alpha-value>)",
        paper: {
          DEFAULT: "rgb(var(--c-paper) / <alpha-value>)",
          soft: "rgb(var(--c-paper-soft) / <alpha-value>)",
          deep: "rgb(var(--c-paper-deep) / <alpha-value>)",
        },
        surface: {
          DEFAULT: "rgb(var(--c-surface) / <alpha-value>)",
          muted: "rgb(var(--c-surface-muted) / <alpha-value>)",
        },
        line: "rgb(var(--c-line) / var(--c-line-a))",
        accent: {
          DEFAULT: "rgb(var(--c-accent) / <alpha-value>)",
          deep: "rgb(var(--c-accent-deep) / <alpha-value>)",
          bright: "rgb(var(--c-accent-bright) / <alpha-value>)",
          wash: "rgb(var(--c-accent) / 0.14)",
          mist: "rgb(var(--c-accent-mist) / <alpha-value>)",
        },
        danger: "rgb(var(--c-danger) / <alpha-value>)",
      },
      fontFamily: {
        sans: ['"Plus Jakarta Sans"', "system-ui", "sans-serif"],
        display: ['"Plus Jakarta Sans"', "system-ui", "sans-serif"],
        body: ['"Plus Jakarta Sans"', "system-ui", "sans-serif"],
      },
      maxWidth: {
        measure: "42rem",
        site: "72rem",
      },
      boxShadow: {
        card: "var(--shadow-card)",
      },
      keyframes: {
        rise: {
          from: { opacity: "0", transform: "translateY(1rem)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        rise: "rise 0.7s ease-out both",
      },
    },
  },
  plugins: [],
};

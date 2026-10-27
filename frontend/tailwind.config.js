module.exports = {
  content: ["./src/**/*.{js,jsx,ts,tsx}"],
  theme: {
    extend: {
      colors: {
        parchment: "#F5F2EB",
        surface: "#FCFAF5",
        ink: "#1A1A1A",
        ink2: "#5C5C5C",
        gold: "#B8860B",
        border1: "#E5E0D3",
        success: "#2E7D32",
        warning: "#E65100",
        projbg: "#000000",
        projgold: "#FFD700",
      },
      fontFamily: {
        hebrew: ["'Noto Serif Hebrew'", "'Frank Ruhl Libre'", "'SBL Hebrew'", "serif"],
        display: ["'Cormorant Garamond'", "serif"],
        body: ["Inter", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
};

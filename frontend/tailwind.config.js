const config = {
    content: ["./index.html", "./src/**/*.{ts,tsx}"],
    theme: {
        extend: {
            colors: {
                canvas: "#0C0C0C",
                surface: "#141414",
                elevated: "#1A1A1A",
                grid: "#222222",
                text: "#F5F5F5",
                secondary: "#A8A8A8",
                tertiary: "#666666",
                verify: "#E8DCC0",
                error: "#CF5A5A",
            },
            fontFamily: {
                sans: ["Inter", "ui-sans-serif", "system-ui"],
                serif: ["Newsreader", "ui-serif", "Georgia"],
                handwritten: ["Inter", "ui-sans-serif", "system-ui"],
                mono: ["IBM Plex Mono", "ui-monospace", "SFMono-Regular"],
            },
            boxShadow: {
                panel: "0 24px 80px rgba(0, 0, 0, 0.45)",
                card: "0 16px 30px rgba(0, 0, 0, 0.35), inset 0 1px 0 rgba(255, 255, 255, 0.05)",
            },
            backgroundImage: {
                grain: "radial-gradient(circle at top, rgba(255,255,255,0.08), transparent 40%), radial-gradient(circle at bottom, rgba(232,220,192,0.04), transparent 35%)",
            },
        },
    },
    plugins: [],
};
export default config;

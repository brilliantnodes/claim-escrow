import { defineConfig } from "vite";

// "Try it yourself": a static page built into ../docs/app, served by GitHub
// Pages next to the run record (../docs/index.html) and the register pages.
export default defineConfig({
  base: "./",
  build: {
    outDir: "../docs/app",
    emptyOutDir: true,
    target: "es2022",
    chunkSizeWarningLimit: 700,
    rollupOptions: { output: { manualChunks(id) { if (id.includes("node_modules")) return "genlayer"; } } },
  },
});

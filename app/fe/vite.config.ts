import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { viteSingleFile } from "vite-plugin-singlefile";
import path from "path";

// Dev proxy target: reads CHATNUT_DEV_PORT from shell env (set by portless dev start script).
// Falls back to 8000 for manual `bun run dev` without portless.
const devPort = process.env.CHATNUT_DEV_PORT || "8000";
const devTarget = `http://localhost:${devPort}`;

export default defineConfig({
  server: {
    port: 5173,
    proxy: {
      "/api": devTarget,
      "/mcp": devTarget,
    },
  },
  plugins: [react(), tailwindcss(), viteSingleFile()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  build: {
    target: "esnext",
    assetsInlineLimit: 100000000,
    chunkSizeWarningLimit: 100000000,
    cssCodeSplit: false,
    rollupOptions: {
      output: { inlineDynamicImports: true },
    },
  },
});

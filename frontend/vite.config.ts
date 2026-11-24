import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The dev server proxies /api (REST + WebSocket) to the FastAPI backend, so no CORS setup is needed.
// API_TARGET / PORT let the end-to-end tests run their own backend and dev server next to yours.
const backend = process.env.API_TARGET ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: Number(process.env.PORT ?? 5173),
    strictPort: true,
    proxy: {
      "/api": {
        target: backend,
        ws: true,
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, ""),
      },
    },
  },
});

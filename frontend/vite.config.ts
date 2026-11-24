import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The dev server proxies /api (REST + WebSocket) to the FastAPI backend, so no CORS setup is needed.
const backend = "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
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

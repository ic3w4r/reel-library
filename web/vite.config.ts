import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev, the Python backend runs on :8080 (`instamcp web`).
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8080",
      "/mcp": "http://127.0.0.1:8080",
    },
  },
});

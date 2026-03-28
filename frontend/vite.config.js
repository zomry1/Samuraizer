import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/analyze": "http://localhost:8000",
      "/analyze-pdf": "http://localhost:8000",
      "/analyze-blog": "http://localhost:8000",
      "/scan-blog": "http://localhost:8000",
      "/entries": "http://localhost:8000",
      "/tags": "http://localhost:8000",
      "/suggest": "http://localhost:8000",
      "/search": "http://localhost:8000",
      "/lists": "http://localhost:8000",
      "/categories": "http://localhost:8000",
      "/provider": "http://localhost:8000",
      "/chat": "http://localhost:8000",
      "/settings": "http://localhost:8000",
      "/ollama": "http://localhost:8000",
      "/rss-feeds": "http://localhost:8000",
      "/yt-channels": "http://localhost:8000",
      "/logs": "http://localhost:8000",
      "/embeddings": "http://localhost:8000",
    },
  },
});

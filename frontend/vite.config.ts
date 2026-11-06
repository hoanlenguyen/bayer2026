import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => ({
  plugins: [react()],
  server: {
    // Forward API calls to the FastAPI backend during development.
    proxy: { "/api": { target: loadEnv(mode, ".", "BAYER_").BAYER_API_URL || "http://localhost:8000", changeOrigin: true } },
  },
}));

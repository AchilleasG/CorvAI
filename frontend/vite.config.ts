import { defineConfig } from "vite";
import path from "path";
import react from "@vitejs/plugin-react";

// VITE_BACKEND_URL helps Docker point the proxy at the backend container.
const backend = process.env.VITE_BACKEND_URL || "http://web:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    allowedHosts: ["ai.corv-labs.tech"],
    fs: {
      allow: [path.resolve(__dirname, "..")],
    },
    proxy: {
      "/api": {
        target: backend,
        changeOrigin: true,
      },
    },
  },
});

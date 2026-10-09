import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server and preview both use 127.0.0.1:5173, the origin the backend allows via CORS.
export default defineConfig({
  plugins: [react()],
  server: { host: "127.0.0.1", port: 5173, strictPort: true },
  preview: { host: "127.0.0.1", port: 5173, strictPort: true },
});

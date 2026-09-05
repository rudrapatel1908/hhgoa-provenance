import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Port 5173 matches the CORS allowlist already hardcoded in src/api.py
// (localhost-only, per project scope -- do not widen either side).
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, strictPort: true },
});

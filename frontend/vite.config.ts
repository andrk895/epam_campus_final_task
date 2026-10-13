import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

// The backend has no CORS setup, so the browser only talks to this dev server,
// which forwards /api/* to the FastAPI app (with the /api prefix stripped).
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "");
  const target = env.API_TARGET || "http://localhost:8000";
  const proxy = {
    "/api": {
      target,
      changeOrigin: true,
      rewrite: (path: string) => path.replace(/^\/api/, ""),
    },
  };
  return {
    plugins: [react()],
    server: { host: true, port: Number(env.PORT) || 5173, strictPort: true, proxy },
    preview: { host: true, port: 4173, proxy },
  };
});

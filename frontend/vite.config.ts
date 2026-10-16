import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Desarrollo local: `URL_APP=https://dxxxx.cloudfront.net npm run dev` reenvía las llamadas al agente y la
// configuración a la app desplegada, así no hace falta CORS.
const target = process.env.URL_APP;

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: target
      ? { "/runtimes": { target, changeOrigin: true }, "/config.json": { target, changeOrigin: true } }
      : undefined,
  },
});

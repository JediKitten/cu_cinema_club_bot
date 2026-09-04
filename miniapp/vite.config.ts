import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Слушаем все интерфейсы: до dev-сервера ходит HTTPS-туннель, а не localhost.
    host: true,
    // Туннель отдаёт случайный домен вида *.trycloudflare.com, заранее его не знаем.
    allowedHosts: true,
    // API проксируем через тот же origin. Иначе телефону пришлось бы ходить
    // на localhost:8000 разработчика — то есть в никуда, — и понадобился бы
    // второй туннель со своими CORS.
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true },
      "/health": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
});

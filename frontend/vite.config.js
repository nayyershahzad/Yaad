import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// SPA served at https://yaad.engstech.com root; API is same-origin (relative paths).
export default defineConfig({
  base: "/",
  plugins: [react()],
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});

import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";

/** Make the built page's /assets/ links relative, so the WebUI also loads
 *  below a path prefix such as Home Assistant's ingress
 *  (/api/hassio_ingress/<token>/). The gateway still serves /assets/<name>. */
function relativeAssetLinks(): Plugin {
  return {
    name: "relative-asset-links",
    apply: "build",
    transformIndexHtml: { order: "post", handler: html => html.replace(/(src|href)="\/assets\//g, '$1="assets/') },
  };
}

export default defineConfig({
  plugins: [react(), relativeAssetLinks()],
  // The Python gateway exposes /assets/<name> while resolving files from the
  // WebUI root, so the production bundle is deliberately flat.
  base: "/assets/",
  build: {
    outDir: "../gateway/webui",
    emptyOutDir: false,
    assetsDir: "",
    sourcemap: false,
    target: "es2022",
    rollupOptions: {
      output: {
        entryFileNames: "v2-[hash].js",
        chunkFileNames: "v2-[hash].js",
        assetFileNames: "v2-[hash][extname]",
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8080",
      "/state.json": "http://127.0.0.1:8080",
      "/history.json": "http://127.0.0.1:8080",
    },
  },
});

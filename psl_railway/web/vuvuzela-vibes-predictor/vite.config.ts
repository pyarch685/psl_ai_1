import { defineConfig } from "vite";
import react from "@vitejs/plugin-react-swc";
import path from "path";
import { componentTagger } from "lovable-tagger";

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
  const isProduction = mode === "production";

  return {
    server: {
      host: "::",
      port: 8080,
    },
    plugins: [
      react(),
      mode === "development" && componentTagger()
    ].filter(Boolean),
    resolve: {
      alias: {
        "@": path.resolve(__dirname, "./src"),
      },
    },
    build: {
      // Production optimizations
      minify: isProduction ? "esbuild" : false,
      sourcemap: !isProduction,
      rollupOptions: {
        output: {
          // Optimize chunk splitting
          manualChunks: {
            vendor: ["react", "react-dom", "react-router-dom"],
            ui: [
              "@radix-ui/react-dialog",
              "@radix-ui/react-tabs",
              "@radix-ui/react-toast",
            ],
          },
        },
      },
      // Increase chunk size warning limit
      chunkSizeWarningLimit: 1000,
    },
    // Environment variable handling
    define: {
      "import.meta.env.VITE_API_URL": JSON.stringify(
        process.env.VITE_API_URL || "http://localhost:8000"
      ),
    },
  };
});


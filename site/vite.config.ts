import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import type { Plugin, ViteDevServer } from "vite";
import { defineConfig } from "vitest/config";
import tailwindcss from "@tailwindcss/vite";

const SECTION_SOURCES = [
  "/src/sections/",
  "/src/content.ts",
  "/index.template.html",
];

function prerenderSections(): Plugin {
  const run = () =>
    execFileSync(
      "bun",
      [fileURLToPath(new URL("./src/prerender.ts", import.meta.url))],
      {
        stdio: "inherit",
      },
    );

  return {
    name: "prerender-sections",
    buildStart() {
      run();
    },
    configureServer(server: ViteDevServer) {
      server.watcher.on("change", (file: string) => {
        if (SECTION_SOURCES.some((source) => file.includes(source))) {
          run();
          server.ws.send({ type: "full-reload" });
        }
      });
    },
  };
}

export default defineConfig({
  base: "/cloud-app/",
  plugins: [prerenderSections(), tailwindcss()],
  build: {
    target: "es2022",
    cssMinify: "lightningcss",
  },
  test: {
    environment: "jsdom",
    include: ["tests/**/*.test.ts"],
  },
});

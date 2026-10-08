import {fileURLToPath} from "node:url";
import {defineConfig} from "vitest/config";

export default defineConfig({
  resolve: {alias: {"@": fileURLToPath(new URL(".", import.meta.url))}},
  test: {
    environment: "jsdom",
    setupFiles: ["./tests/setup.ts"],
    include: ["tests/**/*.test.{ts,tsx}"],
    restoreMocks: true,
    unstubGlobals: true,
    coverage: {
      provider: "v8",
      include: ["app/**/*.tsx", "components/**/*.tsx"],
      exclude: ["app/layout.tsx"],
      reporter: ["text"],
    },
  },
});

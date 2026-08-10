import { defineConfig } from "vitest/config";
import path from "path";

export default defineConfig({
  test: {
    globals: true,
    environment: "node",
    include: ["src/**/*.test.ts", "tests/**/*.test.ts"],
    // Vitest forwards worker console output to the main process over RPC. On
    // Windows that round-trip costs ~1s per call, so a handler that logs (e.g.
    // the 503 branch of the Stripe webhook) blows the 5s test timeout. Writing
    // straight to stdout keeps the logs and removes the stall.
    disableConsoleIntercept: true,
    coverage: {
      provider: "v8",
      include: ["src/**/*.ts"],
      exclude: ["src/**/*.test.ts", "src/**/*.d.ts"],
    },
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
});

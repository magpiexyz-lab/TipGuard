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
    // The default 5s is measured per test but includes the first dynamic
    // `import()` of a route, which pulls in stripe/supabase/next cold. Under a
    // fully parallel run that alone can approach the budget, which made the
    // b-11 flows test flake. 15s is still short enough to catch a real hang.
    testTimeout: 15_000,
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

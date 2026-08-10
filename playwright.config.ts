// @next/env loadEnvConfig: shape depends on loader. .ts (Playwright pirates +
// CJS-transpile) requires NAMED-import; .mjs (raw Node ESM) requires
// default-import + destructure. See "CJS-interop with @next/env" Stack
// Knowledge entry in stacks/analytics/posthog.md for the per-loader contract.
import { loadEnvConfig } from "@next/env";
loadEnvConfig(process.cwd());

import { execSync } from "child_process";
import { defineConfig, devices } from "@playwright/test";

function getSupabaseConfig() {
  try {
    const output = execSync("npx supabase status -o json", {
      encoding: "utf-8",
      timeout: 15000,
    });
    const status = JSON.parse(output);
    return {
      url: status.API_URL || "http://127.0.0.1:54321",
      anonKey: status.ANON_KEY,
      serviceRoleKey: status.SERVICE_ROLE_KEY,
      unreachable: false,
    };
  } catch {
    // Fallback: legacy deterministic keys (Supabase CLI <v2.76)
    return {
      url: "http://127.0.0.1:54321",
      anonKey:
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZS1kZW1vIiwicm9sZSI6ImFub24iLCJleHAiOjE5ODM4MTI5OTZ9.CRXP1A7WOeoJeXxjNni43kdQwgnWNReilDMblYTn_I0",
      serviceRoleKey:
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZS1kZW1vIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImV4cCI6MTk4MzgxMjk5Nn0.EGIM96RAZx35lJzdJsyH-qQwv8Hdp7fsn3W0YpN81IU",
      unreachable: true,
    };
  }
}

const supabase = getSupabaseConfig();
const port = process.env.E2E_PORT || "3099";

// Port-probe (fix #1070 Gap 1): reuseExistingServer is unreliable when a dev
// server is still booting on the target port (the HTTP ping races against
// Next.js startup). If :<port> is already bound, treat the existing process
// as the server and leave webServer undefined — Playwright will run tests
// against the pre-existing dev. When :<port> is idle, start our own dev via
// webServer.command with reuseExistingServer honouring CI semantics. Uses
// execFileSync with explicit argv (no shell) so the port string cannot be
// interpreted as a shell metachar.
const portOccupied = (() => {
  try {
    const { execFileSync } = require("child_process");
    execFileSync("lsof", ["-nPi", `:${port}`, "-sTCP:LISTEN"], { stdio: "ignore" });
    return true;
  } catch {
    return false;
  }
})();

// Make keys available to global-setup/teardown (run in Playwright main process, not webServer)
process.env.NEXT_PUBLIC_SUPABASE_URL = supabase.url;
process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = supabase.anonKey;
process.env.SUPABASE_SERVICE_ROLE_KEY = supabase.serviceRoleKey;

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: "html",
  globalSetup: "./e2e/global-setup.ts",
  globalTeardown: "./e2e/global-teardown.ts",
  use: {
    baseURL: process.env.E2E_BASE_URL || `http://localhost:${port}`,
    trace: "on-first-retry",
  },
  projects: [
    // Production auth setup — only active when E2E_BASE_URL and PROD_TEST_EMAIL are set
    ...(process.env.E2E_BASE_URL && process.env.PROD_TEST_EMAIL
      ? [
          {
            name: "prod-auth-setup",
            testMatch: /prod-auth\.setup\.ts/,
            use: { ...devices["Desktop Chrome"] },
          },
        ]
      : []),
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
      dependencies: process.env.PROD_TEST_EMAIL ? ["prod-auth-setup"] : [],
    },
    { name: "Mobile Chrome", use: { ...devices["Pixel 5"] } },
  ],
  webServer: process.env.E2E_BASE_URL || portOccupied
    ? undefined
    : {
        // cross-env prefix per stacks/testing/playwright.md Stack Knowledge
        // "Windows compatibility for webServer command" — cmd.exe treats a bare
        // `PORT=3099` as an executable name. cross-env is POSIX-safe too.
        command: `cross-env PORT=${port} npm run dev`,
        url: `http://localhost:${port}`,
        reuseExistingServer: !process.env.CI,
        env: {
          NEXT_PUBLIC_SUPABASE_URL: supabase.url,
          NEXT_PUBLIC_SUPABASE_ANON_KEY: supabase.anonKey,
          SUPABASE_SERVICE_ROLE_KEY: supabase.serviceRoleKey,
          // Activate the middleware + server-client demo-mode bypass when
          // Supabase is unreachable (fresh clone, no Docker). The app's
          // `VERCEL === "1"` guards reject DEMO_MODE in production, so this
          // is a no-op when tests run against a real deployment.
          ...(supabase.unreachable
            ? { DEMO_MODE: "true", NEXT_PUBLIC_DEMO_MODE: "true" }
            : {}),
        },
      },
});

---
assumes: [framework/nextjs, database/supabase, auth/supabase, analytics/posthog]
packages:
  runtime: []
  dev: ["@playwright/test", "@axe-core/playwright", "pixelmatch", "pngjs"]
files:
  - playwright.config.ts
  - e2e/global-setup.ts  # conditional: only when all assumes are met
  - e2e/global-teardown.ts  # conditional: only when all assumes are met
  - e2e/prod-auth.setup.ts  # conditional: only when all assumes are met (used by /deploy production testing)
  - e2e/helpers.ts
  - e2e/smoke.spec.ts
  - e2e/funnel.spec.ts  # conditional: only when all assumes are met
  - e2e/behaviors.spec.ts  # conditional: only when experiment.yaml has behaviors with tests entries
  - tests/flows.test.ts      # conditional: only when experiment.yaml has behaviors with actor: system/cron
env:
  server: [E2E_BASE_URL]
  client: []
ci_placeholders: {}
clean:
  files: [playwright.config.ts]
  dirs: [e2e, test-results, playwright-report, blob-report]
gitignore: [/test-results/, /playwright-report/, /blob-report/, /e2e/.auth.json]
---
<!-- coherence-allow: raw-golden_path (sequence-step) scope=["## Files to Create", "## Critical Flow Integration Tests"] — playwright funnel tests (e2e/smoke.spec.ts, e2e/funnel.spec.ts) are populated from golden_path as a sequential state machine; expected events fire in funnel-journey order. Critical Flow Integration Tests section references golden_path as the customer-journey LIST semantics contrast to the system/cron delivery chain. LIST semantics throughout. -->

# Testing: Playwright
> Used when experiment.yaml has `stack.testing: playwright` or when the `/change` skill is invoked for test changes
> Assumes: `database/supabase` and `auth/supabase` (test user lifecycle uses Supabase Admin API), `analytics/posthog` (`blockAnalytics` route pattern targets PostHog)

## Prerequisites (Full-Auth Path Only)

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) — required for `supabase start`
- Supabase CLI — installed as npm dev dependency (`npm install -D supabase`), no global install needed

These are NOT required for the No-Auth Fallback path.

## Packages
```bash
npm install -D @playwright/test
npx playwright install chromium
```

## Files to Create

### `playwright.config.ts` — Playwright configuration
```ts
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
        command: `PORT=${port} npm run dev`,
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
```
- Two projects: Desktop Chrome and Mobile Chrome (Pixel 5) — cross-browser is out of scope per Rule 4, but mobile viewport testing catches layout overflow issues
- `webServer` is conditional: when `E2E_BASE_URL` is set, `webServer` is `undefined` (production server already running). This pattern is used by both the preview-smoke CI job and `/deploy` STATE 4 production testing.
- When `supabase status` fails (no Docker, fresh clone), the config flips `DEMO_MODE=true` + `NEXT_PUBLIC_DEMO_MODE=true` in `webServer.env`. Middleware and server Supabase clients bypass auth in demo mode, letting smoke/funnel tests run without a live database. Production-safe: `createServerSupabaseClient`, `createServiceRoleClient`, and `/auth/callback/route.ts` all reject `DEMO_MODE` when `VERCEL === "1"`.
- When `PROD_TEST_EMAIL` is set alongside `E2E_BASE_URL`, the `prod-auth-setup` project runs first to authenticate via the app's login form and save auth state for downstream tests
- `webServer` starts `npm run dev` automatically and waits for the app (local mode only)
- `getSupabaseConfig()` reads keys dynamically from `supabase status -o json` — works with both legacy JWT keys (CLI <v2.76) and new `sb_publishable_*`/`sb_secret_*` keys (CLI v2.76+)
- Keys are assigned to `process.env` so `global-setup.ts` and `global-teardown.ts` (which run in the Playwright main process) can access them. `webServer.env` passes the same keys to the dev server child process.
- Serial execution (`fullyParallel: false`, `workers: 1`) since funnel tests depend on order
- 1 retry in CI to handle flakiness, 0 locally for fast feedback

### `e2e/global-setup.ts` — Create test user before all tests
```ts
import { createClient } from "@supabase/supabase-js";
import { writeFileSync } from "fs";
import path from "path";

const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL || "http://127.0.0.1:54321";
const SERVICE_ROLE_KEY = process.env.SUPABASE_SERVICE_ROLE_KEY;

const AUTH_FILE = path.join(__dirname, ".auth.json");

export default async function globalSetup() {
  // DEMO_MODE short-circuit (fix #1070 Gap 2): when the app is running in demo
  // mode (fresh bootstrap without Docker, zero-external-deps contract), there
  // is no Supabase admin API to probe. Skip the probe entirely — writing blank
  // credentials and returning avoids the misleading "failed to inspect
  // container health" stderr storm that other agents (behavior-verifier,
  // spec-reviewer) mistake for a real auth-stack regression.
  if (process.env.NEXT_PUBLIC_DEMO_MODE === "true" || process.env.DEMO_MODE === "true") {
    console.log("[global-setup] DEMO_MODE active — skipping Supabase test user creation");
    writeFileSync(AUTH_FILE, JSON.stringify({ email: "", password: "", userId: "" }));
    return;
  }
  if (!SERVICE_ROLE_KEY) {
    console.warn("SUPABASE_SERVICE_ROLE_KEY not set — writing empty test credentials (local Supabase may not be running)");
    writeFileSync(AUTH_FILE, JSON.stringify({ email: "", password: "", userId: "" }));
    return;
  }
  try {
    const supabase = createClient(SUPABASE_URL, SERVICE_ROLE_KEY);
    const email = `e2e-${Date.now()}@test.example`;
    const password = "test-password-e2e-123";
    const { data, error } = await supabase.auth.admin.createUser({
      email,
      password,
      email_confirm: true,
    });
    if (error) throw new Error(`Failed to create test user: ${error.message}`);
    writeFileSync(AUTH_FILE, JSON.stringify({ email, password, userId: data.user.id }));
  } catch (e) {
    console.warn(`Global setup failed (local Supabase may not be running): ${e}`);
    writeFileSync(AUTH_FILE, JSON.stringify({ email: "", password: "", userId: "" }));
  }
}
```
- Reads Supabase URL and service role key from `process.env` — set by `playwright.config.ts` via `webServer.env`
- Uses `supabase.auth.admin.createUser` with `email_confirm: true` to bypass email verification
- Writes credentials to `e2e/.auth.json` for tests to read
- Email pattern `e2e-{timestamp}@test.example` avoids collisions

### `e2e/global-teardown.ts` — Delete test user after all tests
```ts
import { createClient } from "@supabase/supabase-js";
import { readFileSync, unlinkSync } from "fs";
import path from "path";

const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL || "http://127.0.0.1:54321";
const SERVICE_ROLE_KEY = process.env.SUPABASE_SERVICE_ROLE_KEY!;

const AUTH_FILE = path.join(__dirname, ".auth.json");

export default async function globalTeardown() {
  try {
    const { userId } = JSON.parse(readFileSync(AUTH_FILE, "utf-8"));
    const supabase = createClient(SUPABASE_URL, SERVICE_ROLE_KEY);
    await supabase.auth.admin.deleteUser(userId);
    unlinkSync(AUTH_FILE);
  } catch {
    // Swallow errors — cleanup is best-effort
  }
}
```
- Reads Supabase URL and service role key from `process.env` — set by `playwright.config.ts` via `webServer.env`
- Reads user ID from `.auth.json`, deletes via admin API, removes the file
- Swallows all errors so teardown never fails the test run

### `e2e/prod-auth.setup.ts` — Production auth setup (conditional: only when `E2E_BASE_URL` + `PROD_TEST_EMAIL` set)
```ts
import { test as setup } from "@playwright/test";
import { login } from "./helpers";
import { writeFileSync } from "fs";
import path from "path";

const AUTH_FILE = path.join(__dirname, ".auth.json");

setup("authenticate production test user", async ({ page }) => {
  const email = process.env.PROD_TEST_EMAIL;
  const password = process.env.PROD_TEST_PASSWORD;
  if (!email || !password) {
    setup.skip();
    return;
  }

  await login(page, email, password);

  // Save credentials for downstream tests (same format as global-setup.ts)
  const cookies = await page.context().cookies();
  writeFileSync(
    AUTH_FILE,
    JSON.stringify({ email, password, userId: "prod-test-user", cookies })
  );
});
```
- Only runs when `PROD_TEST_EMAIL` and `PROD_TEST_PASSWORD` environment variables are set
- Logs in via the browser (same path as a real user) using the shared `login()` helper — validates the login flow itself
- Writes auth state to `.auth.json` so downstream tests can read credentials via `getTestCredentials()`
- Uses the same `AUTH_FILE` path as `global-setup.ts` for compatibility with `helpers.ts`
- `/deploy` STATE 4 auto-creates the test user and sets these env vars — no manual setup needed

### `e2e/helpers.ts` — Shared test utilities
```ts
import { readFileSync } from "fs";
import path from "path";
import type { Page } from "@playwright/test";

const AUTH_FILE = path.join(__dirname, ".auth.json");

export function getTestCredentials() {
  return JSON.parse(readFileSync(AUTH_FILE, "utf-8")) as {
    email: string;
    password: string;
    userId: string;
  };
}

export async function login(page: Page, email: string, password: string) {
  await page.goto("/login");
  await page.getByLabel(/email/i).fill(email);
  await page.locator('input[type="password"]').fill(password);
  await page.locator("form").getByRole("button", { name: /log in|sign in/i }).click();
  await page.waitForURL((url) => !url.pathname.includes("/login"));
}

export async function blockAnalytics(page: Page) {
  await page.route("**/ingest/**", (route) => route.abort());
}

export interface CapturedEvent {
  event: string;
  properties: Record<string, unknown>;
}

export async function captureAnalytics(page: Page): Promise<CapturedEvent[]> {
  const events: CapturedEvent[] = [];
  await page.route("**/ingest/**", async (route) => {
    try {
      const body = route.request().postDataJSON();
      if (body?.batch) {
        for (const item of body.batch) {
          if (item.event) events.push({ event: item.event, properties: item.properties || {} });
        }
      } else if (body?.event) {
        events.push({ event: body.event, properties: body.properties || {} });
      }
    } catch { /* non-JSON body, ignore */ }
    await route.abort(); // still block from reaching provider
  });
  return events;
}

export async function checkNoHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth
  );
  if (overflow) {
    throw new Error(
      `Horizontal overflow detected (scrollWidth ${await page.evaluate(() => document.documentElement.scrollWidth)}px > clientWidth ${await page.evaluate(() => document.documentElement.clientWidth)}px)`
    );
  }
}
```
- `login()` uses generic selectors — the skill adjusts these based on actual app code
- `blockAnalytics()` intercepts analytics requests via route interception using the endpoint pattern from the analytics stack file's "Test Blocking" section — no app code changes needed. **Provider adaptation:** if using a different analytics provider, update the route pattern to match that provider's endpoint pattern from its stack file.
- `captureAnalytics()` intercepts AND records analytics payloads while still blocking them from reaching the provider. Use in funnel tests to verify events fire correctly. `blockAnalytics` remains available for smoke tests where event verification isn't needed. **Note:** Requires the analytics provider to use XHR transport (not `sendBeacon`) — see the analytics stack file's Test Blocking section for configuration.
- `getTestCredentials()` reads from the `.auth.json` written by global setup

### `e2e/smoke.spec.ts` — Funnel smoke tests (generated by /change skill — test type)
```ts
import { test, expect } from "@playwright/test";
import { blockAnalytics, checkNoHorizontalOverflow } from "./helpers";

test.describe.serial("Funnel smoke test", () => {
  test.beforeEach(async ({ page }) => {
    await blockAnalytics(page);
  });

  test("visit landing page", async ({ page }) => {
    await page.goto("/");
    await expect(page).toHaveTitle(/.+/);
    await checkNoHorizontalOverflow(page);
  });

  // Page-load smoke tests only — add `await checkNoHorizontalOverflow(page)` after every page.goto()
  // See funnel.spec.ts for full user journey tests
});
```
- Uses `test.describe.serial` so funnel steps run in order
- `blockAnalytics` in `beforeEach` prevents analytics calls during tests
- Smoke tests verify pages load without errors — funnel tests (below) verify the full user journey

### `e2e/funnel.spec.ts` — Funnel journey tests (generated by bootstrap from golden_path and actual page source)

#### Full-auth version:
```ts
import { test, expect } from "@playwright/test";
import { getTestCredentials, login, captureAnalytics, type CapturedEvent } from "./helpers";

test.describe.serial("User funnel", () => {
  let analytics: CapturedEvent[];

  test.beforeEach(async ({ page }) => {
    analytics = await captureAnalytics(page);
  });

  // Bootstrap generates tests for:
  // 1. Landing page content verification (h1 text, CTA visible)
  // 2. Activate action if landing has an interactive feature (e.g. waitlist form, use timestamped email)
  // 3. Login with test user → verify redirect to post-auth page
  // 4. Core value pages: navigate and verify content using real selectors from page source
  //
  // Example for a project with waitlist + arena + leaderboard:
  //
  // test("landing page shows pitch", async ({ page }) => {
  //   await page.goto("/");
  //   await expect(page.getByRole("heading", { name: /your h1 text/i })).toBeVisible();
  //   await expect(page.getByRole("link", { name: /cta text/i })).toBeVisible();
  // });
  //
  // test("waitlist form submits", async ({ page }) => {
  //   await page.goto("/");
  //   const email = `funnel-${Date.now()}@test.example`;
  //   const emailInput = page.getByPlaceholder("your@email.com");
  //   await emailInput.fill(email);
  //   await emailInput.press("Enter");
  //   await expect(page.getByText(/success message/i)).toBeVisible({ timeout: 10_000 });
  // });
  //
  // test("login and reach dashboard", async ({ page }) => {
  //   const { email, password } = getTestCredentials();
  //   await login(page, email, password);
  //   await expect(page).toHaveURL(/\/dashboard/);
  // });
});
```

#### No-auth fallback version:
```ts
import { test, expect } from "@playwright/test";
import { captureAnalytics, type CapturedEvent } from "./helpers";

test.describe.serial("User funnel", () => {
  let analytics: CapturedEvent[];

  test.beforeEach(async ({ page }) => {
    analytics = await captureAnalytics(page);
  });

  // Bootstrap generates tests for:
  // 1. Landing page content verification (h1 text, CTA visible)
  // 2. Activate action if landing has an interactive feature
  // 3. Core value pages: navigate and verify content using real selectors
  // (No login test — auth is not configured)

  // Analytics verification test (generated from golden_path entries with non-null event):
  // test("analytics events fired in order", async () => {
  //   const golden = ["visit_landing", "activate"]; // populated from golden_path
  //   const firedEvents = analytics.map(e => e.event);
  //   for (const expected of golden) {
  //     expect(firedEvents).toContain(expected);
  //   }
  // });
});
```

Notes:
- Bootstrap reads actual page source files (created in Step 4) to extract real selectors — heading text, button labels, placeholder text, success messages
- Login test uses the pre-confirmed test user from `global-setup.ts` (not the signup form)
- `retain_return` is skipped — requires 24h+ delay, untestable in E2E
- Waitlist/form tests use timestamped emails (`funnel-${Date.now()}@test.example`) to avoid duplicate conflicts on re-runs
- Unlike smoke tests (page-load only), funnel tests verify the actual user journey through the app
- **Activation assertion**: For golden_path steps marked as activation points, the funnel test asserts the action produces a visible result — not just page load. Bootstrap reads the page source to determine the success indicator (e.g., a success toast, an item appearing in a list, a confirmation message). Example: if the activation step is "Create Invoice" on /invoice-create, the test fills the form, clicks submit, and asserts a success indicator is visible.
- **Analytics verification**: Funnel tests use `captureAnalytics` instead of `blockAnalytics` — this intercepts analytics payloads for verification while still blocking them from reaching the provider. The final test step asserts that all expected events from golden_path (entries with non-null `event`) were fired during the funnel journey.
- **CTA Repeat strict mode**: Landing pages include the CTA at least twice (messaging.md Section B content inventory), so selectors targeting CTAs will match 2+ elements. For **form submit** actions (waitlist, signup), use `input.press("Enter")` instead of clicking the submit button — this binds to user intent and avoids ambiguous button selectors entirely. For **navigation CTAs** (links), use `.first()` on these selectors (e.g., `page.getByRole("link", { name: /cta/i }).first()`). This applies to landing page tests only — other pages have unique selectors.
- **CTA selector role**: Landing page CTAs that navigate to another page use `<Link className={buttonVariants()}>`, which renders as `<a>` (role `"link"`). Use `getByRole("link")` for navigation CTAs. Use `getByRole("button")` only for CTAs that trigger actions (form submits, dialogs). Bootstrap determines the correct role by reading the actual page source.
- **DEMO_MODE skip for auth-dependent steps (#1148)**: When generating funnel.spec.ts test bodies, bootstrap MUST wrap login-required golden_path steps (those that call `getTestCredentials()` / `login()` or navigate to auth-gated routes) in `test.skip(process.env.DEMO_MODE === "true", "DB-dependent — re-run after /deploy")`. The DEMO_MODE bootstrap-time test environment returns empty credentials and stub Supabase responses, so these steps would false-fail with no useful signal. Anonymous/landing-only golden_path steps remain unconditional. Apply the same skip pattern to the analytics-verification test if any of its expected events fire only after login.

## Behavior Verification Tests

When experiment.yaml has `behaviors` with `tests` entries, bootstrap generates `e2e/behaviors.spec.ts` to test
each behavior in isolation. This complements `funnel.spec.ts` (connected journey) with individual behavior correctness.

### `e2e/behaviors.spec.ts` — Behavior tests (generated by bootstrap from experiment.yaml behaviors and actual page source)

#### Full-auth version:
```ts
import { test, expect } from "@playwright/test";
import { blockAnalytics } from "./helpers";

// === Anonymous behaviors (no auth required) ===

test.describe("b-01: <when clause summary>", () => {
  test.beforeEach(async ({ page }) => {
    await blockAnalytics(page);
  });

  // Each entry in behavior.tests becomes one test()
  // Every test() must assert beyond toBeVisible() — verify the `then` clause outcome
  test("<tests[0] verbatim from experiment.yaml>", async ({ page }) => {
    await page.goto("/<page from behavior context>");
    // Interact: trigger the action described in `when` clause (real selectors from page source)
    await page.getByRole("button", { name: /create invoice/i }).click();
    // Assert outcome from `then` clause — not just element presence
    await expect(page.getByText(/invoice #/i)).toBeVisible();
    await expect(page.getByText(/send link/i)).toHaveAttribute("href", /./);
  });

  test("<tests[1] verbatim from experiment.yaml>", async ({ page }) => {
    await page.goto("/<page>");
    // Assert actual data values, not just that an element exists
    await expect(page.getByRole("heading", { name: /actual h1 text/i })).toHaveText(/./);
    await expect(page.getByText(/actual text from page source/i)).toContainText(/expected value/i);
  });
});

// === Auth-gated behaviors (require logged-in user) ===

test.describe("b-05: <when clause summary>", () => {
  // Issue #1148: skip auth-gated tests in DEMO_MODE — global-setup returns empty
  // credentials when Supabase is unavailable, so these tests false-fail with no
  // useful signal. Re-runs on production happen via /deploy or with real Supabase.
  test.skip(
    process.env.DEMO_MODE === "true",
    "DB-dependent — re-run after /deploy or with real Supabase"
  );
  // storageState reuses auth from global-setup (local) or prod-auth.setup (production)
  test.use({ storageState: "e2e/.auth.json" });

  test.beforeEach(async ({ page }) => {
    await blockAnalytics(page);
  });

  // Every test() must assert beyond toBeVisible() — verify the `then` clause outcome
  test("<tests[0] verbatim>", async ({ page }) => {
    await page.goto("/<page>");
    // Navigate, interact, assert — all with real selectors from page source
    await page.getByLabel(/display name/i).fill("Test Name");
    await page.getByRole("button", { name: /save/i }).click();
    await expect(page.getByLabel(/display name/i)).toHaveValue("Test Name");
  });

  test("<tests[1] verbatim>", async ({ page }) => {
    await page.goto("/<another page>");
    await expect(page.getByText("Test Name")).toBeVisible();
  });
});
```

#### No-auth fallback version:
```ts
import { test, expect } from "@playwright/test";
import { blockAnalytics } from "./helpers";

// All behaviors are anonymous (no auth stack configured)

test.describe("b-01: <when clause summary>", () => {
  test.beforeEach(async ({ page }) => {
    await blockAnalytics(page);
  });

  // Every test() must assert beyond toBeVisible() — verify the `then` clause outcome
  test("<tests[0] verbatim>", async ({ page }) => {
    await page.goto("/<page>");
    // Interact with the page per the `when` clause
    await page.getByPlaceholder(/email/i).fill(`test-${Date.now()}@test.example`);
    await page.getByPlaceholder(/email/i).press("Enter");
    // Assert the `then` clause outcome — content, not just presence
    await expect(page.getByText(/thanks|success|confirmed/i)).toBeVisible();
    await expect(page).toHaveURL(/./); // URL did not error-redirect
  });
});

// (No auth-gated behaviors — auth is not configured)
```

Notes:
- Each behavior from experiment.yaml `behaviors` → one `test.describe` block, labeled `"<id>: <when clause summary>"`
- Each entry in `behavior.tests` array → one `test()` case, with the entry string as the test name (verbatim)
- Bootstrap reads actual page source for selectors — same pattern as funnel.spec.ts. Never use natural language as selectors.
- Auth requirement determined from `given` field: "logged-in user", "authenticated user", "user on dashboard" → `test.use({ storageState: "e2e/.auth.json" })`. "anonymous visitor", "new visitor", or no auth context → no storageState.
- `storageState` reuses auth state from `global-setup.ts` (local) or `prod-auth.setup.ts` (production) — no `login()` call needed in each test
- Only `actor: user` (or default) behaviors are included. `actor: system/cron` → covered by `tests/flows.test.ts`
- Uses `blockAnalytics(page)` in `beforeEach` (not `captureAnalytics` — behaviors.spec.ts verifies functionality, not analytics wiring)
- Form submissions use timestamped data (`test-${Date.now()}@test.example`) to avoid duplicate conflicts
- Anonymous behaviors are grouped first, then auth-gated behaviors (for readability)
- **Triple duty**: This file runs in CI (auto-discovered by `npx playwright test`), during local `/verify` (STATE 5 auto-discovers), and in production `/deploy` (STATE 4 step 5d.6 with `E2E_BASE_URL`)
- **Staleness protection**: verify.md STATE 5 has a 3-attempt fix budget that catches and repairs stale selectors (same mechanism as funnel.spec.ts)
- **Regression detection**: When a `/change` modifies unrelated code that breaks an existing behavior, CI catches it on the next PR

### Assertion Depth Patterns

The `then` clause of each behavior determines the assertion pattern for its tests.
Bootstrap uses this mapping when generating test bodies:

| `then` keyword class | Assertion pattern | Playwright API |
|---|---|---|
| "created", "generated" | Verify content exists with expected values | `toContainText(/.../i)`, `toHaveText(/.../i)` |
| "redirected", "navigates", "land on" | Verify URL changed to expected target | `toHaveURL(/\/target/)` |
| "updates", "changes", "marked" | Verify state change is visible | Assert element text/attribute before and after action |
| "shows", "displays", "renders" | Verify actual data values, not just presence | `toHaveText(/\$[0-9]/)` not just `toBeVisible()` |
| "accepts", "validates" | Verify input processing end-to-end | `fill()` → submit → verify result or field-level error |
| (default) | Interact then assert visibility | Click/navigate per `when`, then `toBeVisible()` on outcome |

**Mandatory rule:** Every `test()` in `behaviors.spec.ts` must include at least one assertion
beyond `toBeVisible()`. The `then` clause determines which pattern. If a test can only
assert visibility (e.g., "Landing page renders without errors"), add a content assertion
(e.g., `toHaveText` on the heading text, `toHaveTitle` matching expected title).

This mapping is a heuristic — not an exhaustive parser. When the `then` clause is ambiguous,
prefer the more specific assertion. When multiple keywords match, use the first match in the
table (ordered by specificity).

These rules refine the test body for existing `behaviors[].tests` entries. They do NOT create
additional tests beyond what experiment.yaml specifies.

## Critical Flow Integration Tests

When experiment.yaml has `behaviors with actor: system/cron`, bootstrap generates `tests/flows.test.ts` using vitest
(installed alongside Playwright). These test operational chains at the API level — no browser needed.

### `tests/flows.test.ts` — Integration tests for operational chains
```ts
import { describe, it, expect, beforeAll } from "vitest";

// Invocation pattern depends on framework:
//
// Frameworks with app.request() (Hono, etc.):
//   import app from "../src/index";
//   const res = await app.request("/api/webhooks/payment", { method: "POST", ... });
//
// Frameworks without app.request() (Next.js):
//   import { POST } from "@/app/api/webhooks/payment/route";
//   const res = await POST(new Request("http://localhost/api/webhooks/payment", { method: "POST", ... }));
//
// Never use fetch("http://localhost:...") — tests must run without a server.

// Bootstrap generates one describe block per critical_flow entry:

// Example for a webhook flow:
// describe("payment-fulfillment", () => {
//   it("webhook updates invoice status and sends emails", async () => {
//     // Setup: create a test invoice in database
//     // Act: call webhook handler with test payload (see invocation pattern above)
//     // Assert: invoice status is 'paid' in database
//     // Assert: email API was called (or queue has entries)
//   });
// });
//
// Example for a cron flow:
// describe("overdue-reminder", () => {
//   it("sends reminders for overdue invoices", async () => {
//     // Setup: create overdue invoice in database
//     // Act: call cron handler directly (see invocation pattern above)
//     // Assert: nudge_sent_at is set
//     // Assert: reminder email queued
//   });
// });
```

Notes:
- Uses vitest, not Playwright — these are API-level integration tests
- **Must run via `npm test` without a server** — use `app.request()` or direct handler import (see invocation pattern above), never `fetch("http://localhost:...")`
- Each flow is independent — sets up its own test data, cleans up after
- Webhook tests call the handler with realistic payloads
- Cron tests call the cron handler directly
- Admin tests call admin API handlers (no browser, no login flow)
- Skip tests when required env vars are missing (e.g., Stripe webhook secret)
- **Database-dependent tests**: When a test calls an API route that requires a database connection, use `it.skipIf(!process.env.SUPABASE_URL)` to skip the test when no database is available (common in CI without a live Supabase instance). When a database IS available, the test should reject 500 as a real failure — do not blanket-accept all status codes.
- **Stub generation from behavior.tests**: For each behavior with `actor: system/cron`, iterate over the behavior's `tests` array and generate a stub `it()` block for each entry. Include a descriptive TODO comment for the database assertion even if the assertion body is not yet implemented. This ensures spec-reviewer S5/S7 checks find matching `it()` blocks for every behavior test entry. Example: `it("Call record is inserted into calls table", async () => { // TODO: query database to verify record exists });`
- These complement funnel tests: golden_path tests the customer journey (browser),
  behaviors with actor: system/cron tests the delivery chain (API)

## Environment Variables
```
E2E_PORT=3099                        # Optional, defaults to 3099. Avoids conflicts with other services on port 3000.
E2E_BASE_URL=http://localhost:3099   # Optional, defaults to localhost:${E2E_PORT}. Set to production URL to skip webServer start.
PROD_TEST_EMAIL=mvp-test@slug.test   # Optional, production test user email (auto-created by /deploy STATE 4)
PROD_TEST_PASSWORD=<random>          # Optional, production test user password (auto-created by /deploy STATE 4)
```

Full-Auth path reads local Supabase keys dynamically from `supabase status -o json` in `playwright.config.ts` — no manual env vars needed for database or auth.

**Production mode:** When `E2E_BASE_URL` is set to a production URL, the `webServer` block is skipped (production server already running). When `PROD_TEST_EMAIL` and `PROD_TEST_PASSWORD` are also set, the `prod-auth-setup` project runs before chromium tests to authenticate the test user via the login form. `/deploy` STATE 4 auto-creates the test user and passes these env vars — no manual configuration needed.

**When using the No-Auth Fallback:** same as above — only the optional port and base URL apply. Production mode works without `PROD_TEST_EMAIL`/`PROD_TEST_PASSWORD` (smoke tests run as anonymous visitors).

## .gitignore Additions
```
# Playwright (update if you change stack.testing)
/test-results/
/playwright-report/
/blob-report/
/e2e/.auth.json
```

## package.json Scripts
```json
{
  "test:e2e": "playwright test",
  "test:e2e:ui": "playwright test --ui"
}
```

## CI Job Template
Add this job to `.github/workflows/ci.yml` after the `build` job. Gate
hashFiles checks at the step level — `hashFiles()` at job-level `if:` is
rejected by actionlint and causes GitHub Actions to fail the workflow at
parse time. If the repo already defines a `detect` job (per the workflow
template in this repo), gate on `needs.detect.outputs.e2e_present == 'true'`
and add `detect` to `needs:` instead.
```yaml
  e2e:
    needs: build
    runs-on: ubuntu-latest
    timeout-minutes: 15
    env:
      # Database stack (if stack.database is supabase):
      # NEXT_PUBLIC_SUPABASE_URL: https://placeholder.supabase.co
      # NEXT_PUBLIC_SUPABASE_ANON_KEY: placeholder-anon-key
      # Payment stack (if stack.payment is present in experiment.yaml):
      # STRIPE_SECRET_KEY: ${{ secrets.E2E_STRIPE_SECRET_KEY }}
      # NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY: ${{ secrets.E2E_STRIPE_PUBLISHABLE_KEY }}
      # STRIPE_WEBHOOK_SECRET: ${{ secrets.E2E_STRIPE_WEBHOOK_SECRET }}
    steps:
      - uses: actions/checkout@v4
      - name: Skip if no playwright config
        id: check
        run: |
          if [ -f playwright.config.ts ]; then
            echo "run=true" >> "$GITHUB_OUTPUT"
          else
            echo "run=false" >> "$GITHUB_OUTPUT"
          fi
      - uses: actions/setup-node@v4
        if: steps.check.outputs.run == 'true'
        with:
          node-version-file: '.nvmrc'
          cache: npm
      - uses: supabase/setup-cli@v1
        if: steps.check.outputs.run == 'true'
      - name: Start local Supabase
        if: steps.check.outputs.run == 'true'
        run: supabase start -x realtime,storage,imgproxy,inbucket,pgadmin-schema-diff,migra,postgres-meta,studio,edge-runtime,logflare,pgbouncer,vector
      - name: Apply migrations
        if: steps.check.outputs.run == 'true'
        run: supabase db reset
      - name: Install dependencies
        if: steps.check.outputs.run == 'true'
        run: npm ci
      - name: Install Playwright browsers
        if: steps.check.outputs.run == 'true'
        run: npx playwright install chromium --with-deps
      - name: Run E2E tests
        if: steps.check.outputs.run == 'true'
        run: npx playwright test
      - uses: actions/upload-artifact@v4
        if: ${{ !cancelled() && steps.check.outputs.run == 'true' }}
        with:
          name: playwright-report
          path: playwright-report/
          retention-days: 7
      - name: Stop local Supabase
        if: ${{ always() && steps.check.outputs.run == 'true' }}
        run: supabase stop
```

## No-Auth Fallback

When `assumes` dependencies are not met (e.g., no `auth/supabase` or `database/supabase`), use these simplified templates instead of the full versions above. Tests run as anonymous visitors with no login flow.

### `playwright.config.ts` — Simplified (no global setup/teardown)
```ts
// @next/env loadEnvConfig: shape depends on loader. .ts (Playwright pirates +
// CJS-transpile) requires NAMED-import; .mjs (raw Node ESM) requires
// default-import + destructure. See "CJS-interop with @next/env" Stack
// Knowledge entry in stacks/analytics/posthog.md for the per-loader contract.
import { loadEnvConfig } from "@next/env";
loadEnvConfig(process.cwd());

import { defineConfig, devices } from "@playwright/test";

const port = process.env.E2E_PORT || "3099";

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: "html",
  use: {
    baseURL: process.env.E2E_BASE_URL || `http://localhost:${port}`,
    trace: "on-first-retry",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "Mobile Chrome", use: { ...devices["Pixel 5"] } },
  ],
  webServer: process.env.E2E_BASE_URL
    ? undefined
    : {
        command: `PORT=${port} npm run dev`,
        url: `http://localhost:${port}`,
        reuseExistingServer: !process.env.CI,
      },
});
```
- No `globalSetup`/`globalTeardown` — no test user lifecycle needed
- `webServer` is conditional: when `E2E_BASE_URL` is set, `webServer` is `undefined` (production server already running)
- Two projects: Desktop Chrome and Mobile Chrome (Pixel 5) — same as full config
- Everything else is identical to the full config

### `e2e/helpers.ts` — Simplified (blockAnalytics + captureAnalytics only)
```ts
import type { Page } from "@playwright/test";

export async function blockAnalytics(page: Page) {
  await page.route("**/ingest/**", (route) => route.abort());
}

export interface CapturedEvent {
  event: string;
  properties: Record<string, unknown>;
}

export async function captureAnalytics(page: Page): Promise<CapturedEvent[]> {
  const events: CapturedEvent[] = [];
  await page.route("**/ingest/**", async (route) => {
    try {
      const body = route.request().postDataJSON();
      if (body?.batch) {
        for (const item of body.batch) {
          if (item.event) events.push({ event: item.event, properties: item.properties || {} });
        }
      } else if (body?.event) {
        events.push({ event: body.event, properties: body.properties || {} });
      }
    } catch { /* non-JSON body, ignore */ }
    await route.abort(); // still block from reaching provider
  });
  return events;
}

export async function checkNoHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth
  );
  if (overflow) {
    throw new Error(
      `Horizontal overflow detected (scrollWidth ${await page.evaluate(() => document.documentElement.scrollWidth)}px > clientWidth ${await page.evaluate(() => document.documentElement.clientWidth)}px)`
    );
  }
}
```
- No `getTestCredentials()` or `login()` — tests run as anonymous visitors
- `blockAnalytics()` still prevents analytics pollution for smoke tests. **Provider adaptation:** if using a different analytics provider, update the route pattern to match that provider's endpoint pattern from its analytics stack file's "Test Blocking" section.
- `captureAnalytics()` intercepts AND records analytics payloads — use in funnel tests to verify events fire correctly.

### `e2e/smoke.spec.ts` — Simplified (anonymous visitor)
```ts
import { test, expect } from "@playwright/test";
import { blockAnalytics, checkNoHorizontalOverflow } from "./helpers";

test.describe.serial("Funnel smoke test", () => {
  test.beforeEach(async ({ page }) => {
    await blockAnalytics(page);
  });

  test("visit landing page", async ({ page }) => {
    await page.goto("/");
    await expect(page).toHaveTitle(/.+/);
    await checkNoHorizontalOverflow(page);
  });

  // Page-load smoke tests only — add `await checkNoHorizontalOverflow(page)` after every page.goto()
  // See funnel.spec.ts for full user journey tests
});
```
- No `getTestCredentials` or `login` imports — tests as anonymous visitor
- See funnel.spec.ts (above) for the full user journey test template

### No-Auth CI Job Template
When using the No-Auth Fallback path, use this CI template instead of the full-auth version above. It omits the local Supabase lifecycle (no Docker, no `supabase start/stop`). A step-level `hashFiles()` probe gates the run on `playwright.config.ts` existence — do NOT use job-level `if: hashFiles(...)`, which is rejected by actionlint and causes GitHub Actions to fail the workflow at parse time.
```yaml
  e2e:
    needs: build
    runs-on: ubuntu-latest
    timeout-minutes: 10
    env:
      # Database stack (if stack.database is supabase):
      # NEXT_PUBLIC_SUPABASE_URL: https://placeholder.supabase.co
      # NEXT_PUBLIC_SUPABASE_ANON_KEY: placeholder-anon-key
      # Payment stack (if stack.payment is present in experiment.yaml):
      # STRIPE_SECRET_KEY: ${{ secrets.E2E_STRIPE_SECRET_KEY }}
      # NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY: ${{ secrets.E2E_STRIPE_PUBLISHABLE_KEY }}
      # STRIPE_WEBHOOK_SECRET: ${{ secrets.E2E_STRIPE_WEBHOOK_SECRET }}
    steps:
      - uses: actions/checkout@v4
      - name: Skip if no playwright config
        id: check
        run: |
          if [ -f playwright.config.ts ]; then
            echo "run=true" >> "$GITHUB_OUTPUT"
          else
            echo "run=false" >> "$GITHUB_OUTPUT"
          fi
      - uses: actions/setup-node@v4
        if: steps.check.outputs.run == 'true'
        with:
          node-version-file: '.nvmrc'
          cache: npm
      - name: Install dependencies
        if: steps.check.outputs.run == 'true'
        run: npm ci
      - name: Install Playwright browsers
        if: steps.check.outputs.run == 'true'
        run: npx playwright install chromium --with-deps
      - name: Run E2E tests
        if: steps.check.outputs.run == 'true'
        run: npx playwright test
      - uses: actions/upload-artifact@v4
        if: ${{ !cancelled() && steps.check.outputs.run == 'true' }}
        with:
          name: playwright-report
          path: playwright-report/
          retention-days: 7
```

## Preview Smoke CI Job Template
Add this job to `.github/workflows/ci.yml` after the `e2e` job. It runs page-load smoke tests against Vercel preview deployments on PRs — no auth, no database writes, no Docker required. Job-level `if:` keeps the PR-only gate (`github.event_name`); a step-level `hashFiles()` probe handles the `playwright.config.ts` gate — job-level `hashFiles()` fails workflow parsing.
```yaml
  preview-smoke:
    needs: build
    if: github.event_name == 'pull_request'
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@v4
      - name: Skip if no playwright config
        id: check
        run: |
          if [ -f playwright.config.ts ]; then
            echo "run=true" >> "$GITHUB_OUTPUT"
          else
            echo "run=false" >> "$GITHUB_OUTPUT"
          fi
      - uses: actions/setup-node@v4
        if: steps.check.outputs.run == 'true'
        with:
          node-version-file: '.nvmrc'
          cache: npm
      - name: Wait for Vercel preview
        if: steps.check.outputs.run == 'true'
        uses: patrickedqvist/wait-for-vercel-preview@v1.3.2
        id: preview
        with:
          token: ${{ secrets.GITHUB_TOKEN }}
          max_timeout: 300
      - name: Install dependencies
        if: steps.check.outputs.run == 'true'
        run: npm ci
      - name: Install Playwright browsers
        if: steps.check.outputs.run == 'true'
        run: npx playwright install chromium --with-deps
      - name: Smoke test preview deployment
        if: steps.check.outputs.run == 'true'
        run: npx playwright test e2e/smoke.spec.ts --global-setup="" --global-teardown=""
        env:
          E2E_BASE_URL: ${{ steps.preview.outputs.url }}
      - uses: actions/upload-artifact@v4
        if: ${{ !cancelled() && steps.check.outputs.run == 'true' }}
        with:
          name: preview-smoke-report
          path: playwright-report/
          retention-days: 7
```
- PR-only: `github.event_name == 'pull_request'` since pushes to main don't create preview deployments
- `--global-setup="" --global-teardown=""` disables auth setup for preview smoke (no local Supabase available)
- `E2E_BASE_URL` overrides the default localhost base URL with the Vercel preview URL
- Uses `patrickedqvist/wait-for-vercel-preview@v1.3.2` (well-maintained, 300+ stars) to wait for the preview deployment
- Timeout: 5 minutes (preview deploys are fast, smoke tests are page-load only)

## Patterns
- **Serial tests for funnel**: use `test.describe.serial` — funnel steps depend on each other (signup before activation, activation before payment)
- **Block analytics**: always call `blockAnalytics(page)` in `beforeEach` — tests should not pollute analytics data
- **Test user email pattern**: `e2e-{timestamp}@test.example` — unique per run, clearly identifiable for cleanup
- **Admin API for user lifecycle**: create via `supabase.auth.admin.createUser`, delete via `supabase.auth.admin.deleteUser` — never use the signup form for test user creation
- **Stripe test card**: when `stack.payment` is present, use card number `4242424242424242`, any future expiry, any CVC
- **Funnel happy path only**: test the success path through each funnel step — skip error states, edge cases, and `retain_return` (24h delay makes it untestable)
- **Real selectors from app code**: the /change skill reads actual page components to determine selectors — never guess
- **Mobile viewport smoke test**: every smoke test runs on both Desktop Chrome and Mobile Chrome (Pixel 5). The `checkNoHorizontalOverflow(page)` assertion catches the most common mobile layout issue (elements wider than viewport). Add this check after every `page.goto()` in smoke tests.

## Security
- Local Supabase keys are read dynamically from `supabase status` at test time — works with both legacy JWT keys and new `sb_*` format keys (CLI v2.76+). Fallback keys are well-known deterministic values safe to commit.
- Production Supabase keys are never used in tests
- `e2e/.auth.json` is gitignored — contains test credentials that should not be committed
- Test users are created and deleted per run — no persistent test accounts

## Stack Knowledge

### Strict-mode violations with repeated text across page sections
When asserting text that appears in multiple page sections (e.g., a pricing string like "$297" in hero, features, and pricing sections), `getByText()` in strict mode fails because it resolves to multiple elements. Scope the locator to a specific section or use `.first()` — e.g., `page.getByText("$297").first()`.

### Strict-mode violations with password input and show/hide toggle
When locating a password input on pages with a show/hide visibility toggle, `getByLabel(/password/i)` matches both the input and the toggle button's aria-label. Use `page.locator('input[type="password"]')` instead — it targets the input element by HTML type attribute, which is stable regardless of `id` attribute changes or aria-label conflicts. Avoid `page.locator("#password")` because the `id` attribute may be renamed by design-critic agents or during markup refactoring.

### Mobile-hidden labels cause strict-mode violations
When a UI element uses responsive visibility classes (e.g., `hidden sm:inline`), its text is absent in the Mobile Chrome (Pixel 5) viewport. `getByText()` and `getByRole()` with name matching will fail on mobile because the element is not rendered. Use an always-visible alternative: prefer `getByLabel()` targeting the associated form input, or `getByRole()` targeting an element that is visible at all viewport sizes. Never use `getByText()` on text that is conditionally hidden via responsive classes.

### shadcn CardTitle renders as div, not heading
`shadcn/ui` `CardTitle` renders as a `<div>` by default, not a heading element. `getByRole('heading', { name: ... })` will not match it. Use `getByText('Card Title Text')` or a `data-testid` attribute instead.

### DEMO_MODE redirects bypass expected UI assertions
When `DEMO_MODE` is active, pages that normally show a UI element after an action (e.g., a success message after signup) may instead redirect immediately to another page. Tests asserting on the message will fail even though the action succeeded. Use `waitForURL` as an alternative assertion: `await page.waitForURL(/\/expected-page/)` to verify the redirect occurred, or branch assertions with `if (process.env.NEXT_PUBLIC_DEMO_MODE === "true")`.

### Stale dev server from another project on same port
When another project's dev server is already running on the configured port (e.g., 3099), Playwright connects to it and runs tests against the wrong application. Tests either pass incorrectly or fail with confusing selector errors that don't reflect the actual app. Before running `npm run test:e2e`, verify no stale server occupies the port: `lsof -i :3099` (macOS/Linux) or `netstat -ano | findstr :3099` (Windows). Kill the stale process before starting tests. Playwright's `reuseExistingServer: !process.env.CI` setting intentionally reuses in dev but not in CI.

### Windows compatibility for webServer command
The `webServer.command` uses `` `PORT=${port} npm run dev` `` (POSIX shell syntax). On Windows, `cmd.exe` interprets `PORT=3099` as an executable name, not an environment variable assignment. If developing on Windows, install `cross-env` (`npm install -D cross-env`) and change the command to `` `cross-env PORT=${port} npm run dev` ``.

### When a smoke test assertion targets the Next.js dev indicator or error overlay portal
Scope the locator to `[data-nextjs-dialog-overlay]` rather than the generic portal container. The outer portal wrapper DOM structure changes between Next.js releases; the `data-nextjs-dialog-overlay` attribute is the stable selector for the actual overlay element.

### When testing pages with MagicUI animation components (BlurFade, scroll-triggered effects)
Add a `triggerAllInView()` helper to `e2e/helpers.ts` that scrolls through the full page height to trigger IntersectionObserver-based animations before asserting on elements inside them:

```ts
export async function triggerAllInView(page: Page) {
  const height = await page.evaluate(() => document.body.scrollHeight);
  for (let y = 0; y <= height; y += 200) {
    await page.evaluate((scrollY) => window.scrollTo(0, scrollY), y);
    await page.waitForTimeout(50);
  }
  await page.evaluate(() => window.scrollTo(0, 0));
}
```

Call `await triggerAllInView(page)` after navigation and before asserting on elements that are inside BlurFade or other IntersectionObserver-controlled components. Without this, selectors targeting animated elements return empty results because the elements remain in their pre-animation hidden state.

### When selecting MagicUI ShimmerButton in Playwright tests
Use `page.locator('text=...')` or attribute selectors (`[data-testid=...]`) instead of `page.getByRole('button', { name: '...' })`. ShimmerButton is a styled canvas-based element without a standard ARIA button role, so `getByRole('button')` does not match it.

### When smoke test navigates to auth-protected page that redirects
Pages behind auth guards immediately redirect to a login page. `page.goto()` waits for `load` by default, which fires before the redirect-triggered navigation finishes. Assertions on page content (title, heading) run against the intermediate blank state. Use `waitUntil: 'networkidle'` to wait for the redirect to settle:

```typescript
await page.goto("/protected-page", { waitUntil: "networkidle" });
```

Alternatively, assert on the redirect destination with `page.waitForURL(/\/login/)` instead of asserting on page content.

### When writing e2e selectors for CTA buttons or marketing copy elements

Use `data-testid` or purpose-specific `data-*` attributes (e.g., `data-preview-cta`, `data-pricing-cta`) as the primary selector for CTAs and marketing copy elements, not visible text content. Text-content selectors (`getByText(...)`, `page.locator('text=...')`) break on every copy change — including A/B test rewrites, marketing iteration, and legal/UPL copy adjustments — causing cascading e2e failures unrelated to functional regressions.

```tsx
import { Button } from "@/components/ui/button";

// Component
<Button data-preview-cta>Lock in early-bird pricing</Button>

// Test — stable across copy changes
await expect(page.locator("[data-preview-cta]")).toBeVisible();
await page.locator("[data-preview-cta]").click();
```

If you need to assert that specific copy is visible (e.g., to verify the variant rendered the right headline), do so as a secondary `toHaveText()` assertion on a node already located by its `data-*` attribute:

```tsx
await expect(page.locator("[data-preview-cta]")).toHaveText(/lock in early-bird/i);
```

Attribute selectors decouple test stability from marketing iteration — a one-PR rewrite of the CTA from `"Lock in founding rate"` to `"Lock in early-bird pricing"` would otherwise break 6+ e2e tests across `funnel.spec.ts` and `behaviors.spec.ts`. Apply this rule to landing-page CTAs, pricing-table CTAs, signup/login submit buttons, and any element whose primary identity is its visible copy.

## PR Instructions
- Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) if not already installed
- Start local Supabase: `make supabase-start` (now delegates to `bash .claude/scripts/ensure-supabase-start.sh`, which also writes the ownership marker — safe for both manual dev and in-skill use)
- Run `npm run test:e2e` locally to verify tests pass
- Stop local Supabase: `make supabase-stop` (or `npx supabase stop`) — skill-owned stacks also stop automatically on `/verify` / `/change` finalize
- No CI secrets needed for database/auth E2E — CI starts local Supabase automatically
- If `stack.payment` is present: add Stripe CI secrets (`E2E_STRIPE_SECRET_KEY`, `E2E_STRIPE_PUBLISHABLE_KEY`, `E2E_STRIPE_WEBHOOK_SECRET`) to GitHub repo settings (Settings → Secrets and variables → Actions)

## Local dev container lifecycle

The skill lifecycle owns a transient-services teardown contract so Supabase containers don't accumulate across `/verify` / `/change` runs (see closed issue #968 for the leak history):

- **How ownership is assigned.** `ensure-supabase-start.sh` (invoked directly or via `make supabase-start`) always writes an ownership marker at `<git-common-dir>/transient-resources.json` with one of two owners: `owner=skill` when a skill was active at the time the wrapper invoked `supabase start` (marker stores `run_id`, `ancestors_run_ids`, `project_id`, `repo_root`); `owner=user` when the stack was already running before the wrapper was invoked OR when the wrapper was called with no active skill context (e.g. manual `make supabase-start`). `owner=user` stacks are never touched by the lifecycle — finalize Step 7 and init Step 0.5 both skip them.
- **Teardown.** On normal skill completion, `lifecycle-finalize.sh` Step 7 reads the marker and stops only `owner=skill` stacks matching the current `run_id` (or any ancestor `run_id` for `/change`→embedded `/verify`) via `npx supabase stop --project-id <snapshot>`. A matching `<git-common-dir>/finalize-completed-<run_id>.flag` file is written after the stop succeeds. The next skill's `lifecycle-init.sh` Step 0.5 detects `owner=skill` markers with no matching flag and cleans them up — covering Ctrl-C, crash, and finalize-mid-step failures. A 7-day flag GC runs at the top of orphan-cleanup so `.git/common-dir` never fills up.
- **No-marker policy.** If the marker is absent and Supabase is running, the lifecycle does nothing — it cannot distinguish "user started supabase manually and hasn't invoked the wrapper yet" from "Claude bypassed the wrapper." Preserving user state wins. The wrapper-bypass case is addressed by making `make supabase-start` delegate to the wrapper and by the weekly cleanup one-liner below.
- **Cross-worktree safety.** Two worktrees of the same repo share one Docker daemon, so start/stop is serialized with a python3 `fcntl.flock` on `<git-common-dir>/supabase.lock` (macOS has no `/usr/bin/flock`). Concurrent skill runs line up behind the lock.
- **Docker hang protection.** Both scripts preflight `docker info` and skip the teardown when the daemon is unreachable; the stop step also runs under a 60-second background kill watchdog (macOS has no `timeout(1)`).
- **Manual cleanup across all projects:** `docker ps --filter name=supabase_ -q | xargs -r docker stop`
- **CI note.** The teardown script skips automatically when `GITHUB_ACTIONS=true` or `CI=true`. CI workflows continue to own their own `if: always()` supabase-stop step (see the CI template above).

**When using the No-Auth Fallback path:** Docker and local Supabase are not required — tests run unconditionally. Just run `npm run test:e2e` locally to verify.

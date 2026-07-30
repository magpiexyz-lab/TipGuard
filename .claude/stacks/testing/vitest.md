---
assumes: []
packages:
  runtime: []
  dev: [vitest, "@vitest/coverage-v8"]
files:
  - vitest.config.ts
  - tests/smoke.test.ts       # conditional: service archetype bootstrap smoke tests
  - tests/commands.test.ts    # conditional: cli archetype bootstrap smoke tests
  - tests/flows.test.ts      # conditional: only when experiment.yaml has behaviors with actor: system/cron
env:
  server: []
  client: []
ci_placeholders: {}
clean:
  files: []
  dirs: []
gitignore: []
---
# Testing: Vitest
> Used when experiment.yaml has `stack.testing: vitest`
> Assumes: nothing (framework-agnostic — works with any Node.js project)

## Packages
```bash
npm install -D vitest @vitest/coverage-v8
```

## Files to Create

### `vitest.config.ts` — Vitest configuration
```ts
import { defineConfig } from "vitest/config";
import path from "path";

export default defineConfig({
  test: {
    globals: true,
    environment: "node",
    include: ["src/**/*.test.ts", "tests/**/*.test.ts"],
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
```
- `globals: true` — enables `describe`, `it`, `expect` without imports
- `environment: "node"` — runs tests in Node.js (not jsdom)
- `@/` alias matches the project's TypeScript path alias
- Coverage excludes test files and declaration files

## Test Patterns

### Unit Test for Route Handlers
Place unit tests alongside source files or in a `tests/` directory:

```ts
// src/routes/health.test.ts
import { describe, it, expect } from "vitest";
import app from "../index";

describe("GET /api/health", () => {
  it("returns status ok", async () => {
    const res = await app.request("/api/health");
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.status).toBe("ok");
  });
});
```

- Use the framework's test client (e.g., Hono's `app.request()`) for lightweight API testing without spinning up a server
- For frameworks without a built-in test client, use `supertest` (add to `packages.dev` if needed)

### Unit Test for Business Logic
```ts
// src/lib/convert.test.ts
import { describe, it, expect } from "vitest";
import { convert } from "./convert";

describe("convert", () => {
  it("converts USD to EUR", () => {
    const result = convert(100, "USD", "EUR", 0.85);
    expect(result).toBe(85);
  });

  it("throws on unknown currency", () => {
    expect(() => convert(100, "XXX", "EUR", 0.85)).toThrow();
  });
});
```

### API Integration Test
```ts
// tests/api.test.ts
import { describe, it, expect, beforeAll, afterAll } from "vitest";
import app from "../src/index";

describe("API integration", () => {
  it("converts currency via /api/convert", async () => {
    const res = await app.request("/api/convert", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ from: "USD", to: "EUR", amount: 100 }),
    });
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body).toHaveProperty("result");
  });
});
```

## package.json Scripts
```json
{
  "test": "vitest run",
  "test:watch": "vitest",
  "test:coverage": "vitest run --coverage"
}
```

## CI Integration

Vitest runs in the existing `build` CI job after lint, or in a dedicated test job. Since vitest tests are fast (no browser, no Docker), they fit in the build job:

```yaml
  # Add after the Lint step in the build job:
  - name: Test
    run: |
      if [ -f package.json ] && node -e "process.exit(require('./package.json').scripts?.test ? 0 : 1)" 2>/dev/null; then
        npm test
      else
        echo "No test script found — skipping"
      fi
```

No additional CI env vars or services needed — vitest runs entirely in-process.

## Bootstrap Smoke Tests

Bootstrap generates minimal smoke tests to verify that routes/commands are registered and reachable. These are created by `/bootstrap` Step 7b — not by hand.

### Service Smoke Tests — `tests/smoke.test.ts`

Template for `type: service` projects. One test per experiment.yaml endpoint plus a health check:

```ts
import { describe, it, expect } from "vitest";
import app from "../src/index";

describe("smoke tests", () => {
  it("GET /api/health returns 200", async () => {
    const res = await app.request("/api/health");
    expect(res.status).toBe(200);
  });

  // One test per experiment.yaml endpoint:
  // GET endpoints:
  it("GET /api/<endpoint> does not 500", async () => {
    const res = await app.request("/api/<endpoint>");
    expect(res.status).not.toBe(500);
  });

  // POST endpoints — empty body (verifies route is registered, not input validation):
  it("POST /api/<endpoint> does not 500", async () => {
    const res = await app.request("/api/<endpoint>", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    expect(res.status).not.toBe(500);
  });
});
```

- Imports `app` from `../src/index` — the framework's exported app instance
- Health check asserts status 200 (the `/api/health` endpoint always exists)
- Per-endpoint tests assert `not.toBe(500)` — smoke tests verify route registration, not business logic
- POST endpoints send an empty JSON body — a 400 (validation error) is acceptable, a 500 is not
- **Fallback for frameworks without `app.request()`** (e.g., Virtuals ACP, Next.js): test handler functions directly by importing from the path defined by the framework stack file (e.g., `src/handlers/<name>` for Virtuals ACP, `src/app/api/<endpoint>/route` for Next.js) and calling with mock input. The test verifies the handler exists and returns without throwing.

### CLI Smoke Tests — `tests/commands.test.ts`

Template for `type: cli` projects. Tests `--version`, `--help`, and each experiment.yaml command:

```ts
import { describe, it, expect } from "vitest";
import { execSync } from "child_process";

function runCli(args: string): { stdout: string; exitCode: number } {
  try {
    const stdout = execSync(`node dist/index.js ${args}`, {
      encoding: "utf-8",
      timeout: 10000,
    });
    return { stdout, exitCode: 0 };
  } catch (error: any) {
    return {
      stdout: error.stdout ?? "",
      exitCode: error.status ?? 1,
    };
  }
}

describe("CLI smoke tests", () => {
  it("--version exits 0 and prints semver", () => {
    const { stdout, exitCode } = runCli("--version");
    expect(exitCode).toBe(0);
    expect(stdout.trim()).toMatch(/\d+\.\d+\.\d+/);
  });

  it("--help exits 0 and prints usage", () => {
    const { stdout, exitCode } = runCli("--help");
    expect(exitCode).toBe(0);
    expect(stdout).toContain("Usage:");
  });

  // One test per experiment.yaml command:
  it("<command> --help exits 0", () => {
    const { stdout, exitCode } = runCli("<command> --help");
    expect(exitCode).toBe(0);
    expect(stdout).toContain("<command>");
  });
});
```

- Helper `runCli(args)` runs `node dist/index.js ${args}` via `execSync`, returns `{ stdout, exitCode }`
- `--version` test asserts exit code 0 and a semver-like pattern in output
- `--help` test asserts exit code 0 and "Usage:" in output (Commander.js default)
- Per-command tests run `<command> --help` and assert exit code 0 + command name in output
- **Requires `npm run build` first** — tests run against compiled output in `dist/`. CI runs build before test.

## Critical Flow Integration Tests

When experiment.yaml has `behaviors with actor: system/cron`, bootstrap generates `tests/flows.test.ts` with one test per
critical flow entry. These test operational chains at the API level.

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
- Uses vitest — these are API-level integration tests (no browser needed)
- **Must run via `npm test` without a server** — use `app.request()` or direct handler import (see invocation pattern above), never `fetch("http://localhost:...")`
- Each flow is independent — sets up its own test data, cleans up after
- Webhook tests call the handler with realistic payloads
- Cron tests call the cron handler directly
- Admin tests call admin API handlers (no browser, no login flow)
- Skip tests when required env vars are missing (e.g., Stripe webhook secret)
- These complement golden_path funnel tests: golden_path tests the customer journey,
  behaviors with actor: system/cron tests the delivery chain
- Add `test:flows` script to package.json: `vitest run tests/flows.test.ts`

## Patterns
- **Colocate tests**: place `*.test.ts` files next to the code they test (e.g., `src/routes/health.test.ts`)
- **Use framework test client**: prefer `app.request()` (Hono) or equivalent over `supertest` when available
- **Test file naming**: `*.test.ts` — vitest config includes this pattern by default
- **No browser tests**: vitest handles unit and API tests only — use Playwright for E2E browser testing
- **Bootstrap smoke tests**: service archetypes test endpoints via `app.request()`, CLI archetypes test commands via `--help`. Both use vitest — no browser needed.
- **Coverage threshold**: not enforced by default — add thresholds in vitest.config.ts if needed

## Stack Knowledge

### When live-DB integration tests are unavailable (CI without a real database)
Read the migration SQL file directly and regex-assert database-level invariants — access-control policies, UNIQUE/CHECK constraints, NOT NULL columns, etc. This is a lightweight substitute that catches accidental deletion of security-critical SQL without requiring a live database connection. The example below is Supabase/Postgres; adapt regex patterns for other SQL dialects.

```ts
// tests/rls-migration.test.ts
import { readFileSync } from "fs";
import { join } from "path";
import { describe, it, expect } from "vitest";

describe("migration 000X <table> RLS and constraints", () => {
  const sql = readFileSync(
    join(__dirname, "../supabase/migrations/000X_<table>.sql"),
    "utf-8",
  );

  it("enables RLS on <table>", () => {
    expect(sql).toMatch(/enable row level security/i);
  });

  it("blocks cross-user reads with a SELECT policy", () => {
    expect(sql).toMatch(/create policy.*select.*using.*auth\.uid\(\)/is);
  });

  it("enforces UNIQUE constraint on (<col1>, <col2>)", () => {
    expect(sql).toMatch(/unique.*\(<col1>,\s*<col2>\)/i);
  });
});
```

When the migration file path changes (e.g., after a rename or re-number), update the path in the test — the test will fail clearly rather than silently passing. Spec-reviewer S7 checks that new tables with access-control policies have matching test assertions; this pattern satisfies that without a live DB.

## PR Instructions
- Run `npm test` locally to verify tests pass
- Run `npm run test:coverage` to check coverage
- No CI secrets or external services needed for vitest

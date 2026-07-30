# CONVENTIONS.md — Assayer Implementation Patterns

> Codifies patterns established during bootstrap. CLAUDE.md covers template-level rules;
> this document covers Assayer-specific implementation conventions.
>
> Source of truth: the actual code in `src/`. If a pattern here diverges from the code, the code wins.

---

## 1. API Route Pattern

Every API route follows the same structure: Zod validation, Supabase auth check, query, error handling.

```ts
// src/app/api/experiments/route.ts
import { NextResponse } from "next/server";
import { z } from "zod";
import { createServerSupabaseClient } from "@/lib/supabase-server";
import { handleApiError } from "@/lib/api-error";

const createExperimentSchema = z.object({
  name: z.string().min(1, "Name is required").max(200, "Name too long"),
});

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const { name } = createExperimentSchema.parse(body);

    const supabase = await createServerSupabaseClient();
    const { data: { user } } = await supabase.auth.getUser();
    if (!user) {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }

    const { data, error } = await supabase
      .from("experiments")
      .insert({ user_id: user.id, name, status: "draft" })
      .select("id, name, status, created_at")
      .single();

    if (error) {
      return NextResponse.json({ error: "Failed to create experiment" }, { status: 500 });
    }
    return NextResponse.json({ experiment: data }, { status: 201 });
  } catch (error) {
    return handleApiError(error);
  }
}
```

For routes with dynamic params, use the `withAuth` wrapper from `src/lib/api-auth.ts`:

```ts
// Signature: (request, context, user) where context.params is a Promise
const { id } = await context.params;
```

**Anti-pattern**: Don't inline auth logic in routes that already use `withAuth` — choose one pattern per route.

---

## 2. Supabase Query Safety

Always use explicit column lists. Never use `SELECT *`.

```ts
// Good
const { data } = await supabase
  .from("experiments")
  .select("id, name, description, status, verdict, started_at, ended_at, created_at")
  .eq("user_id", user.id);

// Bad — leaks columns, breaks if schema changes
const { data } = await supabase
  .from("experiments")
  .select("*")
  .eq("user_id", user.id);
```

Always filter by `user_id` (RLS is the safety net, not the primary access control):

```ts
.eq("id", id)
.eq("user_id", user.id)
.single();
```

When using `.select("*")` with callbacks, add explicit type annotations to avoid TS7006:

```ts
// Good
const ids = rows.map((h: { id: string }) => h.id);

// Bad — "implicitly has any type" build error
const ids = rows.map((h) => h.id);
```

---

## 3. Zod Schema Conventions

Schemas are defined at the top of the route file that uses them — not in a shared schemas file.

Rules:
- **Always add `.max()` on strings**, especially for fields forwarded to AI APIs
- Use `.uuid()` for ID fields
- Use `.optional()` for PATCH payloads
- Use `.enum()` for constrained values matching SQL CHECK constraints
- **Do not export inferred types** — database row types live in `types.ts` (Section 5). Use `z.infer<typeof schema>` only as a local type within the route file when needed, never as a shared export.

```ts
// src/app/api/spec/stream/route.ts
const streamSchema = z.object({
  idea: z.string().min(1, "Idea is required").max(10000, "Idea is too long"),
});

// src/app/api/experiments/[id]/route.ts
const updateExperimentSchema = z.object({
  name: z.string().min(1).max(200).optional(),
  description: z.string().max(2000).optional(),
  status: z.enum(["draft", "running", "paused", "completed"]).optional(),
});
```

**Anti-pattern**: A shared `src/lib/schemas.ts` file. Schemas are coupled to the route that validates them; colocating prevents drift.

---

## 4. Error Response Shape

All API errors return a structured object with `code`, `message`, and optional `details`. This matches the schema in `product-design.md` Section 5.

Codes: `validation_error`, `not_found`, `unauthorized`, `rate_limited`, `ai_error`, `internal_error`.

```ts
// Validation error (400)
{ "error": { "code": "validation_error", "message": "Invalid request", "details": ["Name is required", "Idea is too long"] } }

// Auth error (401)
{ "error": { "code": "unauthorized", "message": "Unauthorized" } }

// Not found (404)
{ "error": { "code": "not_found", "message": "Experiment not found" } }

// Rate limited (429)
{ "error": { "code": "rate_limited", "message": "Too many requests. Please try again later." } }

// AI error (502)
{ "error": { "code": "ai_error", "message": "AI service unavailable" } }

// Server error (500)
{ "error": { "code": "internal_error", "message": "Internal server error" } }
```

This is enforced by `withErrorHandler()` in `src/lib/api-error.ts`:
- `ZodError` → `validation_error` (400) with details array
- `ApiError` → corresponding code and status
- All other errors → `internal_error` (500) with generic message (internal message logged, never leaked)

**Anti-pattern**: Flat `{ error: "string" }` without a `code` field. The `code` field enables programmatic error handling by API consumers.

---

## 5. TypeScript Type Locations

Two categories of types, two locations:

| Category | Location | Pattern |
|----------|----------|---------|
| Database row types | `src/lib/types.ts` | One `interface` per table, manually kept in sync with SQL |
| Validation schemas | Inline in route files | Local `const`, not exported (see Section 3) |

There are no shared `*-schemas.ts` files. Schemas stay colocated with the route that validates them to prevent drift between validation and handler logic.

```ts
// src/lib/types.ts
export interface Experiment {
  id: string;
  user_id: string;
  status: "draft" | "running" | "paused" | "completed";
  verdict: "SCALE" | "REFINE" | "PIVOT" | "KILL" | null;
  // ...
}
```

Convenience type aliases extract union types from interfaces:

```ts
export type ExperimentStatus = Experiment["status"];
export type ExperimentVerdict = NonNullable<Experiment["verdict"]>;
export type FunnelStage = ExperimentMetric["funnel_stage"];
```

Keep `types.ts` in sync with `supabase/migrations/001_initial.sql`. The SQL CHECK constraints are the source of truth for valid enum values.

---

## 6. Status Transitions (Forward Convention)

Currently, valid status values are enforced by SQL CHECK constraints only:

```sql
status text NOT NULL DEFAULT 'draft'
  CHECK (status IN ('draft', 'running', 'paused', 'completed'))
```

There is no TypeScript transitions map yet. When implementing status changes (Session 3+), add a transitions map:

```ts
// Future: src/lib/transitions.ts
const VALID_TRANSITIONS: Record<ExperimentStatus, ExperimentStatus[]> = {
  draft: ["running"],
  running: ["paused", "completed"],
  paused: ["running", "completed"],
  completed: [],
};
```

Validate transitions in the PATCH handler before writing to the database.

---

## 7. Test Conventions

Two test layers:

| Layer | Tool | Location | Runs with |
|-------|------|----------|-----------|
| API / business logic | Vitest | `tests/flows.test.ts`, `src/lib/*.test.ts` | `npx vitest run` |
| Browser smoke / funnel | Playwright | `e2e/*.spec.ts` | `npx playwright test` |

Vitest tests hit real endpoints (not mocks):

```ts
// tests/flows.test.ts
const BASE_URL = process.env.E2E_BASE_URL || "http://localhost:3000";

describe("metrics-sync (b-26)", () => {
  it("rejects unauthorized requests", async () => {
    const res = await fetch(`${BASE_URL}/api/cron/metrics-sync`);
    expect(res.status).toBe(401);
  });
});
```

Conventions:
- Describe blocks reference behavior IDs: `"payment-fulfillment (b-25)"`
- Use `it.skipIf()` for tests that need external credentials
- Colocate unit tests: `foo.ts` → `foo.test.ts`

---

## 8. Import Alias

All imports use `@/` which maps to `src/`. No relative imports outside the current directory.

```ts
// Good
import { handleApiError } from "@/lib/api-error";
import { createServerSupabaseClient } from "@/lib/supabase-server";

// Bad
import { handleApiError } from "../../lib/api-error";
```

Relative imports are fine within the same directory (e.g., a page importing a colocated component).

---

## 9. Soft Delete Pattern (Forward Convention)

Not yet implemented — no `archived_at` column exists in the schema.

Convention for Session 3+:
- **User-owned rows**: Use soft delete with `archived_at timestamptz` column. Query with `.is("archived_at", null)` by default.
- **Anonymous/system rows**: May hard-delete. The spec-cleanup cron hard-deletes anonymous specs older than 24h by design (they have no `user_id`).
- **Cascade deletes**: Child tables (`experiment_hypotheses`, `experiment_metrics`, etc.) use `ON DELETE CASCADE` — deleting an experiment removes all children.

---

## 10. Analytics Events

Two files, clear separation:

| File | Purpose |
|------|---------|
| `src/lib/analytics.ts` | PostHog init, generic `track()`, `identify()`, `reset()` |
| `src/lib/events.ts` | Typed event wrappers — one function per event from experiment/EVENTS.yaml |

```ts
// Client-side: use typed wrappers
import { trackSpecGenerated } from "@/lib/events";
trackSpecGenerated({ anonymous: true, idea_length: 250 });

// Generic track() for one-off events
import { track } from "@/lib/analytics";
track("one_off_event", { key: "value" });
```

Global properties (`project_name`, `project_owner`) are auto-attached by `track()`. Never pass them manually.

Server-side analytics use `trackServerEvent()` from `src/lib/analytics-server.ts` with an explicit `distinctId`.

**Anti-pattern**: Never import `posthog-js` directly in pages or components. Always go through `@/lib/events` (typed wrappers) or `@/lib/analytics` (generic `track()`). Only `analytics.ts` itself imports PostHog.

---

## 11. Naming

| Thing | Convention | Example |
|-------|-----------|---------|
| Database tables | `snake_case`, plural | `experiment_hypotheses` |
| Database columns | `snake_case` | `user_id`, `spec_json`, `created_at` |
| TypeScript interfaces | `PascalCase`, singular | `ExperimentHypothesis` |
| Type aliases | `PascalCase` | `ExperimentStatus`, `FunnelStage` |
| API routes | `kebab-case` | `/api/cron/metrics-sync` |
| Route files | `route.ts` in folder matching URL | `src/app/api/experiments/[id]/route.ts` |
| Page files | `page.tsx` in folder matching URL | `src/app/lab/page.tsx` |
| Lib files | `kebab-case` | `api-error.ts`, `supabase-server.ts` |
| Component files | `PascalCase` | Colocated with page or in `src/components/` |
| Zod schemas | `camelCase` with `Schema` suffix | `createExperimentSchema` |

---

## 12. Migration Convention

Single migration file: `supabase/migrations/001_initial.sql`.

Structure within the file:
1. `CREATE TABLE IF NOT EXISTS` with all columns and CHECK constraints
2. `ALTER TABLE ... ENABLE ROW LEVEL SECURITY`
3. `DROP POLICY IF EXISTS` + `CREATE POLICY` (idempotent pair)
4. Indexes at the end, grouped

```sql
CREATE TABLE IF NOT EXISTS experiments (
  id       uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id  uuid REFERENCES auth.users(id) NOT NULL,
  status   text NOT NULL DEFAULT 'draft'
             CHECK (status IN ('draft', 'running', 'paused', 'completed')),
  -- ...
);

ALTER TABLE experiments ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can manage their own experiments" ON experiments;
CREATE POLICY "Users can manage their own experiments" ON experiments
  FOR ALL USING (auth.uid() = user_id);
```

One migration per PR, with sequential numbers: `002_add_foo.sql`. To alter CHECK constraints, use `DROP CONSTRAINT IF EXISTS` + `ADD CONSTRAINT` (PostgreSQL doesn't support `ALTER CONSTRAINT`).

**Admin client**: Server-to-server operations (webhooks, crons) use `createAdminSupabaseClient()` from `src/lib/supabase-admin.ts` which uses the service role key and bypasses RLS. Never use this client in user-facing routes.

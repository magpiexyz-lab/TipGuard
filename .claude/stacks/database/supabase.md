---
assumes: [framework/nextjs]
packages:
  runtime: ["@supabase/supabase-js", "@supabase/ssr", pg]
  dev: []
files:
  - src/lib/supabase.ts  # conditional: only when framework is nextjs
  - src/lib/supabase-server.ts  # conditional: templates differ per framework
  - src/lib/types.ts
  - scripts/auto-migrate.mjs  # conditional: templates differ per framework
env:
  server: [SUPABASE_SERVICE_ROLE_KEY]
  client: [NEXT_PUBLIC_SUPABASE_URL, NEXT_PUBLIC_SUPABASE_ANON_KEY]
ci_placeholders:
  NEXT_PUBLIC_SUPABASE_URL: "https://placeholder.supabase.co"
  NEXT_PUBLIC_SUPABASE_ANON_KEY: placeholder-anon-key
  SUPABASE_SERVICE_ROLE_KEY: placeholder-service-role-key
clean:
  files: []
  dirs: []
gitignore: []
---
# Database: Supabase (Postgres)
> Used when experiment.yaml has `stack.database: supabase`
> Assumes: `framework/nextjs` (server client uses `next/headers` for cookies)

## Packages
```bash
npm install @supabase/supabase-js @supabase/ssr pg
```

## Files to Create

### `src/lib/supabase.ts` — Browser client
```ts
import { createBrowserClient } from "@supabase/ssr";

function createDemoClient() {
  // Demo seed data: 3 generic rows for populated UI in demo mode.
  // Pages render real-looking data instead of empty states.
  const DEMO_SEED_DATA = [
    { id: "demo-1", name: "Sample Item 1", status: "active", created_at: new Date(Date.now() - 86400000 * 3).toISOString(), user_id: "demo-user-id" },
    { id: "demo-2", name: "Sample Item 2", status: "active", created_at: new Date(Date.now() - 86400000 * 1).toISOString(), user_id: "demo-user-id" },
    { id: "demo-3", name: "Sample Item 3", status: "pending", created_at: new Date().toISOString(), user_id: "demo-user-id" },
  ];
  // CANONICAL chainable factory — keep this body in sync with src/lib/supabase-server.ts
  // (the only other live copy). See `## Stack Knowledge > Canonical chainable factory`
  // for the contract. ctx tracks mutation state across the chain so
  // `.from('x').insert(payload).select().single()` returns a synthesized row
  // instead of null — the canonical API-route pattern (issue #1396).
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const chainable = (terminal: unknown, ctx: { hasMutation?: boolean; payload?: unknown } = {}): any =>
    new Proxy(() => terminal, {
      get: (_, prop) => {
        if (prop === "then") return (resolve: (v: unknown) => void) => resolve(terminal);
        if (prop === "insert" || prop === "update" || prop === "upsert") {
          return (payload: unknown) => chainable(terminal, { hasMutation: true, payload });
        }
        if (prop === "select") {
          // Reset terminal to seed data but PRESERVE ctx so .insert(p).select().single() carries hasMutation through.
          return () => chainable({ data: DEMO_SEED_DATA, error: null }, ctx);
        }
        if (prop === "single" || prop === "maybeSingle") {
          if (ctx.hasMutation) {
            const row = { id: `demo-${Date.now()}`, created_at: new Date().toISOString(), ...(ctx.payload as object) };
            return () => chainable({ data: row, error: null });
          }
          return () => chainable({ data: null, error: null });
        }
        return chainable(terminal, ctx);
      },
      apply: () => chainable(terminal, ctx),
    });
  const demoUser = {
    id: "demo-user-id",
    email: "demo@example.com",
    app_metadata: {},
    user_metadata: {},
    aud: "authenticated",
    created_at: new Date().toISOString(),
  };
  return {
    // .from() returns the mutation-aware chainable directly so .insert/.update/.upsert
    // flow through the proxy's get handler (issue #1396).
    from: () => chainable({ data: DEMO_SEED_DATA, error: null }, {}),
    auth: new Proxy(
      {
        getUser: () =>
          Promise.resolve({ data: { user: demoUser }, error: null }),
        getSession: () =>
          Promise.resolve({
            data: { session: { user: demoUser, access_token: "demo-token", refresh_token: "demo-refresh", expires_at: Date.now() + 3600 } },
            error: null,
          }),
        signUp: () =>
          Promise.resolve({
            data: { user: demoUser, session: { access_token: "demo-token", refresh_token: "demo-refresh" } },
            error: null,
          }),
        signInWithPassword: () =>
          Promise.resolve({ data: { user: demoUser, session: { access_token: "demo-token", refresh_token: "demo-refresh" } }, error: null }),
        signOut: () => Promise.resolve({ error: null }),
        resetPasswordForEmail: () => Promise.resolve({ data: {}, error: null }),
        onAuthStateChange: () => ({
          data: { subscription: { unsubscribe: () => {} } },
        }),
      },
      {
        get: (target, prop) =>
          prop in target
            ? target[prop as keyof typeof target]
            : () => Promise.resolve({ data: {}, error: null }),
      }
    ),
    rpc: () => chainable({ data: null, error: null }),
  } as unknown as ReturnType<typeof createBrowserClient>;
}

// Issue #1170 follow-up: warn-once when placeholder fallback hits in a deployed-host
// context. Routing to the demo client is intentional (#1145) and stays unchanged, but
// silently routing to demo in production usually means env vars were not configured;
// surface that as a one-time `console.error` so operators can see it in logs / DevTools.
let _supabasePlaceholderWarned = false;
function _warnSupabasePlaceholder(side: "client" | "server") {
  if (_supabasePlaceholderWarned) return;
  if (typeof window !== "undefined") {
    // Client side: only warn on deployed hostnames.
    const host = window.location.hostname;
    const isLocal =
      ["localhost", "127.0.0.1", "0.0.0.0", "[::1]"].includes(host) ||
      host.endsWith(".local");
    if (isLocal) return;
  } else {
    // Server side: only warn on hosting platforms.
    const isHostingPlatform =
      process.env.VERCEL === "1" || !!process.env.RAILWAY_ENVIRONMENT_NAME;
    if (!isHostingPlatform) return;
  }
  _supabasePlaceholderWarned = true;
  console.error(
    `[supabase] ${side === "client" ? "Browser" : "Server"} Supabase ` +
    "placeholder fallback was hit — this deployment is using the demo client " +
    "with mocked data. Set NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY " +
    "in your hosting platform (Vercel Supabase Integration auto-injects these) " +
    "to use a real Supabase project."
  );
}

export function createClient() {
  // Issue #1145: NEXT_PUBLIC_* env vars are inlined at build time by Next.js, so a
  // build produced without NEXT_PUBLIC_DEMO_MODE=true compiles the demo branch to
  // dead code. Detect a placeholder configuration at runtime — when the URL/key are
  // missing or match the canonical placeholder default, fall back to the demo
  // client instead of attempting placeholder.supabase.co DNS.
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL || "";
  const anon = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || "";
  const isDemoFlag = process.env.NEXT_PUBLIC_DEMO_MODE === "true";
  const isPlaceholder = !url || !anon || url === "https://placeholder.supabase.co";
  if (isPlaceholder && !isDemoFlag) _warnSupabasePlaceholder("client");
  if (isDemoFlag || isPlaceholder) return createDemoClient();
  // Use `||` (falsy check) rather than `??` so empty-string env values (common on
  // CI/Vercel when a var is declared but unset) fall back to the placeholder
  // instead of initializing the SDK with "" and crashing on first request.
  return createBrowserClient(
    url || "https://placeholder.supabase.co",
    anon || "placeholder-anon-key"
  );
}
```

### `src/lib/supabase-server.ts` — Server client for API routes
```ts
import { createServerClient } from "@supabase/ssr";
import { createClient } from "@supabase/supabase-js";
import { cookies } from "next/headers";

function createDemoClient() {
  // Demo seed data: 3 generic rows for populated UI in demo mode.
  const DEMO_SEED_DATA = [
    { id: "demo-1", name: "Sample Item 1", status: "active", created_at: new Date(Date.now() - 86400000 * 3).toISOString(), user_id: "demo-user-id" },
    { id: "demo-2", name: "Sample Item 2", status: "active", created_at: new Date(Date.now() - 86400000 * 1).toISOString(), user_id: "demo-user-id" },
    { id: "demo-3", name: "Sample Item 3", status: "pending", created_at: new Date().toISOString(), user_id: "demo-user-id" },
  ];
  // CANONICAL chainable factory — keep this body in sync with src/lib/supabase.ts
  // (the only other live copy). See `## Stack Knowledge > Canonical chainable factory`
  // for the contract. ctx tracks mutation state across the chain so
  // `.from('x').insert(payload).select().single()` returns a synthesized row
  // instead of null — the canonical API-route pattern (issue #1396).
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const chainable = (terminal: unknown, ctx: { hasMutation?: boolean; payload?: unknown } = {}): any =>
    new Proxy(() => terminal, {
      get: (_, prop) => {
        if (prop === "then") return (resolve: (v: unknown) => void) => resolve(terminal);
        if (prop === "insert" || prop === "update" || prop === "upsert") {
          return (payload: unknown) => chainable(terminal, { hasMutation: true, payload });
        }
        if (prop === "select") {
          // Reset terminal to seed data but PRESERVE ctx so .insert(p).select().single() carries hasMutation through.
          return () => chainable({ data: DEMO_SEED_DATA, error: null }, ctx);
        }
        if (prop === "single" || prop === "maybeSingle") {
          if (ctx.hasMutation) {
            const row = { id: `demo-${Date.now()}`, created_at: new Date().toISOString(), ...(ctx.payload as object) };
            return () => chainable({ data: row, error: null });
          }
          return () => chainable({ data: null, error: null });
        }
        return chainable(terminal, ctx);
      },
      apply: () => chainable(terminal, ctx),
    });
  const demoUser = {
    id: "demo-user-id",
    email: "demo@example.com",
    app_metadata: {},
    user_metadata: {},
    aud: "authenticated",
    created_at: new Date().toISOString(),
  };
  return {
    from: () => chainable({ data: DEMO_SEED_DATA, error: null }, {}),
    auth: new Proxy(
      {
        getUser: () =>
          Promise.resolve({ data: { user: demoUser }, error: null }),
        getSession: () =>
          Promise.resolve({
            data: { session: { user: demoUser, access_token: "demo-token", refresh_token: "demo-refresh", expires_at: Date.now() + 3600 } },
            error: null,
          }),
        signUp: () =>
          Promise.resolve({
            data: { user: demoUser, session: { access_token: "demo-token", refresh_token: "demo-refresh" } },
            error: null,
          }),
        signInWithPassword: () =>
          Promise.resolve({ data: { user: demoUser, session: { access_token: "demo-token", refresh_token: "demo-refresh" } }, error: null }),
        signOut: () => Promise.resolve({ error: null }),
        resetPasswordForEmail: () => Promise.resolve({ data: {}, error: null }),
      },
      {
        get: (target, prop) =>
          prop in target
            ? target[prop as keyof typeof target]
            : () => Promise.resolve({ data: {}, error: null }),
      }
    ),
    rpc: () => chainable({ data: null, error: null }),
  } as unknown as ReturnType<typeof createServerClient>;
}

// Issue #1170 follow-up: server-side warn-once shares the same flag as client.
// (See `_supabasePlaceholderWarned` and `_warnSupabasePlaceholder` defined alongside
// `createClient()` in supabase.ts. In `supabase-server.ts` they are a parallel pair.)
let _supabaseServerPlaceholderWarned = false;
function _warnSupabaseServerPlaceholder() {
  if (_supabaseServerPlaceholderWarned) return;
  const isHostingPlatform =
    process.env.VERCEL === "1" || !!process.env.RAILWAY_ENVIRONMENT_NAME;
  if (!isHostingPlatform) return;
  _supabaseServerPlaceholderWarned = true;
  console.error(
    "[supabase-server] Server Supabase placeholder fallback was hit — this deployment " +
    "is using the demo client with mocked data. Set NEXT_PUBLIC_SUPABASE_URL and " +
    "NEXT_PUBLIC_SUPABASE_ANON_KEY in your hosting platform (Vercel Supabase " +
    "Integration auto-injects these) to use a real Supabase project."
  );
}

export async function createServerSupabaseClient() {
  if (process.env.DEMO_MODE === "true" && process.env.VERCEL === "1") {
    throw new Error("DEMO_MODE is not allowed in production");
  }
  // Issue #1145: also fall back to the demo client when env vars are missing or set to
  // the canonical placeholder. Prevents server-side requests from hitting placeholder
  // DNS in unconfigured deployments.
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL || "";
  const anon = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || "";
  const isPlaceholder = !url || !anon || url === "https://placeholder.supabase.co";
  if (isPlaceholder && process.env.DEMO_MODE !== "true") _warnSupabaseServerPlaceholder();
  if (process.env.DEMO_MODE === "true" || isPlaceholder) return createDemoClient();
  const cookieStore = await cookies();

  return createServerClient(
    url || "https://placeholder.supabase.co",
    anon || "placeholder-anon-key",
    {
      cookies: {
        getAll() {
          return cookieStore.getAll();
        },
        setAll(cookiesToSet) {
          cookiesToSet.forEach(({ name, value, options }) => {
            cookieStore.set(name, value, options);
          });
        },
      },
    }
  );
}

export function createServiceRoleClient() {
  if (process.env.DEMO_MODE === "true" && process.env.VERCEL === "1") {
    throw new Error("DEMO_MODE is not allowed in production");
  }
  if (process.env.DEMO_MODE === "true") return createDemoClient();
  const serviceRoleKey = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!serviceRoleKey) throw new Error("SUPABASE_SERVICE_ROLE_KEY is not configured");
  return createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL || "https://placeholder.supabase.co",
    serviceRoleKey
  );
}
```
- `createServerSupabaseClient()`: Use in API route handlers for user-scoped operations — enforces RLS via cookie-based auth
- `createServiceRoleClient()`: Use for admin API routes and webhook handlers that need to bypass RLS (e.g., updating payment status from Stripe webhook). Never use in client-side code or expose the key to the browser. Auto-injected by the Supabase Vercel Integration and /deploy provisioning — only set manually if using a non-Vercel hosting provider.
- Import `cookies` from `next/headers` (server-only)

### Two server-side modes: cookie-authed vs token-authed

`createServerSupabaseClient()` reads auth from cookies. Use it ONLY when the calling page/route requires the user to be logged in (cookie session present).

When a route is called from an anonymous flow that authorizes via a token in the URL or request body — e.g.:

- `/quote/[token]` → POST `/api/checkout`
- `/invite/[token]` → POST `/api/invite/accept`
- `/share/[token]` → GET `/api/share/data`
- `/reset/[token]` → POST `/api/auth/reset-confirm`

…the cookie-auth client returns no rows even when the underlying row exists, because RLS evaluates `auth.uid()` as NULL.

| Mode | Auth source | Client | RLS posture |
|---|---|---|---|
| Cookie-authed user | Supabase auth cookies | `createServerSupabaseClient()` | per-user RLS (`auth.uid()`) |
| Token-authed flow | Token in URL/body | `createServiceRoleClient()` | RLS bypassed; **app code MUST validate the token** |

DO NOT relax RLS to allow `anon SELECT` on token-authorized tables — that opens row enumeration / token-bypass attacks (an attacker can scan IDs without a valid token). Use the service-role client and validate the token in application code instead:

```ts
// src/app/api/checkout/route.ts — token-authed canonical pattern
import { NextResponse } from "next/server";
import { createServiceRoleClient } from "@/lib/supabase-server";

export async function POST(req: Request) {
  const { token } = await req.json();
  if (typeof token !== "string" || token.length < 16) {
    return NextResponse.json({ error: "invalid token" }, { status: 400 });
  }

  // Service-role client bypasses RLS; the token is the authorization.
  const supabase = createServiceRoleClient();
  const { data: quote, error } = await supabase
    .from("quotes")
    .select("id, amount_cents, status, token_expires_at")
    .eq("token", token)
    .single();

  if (error || !quote) {
    return NextResponse.json({ error: "not found" }, { status: 404 });
  }
  if (quote.token_expires_at && new Date(quote.token_expires_at) < new Date()) {
    return NextResponse.json({ error: "token expired" }, { status: 410 });
  }
  if (quote.status !== "signed") {
    return NextResponse.json({ error: "not payable" }, { status: 409 });
  }

  // … proceed with state-transition guards + payment-provider checkout creation.
  return NextResponse.json({ ok: true, amount_cents: quote.amount_cents });
}
```

When the token-authorized table holds state-machine financial state (status / amount columns), the table's write policies MUST also be service-role-only (see `### When a table holds state-machine financial state, write policies must be service-role-only` below). The two patterns are complementary: token-auth handles the read path; service-role-only writes block the client-side mutation path.

### `scripts/auto-migrate.mjs`

Runs as the `prebuild` script before every `npm run build`. Applies SQL migrations from `supabase/migrations/` in order, tracking applied migrations in an `_auto_migrations` table.

```js
import nextEnv from "@next/env";
import pg from "pg";
import { readdir, readFile } from "fs/promises";
import { join } from "path";

// .mjs (raw Node ESM) requires DEFAULT-import + destructure for @next/env. The
// named-import form fails here under Node 22 with `SyntaxError: Named export
// 'loadEnvConfig' not found` because Node's CJS named-export detection does not
// surface this package's exports. .ts files loaded by Playwright/jest/tsx
// (CJS-transpile via pirates) require the OPPOSITE shape — see the
// "CJS-interop with @next/env" Stack Knowledge entry in the analytics stack
// file for the per-loader contract and an empirical verification snippet.
const { loadEnvConfig } = nextEnv;

loadEnvConfig(process.cwd());

const connectionString = process.env.POSTGRES_URL_NON_POOLING;
if (!connectionString) process.exit(0); // No database URL — skip silently (local dev, CI)

const client = new pg.Client({ connectionString });
await client.connect();

await client.query(`
  CREATE TABLE IF NOT EXISTS _auto_migrations (
    name TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ DEFAULT now()
  )
`);

const { rows: applied } = await client.query("SELECT name FROM _auto_migrations");
const appliedSet = new Set(applied.map((r) => r.name));

const migrationsDir = join(process.cwd(), "supabase", "migrations");
let files;
try {
  files = (await readdir(migrationsDir)).filter((f) => f.endsWith(".sql")).sort();
} catch {
  await client.end();
  process.exit(0); // No migrations directory — skip
}

for (const file of files) {
  if (appliedSet.has(file)) continue;
  const sql = await readFile(join(migrationsDir, file), "utf8");
  await client.query(sql);
  await client.query("INSERT INTO _auto_migrations (name) VALUES ($1)", [file]);
  console.log(`Applied migration: ${file}`);
}

await client.end();
```

## Environment Variables
```
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your-publishable-api-key
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
```

> **Note:** `NEXT_PUBLIC_SUPABASE_ANON_KEY` keeps its name for SDK compatibility, but in the Supabase Dashboard this is called **Publishable Key** (Project Home → Data API popup). New keys start with `sb_publishable_`.

> **Note:** `SUPABASE_SERVICE_ROLE_KEY` is auto-injected by the Supabase Vercel Integration and by `/deploy` provisioning. Only set manually if using a non-Vercel hosting provider. Find it at: Supabase Dashboard → Settings → API → Service Role Key.

## Schema Management
- SQL migrations go in `supabase/migrations/` as numbered files (`001_initial.sql`, `002_feature.sql`, etc.)
- Use `CREATE TABLE IF NOT EXISTS` for tables and `DROP POLICY IF EXISTS ... ; CREATE POLICY ...` for RLS policies (safe to re-run — `CREATE POLICY IF NOT EXISTS` is not valid PostgreSQL). Bare `CREATE POLICY` without a preceding `DROP POLICY IF EXISTS` is NOT idempotent: both `supabase db push` and the `prebuild` auto-migrate runner attempt to apply migrations, and re-applying a non-idempotent policy file raises `policy "X" for table "Y" already exists` and fails the build. The Provisioning seeding step (below) mitigates this on first deploy, but migrations MUST still follow the idempotent pattern to survive any tracker desync.
- Every table must have:
  - `id uuid DEFAULT gen_random_uuid() PRIMARY KEY`
  - `created_at timestamptz DEFAULT now()`
- User-owned tables must have:
  - `user_id uuid REFERENCES auth.users(id) NOT NULL`
- `ALTER TABLE ... ENABLE ROW LEVEL SECURITY` on every table
- RLS policies (default `_own` pattern — appropriate for user-owned content like profiles, journals, notes):
  - SELECT: `USING (auth.uid() = user_id)`
  - INSERT: `WITH CHECK (auth.uid() = user_id)`
  - UPDATE: `USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id)` — the WITH CHECK clause prevents a user from changing `user_id` to another user's ID (privilege escalation via `UPDATE SET user_id = ...`)
  - DELETE: `USING (auth.uid() = user_id)`

### When a table holds state-machine financial state, write policies must be service-role-only

The default `_own` RLS pattern above is the WRONG default for tables whose status / amount / timestamp columns are mutated ONLY by server-side flows (admin signature route, payment-webhook handler, milestone-approve route with state-transition guards). The `_update_own` policy on these tables lets authenticated clients UPDATE every column of their own row directly via the Supabase JS client from the browser console, bypassing every server-side guard:

```js
// Concrete exploit (browser console after admin signs the $25,000 quote):
await supabase.from('quotes').update({ amount_cents: 100 }).eq('id', '<their-quote-id>');
// Then click "Pay 50% deposit" on /quote/[token]
// /api/checkout reads the tampered row, creates a payment session for $0.50.
```

The studio is contractually committed to deliver $25k of work for 50 cents. Application-layer `.eq('user_id', user.id)` filters do NOT compensate — UPDATE policies on financial columns leak directly to PostgREST; the application code never sees the request.

#### Decision tree: do my tables need service-role-only writes?

Walk this top-down. STOP at the first YES — that table needs service-role-only writes.

1. **Step 1 — lexical pre-filter (catches common cases).** Does this table have ANY column whose name matches one of:
   - Money: `amount_cents`, `amount`, `balance`, `subtotal`, `total`, `price`, `fee`, `payout`, `refund`
   - State machines: `status`, `state`, `lifecycle`, `phase`, `stage`, `step`
   - Server-only timestamps: `paid_at`, `signed_at`, `approved_at`, `released_at`, `webhook_received_at`
2. **Step 2 — invariant question (catches domain-specific names).** Does ANY column on this table get mutated by application logic that the user must NOT bypass — e.g., a state-transition guard, a webhook write, an admin signature, a Stripe sync?
   - Examples that the lexical filter misses but this question catches: `escrow_balance`, `workflow_step`, `commitment_value`, `sla_window_close`.

YES on either step → service-role-only writes. The lexical filter is a reading aid for common cases; the invariant question is the authoritative test.

#### Service-role-only RLS template

```sql
ALTER TABLE quotes ENABLE ROW LEVEL SECURITY;

-- Owners may read their own row (RLS still gates SELECT).
DROP POLICY IF EXISTS "quotes_select_own" ON quotes;
CREATE POLICY "quotes_select_own" ON quotes
  FOR SELECT USING (auth.uid() = user_id);

-- NO INSERT / UPDATE / DELETE policies for clients.
-- The absence of these policies means PostgREST returns 401 / 403 on any
-- client-issued INSERT / UPDATE / DELETE. Server-side flows use the
-- service-role client which bypasses RLS entirely.
```

The route that performs the legitimate write uses `createServiceRoleClient()` and applies the state-transition guard in application code:

```ts
// src/app/api/quote/sign/route.ts — server-only mutation path
const supabase = createServiceRoleClient();
const { data: row } = await supabase
  .from("quotes")
  .select("id, status, amount_cents")
  .eq("id", quoteId)
  .single();
if (row.status !== "draft") return NextResponse.json({ error: "not draftable" }, { status: 409 });
await supabase
  .from("quotes")
  .update({ status: "signed", signed_at: new Date().toISOString() })
  .eq("id", quoteId);
```

Existing user-owned tables (profiles, journals, notes) keep the default `_own` pattern above. Only state-machine financial tables get the service-role-only treatment.

- Add SQL comments explaining each table's purpose
- Migrations are applied automatically during Vercel builds via the `prebuild` script (when `POSTGRES_URL_NON_POOLING` is set by the Supabase Vercel Integration). They are also applied by CI on merge to `main` (via `supabase db push` if CI secrets are configured). For manual use: `make migrate`. Fallback: copy SQL into Supabase Dashboard → SQL Editor.

## Local Development (when `stack.testing` is present)

When the project has `stack.testing` configured, E2E tests run against a **local** Supabase instance instead of the remote project. This keeps tests isolated, fast, and secret-free.

- `supabase init` creates `supabase/config.toml` (commit this file — it configures the local instance)
- `supabase start` starts local Postgres + Auth + API (requires Docker Desktop)
- `supabase db reset` applies all migrations from `supabase/migrations/`
- `supabase stop` shuts down the local instance

## Remote Migration (Production)

Migrations are pushed to the remote Supabase database using `supabase db push`. This happens automatically in CI on merge to `main`, or manually via `make migrate`.

### One-time setup (local `make migrate`)
1. Run `npx supabase login` to authenticate the CLI
2. Run `npx supabase link --project-ref <ref>` to link to your remote project
   - Find your project ref: Supabase Dashboard → Settings → General → Reference ID
3. Set `SUPABASE_DB_PASSWORD` in your shell: `export SUPABASE_DB_PASSWORD=your-password`
   - Find it: Supabase Dashboard → Settings → Database → Database password
4. Run `make migrate`

### One-time setup (CI auto-migration)
Add three GitHub repository secrets (repo → Settings → Secrets and variables → Actions):
| Secret | Where to find it |
|--------|-----------------|
| `SUPABASE_PROJECT_REF` | Supabase Dashboard → Settings → General → Reference ID |
| `SUPABASE_DB_PASSWORD` | Supabase Dashboard → Settings → Database → Database password |
| `SUPABASE_ACCESS_TOKEN` | [supabase.com/dashboard/account/tokens](https://supabase.com/dashboard/account/tokens) → Generate new token |

## CLI Project Creation (Non-Interactive)

Used by the `/deploy` skill for automated Supabase setup.

### Organization Discovery
- `supabase orgs list -o json` — returns `[{"id": "...", "name": "..."}]`

### Project Creation
- `supabase projects create <name> --org-id <id> --region <region> --db-password <pw_raw>`
- Generate the raw password once, then keep two forms — the CLI accepts the raw value, the connection URL needs URL-encoding:
  ```bash
  PASSWORD_RAW="$(openssl rand -base64 24)"
  PASSWORD_ENC="$(python3 -c "import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=''))" "$PASSWORD_RAW")"
  ```
  Base64 output can contain `/`, `+`, and `=`, which are reserved in the userinfo URI component (RFC 3986). Embedding `PASSWORD_RAW` into a `postgresql://` URL is a footgun — use `PASSWORD_ENC` at every URL assembly site.
- Pass `PASSWORD_RAW` to the CLI (`--db-password "$PASSWORD_RAW"`).
- Project takes ~60s to initialize after creation

### Readiness Polling
- `supabase projects api-keys --project-ref <ref> -o json`
- Poll every 5s, max 12 attempts (60s total)
- Returns: `[{"name": "anon", "api_key": "..."}, {"name": "service_role", "api_key": "..."}]`

### URL/Connection String Construction
- URL: `https://<ref>.supabase.co`
- DB (non-pooling): Discover the pooler host via the Management API:
  ```bash
  curl -s "https://api.supabase.com/v1/projects/<ref>/config/database/pooler" \
    -H "Authorization: Bearer <access-token>"
  ```
  Use the `host` from the response with port `5432` (session mode = direct connection). Substitute the URL-encoded password (`PASSWORD_ENC` from Project Creation — NEVER the raw base64 value):
  `postgresql://postgres.<ref>:${PASSWORD_ENC}@<pooler-host>:5432/postgres`

## Auto-Migration on Vercel Build

When deployed via the Supabase Vercel Integration, migrations are applied automatically during every Vercel build via a `prebuild` script (`scripts/auto-migrate.mjs`). No additional configuration needed.

### How it works
- `package.json` has `"prebuild": "node scripts/auto-migrate.mjs"`
- npm runs `prebuild` before every `build` (including on Vercel)
- The script connects using `POSTGRES_URL_NON_POOLING` (injected by the Integration)
- Applies all SQL files from `supabase/migrations/` in order
- Tracks applied migrations in `_auto_migrations` table to avoid re-running
- If `POSTGRES_URL_NON_POOLING` is not set (local dev, CI), exits silently

### Coexistence with CI migrate and supabase db push
- Auto-migrate tracks in `_auto_migrations`; `supabase db push` tracks in `supabase_migrations.schema_migrations`
- Independent tracking, no conflict — migrations are idempotent (`IF NOT EXISTS`)
- Both can be active safely; CI migrate provides a fallback for non-Vercel deployments

### Local keys

These keys are generated by the local Supabase instance. On CLI versions before v2.76, they are deterministic JWT tokens. On v2.76+, they use the `sb_publishable_*`/`sb_secret_*` format and may vary across installs. The testing stack reads keys dynamically from `supabase status -o json` — hardcoding is no longer necessary.

- **URL:** `http://127.0.0.1:54321`
- **Legacy anon key (CLI <v2.76):** `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZS1kZW1vIiwicm9sZSI6ImFub24iLCJleHAiOjE5ODM4MTI5OTZ9.CRXP1A7WOeoJeXxjNni43kdQwgnWNReilDMblYTn_I0`
- **Legacy service role key (CLI <v2.76):** `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZS1kZW1vIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImV4cCI6MTk4MzgxMjk5Nn0.EGIM96RAZx35lJzdJsyH-qQwv8Hdp7fsn3W0YpN81IU`

## Types
- Create TypeScript types matching table schemas in `src/lib/types.ts`

## Production Observability

When `NEXT_PUBLIC_SUPABASE_URL` / `NEXT_PUBLIC_SUPABASE_ANON_KEY` are missing or match the canonical placeholder defaults (`https://placeholder.supabase.co` / `placeholder-anon-key`), `createClient()` and `createServerSupabaseClient()` fall back to a demo client that returns mocked seed data. The fallback was introduced in `#1145` to prevent production builds from attempting `placeholder.supabase.co` DNS lookups, but its silent-routing nature can hide a misconfigured production deploy until users complain about empty data.

**Fail-loud mechanism (issue #1170 follow-up):** the placeholder branch in each factory function calls a `_warnSupabasePlaceholder` once-flag helper that emits `console.error` when:
- Client (`createClient`): hostname is NOT localhost / `127.0.0.1` / `0.0.0.0` / `[::1]` / `*.local`.
- Server (`createServerSupabaseClient`): `process.env.VERCEL === "1"` OR `process.env.RAILWAY_ENVIRONMENT_NAME` is set.

The warning is one-time per module instance to avoid log spam. The demo-client routing itself is unchanged — operators see "demo client was hit" diagnostics in production logs without losing the dev-mode safety of `#1145`.

The recommended fix path is the [Supabase Vercel Integration](https://vercel.com/integrations/supabase), which auto-injects `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, and the server-only env vars in one click. See `## Provisioning` and `## CLI Project Creation (Non-Interactive)` for setup.

## Security
- Never expose `service_role` key to the client — use `createServiceRoleClient()` only in server-side API routes and webhook handlers
- Always use RLS — never trust the client
- Use the server client (`supabase-server.ts`) in all API route handlers
- When `stack.auth` is present, add `.eq("user_id", user.id)` to all user-scoped queries in API routes for defense-in-depth. Do not rely solely on RLS — the application-layer filter prevents IDOR if RLS policies are misconfigured or when the service role client is used for non-admin operations.
- Never use string-interpolated `.or()` filters with user-supplied data (e.g., `.or(\`col.eq.${value}\`)`). This creates a PostgREST filter injection vector. Instead, use separate parameterized `.eq()` calls or split into two sequential queries — PostgREST only parameterizes individual filter methods, not the `.or()` string.
- Never hardcode a `role` field in `.upsert()` calls (e.g., `.upsert({ role: 'client', ... })`). If an admin has promoted a user, the upsert silently reverts their role. Use a check-then-insert/update pattern: query the existing record first, and only set `role` on initial insert (not on update).
- Always use explicit column lists in `.select()` (e.g., `.select('id, name, email, created_at')`) instead of `.select()` or `.select('*')`. Bare select returns all columns, including sensitive fields (Stripe IDs, admin-only pricing, internal status). RLS controls row access but not column access — explicit column lists are the only defense against field leakage in user-facing queries.
- Never use `WITH CHECK (true)` on INSERT policies — this allows any authenticated (or even unauthenticated) user to insert rows into the table regardless of identity. Use `WITH CHECK (auth.uid() = user_id)` for user-scoped inserts, or `WITH CHECK (auth.role() = 'service_role')` for tables that should only be written by backend/webhook handlers. A permissive INSERT check combined with a restrictive SELECT policy gives false confidence that data is protected.
- When a table has a `role` column that must not be self-modifiable, the UPDATE policy must include a `WITH CHECK` clause that prevents users from changing their own role. Without this, users can self-escalate to any role by sending an UPDATE with `role = 'admin'`. Example: `CREATE POLICY "update own profile (no role escalation)" ON users FOR UPDATE USING (auth.uid() = id) WITH CHECK (auth.uid() = id AND role = (SELECT role FROM users WHERE id = auth.uid()));`
- When a profile/user table accumulates **multiple** server-managed columns (plan_tier, trial_ends_at, activated_at, retention_milestone_fired_at, first_content_approved_at, billing status, quota counters), the single-column `WITH CHECK (col = (SELECT col FROM ...))` pattern above does not scale — each additional column extends the chain and requires editing the RLS policy. Prefer column-level `REVOKE UPDATE` alongside the row-level RLS policy:

  ```sql
  -- Keep the row-level RLS policy for access control:
  CREATE POLICY "profiles_update_own" ON profiles
    FOR UPDATE USING (auth.uid() = id) WITH CHECK (auth.uid() = id);

  -- Then structurally prevent writes to server-managed columns:
  REVOKE UPDATE (plan_tier, trial_ends_at, activated_at, /* ...other server columns */ )
    ON profiles FROM authenticated;
  ```

  PostgREST honours column privileges: any PATCH from a user JWT that touches a revoked column returns 403, regardless of the RLS policy. The service-role client (Stripe webhooks, cron, ops scripts) bypasses the REVOKE via default grants. This scales linearly with the column list, doesn't require editing RLS policies as columns are added, and makes server-managed-ness explicit in the migration diff.

  **When widening a CHECK constraint on a server-managed column** (e.g., adding a new plan tier to an existing enum), audit whether the old CHECK was the only thing preventing self-escalation. If yes, add the column to the REVOKE list in the same migration.

- When a Supabase operation fails in an API route, log the raw error server-side (`console.error`) and return a generic message to the client. Postgres errors include internal schema details (table names, constraint names, RLS policy names) that reveal database structure to attackers (OWASP A4-InfoLeakage). See `## Stack Knowledge` → "When catching Supabase errors in API routes" for the canonical pattern.

## Patterns
- Browser client (`supabase.ts`) for client-side components
- Server client (`createServerSupabaseClient()`) for user-scoped API routes — enforces RLS via cookie-based auth
- Service role client (`createServiceRoleClient()`) for admin API routes and webhook handlers that bypass RLS (e.g., updating payment status from Stripe webhook)
- When creating a new migration, use the next sequential number after existing migrations. Note: concurrent branches may create conflicting numbers (e.g., two branches both create `002_*.sql`) — resolve by renumbering the later-merged migration at merge time. This is acceptable for MVP workflows.
- **Mutation routes on state-machine tables SELECT the status column by default.** For any mutation route (`POST /api/<entity>/<action>`, `PATCH /api/<entity>/[id]/<action>`) targeting a table with a `status` column whose values form a DAG of allowed transitions, the SELECT that precedes the mutation MUST include `status` so the state-transition guard (see `.claude/procedures/wire.md` Step 5) can return 409 when `current_status !== expected_pre_state`. The default SELECT shape is `select("id, status, <other-fields-needed>")` — omitting `status` is the class of defect surfaced by #1062 (tests failed with 500 instead of 409 because the route never read current state).

## Stack Knowledge

### When catching Supabase errors in API routes
Return a generic message to the client and log the raw error server-side. Supabase errors include internal Postgres details — table names, constraint names, RLS policy names — that reveal database schema and access-control structure to attackers (OWASP A4-InfoLeakage). The pattern:

```typescript
const { data, error } = await supabase.from("tasks").insert(input);
if (error) {
  console.error("[tasks] Supabase error:", error);
  return NextResponse.json({ error: "Failed to create task" }, { status: 500 });
}
return NextResponse.json({ data });
```

Never do: `return NextResponse.json({ error: error.message }, { status: 500 })` — this forwards the raw Postgres error string (e.g., `new row violates row-level security policy "tasks_insert_own"`) which leaks both the table identity and the policy identity to the caller.

For `ZodError` validation failures the same principle applies — see your framework stack file (`.claude/stacks/framework/<value>.md` "When catching ZodError" / API Route Conventions). Stack-level rule of thumb: every `if (error)` branch in an API route handler MUST log the raw error and return a generic message. The server-side log retains the full diagnostic; the client receives only the failure category.

### Demo mode returns generic seed data, not schema-specific data
The demo client (`createDemoClient()`) returns `DEMO_SEED_DATA` — 3 generic rows with `id`, `name`, `status`, `created_at`, `user_id` fields — for all `.from().select()` calls. Pages that destructure schema-specific fields (e.g., `row.amount`, `row.description`) will get `undefined` in demo mode. This is intentional: the demo client cannot know the real schema at template time.

**Mitigation for page authors:** When rendering data from Supabase queries, use optional chaining or defaults for schema-specific fields: `row.amount ?? 0`, `row.description ?? ""`. The generic fields (`id`, `name`, `status`, `created_at`) are always present in demo data.

### Single-row queries return null in demo mode (read paths)
The chainable proxy's `.single()` and `.maybeSingle()` methods return `{ data: null, error: null }` on read chains (`.from("table").select().eq(...).single()`) — not a row from `DEMO_SEED_DATA`. Pages that read by-id and expect a non-null result should handle the null case (loading state or fallback UI). For `.maybeSingle()`, this matches real Supabase behavior when zero rows match the filter; for `.single()`, real Supabase returns a `PGRST116` error on zero rows while the demo client returns `error:null` (a pre-existing simplification — pages that branch on `error.code === "PGRST116"` will not exercise that branch in demo mode).

### Mutation chains synthesize a row in demo mode (write paths) — issue #1396

When the chain is a mutation (`.from("table").insert(payload).select().single()` or `.update(payload)`/`.upsert(payload)`), `.single()` and `.maybeSingle()` return `{ data: <synthesized row>, error: null }`. The synthesized row is `{ id: \`demo-${Date.now()}\`, created_at: <iso>, ...payload }`. This unblocks the canonical API-route pattern:

```ts
const { data, error } = await supabase.from("orders").insert(payload).select().single();
if (error || !data) return NextResponse.json({ error: "failed" }, { status: 500 });
await trackServerEvent("result_view", userId, { ... });
return NextResponse.json(data);
```

Before this fix, DEMO_MODE returned `{data: null}` on every insert chain → the `!data` guard fired, the route returned 500, `trackServerEvent` was never reached, and every mutation-path funnel event was missing in `/verify`'s behavior-verifier walks. The mutation-aware factory in `## Stack Knowledge > Canonical chainable factory (mutation-aware)` keeps read-path nulls (preserves #1178's `.maybeSingle` contract) while round-tripping the inserted payload on write chains.

### Canonical chainable factory (mutation-aware)

The chainable factory shape MUST be identical between `src/lib/supabase.ts` (browser) and `src/lib/supabase-server.ts` (server). Both copies carry the `// CANONICAL chainable factory — keep this body in sync with src/lib/supabase-server.ts` (or `supabase.ts`) marker comment. Auth-only clients (`src/lib/supabase-auth.ts`, `src/lib/supabase-auth-server.ts` — only emitted when `stack.database` is NOT supabase) do NOT carry a chainable factory: those clients only mock `auth.*` methods, never `.from()`.

The two live copies share this body:

```ts
const chainable = (terminal: unknown, ctx: { hasMutation?: boolean; payload?: unknown } = {}): any =>
  new Proxy(() => terminal, {
    get: (_, prop) => {
      if (prop === "then") return (resolve: (v: unknown) => void) => resolve(terminal);
      if (prop === "insert" || prop === "update" || prop === "upsert") {
        return (payload: unknown) => chainable(terminal, { hasMutation: true, payload });
      }
      if (prop === "select") {
        // Reset terminal to seed data, preserve ctx so insert(p).select().single() carries hasMutation through.
        return () => chainable({ data: DEMO_SEED_DATA, error: null }, ctx);
      }
      if (prop === "single" || prop === "maybeSingle") {
        if (ctx.hasMutation) {
          const row = { id: `demo-${Date.now()}`, created_at: new Date().toISOString(), ...(ctx.payload as object) };
          return () => chainable({ data: row, error: null });
        }
        return () => chainable({ data: null, error: null });
      }
      return chainable(terminal, ctx);
    },
    apply: () => chainable(terminal, ctx),
  });
```

When updating the factory (e.g., adding a new chained terminal method like `.csv()` or `.geojson()`), update BOTH copies in the same PR. Drift between the two breaks DEMO_MODE behavior in either client-only or server-only routes.

### When migrations declare CREATE [UNIQUE] INDEX on (timestamptz_col::date), wrap in `AT TIME ZONE 'UTC'` to keep the expression IMMUTABLE

PostgreSQL rejects `(<col>::date)` inside `CREATE [UNIQUE] INDEX` expressions when `<col>` is `timestamptz`, because the cast is STABLE (depends on the session's `TimeZone`), not IMMUTABLE. Postgres requires IMMUTABLE expressions in indexes. Symptom at `supabase db push` / `make migrate`:

```
ERROR: functions in index expression must be marked IMMUTABLE (SQLSTATE 42P17)
```

**Anti-pattern:** vitest does not apply migrations against a real Postgres in the default mvp-template test setup — the bug only surfaces at `/deploy` time, by which point the failing migration has likely already been merged.

```sql
-- WRONG — STABLE cast, fails at db push with 42P17
CREATE UNIQUE INDEX leads_email_per_day
  ON leads(email, (created_at::date));

-- CORRECT — explicit UTC anchor makes the expression IMMUTABLE
DROP INDEX IF EXISTS leads_email_per_day;
CREATE UNIQUE INDEX leads_email_per_day
  ON leads(email, ((created_at AT TIME ZONE 'UTC')::date));
```

UTC is the right anchor because `now()` returns UTC `timestamptz` and dedupe is consistent regardless of session timezone. Pair with `DROP INDEX IF EXISTS <name>;` before the `CREATE` so a pre-existing broken-expression index is replaced rather than silently kept. The same trap applies to other STABLE timestamptz operations inside index expressions (e.g., `date_trunc('day', timestamptz_col)` without a UTC anchor).

`composite_identity:`
- `root_cause_class: stable-expression-in-unique-index`
- `divergence_pattern: sql-immutability-violation`
- `stack_scope: database/supabase`
- `maturity: canonical`
- `anti_pattern: true`

### When a table uses share/invite tokens for anonymous access, do NOT add `USING (TRUE)` SELECT policies

```yaml
id: supabase-rls-using-true-token-authed
maturity: raw
anti_pattern: false
composite_identity:
  root_cause_class: rls-policy-overly-permissive-on-token-authed-table
  divergence_pattern: USING-true-instead-of-service-role-client
  stack_scope: database/supabase
composite_identity_hash: 05e3bdde373d
symptom_keywords: [supabase, rls, USING-true, share-token, intake_forms, token-auth, anon-select, row-enumeration]
fix_template: |
  Drop the `USING (TRUE)` SELECT policy. Use `createServiceRoleClient()` in
  the API route to bypass RLS for the token lookup; validate token length +
  match + expiry + status in app code. See "Two server-side modes" section.
prevention_mechanism: stack-knowledge-anti-pattern-guidance
confidence_score: 0.9
occurrence_count: 1
linked_issues: [1346]
first_seen: 2026-05-10
last_seen: 2026-05-10
graduated_to: null
```

A `USING (TRUE)` SELECT policy grants unrestricted read access to every row in the table — defeating RLS. The `intake_forms` policy removed during PR-E1 (security-fixer fix_id `security-fixer:verify-2026-05-07T20:02:24Z:0`) was added under the mistaken intuition that "anonymous users need to fetch by token, so RLS must allow public SELECT." The correct pattern is the **service-role client + token validation** flow already documented at [`### Two server-side modes: cookie-authed vs token-authed`](#two-server-side-modes-cookie-authed-vs-token-authed): the route handler imports `createServiceRoleClient()` (RLS bypassed), validates the token in application code (length, equality, expiry, status), and returns 404 on miss. RLS stays restrictive; the token is the authorization.

```sql
-- WRONG — opens row enumeration / token-bypass attacks. An attacker can scan
-- IDs (or any indexed column) without ever knowing a valid token.
CREATE POLICY "intake_forms_public_read" ON intake_forms
  FOR SELECT USING (TRUE);

-- RIGHT — keep RLS restrictive (no SELECT policy for anon at all). API route
-- handles the lookup via createServiceRoleClient() with token validation
-- (see "Two server-side modes" section above for the canonical pattern).
```

The same warning applies to `WITH CHECK (TRUE)` on INSERT policies — see the existing Security bullet (`Never use WITH CHECK (true) on INSERT policies`) in the Security section. Both forms grant unconditional access.

### When `npm run dev` fails with `TypeError: Failed to fetch` in demo mode
Client-side Supabase needs `NEXT_PUBLIC_DEMO_MODE=true` in addition to server-side `DEMO_MODE=true`. Always set both together:

```bash
DEMO_MODE=true NEXT_PUBLIC_DEMO_MODE=true npm run dev
```

The server-side guard reads `process.env.DEMO_MODE`; the browser bundle reads `process.env.NEXT_PUBLIC_DEMO_MODE` (Next.js only exposes env vars with the `NEXT_PUBLIC_` prefix to client code). If only `DEMO_MODE` is set, the server renders the demo shell but the browser falls through to a real Supabase client using placeholder URLs → `TypeError: Failed to fetch` on every auth/data call.

For developers who want persistent local-dev demo mode without prefixing every command, add BOTH lines to `.env.local`:

```bash
DEMO_MODE=true
NEXT_PUBLIC_DEMO_MODE=true
```

`.env.local` is gitignored and never committed. **Never** add `DEMO_MODE` or `NEXT_PUBLIC_DEMO_MODE` to `.env.example` — these are local-only flags and must not leak into production configs (production protection is enforced by the `VERCEL === "1"` guard in `createBrowserClient()` / `createServerClient()` — see the code templates above).

### When a project stores a plan_tier DB column or enum that maps to UI display names

Applies regardless of `stack.payment` — plan_tier can exist without a payment integration (feature-gating, trial management, internal role tiers). When the DB stores a short machine key (`starter | growth | enterprise`) and the UI renders a capitalized or rebranded label (`Studio | Agency | Enterprise`), inline `capitalize(rawKey)` or ternary chains at each callsite produce drift: one component renders `Growth`, another renders `growth`, a third renders `$149`. Tier renames (a common early-MVP event) then require hunting down every callsite.

**Pattern:** Create a single `getTierDisplayName(tier: PlanTier): string` helper (and any other per-tier formatters — description, CTA copy, aria-label) and import it at every callsite. Colocate with `PLAN_PRICES` when that constant already exists (`stack.payment: stripe` projects define it in `.claude/stacks/payment/stripe.md`'s target file — typically `src/lib/plan.ts` or `src/lib/pricing.ts`). When `stack.payment` is absent, create `src/lib/plan.ts` and put the helper there alongside the `PlanTier` type.

```ts
// src/lib/plan.ts — colocated with PLAN_PRICES when it exists
export type PlanTier = "starter" | "growth" | "enterprise";

export function getTierDisplayName(tier: PlanTier): string {
  const labels: Record<PlanTier, string> = {
    starter: "Studio",
    growth: "Agency",
    enterprise: "Enterprise",
  };
  return labels[tier];
}
```

All components — dashboard cards, billing pages, upgrade CTAs, aria-labels — must import from this one file. Do NOT call `capitalize()` on the raw enum key; do NOT write inline `tier === "growth" ? "Growth" : ...` chains.

Tier renames now require a one-line change in one file. Type-checking catches unknown tier values at compile time. When `stack.payment: stripe` is added later, migrate the helper to the same file as `PLAN_PRICES` — the import path stays stable if you keep the module path.

```yaml
id: supabase-demo-client-maybesingle-alias
maturity: raw
anti_pattern: false
composite_identity:
  root_cause_class: demo-client proxy missing API method alias
  divergence_pattern: alias-handler-absent
  stack_scope: database/supabase
composite_identity_hash: 4400992b48ea
symptom_keywords: [maybeSingle, demo-mode, 404, chainable, proxy, supabase, single-row]
fix_template: |
  When real Supabase exposes paired terminal methods with identical zero-row
  semantics (.single() / .maybeSingle()), the demo-client chainable Proxy must
  intercept BOTH props — not just one. Pattern:
    get: (_, prop) => {
      if (prop === "then") return (resolve) => resolve(terminal);
      if (prop === "single") return () => chainable({ data: null, error: null });
      if (prop === "maybeSingle") return () => chainable({ data: null, error: null });
      return chainable(terminal);
    }
  Without the maybeSingle handler, .from(...).select().eq(...).maybeSingle()
  falls through to the seed-row array terminal, breaking page null-coalescing
  logic and rendering 404 in DEMO_MODE on dynamic-segment routes.
prevention_mechanism: TEMPLATE.md canonical proxy pattern teaches both handlers; consolidated Stack Knowledge entry above documents both methods. Recurrence guard is documentation-quality only.
confidence_score: 0.7
occurrence_count: 1
linked_issues: [1178, 1396]
first_seen: 2026-04-30
last_seen: 2026-05-13
graduated_to: "## Stack Knowledge > Canonical chainable factory (mutation-aware)"
```

When the demo-client chainable proxy intercepts only `.single()` and not its
sibling `.maybeSingle()` (or analogous paired terminals — `.csv()/.geojson()`,
etc., when their semantics align), pages calling the unintercepted method fall
through to the array terminal and render 404 / broken state in DEMO_MODE. The
fix is to add an explicit handler for the missing method; the prevention is to
keep the canonical mutation-aware factory teaching both handlers so future
stack authors copy the both-aliases form. Superseded by the mutation-aware
canonical factory (#1396) which handles both methods + mutation-state
synthesis in one shape.

```yaml
id: supabase-error-leak-api-route
maturity: raw
anti_pattern: false
composite_identity:
  root_cause_class: API-route error response leaks raw database error
  divergence_pattern: stack-file-security-guidance-gap
  stack_scope: database/supabase
composite_identity_hash: b90753595312
symptom_keywords: [supabase, error.message, api-route, info-leakage, OWASP-A4, RLS, schema-leak, postgres]
fix_template: |
  Every if (error) branch in an API route handler that calls Supabase MUST
  log the raw error via console.error (server-side) and return a generic
  message to the client. Never forward error.message — it leaks Postgres
  internals: table names, constraint names, RLS policy names. Pattern:
    if (error) {
      console.error("[<entity>] Supabase error:", error);
      return NextResponse.json({ error: "Failed to <action>" }, { status: 500 });
    }
  This pairs with the framework-level rule for ZodError forwarding (see
  framework/nextjs.md API Route Conventions). A single shared mental model
  for every error response: log raw, return generic.
prevention_mechanism: Stack Knowledge entry above documents the pattern; pairing with framework-level ZodError rule covers both validation and database error paths. Recurrence guard is documentation-quality.
confidence_score: 0.7
occurrence_count: 1
linked_issues: [1229]
first_seen: 2026-05-01
last_seen: 2026-05-01
graduated_to: null
```

### When inserting a record derived from a related-entity lookup, carry user_id explicitly to the insert payload

When an API route reads a parent entity (spec, session, template) and then inserts a child entity derived from it, the `user_id` must be captured from the parent row at query time and included in the INSERT payload. Relying on RLS `WITH CHECK (auth.uid() = user_id)` does NOT auto-populate `user_id` — it only validates the value already present. If `user_id` is omitted from the insert, the INSERT succeeds (no constraint error) but the row has `NULL` for `user_id`. The SELECT-own policy (`USING (auth.uid() = user_id)`) then filters the row out on the very next read, appearing to the client as if the record was never created.

Pattern:

```typescript
// CORRECT — capture user_id from parent lookup, carry onto child INSERT
const { data: spec } = await supabase
  .from("specs")
  .select("user_id, ...other-fields")
  .eq("id", specId)
  .single();
if (!spec) return NextResponse.json({ error: "Spec not found" }, { status: 404 });

const userId = spec.user_id;  // capture at lookup time

const { data: quote, error } = await supabase
  .from("quotes")
  .insert({ spec_id: specId, user_id: userId, ...other-fields })  // carry onto insert
  .select()
  .single();
```

**Wrong** (silent failure):

```typescript
// WRONG — user_id omitted; INSERT succeeds with NULL but SELECT-own filters it out
const { data: quote } = await supabase
  .from("quotes")
  .insert({ spec_id: specId /* no user_id */ })
  .select()
  .single();
// Client sees quote.id, then GET /api/quotes/<id> returns 404 (RLS filtered).
```

Applies to any multi-step route that reads entity A and inserts entity B derived from A, where B has a `user_id` column with an `_own` RLS policy. The defect is silent at INSERT time and only surfaces on the next read — making it hard to diagnose without explicit tests for read-after-write across user contexts.

## PR Instructions
- When creating migrations, add to the PR body: "After merging, migrations are applied automatically during the next Vercel build (via the `prebuild` script). If not using the Supabase Vercel Integration, CI applies them on merge to `main` (requires CI secrets), or run `make migrate` manually — see Migration Setup in README."
- For the bootstrap PR, also add: "Run `/deploy` to set up Vercel + Supabase automatically, or manually add the Supabase Vercel Integration at vercel.com/integrations/supabase."

## Deploy Interface

Standardized subsections referenced by deploy.md and teardown.md. Each subsection is a self-contained recipe — deploy.md reads them by name and executes the instructions.

### Prerequisites

- **install_check:** `which supabase`
- **install_fix:** `brew install supabase/tap/supabase` (macOS/Linux) or see https://supabase.com/docs/guides/cli/getting-started
- **auth_check:** `supabase projects list`
- **auth_fix:** `supabase login`

### Config Gathering

- **Org discovery:** `supabase orgs list -o json` — returns `[{"id": "...", "name": "..."}]`
- Always prompt user for org/region selection or use Supabase CLI defaults (no experiment.yaml fields for these)

### Provisioning

1. **Check existing:** `supabase projects list -o json` — if a project with this name exists in the org, ask the user whether to reuse or create new
2. **Create project:** Generate the raw password once, then derive the URL-encoded form for connection strings (base64 output can contain `/`, `+`, `=` which are reserved in the userinfo URI component per RFC 3986 — embedding the raw value in `postgresql://` URLs produces a malformed URI that crashes pg.Client with ERR_INVALID_URL):
   ```bash
   PASSWORD_RAW="$(openssl rand -base64 24)"
   PASSWORD_ENC="$(python3 -c "import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=''))" "$PASSWORD_RAW")"
   supabase projects create <name> --org-id <org-id> --region <region> --db-password "$PASSWORD_RAW"
   ```
   Pass `PASSWORD_RAW` to the CLI (`--db-password`) and use `PASSWORD_ENC` in Step 6's `POSTGRES_URL_NON_POOLING` assembly. Do NOT embed `PASSWORD_RAW` into a connection URL.
3. **Extract ref** from creation output
4. **Readiness polling:**
   ```bash
   supabase projects api-keys --project-ref <ref> -o json
   ```
   Poll every 5s, max 12 attempts (60s total). Returns:
   `[{"name": "anon", "api_key": "..."}, {"name": "service_role", "api_key": "..."}]`
5. **Extract keys:**
   - `anon` key → `NEXT_PUBLIC_SUPABASE_ANON_KEY`
   - `service_role` key → `SUPABASE_SERVICE_ROLE_KEY`
6. **Construct URLs:**
   - `NEXT_PUBLIC_SUPABASE_URL` = `https://<ref>.supabase.co`
   - `POSTGRES_URL_NON_POOLING`: query the pooler config (**after** project is ACTIVE_HEALTHY):
     ```bash
     curl -s "https://api.supabase.com/v1/projects/<ref>/config/database/pooler" \
       -H "Authorization: Bearer <token>"
     ```
     If empty (`[]`), wait 5s and retry (max 3 attempts). Use `host` with port `5432` and the URL-encoded password from Step 2 (`PASSWORD_ENC`, NEVER `PASSWORD_RAW`):
     `postgresql://postgres.<ref>:${PASSWORD_ENC}@<pooler-host>:5432/postgres`
7. **Link local project:**
   ```bash
   supabase link --project-ref <ref>
   ```
8. **Apply migrations** (if `supabase/migrations/` has files) **and seed `_auto_migrations` on success** (prevents the `prebuild` auto-migrate runner on Vercel from re-applying already-applied migrations on the first production build — see `scripts/auto-migrate.mjs`). The seeding ONLY runs when `supabase db push --yes` exits 0 — a partial failure leaves `_auto_migrations` untouched so the Vercel runner can resume:
   ```bash
   if supabase db push --yes; then
     MIGRATION_FILES=$(ls supabase/migrations/*.sql 2>/dev/null | xargs -n1 basename | sort)
     if [ -n "$MIGRATION_FILES" ]; then
       FILE_ARRAY=$(printf '%s\n' "$MIGRATION_FILES" | python3 -c "import sys,json; print(','.join(json.dumps(l.strip()) for l in sys.stdin if l.strip()))")
       psql "$POSTGRES_URL_NON_POOLING" -v ON_ERROR_STOP=1 -c "
         CREATE TABLE IF NOT EXISTS _auto_migrations (
           name TEXT PRIMARY KEY, applied_at TIMESTAMPTZ DEFAULT now()
         );
         INSERT INTO _auto_migrations (name)
         SELECT unnest(ARRAY[$FILE_ARRAY])
         ON CONFLICT DO NOTHING;
       "
     fi
   fi
   ```
   If `psql` is not available in the environment, the seed step may be skipped — the auto-migrate runner will still succeed as long as migrations follow the idempotent pattern in `## Schema Management` (DROP POLICY IF EXISTS ; CREATE POLICY ...).

### Hosting Requirements

- **incompatible_hosting:** `[]`
- **volume_config:** `{ needed: false }`

### Auth Config

**Spawn condition:** `stack.auth: supabase` AND `stack.database: supabase`

1. **Read Supabase access token** (try in order):
   - File: `~/.supabase/access-token`
   - macOS Keychain: `security find-generic-password -s "Supabase CLI" -w 2>/dev/null` — strip `go-keyring-base64:` prefix, base64-decode remainder
   - If neither found: ask user for token (generate at supabase.com/dashboard/account/tokens) or skip
2. **Extract short title:** experiment.yaml `title` up to first ` — `, ` - `, or ` | ` delimiter; fallback to capitalized `name`
3. **Configure auth, email templates, and SMTP:**

   Build a single JSON body with the following fields. Replace `<short-title>` with the value from step 2.

   **Base fields (always include):**
   ```json
   {
     "site_url": "https://<canonical_url>",
     "uri_allow_list": "https://<canonical_url>/**",
     "mailer_subjects_confirmation": "Confirm your <short-title> account",
     "mailer_subjects_recovery": "Reset your <short-title> password",
     "mailer_subjects_magic_link": "Your <short-title> login link"
   }
   ```

   **Email template fields (always include):**

   Add these three fields to the same JSON. Each value is an HTML string — collapse to a single line, escape all double quotes (`\"`) for JSON embedding, and replace `<short-title>` with the extracted value.

   `mailer_templates_confirmation_content` — Confirmation email:
   ```html
   <table width="100%" cellpadding="0" cellspacing="0" role="presentation" style="margin:0;padding:0;background-color:#f4f4f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif">
     <tr>
       <td align="center" style="padding:40px 16px">
         <table width="560" cellpadding="0" cellspacing="0" role="presentation" style="max-width:560px;width:100%;background-color:#ffffff;border-radius:8px;border:1px solid #e4e4e7;overflow:hidden">
           <tr><td style="height:4px;background-color:#2563eb;font-size:0;line-height:0">&nbsp;</td></tr>
           <tr>
             <td style="padding:40px 40px 0 40px">
               <p style="margin:0 0 4px;font-size:14px;font-weight:600;color:#2563eb;letter-spacing:0.5px;text-transform:uppercase"><short-title></p>
               <h1 style="margin:0 0 24px;font-size:24px;font-weight:700;color:#18181b;line-height:1.3">Confirm your email address</h1>
               <p style="margin:0 0 24px;font-size:16px;color:#3f3f46;line-height:1.6">Thanks for signing up. Please confirm your email address to activate your account and get started.</p>
             </td>
           </tr>
           <tr>
             <td align="center" style="padding:8px 40px 32px">
               <a href="{{ .ConfirmationURL }}" target="_blank" style="display:inline-block;padding:14px 32px;background-color:#2563eb;color:#ffffff;font-size:16px;font-weight:600;text-decoration:none;border-radius:6px;line-height:1">Confirm Email</a>
             </td>
           </tr>
           <tr>
             <td style="padding:0 40px 32px">
               <p style="margin:0;font-size:13px;color:#71717a;line-height:1.6">If the button doesn't work, copy and paste this URL into your browser:</p>
               <p style="margin:8px 0 0;font-size:13px;color:#2563eb;word-break:break-all;line-height:1.6">{{ .ConfirmationURL }}</p>
             </td>
           </tr>
           <tr><td style="height:1px;background-color:#e4e4e7;font-size:0;line-height:0">&nbsp;</td></tr>
           <tr>
             <td style="padding:24px 40px">
               <p style="margin:0;font-size:12px;color:#a1a1aa;line-height:1.6">This email was sent to {{ .Email }} because an account was created at <a href="{{ .SiteURL }}" style="color:#a1a1aa"><short-title></a>. If you did not sign up, you can safely ignore this email.</p>
             </td>
           </tr>
         </table>
       </td>
     </tr>
   </table>
   ```

   `mailer_templates_recovery_content` — Password reset email:
   ```html
   <table width="100%" cellpadding="0" cellspacing="0" role="presentation" style="margin:0;padding:0;background-color:#f4f4f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif">
     <tr>
       <td align="center" style="padding:40px 16px">
         <table width="560" cellpadding="0" cellspacing="0" role="presentation" style="max-width:560px;width:100%;background-color:#ffffff;border-radius:8px;border:1px solid #e4e4e7;overflow:hidden">
           <tr><td style="height:4px;background-color:#2563eb;font-size:0;line-height:0">&nbsp;</td></tr>
           <tr>
             <td style="padding:40px 40px 0 40px">
               <p style="margin:0 0 4px;font-size:14px;font-weight:600;color:#2563eb;letter-spacing:0.5px;text-transform:uppercase"><short-title></p>
               <h1 style="margin:0 0 24px;font-size:24px;font-weight:700;color:#18181b;line-height:1.3">Reset your password</h1>
               <p style="margin:0 0 24px;font-size:16px;color:#3f3f46;line-height:1.6">We received a request to reset the password for your account. Click the button below to choose a new password.</p>
             </td>
           </tr>
           <tr>
             <td align="center" style="padding:8px 40px 32px">
               <a href="{{ .ConfirmationURL }}" target="_blank" style="display:inline-block;padding:14px 32px;background-color:#2563eb;color:#ffffff;font-size:16px;font-weight:600;text-decoration:none;border-radius:6px;line-height:1">Reset Password</a>
             </td>
           </tr>
           <tr>
             <td style="padding:0 40px 32px">
               <p style="margin:0;font-size:13px;color:#71717a;line-height:1.6">If the button doesn't work, copy and paste this URL into your browser:</p>
               <p style="margin:8px 0 0;font-size:13px;color:#2563eb;word-break:break-all;line-height:1.6">{{ .ConfirmationURL }}</p>
             </td>
           </tr>
           <tr><td style="height:1px;background-color:#e4e4e7;font-size:0;line-height:0">&nbsp;</td></tr>
           <tr>
             <td style="padding:24px 40px">
               <p style="margin:0;font-size:12px;color:#a1a1aa;line-height:1.6">This email was sent to {{ .Email }} for your <a href="{{ .SiteURL }}" style="color:#a1a1aa"><short-title></a> account. If you did not request a password reset, you can safely ignore this email.</p>
             </td>
           </tr>
         </table>
       </td>
     </tr>
   </table>
   ```

   `mailer_templates_magic_link_content` — Magic link email:
   ```html
   <table width="100%" cellpadding="0" cellspacing="0" role="presentation" style="margin:0;padding:0;background-color:#f4f4f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif">
     <tr>
       <td align="center" style="padding:40px 16px">
         <table width="560" cellpadding="0" cellspacing="0" role="presentation" style="max-width:560px;width:100%;background-color:#ffffff;border-radius:8px;border:1px solid #e4e4e7;overflow:hidden">
           <tr><td style="height:4px;background-color:#2563eb;font-size:0;line-height:0">&nbsp;</td></tr>
           <tr>
             <td style="padding:40px 40px 0 40px">
               <p style="margin:0 0 4px;font-size:14px;font-weight:600;color:#2563eb;letter-spacing:0.5px;text-transform:uppercase"><short-title></p>
               <h1 style="margin:0 0 24px;font-size:24px;font-weight:700;color:#18181b;line-height:1.3">Your login link</h1>
               <p style="margin:0 0 24px;font-size:16px;color:#3f3f46;line-height:1.6">Click the button below to log in to your account. This link will expire in 24 hours.</p>
             </td>
           </tr>
           <tr>
             <td align="center" style="padding:8px 40px 32px">
               <a href="{{ .ConfirmationURL }}" target="_blank" style="display:inline-block;padding:14px 32px;background-color:#2563eb;color:#ffffff;font-size:16px;font-weight:600;text-decoration:none;border-radius:6px;line-height:1">Log In</a>
             </td>
           </tr>
           <tr>
             <td style="padding:0 40px 32px">
               <p style="margin:0;font-size:13px;color:#71717a;line-height:1.6">If the button doesn't work, copy and paste this URL into your browser:</p>
               <p style="margin:8px 0 0;font-size:13px;color:#2563eb;word-break:break-all;line-height:1.6">{{ .ConfirmationURL }}</p>
             </td>
           </tr>
           <tr><td style="height:1px;background-color:#e4e4e7;font-size:0;line-height:0">&nbsp;</td></tr>
           <tr>
             <td style="padding:24px 40px">
               <p style="margin:0;font-size:12px;color:#a1a1aa;line-height:1.6">This email was sent to {{ .Email }} for your <a href="{{ .SiteURL }}" style="color:#a1a1aa"><short-title></a> account. If you did not request this link, you can safely ignore this email.</p>
             </td>
           </tr>
         </table>
       </td>
     </tr>
   </table>
   ```

   **SMTP fields (include only when `stack.email: resend` AND `RESEND_API_KEY` is available):**

   Add these fields to the same JSON object. If `stack.email` is not `resend` or `RESEND_API_KEY` was not provided, omit them entirely.
   ```json
   {
     "smtp_host": "smtp.resend.com",
     "smtp_port": "465",
     "smtp_user": "resend",
     "smtp_pass": "<RESEND_API_KEY>",
     "smtp_admin_email": "noreply@<domain>",
     "smtp_sender_name": "<short-title>"
   }
   ```
   Where `<domain>` is `deploy.domain` from experiment.yaml; fallback to `draftlabs.org`.
   Note: `smtp_port` must be a **string** (`"465"`), not an integer — per the Supabase API spec.

   **Send the PATCH request:**

   Merge all applicable fields into a single JSON object and send:
   ```bash
   curl -s -X PATCH "https://api.supabase.com/v1/projects/<ref>/config/auth" \
     -H "Authorization: Bearer <token>" \
     -H "Content-Type: application/json" \
     -d '<merged-json>'
   ```

4. **Configure OAuth providers** (if `stack.auth_providers` present and credentials provided):
   Include in the same PATCH call: `"external_<provider>_enabled": true,
   "external_<provider>_client_id": "<id>", "external_<provider>_secret": "<secret>"`.
   Supported slugs: google, github, apple, azure, bitbucket, discord, facebook,
   figma, gitlab, kakao, keycloak, linkedin_oidc, notion, slack_oidc, spotify,
   twitch, twitter, workos, zoom.

### Teardown

1. **Pre-delete safety check** — query user-facing table row counts:
   ```bash
   curl -s "https://<ref>.supabase.co/rest/v1/<table>?select=count" \
     -H "Authorization: Bearer <service_role_key>" \
     -H "apikey: <anon_key>" \
     -H "Prefer: count=exact"
   ```
   Check tables from `supabase/migrations/` (parse CREATE TABLE statements). If any table has rows > 0, warn and require explicit `delete` confirmation.
2. **Delete project:**
   ```bash
   supabase projects delete --project-ref <ref>
   ```
3. **Dashboard URL (manual fallback):** `https://supabase.com/dashboard/project/<ref>/settings/general`

### Manifest Keys

```json
{
  "provider": "supabase",
  "ref": "<ref>",
  "org_id": "<org-id>"
}
```

## Non-Next.js Fallback

> Used when `stack.database: supabase` but framework is **not** nextjs (e.g., Hono service, Commander CLI).
> The browser client (`src/lib/supabase.ts`) is not created — service/CLI archetypes have no browser runtime.
> Replace `@supabase/ssr` with direct `@supabase/supabase-js` usage and `@next/env` with `dotenv`.

### Fallback Packages
```bash
npm install @supabase/supabase-js pg dotenv
```

### `src/lib/supabase-server.ts` — Server client (non-Next.js)
```ts
import { createClient } from "@supabase/supabase-js";

export function createServerSupabaseClient() {
  return createClient(
    process.env.SUPABASE_URL || "https://placeholder.supabase.co",
    process.env.SUPABASE_ANON_KEY || "placeholder-anon-key"
  );
}

export function createServiceRoleClient() {
  const serviceRoleKey = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!serviceRoleKey) throw new Error("SUPABASE_SERVICE_ROLE_KEY is not configured");
  return createClient(
    process.env.SUPABASE_URL || "https://placeholder.supabase.co",
    serviceRoleKey
  );
}
```
- `createServerSupabaseClient()`: Use in route handlers for anon-scoped operations
- `createServiceRoleClient()`: Use for admin operations that bypass RLS
- No cookie-based auth — service/CLI archetypes use API keys or service tokens directly

### `scripts/auto-migrate.mjs` — Migration runner (non-Next.js)
```js
import "dotenv/config";
import pg from "pg";
import { readdir, readFile } from "fs/promises";
import { join } from "path";

const connectionString = process.env.POSTGRES_URL_NON_POOLING;
if (!connectionString) process.exit(0); // No database URL — skip silently (local dev, CI)

const client = new pg.Client({ connectionString });
await client.connect();

await client.query(`
  CREATE TABLE IF NOT EXISTS _auto_migrations (
    name TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ DEFAULT now()
  )
`);

const { rows: applied } = await client.query("SELECT name FROM _auto_migrations");
const appliedSet = new Set(applied.map((r) => r.name));

const migrationsDir = join(process.cwd(), "supabase", "migrations");
let files;
try {
  files = (await readdir(migrationsDir)).filter((f) => f.endsWith(".sql")).sort();
} catch {
  await client.end();
  process.exit(0); // No migrations directory — skip
}

for (const file of files) {
  if (appliedSet.has(file)) continue;
  const sql = await readFile(join(migrationsDir, file), "utf8");
  await client.query(sql);
  await client.query("INSERT INTO _auto_migrations (name) VALUES ($1)", [file]);
  console.log(`Applied migration: ${file}`);
}

await client.end();
```

### Fallback Environment Variables
```
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-publishable-api-key
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
# <password> below is the URL-encoded form (PASSWORD_ENC from Provisioning step 2), not the raw base64 output
POSTGRES_URL_NON_POOLING=postgresql://postgres.<ref>:<url-encoded-password>@<pooler-host>:5432/postgres
```

> **Note:** Non-Next.js runtimes use `SUPABASE_URL` and `SUPABASE_ANON_KEY` (no `NEXT_PUBLIC_` prefix) since there is no client-side bundle exposure distinction.

> **Note:** `POSTGRES_URL_NON_POOLING` is required for the auto-migrate script. Find it at: Supabase Dashboard → Settings → Database → Connection string (URI, session mode). When using the Supabase Vercel Integration, this is injected automatically.

### Fallback Build Integration

Add the migration runner to `package.json` so it runs before each build. **scaffold-libs owns this write** — it writes BOTH `scripts/auto-migrate.mjs` AND the `prebuild` entry in a single pass. The framework-side scaffold-setup must NOT pre-write the `prebuild` script (see `.claude/stacks/framework/nextjs.md` Project Setup), otherwise intermediate `npm run build` calls between scaffold-setup and scaffold-libs crash on the missing runner file.

Recommended entry:
```json
{ "scripts": { "prebuild": "test ! -f scripts/auto-migrate.mjs || node scripts/auto-migrate.mjs" } }
```

- `test ! -f scripts/auto-migrate.mjs` returns true (exit 0) when the file is MISSING — prebuild is a no-op in that case, so any accidental early build succeeds.
- When the file EXISTS, the `||` short-circuit doesn't fire and `node scripts/auto-migrate.mjs` runs — its non-zero exit code (SQL error, permission denied, network failure) **propagates** so genuine migration failures still fail the build.
- Do NOT use `test -f X && node X || true` — `|| true` swallows real migration errors, masking production regressions.

- On Vercel: `prebuild` runs automatically before `build`
- On other platforms (Docker, Fly.io, Railway): add `node scripts/auto-migrate.mjs` as a pre-start or build step (with the same missing-file guard if the script can be absent)
- Locally: run `node scripts/auto-migrate.mjs` manually, or use `make migrate` with `supabase db push`

The migration runner also exits silently when `POSTGRES_URL_NON_POOLING` is not set (local dev without database), so adding `prebuild` is safe even when the env variable is absent.

### Composing prebuild with other stacks

When `stack.analytics: posthog` is also present, scaffold-libs Step 6.5 composes both prebuild segments via `&&`-chained, defensively-guarded form. The composed entry stays a single `prebuild` value (npm does not natively run multiple scripts under one lifecycle hook), and each segment retains its own `test ! -f X || node X` guard so partial-bootstrap states stay safe:

```json
{ "scripts": { "prebuild": "(test ! -f scripts/auto-migrate.mjs || node scripts/auto-migrate.mjs) && (test ! -f scripts/check-analytics-env.mjs || node scripts/check-analytics-env.mjs)" } }
```

The order is "infrastructure first, then config check" — migrations run first so any DB schema the analytics check might rely on is in place; `&&` propagates any non-zero exit so genuine failures still fail the build. See `.claude/stacks/analytics/posthog.md` `## Production Observability > Prebuild composition with other stacks` for the full canonical contract.

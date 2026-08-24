import {
  demoAccount,
  demoEmployees,
  demoNotices,
  demoSignatures,
  demoOpenViolations,
} from "@/lib/demo-fixtures";

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
  // (the only other live copy). ctx tracks mutation state across the chain so
  // `.from('x').insert(payload).select().single()` returns a synthesized row
  // instead of null — the canonical API-route pattern.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const chainable = (terminal: unknown, ctx: { hasMutation?: boolean; payload?: unknown } = {}): any =>
    new Proxy(() => terminal, {
      get: (_, prop) => {
        if (prop === "then") return (resolve: (v: unknown) => void) => resolve(terminal);
        if (prop === "insert" || prop === "update" || prop === "upsert") {
          return (payload: unknown) => chainable(terminal, { hasMutation: true, payload });
        }
        if (prop === "select") {
          // Preserve the terminal (which now carries this table's rows) as well
          // as ctx, so .insert(p).select().single() still carries hasMutation
          // through while .from("employees").select() keeps the employee rows
          // instead of resetting to the generic seed.
          return () => chainable(terminal, ctx);
        }
        if (prop === "single" || prop === "maybeSingle") {
          if (ctx.hasMutation) {
            const row = { id: `demo-${Date.now()}`, created_at: new Date().toISOString(), ...(ctx.payload as object) };
            return () => chainable({ data: row, error: null });
          }
          // A read (no mutation) resolves to the first row of the table rather
          // than null. Returning null here is what made resolveAccount() report
          // no_account for every demo request.
          const rows = (terminal as { data?: unknown[] })?.data;
          const first = Array.isArray(rows) && rows.length > 0 ? rows[0] : null;
          return () => chainable({ data: first, error: null });
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
  // Table-aware seeds. The generic three-row DEMO_SEED_DATA above matches no
  // real table, and maybeSingle() returns null without a mutation -- so the
  // accounts lookup in resolveAccount() found nothing, every authenticated
  // route fell to no_account, and /staff, /notices and /audit-file rendered
  // empty. /dashboard and /violations only looked populated because they hold
  // their own fixtures and never call the API at all.
  //
  // Correctly shaped rows per table let each route run its REAL query path
  // against demo data, so the demo exercises the same joining, ranking and
  // counting code as production instead of a parallel mock.
  const demoTable = (table: string): unknown[] => {
    const now = Date.now();
    if (table === "accounts") return [demoAccount()];
    if (table === "employees") return demoEmployees(now);
    if (table === "notices") return demoNotices(now);
    if (table === "signatures") return demoSignatures(now);
    if (table === "pay_periods") return [];
    if (table === "violations") return demoOpenViolations(now);
    return DEMO_SEED_DATA;
  };
  return {
    from: (table: string) =>
      chainable({ data: demoTable(table), error: null }, {}),
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

export const PLACEHOLDER_SUPABASE_URL = "https://placeholder.supabase.co";

/** True on a real deployment target (Vercel / Railway), false on a dev box. */
function isHostingPlatform(): boolean {
  return process.env.VERCEL === "1" || !!process.env.RAILWAY_ENVIRONMENT_NAME;
}

/** True when the Supabase browser-scope config is absent or still the placeholder. */
function isPlaceholderConfig(): boolean {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL || "";
  const anon = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || "";
  return !url || !anon || url === PLACEHOLDER_SUPABASE_URL;
}

// Server-side warn-once shares the same intent as the client warning in
// supabase.ts — they are a parallel pair. Only reachable off-platform now;
// on a hosting platform the same condition throws instead (see below).
let _supabaseServerPlaceholderWarned = false;
function _warnSupabaseServerPlaceholder() {
  if (_supabaseServerPlaceholderWarned) return;
  _supabaseServerPlaceholderWarned = true;
  console.error(
    "[supabase-server] Server Supabase placeholder fallback was hit — this process " +
    "is using the demo client with mocked data. Set NEXT_PUBLIC_SUPABASE_URL and " +
    "NEXT_PUBLIC_SUPABASE_ANON_KEY to use a real Supabase project."
  );
}

export async function createServerSupabaseClient() {
  if (process.env.DEMO_MODE === "true" && process.env.VERCEL === "1") {
    throw new Error("DEMO_MODE is not allowed in production");
  }

  const placeholder = isPlaceholderConfig();

  // SECURITY: the demo client's `auth.getUser()` returns a synthetic
  // authenticated user. Falling back to it because env vars are MISSING would
  // make authentication a function of configuration absence — one unset
  // variable on a real deployment and every anonymous request is treated as
  // signed in, against a real service-role client. Fail closed instead. The
  // throw is caught by resolveAccount(), which degrades to `unavailable` (503)
  // per its documented contract: no user, no data.
  if (placeholder && isHostingPlatform() && process.env.DEMO_MODE !== "true") {
    throw new Error(
      "Supabase is not configured on this deployment. Set NEXT_PUBLIC_SUPABASE_URL " +
      "and NEXT_PUBLIC_SUPABASE_ANON_KEY (the Vercel Supabase Integration injects " +
      "both). Refusing to serve the demo client in a hosted environment."
    );
  }

  // Off-platform (local dev, CI, e2e) the demo fallback is still what makes the
  // app runnable with no keys at all, so keep it — but say so loudly.
  if (placeholder && process.env.DEMO_MODE !== "true") _warnSupabaseServerPlaceholder();
  if (process.env.DEMO_MODE === "true" || placeholder) return createDemoClient();

  const url = process.env.NEXT_PUBLIC_SUPABASE_URL || "";
  const anon = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || "";
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

  // SECURITY: never point a real service-role key at a host we do not own.
  // Defaulting the URL to the placeholder would put the key in an Authorization
  // header addressed to `placeholder.supabase.co` — a domain outside our
  // control — on any deployment where the key is set but the URL is not.
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL || "";
  if (!url || url === PLACEHOLDER_SUPABASE_URL) {
    throw new Error(
      "SUPABASE_SERVICE_ROLE_KEY is set but NEXT_PUBLIC_SUPABASE_URL is missing or " +
      "still the placeholder. Refusing to send a service-role key to an unowned host."
    );
  }
  return createClient(url, serviceRoleKey);
}

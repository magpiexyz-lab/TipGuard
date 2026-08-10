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

// Server-side warn-once shares the same intent as the client warning in
// supabase.ts — they are a parallel pair.
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
  // Also fall back to the demo client when env vars are missing or set to the
  // canonical placeholder. Prevents server-side requests from hitting
  // placeholder DNS in unconfigured deployments.
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

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
    // .from() returns the mutation-aware chainable directly so .insert/.update/.upsert
    // flow through the proxy's get handler.
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

// Warn-once when placeholder fallback hits in a deployed-host context. Routing
// to the demo client is intentional, but silently routing to demo in
// production usually means env vars were not configured; surface that as a
// one-time `console.error` so operators can see it in logs / DevTools.
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
  // NEXT_PUBLIC_* env vars are inlined at build time by Next.js, so a build
  // produced without NEXT_PUBLIC_DEMO_MODE=true compiles the demo branch to
  // dead code. Detect a placeholder configuration at runtime — when the
  // URL/key are missing or match the canonical placeholder default, fall
  // back to the demo client instead of attempting placeholder.supabase.co DNS.
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

// Unit tests for the Supabase client factories' fail-closed behaviour.
//
// The demo client's `auth.getUser()` returns a synthetic AUTHENTICATED user.
// That is correct for local development with no keys, and catastrophic on a
// real deployment: if the fallback were reachable there, authentication would
// become a function of configuration ABSENCE — one unset environment variable
// and every anonymous request is treated as signed in, while
// `createServiceRoleClient()` hands the route a client that bypasses RLS on
// every table.
//
// These tests pin the boundary: off-platform the demo fallback stays (it is
// what makes `npm run dev` work with an empty .env), on-platform the same
// condition throws. `resolveAccount()` catches the throw and degrades to
// `unavailable` (503) per its documented contract — no user, no data.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/headers", () => ({
  cookies: () => Promise.resolve({ getAll: () => [], set: () => {} }),
}));

// The real factories spin up a RealtimeClient, which needs a WebSocket
// implementation Node does not provide under vitest. Mock them so the
// positive-path cases can assert WHICH url/key was handed over — a stronger
// claim than "a client came back".
const { createServerClient, createClient } = vi.hoisted(() => ({
  createServerClient: vi.fn(() => ({ __kind: "ssr-client" })),
  createClient: vi.fn(() => ({ __kind: "service-role-client", from: () => {} })),
}));
vi.mock("@supabase/ssr", () => ({ createServerClient }));
vi.mock("@supabase/supabase-js", () => ({ createClient }));

const REAL_URL = "https://abcdefghijklmnop.supabase.co";
const REAL_ANON = "sb_publishable_realkey";
const REAL_SERVICE = "sb_secret_realservicekey";
const PLACEHOLDER = "https://placeholder.supabase.co";

/** Env keys these factories read; cleared before each case for isolation. */
const KEYS = [
  "VERCEL",
  "RAILWAY_ENVIRONMENT_NAME",
  "DEMO_MODE",
  "NEXT_PUBLIC_SUPABASE_URL",
  "NEXT_PUBLIC_SUPABASE_ANON_KEY",
  "SUPABASE_SERVICE_ROLE_KEY",
] as const;

let saved: Record<string, string | undefined>;

beforeEach(() => {
  saved = Object.fromEntries(KEYS.map((k) => [k, process.env[k]]));
  for (const k of KEYS) delete process.env[k];
  // The placeholder warning is warn-once per module instance.
  vi.resetModules();
  vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  for (const k of KEYS) {
    if (saved[k] === undefined) delete process.env[k];
    else process.env[k] = saved[k];
  }
  vi.restoreAllMocks();
});

async function load() {
  return import("./supabase-server");
}

describe("createServerSupabaseClient — hosted deployments fail closed", () => {
  // The core regression: a hosted deployment missing Supabase config must NOT
  // receive a client that reports an authenticated user.
  it.each([
    ["VERCEL", "1"],
    ["RAILWAY_ENVIRONMENT_NAME", "production"],
  ])(
    "throws instead of returning the demo client when %s is set and config is absent",
    async (platformKey, platformValue) => {
      process.env[platformKey] = platformValue;

      const { createServerSupabaseClient } = await load();
      await expect(createServerSupabaseClient()).rejects.toThrow(
        /Supabase is not configured on this deployment/
      );
    }
  );

  it("throws on a hosted deployment when the URL is still the placeholder", async () => {
    process.env.VERCEL = "1";
    process.env.NEXT_PUBLIC_SUPABASE_URL = PLACEHOLDER;
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = REAL_ANON;

    const { createServerSupabaseClient } = await load();
    await expect(createServerSupabaseClient()).rejects.toThrow(
      /Refusing to serve the demo client in a hosted environment/
    );
  });

  it("throws on a hosted deployment when only the anon key is missing", async () => {
    process.env.VERCEL = "1";
    process.env.NEXT_PUBLIC_SUPABASE_URL = REAL_URL;

    const { createServerSupabaseClient } = await load();
    await expect(createServerSupabaseClient()).rejects.toThrow(
      /Supabase is not configured/
    );
  });

  // No synthetic session may escape on the failing path — not even briefly.
  it("never yields a client reporting an authenticated user when hosted and unconfigured", async () => {
    process.env.VERCEL = "1";

    const { createServerSupabaseClient } = await load();
    const result = await createServerSupabaseClient().then(
      (client) => ({ threw: false, client }),
      () => ({ threw: true, client: null })
    );

    expect(result.threw).toBe(true);
    expect(result.client).toBeNull();
  });

  it("still rejects DEMO_MODE on Vercel with the production guard", async () => {
    process.env.VERCEL = "1";
    process.env.DEMO_MODE = "true";

    const { createServerSupabaseClient } = await load();
    await expect(createServerSupabaseClient()).rejects.toThrow(
      "DEMO_MODE is not allowed in production"
    );
  });
});

describe("createServerSupabaseClient — local development keeps the demo fallback", () => {
  // Off-platform this fallback is the reason `npm run dev` works with no .env
  // at all, and e2e runs in DEMO_MODE. Breaking it would break both.
  it("returns the demo client when unconfigured and not on a hosting platform", async () => {
    const { createServerSupabaseClient } = await load();
    const client = await createServerSupabaseClient();
    const { data } = await client.auth.getUser();

    expect(data.user?.id).toBe("demo-user-id");
  });

  it("warns loudly on the local fallback rather than staying silent", async () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});

    const { createServerSupabaseClient } = await load();
    await createServerSupabaseClient();

    expect(spy).toHaveBeenCalledWith(
      expect.stringContaining("placeholder fallback was hit")
    );
  });

  it("returns the demo client under an explicit DEMO_MODE off-platform", async () => {
    process.env.DEMO_MODE = "true";
    process.env.NEXT_PUBLIC_SUPABASE_URL = REAL_URL;
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = REAL_ANON;

    const { createServerSupabaseClient } = await load();
    const { data } = await (await createServerSupabaseClient()).auth.getUser();

    expect(data.user?.id).toBe("demo-user-id");
  });

  it("builds a real client against the configured project when fully configured", async () => {
    process.env.VERCEL = "1";
    process.env.NEXT_PUBLIC_SUPABASE_URL = REAL_URL;
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = REAL_ANON;

    const { createServerSupabaseClient } = await load();
    const client = await createServerSupabaseClient();

    // The real @supabase/ssr factory, addressed at the configured project —
    // never the placeholder host the old `url || PLACEHOLDER` default allowed.
    expect(createServerClient).toHaveBeenCalledTimes(1);
    expect(createServerClient).toHaveBeenCalledWith(
      REAL_URL,
      REAL_ANON,
      expect.anything()
    );
    expect(client).toMatchObject({ __kind: "ssr-client" });
  });
});

describe("createServiceRoleClient — never addresses an unowned host", () => {
  // A service-role key bypasses RLS on every table. Defaulting the URL to the
  // placeholder would put that key in an Authorization header aimed at
  // `placeholder.supabase.co`, a domain outside our control.
  it("throws when the service-role key is set but the URL is missing", async () => {
    process.env.SUPABASE_SERVICE_ROLE_KEY = REAL_SERVICE;

    const { createServiceRoleClient } = await load();
    expect(() => createServiceRoleClient()).toThrow(
      /Refusing to send a service-role key to an unowned host/
    );
  });

  it("throws when the URL is still the placeholder", async () => {
    process.env.SUPABASE_SERVICE_ROLE_KEY = REAL_SERVICE;
    process.env.NEXT_PUBLIC_SUPABASE_URL = PLACEHOLDER;

    const { createServiceRoleClient } = await load();
    expect(() => createServiceRoleClient()).toThrow(
      /Refusing to send a service-role key to an unowned host/
    );
  });

  it("does not leak the key value in the error message", async () => {
    process.env.SUPABASE_SERVICE_ROLE_KEY = REAL_SERVICE;

    const { createServiceRoleClient } = await load();
    let message = "";
    try {
      createServiceRoleClient();
    } catch (error) {
      message = (error as Error).message;
    }

    expect(message).not.toContain(REAL_SERVICE);
  });

  it("still reports a missing service-role key distinctly", async () => {
    process.env.NEXT_PUBLIC_SUPABASE_URL = REAL_URL;

    const { createServiceRoleClient } = await load();
    expect(() => createServiceRoleClient()).toThrow(
      "SUPABASE_SERVICE_ROLE_KEY is not configured"
    );
  });

  it("sends the service-role key only to the configured project host", async () => {
    process.env.NEXT_PUBLIC_SUPABASE_URL = REAL_URL;
    process.env.SUPABASE_SERVICE_ROLE_KEY = REAL_SERVICE;

    const { createServiceRoleClient } = await load();
    createServiceRoleClient();

    expect(createClient).toHaveBeenCalledTimes(1);
    expect(createClient).toHaveBeenCalledWith(REAL_URL, REAL_SERVICE);
    // The placeholder host must never appear as a destination for this key.
    expect(createClient).not.toHaveBeenCalledWith(
      PLACEHOLDER,
      expect.anything()
    );
  });

  it("still rejects DEMO_MODE on Vercel", async () => {
    process.env.VERCEL = "1";
    process.env.DEMO_MODE = "true";

    const { createServiceRoleClient } = await load();
    expect(() => createServiceRoleClient()).toThrow(
      "DEMO_MODE is not allowed in production"
    );
  });
});

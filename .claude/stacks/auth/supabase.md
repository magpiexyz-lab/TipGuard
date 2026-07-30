---
assumes: [framework/nextjs]
packages:
  runtime: ["@supabase/supabase-js", "@supabase/ssr"]
  dev: []
files:
  # --- scaffold-wire creates (auth infrastructure, STATE 14) ---
  - src/app/auth/callback/route.ts          # always; scaffold-wire
  - src/app/auth/reset-password/page.tsx     # always; scaffold-wire
  - src/components/nav-bar.tsx               # always; scaffold-wire
  # --- scaffold-pages creates (user-facing pages, STATE 11c) ---
  - src/app/signup/page.tsx                  # auto-included in derive_scope_pages() when stack.auth is set; scaffold-pages
  - src/app/login/page.tsx                   # auto-included in derive_scope_pages() when stack.auth is set; scaffold-pages
  # --- scaffold-libs creates (library + proxy, STATE 11a — LIB_SPAWN) ---
  - src/proxy.ts                             # always; scaffold-libs (Next.js 16+ default — filename<->export-name invariant: src/proxy.ts paired with `export async function proxy(...)`; see .claude/stacks/framework/nextjs.md Stack Knowledge for the empirical 16.2.6 verification superseding #1120).
  - src/lib/supabase-auth.ts                 # only when stack.database is NOT supabase; scaffold-libs
  - src/lib/supabase-auth-server.ts          # only when stack.database is NOT supabase; scaffold-libs
env:
  server: []
  client: [NEXT_PUBLIC_SUPABASE_URL, NEXT_PUBLIC_SUPABASE_ANON_KEY]
ci_placeholders:
  NEXT_PUBLIC_SUPABASE_URL: "https://placeholder.supabase.co"
  NEXT_PUBLIC_SUPABASE_ANON_KEY: placeholder-anon-key
clean:
  files: []
  dirs: []
gitignore: []
emits_events: [signup_start, signup_complete]  # conditional: only when stack.analytics is present; archetypes: [web-app]; auth template fires from src/app/signup/page.tsx
demo_mode:
  # Issue #1077: structured DEMO_MODE policy consumed by
  # .claude/scripts/lib/derive_slot_intent.py:derive_runtime_gate().
  # demo_mode_role: the role baked into the demo user (null = no role
  # claim, e.g., empty app_metadata). When the demo user lacks a role
  # required by a behavior (behaviors[].requires_role), that behavior's
  # slot is unreachable in DEMO_MODE — slot-intent declares it conditional.
  demo_mode_role: null
  # demo_user_metadata: shape of demoUser.app_metadata in the demo client.
  # Empty object means "no role claims" — admin-gated routes are unreachable.
  # (Documented at .claude/stacks/auth/supabase.md demoUser block.)
  demo_user_metadata: {}
---
# Auth: Supabase Auth
> Used when experiment.yaml has `stack.auth: supabase`
> Assumes: `framework/nextjs` (server-side auth check uses `NextResponse`)

## Packages
Shares the same packages as `database/supabase` — no additional installs needed when `stack.database` is also `supabase`.

If `stack.database` is NOT supabase, install:
```bash
npm install @supabase/supabase-js @supabase/ssr
```

## Signup/Login UI
- Use Supabase Auth UI or simple email/password forms
- Signup page: email + password fields, submit button
- Login page: email + password fields, submit button, link to signup
- Enforce a minimum password length of 8 characters on the signup form
- Recommend enabling email verification in Supabase Dashboard (Authentication → Settings → Email Auth → "Confirm email")

## Files to Create

### `src/app/auth/callback/route.ts` — Auth callback handler (always created)

Exchanges PKCE authorization codes for sessions. Required for email confirmation auto-login, OAuth/social login, password reset, and magic link flows.

#### When `stack.database` is also `supabase` (shared client):
```ts
import { NextResponse } from "next/server";
import { z } from "zod";
import { createServerSupabaseClient } from "@/lib/supabase-server";
// When `stack.analytics` is present: also import the server-analytics helper.
// Remove this import line and the trackServerEvent block below if stack.analytics is absent.
import { trackServerEvent } from "@/lib/analytics-server";

// PKCE codes are URL-safe base64, typically 40-200 chars. Cap generously.
const codeSchema = z.string().min(20).max(512).regex(/^[A-Za-z0-9_-]+$/);

// New-user recency window (ms) for activate-stage event firing. Covers OAuth and
// magic-link signups (user.created_at is set during the handshake) and
// prompt-email-confirm signups; skips password-reset and returning magic-link
// users where user.created_at is older. See Stack Knowledge entry
// "When stack.analytics is present, fire signup_complete from the callback route".
const SIGNUP_RECENCY_MS = 60_000;

export async function GET(request: Request) {
  const { searchParams, origin } = new URL(request.url);
  if (process.env.DEMO_MODE === "true" && process.env.VERCEL === "1") {
    throw new Error("DEMO_MODE is not allowed in production");
  }
  if (process.env.DEMO_MODE === "true") return NextResponse.redirect(`${origin}/`);

  const rawCode = searchParams.get("code");
  const rawNext = searchParams.get("next") ?? "/";
  const next = rawNext.startsWith("/") && !rawNext.startsWith("//") ? rawNext : "/";

  const parsedCode = rawCode ? codeSchema.safeParse(rawCode) : null;
  if (parsedCode?.success) {
    const supabase = await createServerSupabaseClient();
    const { error } = await supabase.auth.exchangeCodeForSession(parsedCode.data);
    if (!error) {
      // When `stack.analytics` is present: fire signup_complete at the callback
      // chokepoint for OAuth/email-confirm/magic-link signups. Recency filter
      // skips password-reset and returning magic-link users. Remove the entire
      // `const { data: { user } } ...` block below when stack.analytics is absent.
      const { data: { user } } = await supabase.auth.getUser();
      if (user && Date.now() - new Date(user.created_at).getTime() < SIGNUP_RECENCY_MS) {
        const provider = (user.app_metadata?.provider as string | undefined) ?? "email";
        await trackServerEvent("signup_complete", user.id, { provider });
      }
      return NextResponse.redirect(`${origin}${next}`);
    }
  }
  return NextResponse.redirect(`${origin}/login?error=auth`);
}
```

#### When `stack.database` is NOT supabase (standalone client):
Replace the `createServerSupabaseClient` import (the third `import` line in the template above):
```ts
// Instead of: import { createServerSupabaseClient } from "@/lib/supabase-server";
import { createServerAuthClient as createServerSupabaseClient } from "@/lib/supabase-auth-server";
```
This aliasing keeps the rest of the route handler code identical — only that one import changes. The zod import, `codeSchema` constant, and (when `stack.analytics` is present) the `trackServerEvent` import + activate-stage block stay as shown.

### `src/app/auth/reset-password/page.tsx` — Reset password page (always created)

Lets the user set a new password after clicking the reset link from their email. The callback route exchanges the PKCE code and redirects here with an active session.

#### When `stack.database` is also `supabase` (shared client):
```tsx
"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export default function ResetPasswordPage() {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const router = useRouter();

  async function handleReset(e: React.SyntheticEvent<HTMLFormElement>) {
    e.preventDefault();
    if (password.length < 8) {
      setError("Password must be at least 8 characters");
      return;
    }
    setLoading(true);
    setError("");
    const supabase = createClient();
    const { error: updateError } = await supabase.auth.updateUser({ password });
    setLoading(false);
    if (updateError) { setError(updateError.message); return; }
    router.push("/");
  }

  return (
    <form onSubmit={handleReset} className="space-y-4">
      <div>
        <Label htmlFor="password">New Password</Label>
        <Input id="password" type="password" placeholder="Min 8 characters"
          value={password} onChange={e => setPassword(e.target.value)} required minLength={8} />
      </div>
      {error && <p className="text-red-500 text-sm">{error}</p>}
      <Button type="submit" disabled={loading}>
        {loading ? "Updating..." : "Set new password"}
      </Button>
    </form>
  );
}
```

#### When `stack.database` is NOT supabase (standalone client):
Replace the import on line 5:
<!-- coherence-allow: line-number-cross-reference: refers to embedded code block below -->
```tsx
// Instead of: import { createClient } from "@/lib/supabase";
import { createAuthClient as createClient } from "@/lib/supabase-auth";
```
The rest of the component code remains identical — only the import changes.

### `src/app/signup/page.tsx` — Signup page (auto-included in `derive_scope_pages()` when `stack.auth` is set)

When `stack.analytics` is absent: remove the `@/lib/events` import and all `trackSignupStart()`/`trackSignupComplete()` calls from the template below. The signup flow works without analytics.

#### When `stack.database` is also `supabase` (shared client):
```tsx
"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { createClient } from "@/lib/supabase";
import { trackSignupStart, trackSignupComplete } from "@/lib/events";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export default function SignupPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [loading, setLoading] = useState(false);
  const router = useRouter();

  useEffect(() => { trackSignupStart({ method: "email" }); }, []);

  async function handleSignup(e: React.SyntheticEvent<HTMLFormElement>) {
    e.preventDefault();
    if (password.length < 8) {
      setError("Password must be at least 8 characters");
      return;
    }
    setLoading(true);
    setError("");
    const supabase = createClient();
    const { data, error: authError } = await supabase.auth.signUp({
      email,
      password,
      options: { emailRedirectTo: `${window.location.origin}/auth/callback` },
    });
    setLoading(false);
    if (authError) { setError(authError.message); return; }
    if (data.user?.identities?.length === 0) {
      setError("An account with this email already exists. Please log in.");
      setLoading(false);
      return;
    }
    if (!data.session) {
      setSuccess("Check your email for a confirmation link to complete signup.");
      return;
    }
    trackSignupComplete({ method: "email" });
    router.push("/"); // Redirect to landing — bootstrap will update to the first non-auth page from experiment.yaml
  }

  return success ? (
    <div className="space-y-4 text-center">
      <p className="text-green-600 font-medium">{success}</p>
      <p className="text-sm text-muted-foreground">
        Already confirmed? <Link href="/login" className="underline">Log in</Link>
      </p>
    </div>
  ) : (
    <form onSubmit={handleSignup} className="space-y-4">
      <div>
        <Label htmlFor="email">Email</Label>
        <Input id="email" type="email" placeholder="you@example.com" value={email}
          onChange={e => setEmail(e.target.value)} required />
      </div>
      <div>
        <Label htmlFor="password">Password</Label>
        <Input id="password" type="password" placeholder="Min 8 characters" value={password}
          onChange={e => setPassword(e.target.value)} required minLength={8} />
      </div>
      {error && <p className="text-red-500 text-sm">{error}</p>}
      <Button type="submit" disabled={loading}>
        {loading ? "Creating account..." : "Sign up"}
      </Button>
    </form>
  );
}
```

#### When `stack.database` is NOT supabase (standalone client):
Replace the import on line 4 of the signup page:
<!-- coherence-allow: line-number-cross-reference: refers to embedded code block below -->
```tsx
// Instead of: import { createClient } from "@/lib/supabase";
import { createAuthClient as createClient } from "@/lib/supabase-auth";
```
This aliasing keeps the rest of the component code identical — only the import changes.

- Adapt this pattern for your app — update imports, add fields, and adjust redirects

#### OAuth buttons (conditional: only when `stack.auth_providers` is present)

When generating the signup page and `stack.auth_providers` exists in experiment.yaml,
add these elements below the email/password form:

1. Import the `handleOAuthLogin` function (from the OAuth section below)
2. Add an "Or continue with" separator
3. Add one `<Button variant="outline">` per provider in `auth_providers`

Example (for `auth_providers: [google, github]`):
```tsx
import { Button } from "@/components/ui/button";
{/* Add after the email/password </form> closing tag */}
<div className="relative my-4">
  <div className="absolute inset-0 flex items-center"><span className="w-full border-t" /></div>
  <div className="relative flex justify-center text-xs uppercase">
    <span className="bg-background px-2 text-muted-foreground">Or continue with</span>
  </div>
</div>
<div className="flex flex-col gap-2">
  <Button variant="outline" type="button" onClick={() => handleOAuthLogin("google")}>
    Continue with Google
  </Button>
  <Button variant="outline" type="button" onClick={() => handleOAuthLogin("github")}>
    Continue with GitHub
  </Button>
</div>
```

The `handleOAuthLogin` function (in the "OAuth / Social Login" section below) and
`/auth/callback` route (created above) handle the rest — no new routes or packages needed.

When `stack.auth_providers` is absent, do not add OAuth buttons — email/password only.

### `src/app/login/page.tsx` — Login page (auto-included in `derive_scope_pages()` when `stack.auth` is set)

Follows the same structure as the signup page above, with these differences:
- Calls `supabase.auth.signInWithPassword()` instead of `signUp()`
- No password minimum-length validation (existing accounts may have any length)
- No analytics events (experiment/EVENTS.yaml defines no login event)

#### When `stack.database` is also `supabase` (shared client):
```tsx
"use client";

import { useState, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { createClient } from "@/lib/supabase";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

function LoginForm() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [forgotMode, setForgotMode] = useState(false);
  const [forgotSent, setForgotSent] = useState(false);
  const router = useRouter();
  const searchParams = useSearchParams();
  const confirmed = searchParams.get("confirmed") === "true";
  const authError = searchParams.get("error") === "auth";

  async function handleLogin(e: React.SyntheticEvent<HTMLFormElement>) {
    e.preventDefault();
    setLoading(true);
    setError("");
    const supabase = createClient();
    const { error: authError } = await supabase.auth.signInWithPassword({ email, password });
    setLoading(false);
    if (authError) { setError(authError.message); return; }
    router.push("/"); // Redirect to landing — bootstrap will update to the first non-auth page from experiment.yaml
  }

  async function handleForgotPassword(e: React.SyntheticEvent<HTMLFormElement>) {
    e.preventDefault();
    setLoading(true);
    setError("");
    const supabase = createClient();
    const { error: resetError } = await supabase.auth.resetPasswordForEmail(email, {
      redirectTo: `${window.location.origin}/auth/callback?next=/auth/reset-password`,
    });
    setLoading(false);
    if (resetError) { setError(resetError.message); return; }
    setForgotSent(true);
  }

  return (
    <div className="space-y-4">
      {confirmed && (
        <p className="text-green-600 font-medium text-center">
          Email confirmed! Please log in.
        </p>
      )}
      {authError && (
        <p className="text-red-500 font-medium text-center">
          Authentication failed. Please try logging in.
        </p>
      )}
      {forgotMode ? (
        forgotSent ? (
          <div className="space-y-4 text-center">
            <p className="text-green-600 font-medium">Check your email for a reset link.</p>
            <button type="button" className="text-sm underline text-muted-foreground"
              onClick={() => { setForgotMode(false); setForgotSent(false); }}>
              Back to login
            </button>
          </div>
        ) : (
          <form onSubmit={handleForgotPassword} className="space-y-4">
            <div>
              <Label htmlFor="email">Email</Label>
              <Input id="email" type="email" placeholder="you@example.com" value={email}
                onChange={e => setEmail(e.target.value)} required />
            </div>
            {error && <p className="text-red-500 text-sm">{error}</p>}
            <Button type="submit" disabled={loading}>
              {loading ? "Sending..." : "Send reset link"}
            </Button>
            <button type="button" className="text-sm underline text-muted-foreground block"
              onClick={() => { setForgotMode(false); setError(""); }}>
              Back to login
            </button>
          </form>
        )
      ) : (
        <form onSubmit={handleLogin} className="space-y-4">
          <div>
            <Label htmlFor="email">Email</Label>
            <Input id="email" type="email" placeholder="you@example.com" value={email}
              onChange={e => setEmail(e.target.value)} required />
          </div>
          <div>
            <Label htmlFor="password">Password</Label>
            <Input id="password" type="password" placeholder="Password" value={password}
              onChange={e => setPassword(e.target.value)} required />
          </div>
          <div className="flex justify-end">
            <button type="button" className="text-sm underline text-muted-foreground"
              onClick={() => { setForgotMode(true); setError(""); }}>
              Forgot password?
            </button>
          </div>
          {error && <p className="text-red-500 text-sm">{error}</p>}
          <Button type="submit" disabled={loading}>
            {loading ? "Logging in..." : "Log in"}
          </Button>
          <p className="text-sm text-muted-foreground">
            Don't have an account? <a href="/signup" className="underline">Sign up</a>
          </p>
        </form>
      )}
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}
```

> **Next.js 16 note:** `useSearchParams()` requires a `<Suspense>` boundary. The default export wraps the inner form component.

#### When `stack.database` is NOT supabase (standalone client):
Replace the import on line 5 of the login page:
<!-- coherence-allow: line-number-cross-reference: refers to embedded code block below -->
```tsx
// Instead of: import { createClient } from "@/lib/supabase";
import { createAuthClient as createClient } from "@/lib/supabase-auth";
```
The rest of the component code (Suspense wrapper, confirmed banner, `createClient()` inside handler) remains identical.

#### OAuth buttons (conditional: only when `stack.auth_providers` is present)

When generating the login page and `stack.auth_providers` exists in experiment.yaml,
add the same OAuth button block used in the signup page (see signup OAuth buttons section above)
below the email/password form. Use the same `handleOAuthLogin` function and separator pattern.
Fire `trackSignupStart({ method: "<provider>" })` before the OAuth redirect — the analytics
event is the same regardless of whether the user is signing up or logging in via OAuth.

### `src/components/nav-bar.tsx` — Auth-aware navigation (always created when `stack.auth: supabase`)

#### When `stack.database` is also `supabase` (shared client):
```tsx
"use client";

import { useState, useEffect } from "react";
import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Menu } from "lucide-react";
import { createClient } from "@/lib/supabase";
import { Button, buttonVariants } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import type { User } from "@supabase/supabase-js";

export function NavBar() {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  useEffect(() => {
    const supabase = createClient();

    supabase.auth.getSession().then(({ data: { session } }) => {
      setUser(session?.user ?? null);
      setLoading(false);
    });

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, session) => {
      setUser(session?.user ?? null);
    });

    return () => subscription.unsubscribe();
  }, []);

  async function handleLogout() {
    const supabase = createClient();
    await supabase.auth.signOut();
    router.push("/");
    router.refresh();
  }

  const navLinks = (
    <>
      {/* DERIVED-FROM: derive_scope_pages */}
      {/* Bootstrap emits <Link href="/<page>">{LABEL}</Link> for each page
          in derive_scope_pages(experiment), excluding landing/auth routes.
          Ordering: golden_path pages first in funnel sequence; behavior-only
          pages appended alphabetically. See procedures/wire.md Step 5b.3. */}
    </>
  );

  const authSection = loading ? (
    <Button variant="outline" disabled className="min-w-[70px]">
      &nbsp;
    </Button>
  ) : user ? (
    <>
      <span className="text-sm text-muted-foreground truncate max-w-[200px]">
        {user.email}
      </span>
      <Button variant="outline" onClick={handleLogout}>
        Log out
      </Button>
    </>
  ) : (
    <Link href="/login" className={buttonVariants({ variant: "outline" })}>
      Log in
    </Link>
  );

  return (
    <nav aria-label="Primary" className="flex items-center justify-between px-6 py-4 border-b">
      <Link href="/" className="flex items-center gap-2">
        {/* Logo from scaffold-images — read path from .runs/image-manifest.json */}
        {/* Decorative: brand name is already announced by the adjacent <span>, so alt="" + aria-hidden prevents double announcement. */}
        {/* unoptimized: next/image rejects SVG by default (returns HTTP 400 → broken-image icon). See framework/nextjs.md "When loading SVG assets through next/image". */}
        <Image src="/images/logo.svg" alt="" aria-hidden width={32} height={32} unoptimized />
        <span className="text-xl font-bold">APP_NAME</span>
      </Link>
      {/* Desktop nav */}
      <div className="hidden md:flex items-center gap-4">
        {navLinks}
        {authSection}
      </div>
      {/* Mobile hamburger menu */}
      {/* SheetTrigger renders its own <button> element (Base UI Dialog.Trigger primitive from @/components/ui/sheet.tsx). */}
      {/* Do NOT wrap a <Button> inside — that produces nested <button><button> and a React hydration error on every page */}
      {/* that renders <NavBar/>, which cascades to disable client-side analytics events (fix #1068). */}
      {/* Style the trigger directly via buttonVariants() — or use the `render` prop if you need Button behavior (see shadcn.md). */}
      <div className="md:hidden">
        <Sheet>
          <SheetTrigger
            aria-label="Open menu"
            className={buttonVariants({ variant: "ghost", size: "icon" })}
          >
            <Menu className="h-5 w-5" />
          </SheetTrigger>
          <SheetContent side="right" className="w-[280px]">
            {/* WCAG 4.1.2: every dialog needs an accessible name. SheetContent renders a dialog;
                see .claude/stacks/ui/shadcn.md → "When using SheetContent, always include SheetTitle". */}
            <SheetTitle className="sr-only">Site navigation</SheetTitle>
            <div className="flex flex-col gap-4 mt-8">
              {navLinks}
              {authSection}
            </div>
          </SheetContent>
        </Sheet>
      </div>
    </nav>
  );
}
```

#### When `stack.database` is NOT supabase (standalone client):
Replace the import on line 6:
<!-- coherence-allow: line-number-cross-reference: refers to embedded code block below -->
```tsx
import { createAuthClient as createClient } from "@/lib/supabase-auth";
```

Notes:
- Bootstrap replaces `APP_NAME` with experiment.yaml `name` and adds page-specific navigation links
- Bootstrap reads `.runs/image-manifest.json` for the logo path and updates the `<Image>` `src` attribute
- The `navLinks` and `authSection` are shared between desktop and mobile layouts — bootstrap populates `navLinks` from `derive_scope_pages(experiment)` (canonical SET inventory), ordered golden_path pages first in funnel sequence and behavior-only pages appended alphabetically. See `.claude/procedures/wire.md` Step 5b.3 and `.claude/scripts/lib/derive_pages.py`
- `getSession()` on mount sets initial auth state; `onAuthStateChange()` reacts to login/logout
- Loading state prevents flash of "Log in" button before auth state is known
- `router.refresh()` after logout clears server-side cached session data
- The `Sheet` component requires `npx shadcn@latest add -y sheet` — this is included in the base component set (see UI stack file)
- **Layout wiring (scaffold-wire, Step 5c):** After creating `nav-bar.tsx`, scaffold-wire must add `import { NavBar } from "@/components/nav-bar";` to `src/app/layout.tsx` and render `<NavBar />` as the first child inside `<body>`, before `<main>`. See wire.md Step 5c.

## Client-Side Auth State
- The `NavBar` component (above) demonstrates the pattern: `getSession()` for initial state + `onAuthStateChange()` for reactive updates
- On login/signup success, redirect to the appropriate page
- Use the same pattern in any component that needs to react to auth changes

## Server-Side Auth Check
In API route handlers, verify the user session before processing the request. The import depends on whether `stack.database` is also `supabase`.

#### When `stack.database` is also `supabase` (shared client):
```ts
import { NextResponse } from "next/server";
import { createServerSupabaseClient } from "@/lib/supabase-server";

// At the start of your route handler:
const supabase = await createServerSupabaseClient();
const { data: { user } } = await supabase.auth.getUser();
if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
// Use user.id for database queries and metadata
```

#### When `stack.database` is NOT supabase (standalone client):
```ts
import { NextResponse } from "next/server";
import { createServerAuthClient } from "@/lib/supabase-auth-server";

// At the start of your route handler:
const supabase = await createServerAuthClient();
const { data: { user } } = await supabase.auth.getUser();
if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
// Use user.id for database queries and metadata
```

## Proxy (Route Protection)

Protect authenticated pages at the routing level so unauthenticated users are redirected before the page renders. Bootstrap creates this file when `stack.auth: supabase` is present.

On Next.js 16+ (today's template default), this file is `src/proxy.ts` and the exported function is `proxy`. Next.js 16 enforces a **filename↔export-name invariant**: the file MUST be named `src/proxy.ts` AND the exported function MUST be named `proxy`. Renaming only one (file but not export, or vice versa) produces an empty `.next/server/middleware-manifest.json` and silent non-registration of the proxy — this is the symptom #1120 originally reported, since superseded by empirical 16.2.6 verification (see `.claude/stacks/framework/nextjs.md` Stack Knowledge entry "Next.js 16+: scaffold src/proxy.ts + filename↔export-name invariant"). The `config` export is unchanged. Already-bootstrapped projects on `src/middleware.ts` continue to work on 16+ but emit a deprecation warning at build time — migrate via `git mv src/middleware.ts src/proxy.ts` and rename the exported function from `middleware` to `proxy` in the same commit.

### `src/proxy.ts` — Route protection (Next.js 16+ default)

#### When `stack.database` is also `supabase` (shared client):
```ts
import { NextResponse, type NextRequest } from "next/server";
import { createServerClient } from "@supabase/ssr";

const publicPaths = ["/", "/login", "/signup", "/auth/callback", "/auth/reset-password", "/api/health"];

export async function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Skip public paths, static files, API routes, analytics proxy, and variant routes
  if (
    publicPaths.some((p) => pathname === p) ||
    pathname.startsWith("/_next") ||
    pathname.startsWith("/api/") ||
    pathname.startsWith("/ingest/") ||
    pathname.startsWith("/v/") ||
    pathname.includes(".")
  ) {
    return NextResponse.next();
  }

  // Bypass auth in demo mode (no Supabase credentials available)
  if (process.env.NEXT_PUBLIC_DEMO_MODE === "true") {
    return NextResponse.next();
  }

  const response = NextResponse.next();
  // Use `||` (falsy check) not `!` (non-null assertion) — non-null assertions
  // pass through empty-string env values ("" is set but empty), causing the SDK
  // to initialize with "" and crash on the first cookie refresh.
  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL || "https://placeholder.supabase.co",
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || "placeholder-anon-key",
    {
      cookies: {
        getAll() { return request.cookies.getAll(); },
        setAll(cookiesToSet) {
          cookiesToSet.forEach(({ name, value, options }) => {
            response.cookies.set(name, value, options);
          });
        },
      },
    }
  );

  const { data: { user } } = await supabase.auth.getUser();
  if (!user) {
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("next", pathname);
    return NextResponse.redirect(loginUrl);
  }

  return response;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|.*\\..*).*)"],
};
```

Notes:
- `publicPaths` MUST be replaced by `scaffold-libs` Step 3 with the canonical set returned by `derive_public_paths(experiment)` — call `python3 .claude/scripts/lib/derive_pages.py public_paths < experiment/experiment.yaml`. The static array shown above is a placeholder used only when experiment.yaml is unavailable. The canonical set covers: marketing landing (`/`), auth landing (`/login`, `/signup`, `/auth/callback`, `/auth/reset-password`), `/api/health`, plus any `behavior.pages` whose owning behavior(s) declare `anonymous_allowed: true` (fail-secure intersection: a page shared by two behaviors is public iff BOTH mark anonymous_allowed). See `.claude/templates/experiment-yaml.md` for the `behavior.anonymous_allowed` schema field (Issue #1126).
- `/v/` variant routes are excluded via `pathname.startsWith("/v/")` — these are A/B test landing pages that must be publicly accessible
- `/ingest/` is excluded via `pathname.startsWith("/ingest/")` — this is the client-side analytics reverse-proxy prefix defined by the analytics stack file's `next.config.ts` rewrite (see `.claude/stacks/analytics/posthog.md` Reverse Proxy Setup). Without this skip, unauthenticated PostHog event POSTs from landing/demo/signup pages would 307-redirect to `/login?next=/ingest/...` and return 405, silently breaking top-of-funnel analytics in production (was issue #983). Any auth stack file authoring its own middleware template must replicate this skip-list entry when `stack.analytics` uses a client-side reverse proxy.
- API routes are excluded — they use server-side auth checks in route handlers instead. **Do not add proxy auth for `/api/` routes.** Proxy and API route handlers create separate Supabase clients from the same request cookies. Supabase refresh tokens are single-use: if the access token expires, the proxy consumes the refresh token, and the API route handler's subsequent refresh attempt fails silently (returns 401). API routes must handle auth independently via `createServerSupabaseClient()` + `getUser()`.
- The `matcher` config excludes static assets for performance
- Redirects to `/login?next=<path>` so the login page can redirect back after auth
- Uses `getUser()` (not `getSession()`) for security — `getUser()` validates the JWT with the Supabase Auth server

#### When `stack.database` is NOT supabase (standalone client):
Replace the Supabase client creation with:
```ts
import { createServerClient } from "@supabase/ssr";

// Replace the createServerClient block with:
const supabase = createServerClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL || "https://placeholder.supabase.co",
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || "placeholder-anon-key",
  { cookies: { /* same cookie handlers as above */ } }
);
```

## Session Token Lifecycle

- **Access token**: Expires after 1 hour (configurable in Supabase Dashboard → Auth → Settings)
- **Refresh token**: Expires after 7 days (configurable)
- **Auto-refresh**: The `supabase-server.ts` client auto-refreshes tokens via cookies on each request. No manual refresh logic needed.
- **Edge case**: If a user is inactive for >7 days, the refresh token expires and they must re-authenticate. The middleware will redirect them to the login page automatically.
- **Monitor**: Watch for `AuthApiError: Invalid Refresh Token` in server logs — a spike indicates users hitting the 7-day expiry window. Consider increasing refresh token lifetime if this is frequent.

## Analytics Integration
- Fire `signup_start` on form render (include `method` property: `"email"`, `"google"`, `"github"`)
- Fire `signup_complete` only when `data.session` exists after `signUp()` — when email confirmation is enabled (the default), `signUp()` returns `session: null` and the user must confirm their email before they're logged in. `signup_complete` should only fire for confirmed, logged-in users.

## Production Observability

When the URL/key env vars are missing or match the canonical placeholder default (`https://placeholder.supabase.co` / `placeholder-anon-key`), `createAuthClient()` and `createServerAuthClient()` route to a demo client that returns mocked auth data — no real user can sign up or log in. This routing is intentional (`#1145` mitigates `placeholder.supabase.co` DNS attempts at build/import time), but in production it means the deployment is silently running with mocked auth.

**Fail-loud mechanism (issue #1170 follow-up):** the placeholder branch in both factory functions calls a `_warn*PlaceholderWarned` once-flag helper that emits `console.error` when:
- Client (`createAuthClient`): hostname is NOT localhost / `127.0.0.1` / `0.0.0.0` / `[::1]` / `*.local`.
- Server (`createServerAuthClient`): `process.env.VERCEL === "1"` OR `process.env.RAILWAY_ENVIRONMENT_NAME` is set.

This makes silent demo routing visible in production logs and DevTools without breaking dev/local where the placeholder is the expected default. The warning is one-time per module instance to avoid log spam; it surfaces "this deployment used the demo auth client because env vars were not set" so operators can investigate (typically: forgot to wire the Supabase Vercel Integration, or env vars set to empty string instead of the real values).

The Supabase Vercel Integration auto-injects `NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_ANON_KEY`; using the integration eliminates this misconfiguration class. See `database/supabase.md` `## Provisioning` for the integration setup.

## OAuth / Social Login

The callback route (`src/app/auth/callback/route.ts`, created above) handles OAuth redirects — no additional route infrastructure is needed to add social login.

### Adding an OAuth provider button

Add this to your signup or login page alongside the existing email/password form:

```ts
async function handleOAuthLogin(provider: "google" | "github") {
  trackSignupStart({ method: provider });
  const supabase = createClient();
  await supabase.auth.signInWithOAuth({
    provider,
    options: { redirectTo: `${window.location.origin}/auth/callback` },
  });
}
```

When the OAuth flow completes, Supabase redirects to `/auth/callback` with an authorization code. The callback route exchanges it for a session and redirects the user into the app.

### Analytics
- Fire `trackSignupStart({ method: "google" })` (or `"github"`) **before** the OAuth call — the redirect leaves the page, so this must fire first
- `signup_complete` fires server-side from the callback route template above (the shared chokepoint for OAuth, email-confirm, and magic-link signups). The recency filter (`user.created_at < 60s`) skips returning users and password-reset clickers. Destination-page or `onAuthStateChange` wiring is no longer required — the callback route covers all three flows. See `## Stack Knowledge > When stack.analytics is present, fire signup_complete from the callback route` for rationale and edge cases.

### Enabling a provider

When `stack.auth_providers` is declared in experiment.yaml:
- `/bootstrap` generates OAuth buttons for each listed provider
- `/deploy` collects credentials and configures providers via Management API

For providers added after initial deploy, update `auth_providers` and re-run `/deploy`.

**Manual alternative:** Supabase Dashboard → Authentication → Providers → enable +
paste Client ID/Secret. Set redirect URI to `https://<ref>.supabase.co/auth/v1/callback`.

### Custom OAuth Security (non-Supabase flows)

Supabase's built-in `signInWithOAuth()` handles CSRF protection via PKCE — no additional state management is needed. However, if the project implements custom OAuth flows outside of Supabase (e.g., GitHub App OAuth for API access, third-party service integrations), the `state` parameter must be HMAC-signed to prevent login CSRF:

1. **Generate state:** `state = nonce + "." + hmac_sha256(nonce + payload, OAUTH_STATE_SECRET)`
2. **Store nonce** in a short-lived httpOnly cookie (TTL: 10 minutes max)
3. **Verify on callback:** extract nonce from cookie, recompute HMAC, compare using `crypto.timingSafeEqual(Buffer.from(expected), Buffer.from(received))` — do NOT use `===` or `!==` string comparison, which is vulnerable to timing side-channel attacks
4. **Reject** if nonce is missing, HMAC mismatches, or TTL expired

Store `OAUTH_STATE_SECRET` in server environment variables (generate with `openssl rand -hex 32`). Without signing, an attacker can craft a callback URL with their own authorization code and trick a victim into linking the attacker's account.

This applies only to custom OAuth implementations — Supabase-managed OAuth (via `signInWithOAuth()` and the auth callback route above) is already protected.

## Shared Client Note
When `stack.auth` matches `stack.database` (both `supabase`), they share the same client files (`supabase.ts` and `supabase-server.ts`). When `stack.database` is absent or a different provider, auth needs its own library file — see "Standalone Client" below.

### Standalone Client (when `stack.database` is not supabase)

If `stack.database` is NOT supabase, the shared client files don't exist. Create auth-specific clients:

#### `src/lib/supabase-auth.ts` — Browser client for auth
```ts
import { createBrowserClient } from "@supabase/ssr";

function createDemoClient() {
  // Auth-only demo client: NO chainable factory here — this client never
  // exposes `.from()` (DB queries go through the standalone database client
  // when stack.database is configured). The chainable factory is owned by
  // database/supabase.md's createDemoClient — see that file's
  // `## Stack Knowledge > Canonical chainable factory (mutation-aware)`.
  const demoUser = {
    id: "demo-user-id",
    email: "demo@example.com",
    app_metadata: {},
    user_metadata: {},
    aud: "authenticated",
    created_at: new Date().toISOString(),
  };
  return {
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
  } as unknown as ReturnType<typeof createBrowserClient>;
}

// Issue #1170 follow-up: warn-once when placeholder fallback hits in a deployed-host
// context. Routing to demo client is intentional (#1145) but silent in production
// usually means env vars were not configured — surface as `console.error`.
let _supabaseAuthPlaceholderWarned = false;
function _warnSupabaseAuthPlaceholder() {
  if (_supabaseAuthPlaceholderWarned) return;
  if (typeof window !== "undefined") {
    const host = window.location.hostname;
    const isLocal =
      ["localhost", "127.0.0.1", "0.0.0.0", "[::1]"].includes(host) ||
      host.endsWith(".local");
    if (isLocal) return;
  }
  _supabaseAuthPlaceholderWarned = true;
  console.error(
    "[supabase-auth] Browser auth client placeholder fallback was hit — this " +
    "deployment is using the demo auth client. Set NEXT_PUBLIC_SUPABASE_URL " +
    "and NEXT_PUBLIC_SUPABASE_ANON_KEY in your hosting platform to enable real auth."
  );
}

export function createAuthClient() {
  // Issue #1145: NEXT_PUBLIC_* env vars are inlined at build time by Next.js, so a
  // build produced without NEXT_PUBLIC_DEMO_MODE=true compiles the demo branch to
  // dead code. Detect a placeholder configuration at runtime — when the URL/key
  // are missing or match the canonical placeholder default, fall back to the demo
  // client instead of attempting placeholder.supabase.co DNS.
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL || "";
  const anon = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || "";
  const isDemoFlag = process.env.NEXT_PUBLIC_DEMO_MODE === "true";
  const isPlaceholder = !url || !anon || url === "https://placeholder.supabase.co";
  if (isPlaceholder && !isDemoFlag) _warnSupabaseAuthPlaceholder();
  if (isDemoFlag || isPlaceholder) return createDemoClient();
  return createBrowserClient(
    url || "https://placeholder.supabase.co",
    anon || "placeholder-anon-key"
  );
}
```

#### `src/lib/supabase-auth-server.ts` — Server client for auth
```ts
import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";

function createDemoClient() {
  // Auth-only server demo client: NO chainable factory here — this client
  // never exposes `.from()`. DB queries go through the standalone database
  // client when stack.database is configured. The chainable factory is owned
  // by database/supabase.md's createDemoClient — see that file's
  // `## Stack Knowledge > Canonical chainable factory (mutation-aware)`.
  const demoUser = {
    id: "demo-user-id",
    email: "demo@example.com",
    app_metadata: {},
    user_metadata: {},
    aud: "authenticated",
    created_at: new Date().toISOString(),
  };
  return {
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
      },
      {
        get: (target, prop) =>
          prop in target
            ? target[prop as keyof typeof target]
            : () => Promise.resolve({ data: {}, error: null }),
      }
    ),
  } as unknown as ReturnType<typeof createServerClient>;
}

// Issue #1170 follow-up: server-side warn-once for auth placeholder fallback.
let _supabaseAuthServerPlaceholderWarned = false;
function _warnSupabaseAuthServerPlaceholder() {
  if (_supabaseAuthServerPlaceholderWarned) return;
  const isHostingPlatform =
    process.env.VERCEL === "1" || !!process.env.RAILWAY_ENVIRONMENT_NAME;
  if (!isHostingPlatform) return;
  _supabaseAuthServerPlaceholderWarned = true;
  console.error(
    "[supabase-auth-server] Server auth client placeholder fallback was hit — this " +
    "deployment is using the demo auth client. Set NEXT_PUBLIC_SUPABASE_URL and " +
    "NEXT_PUBLIC_SUPABASE_ANON_KEY in your hosting platform to enable real auth."
  );
}

export async function createServerAuthClient() {
  if (process.env.DEMO_MODE === "true" && process.env.VERCEL === "1") {
    throw new Error("DEMO_MODE is not allowed in production");
  }
  // Issue #1145: also fall back to the demo client when env vars are missing or set
  // to the canonical placeholder. Prevents server-side requests from hitting
  // placeholder DNS in unconfigured deployments.
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL || "";
  const anon = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || "";
  const isPlaceholder = !url || !anon || url === "https://placeholder.supabase.co";
  if (isPlaceholder && process.env.DEMO_MODE !== "true") _warnSupabaseAuthServerPlaceholder();
  if (process.env.DEMO_MODE === "true" || isPlaceholder) return createDemoClient();
  const cookieStore = await cookies();
  return createServerClient(
    url || "https://placeholder.supabase.co",
    anon || "placeholder-anon-key",
    {
      cookies: {
        getAll() { return cookieStore.getAll(); },
        setAll(cookiesToSet) {
          cookiesToSet.forEach(({ name, value, options }) => {
            cookieStore.set(name, value, options);
          });
        },
      },
    }
  );
}
```

Update signup/login page imports to use `createAuthClient` from `@/lib/supabase-auth` instead of `@/lib/supabase`.

## Environment Variables
When `stack.database` is also `supabase`, auth shares the database environment variables (`NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`). No additional env vars needed.

When `stack.database` is NOT supabase, add these env vars for auth:
```
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your-publishable-api-key
```

## Production URL Configuration

After deploying to production, the Supabase project's auth settings must include the deployment URL for redirects to work correctly (email confirmations, password resets, OAuth callbacks).

The `/deploy` skill configures this automatically via the Supabase Management API:
```bash
curl -s -X PATCH "https://api.supabase.com/v1/projects/<ref>/config/auth" \
  -H "Authorization: Bearer <supabase-access-token>" \
  -H "Content-Type: application/json" \
  -d '{"site_url": "https://<url>", "uri_allow_list": "https://<url>/**"}'
```

**Manual fallback:** Supabase Dashboard → Authentication → URL Configuration → set Site URL and add Redirect URLs.

> **Note:** The `uri_allow_list` wildcard (`https://<url>/**`) already covers `/auth/callback` — no additional deploy changes are needed when adding OAuth providers.

The `/deploy` skill also configures email subject lines and professional HTML email templates in the same PATCH call, using the app's short title from experiment.yaml (e.g., "Confirm your MyApp account"). Templates include a branded header, responsive layout, and clear CTA button for confirmation, password reset, and magic link emails. When `stack.email: resend`, deploy also configures Supabase to send auth emails through Resend's SMTP (`smtp.resend.com`), so emails come from your domain (e.g., `noreply@draftlabs.org`) instead of Supabase's default sender. To customize further: Supabase Dashboard → Authentication → Email Templates.

The access token is read from `~/.supabase/access-token` (created by `supabase login`). If unavailable, generate one at supabase.com/dashboard/account/tokens.

## OAuth Provider Configuration

When `stack.auth_providers` is declared in experiment.yaml, `/deploy` configures each provider
via the same Management API PATCH call used for redirect URLs and email subjects:

```bash
curl -s -X PATCH "https://api.supabase.com/v1/projects/<ref>/config/auth" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "external_google_enabled": true,
    "external_google_client_id": "<client-id>",
    "external_google_secret": "<client-secret>"
  }'
```

Supported provider slugs (use as `external_<slug>_enabled`): google, github, apple, azure,
bitbucket, discord, facebook, figma, gitlab, kakao, keycloak, linkedin_oidc, notion,
slack_oidc, spotify, twitch, twitter, workos, zoom.

The callback URL for all providers is: `https://<ref>.supabase.co/auth/v1/callback`
(already covered by the `uri_allow_list` wildcard set during deploy).

**Manual fallback:** Supabase Dashboard → Authentication → Providers → enable the provider
→ paste Client ID and Secret from the provider's developer console.

## Stack Knowledge

### When a signup or profile API route inserts a user row, use the session email — never the body-supplied email
If a project adds a server-side API route that mirrors signup to a database table (e.g., `src/app/api/auth/signup/route.ts` inserting into a `profiles` table), the client-supplied email in the POST body cannot be trusted. An attacker who has authenticated with email A can pass email B in the request body and insert a row under email B's identity. Always derive the email from the verified auth session:

```typescript
// WRONG — trusts client-supplied email (A1 validation bypass)
const { email } = await request.json();
await supabase.from("profiles").insert({ user_id: user.id, email });

// CORRECT — uses the authenticated identity from the Supabase session
const supabase = await createServerSupabaseClient();
const { data: { user } } = await supabase.auth.getUser();
if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
await supabase.from("profiles").insert({ user_id: user.id, email: user.email });
```

The client form should omit `email` from the POST body entirely — the server always derives it from `supabase.auth.getUser()`. This applies to any mutation that writes an email-derived identifier (display name, hashed email, external-system user tag): if the auth session already verifies the value, trust the session, not the request body.

### When an API route should be restricted to admin users
Verify `user.app_metadata?.role === "admin"` after the standard auth check, with an `ADMIN_EMAILS` env var fallback for initial setup before roles are assigned in Supabase:

```typescript
const { data: { user } } = await supabase.auth.getUser();
if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

const adminEmails = (process.env.ADMIN_EMAILS ?? "").split(",").map(e => e.trim()).filter(Boolean);
const isAdmin = user.app_metadata?.role === "admin" || adminEmails.includes(user.email ?? "");
if (!isAdmin) return NextResponse.json({ error: "Forbidden" }, { status: 403 });
```

`app_metadata` is set server-side via the Supabase service role client and cannot be modified by users — it is safe for authorization decisions. The `ADMIN_EMAILS` fallback allows admin operations before Supabase role metadata is configured. Missing this check allows any authenticated user to call admin-only routes, returning 200 instead of 403.

### When Google (or any OAuth provider) fails with `oauth_email_missing`
If a user declines to share their Google account email during OAuth consent — or signs in with a Google account that has no primary email — Supabase redirects to `/auth/callback?error=oauth_email_missing`. Without explicit handling the user lands on a generic error banner or a bare login form with no recovery path.

**Required wiring:**

1. In `/auth/callback` (`src/app/auth/callback/route.ts`), forward the `error` query param to `/login` instead of collapsing to the generic `?error=auth`:

   ```ts
   const error = searchParams.get("error");
   if (error) return NextResponse.redirect(`${origin}/login?error=${encodeURIComponent(error)}`);
   ```

2. On the login page (`src/app/login/page.tsx`), read the `error` param and render a provider-specific banner when it equals `oauth_email_missing`:

   ```tsx
   {error === "oauth_email_missing" ? (
     <div role="alert" className="rounded-md bg-crimson-50 p-4 text-sm text-crimson-900">
       <p className="font-medium">We need your email to create an account.</p>
       <p className="mt-2">Two ways forward:</p>
       <ul className="mt-1 ml-4 list-disc">
         <li>Use the email + password form below.</li>
         <li>Retry Google sign-in and allow access to your email address on the consent screen.</li>
       </ul>
     </div>
   ) : null}
   ```

The specific copy and styling come from the project's design system — what matters is that the banner (a) names the failure mode in plain language, (b) offers at least two recovery paths, and (c) uses a `role="alert"` region so screen readers announce it on arrival. Applies to any OAuth provider that can return this error (`stack.auth_providers: [google, apple, ...]`).

### When implementing an anonymous-to-authenticated resource claim, verify anon_session_id

```yaml
id: anon-to-authed-claim-session-verification
maturity: stable
anti_pattern: false
composite_identity:
  root_cause_class: horizontal-privilege-escalation-via-unverified-claim
  divergence_pattern: claim-routes-trust-row-id-without-session-binding
  stack_scope: auth/supabase
composite_identity_hash: 8e3c39f0f7a5
symptom_keywords: [anonymous, claim, anon_session_id, idor, horizontal-privilege-escalation, finalize, draft, adopt, sessionStorage]
fix_template: |
  Three legs are required. Skipping ANY leg leaves the IDOR open.

  Leg 1 — Schema: add an `anon_session_id text` column on the resource table.
  See database/supabase.md migration patterns for the canonical migration shape.

      -- supabase/migrations/<N>_<resource>_anon_session_id.sql
      alter table <resource> add column anon_session_id text;

  Leg 2 — Anonymous-create route + client wiring:
  Client generates a cryptographically-random session ID once per resource and
  stores it in sessionStorage (tab-scoped, NOT a cookie — cookies forward
  automatically and a future authed user could collide). Client includes the
  value in the create POST body. Server (service-role client, since the row is
  unowned at create time) writes the value to the resource row.

      // Client — at the point of resource creation:
      let anonSessionId = sessionStorage.getItem("anon_session_id");
      if (!anonSessionId) {
        anonSessionId = crypto.randomUUID();
        sessionStorage.setItem("anon_session_id", anonSessionId);
      }
      await fetch("/api/<resource>", {
        method: "POST",
        body: JSON.stringify({ ...payload, anon_session_id: anonSessionId }),
      });

      // Server — /api/<resource> create handler (service-role for unowned rows):
      const supabase = createServiceRoleClient();
      const { data, error } = await supabase
        .from("<resource>")
        .insert({ ...validated, anon_session_id: body.anon_session_id, user_id: null })
        .select("id")
        .single();

  Leg 3 — Authenticated-claim route:
  Client forwards the stored sessionStorage value (must be read at the point of
  user action, NOT auto-forwarded by the browser). Server validates with
  crypto.timingSafeEqual. ALL rejection branches collapse to a uniform 404
  response so attackers cannot enumerate resource IDs.

      // Client — at the point of claim action (e.g., signup-then-claim):
      const anonSessionId = sessionStorage.getItem("anon_session_id");
      await fetch("/api/<resource>/finalize", {
        method: "POST",
        body: JSON.stringify({ id: resourceId, anon_session_id: anonSessionId }),
      });

      // Server — /api/<resource>/finalize handler:
      import { timingSafeEqual } from "crypto";
      const supabase = await createServerSupabaseClient();
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

      const { data: row } = await createServiceRoleClient()
        .from("<resource>")
        .select("anon_session_id, user_id")
        .eq("id", body.id)
        .single();

      const provided = Buffer.from(body.anon_session_id ?? "");
      const stored = Buffer.from(row?.anon_session_id ?? "");
      // Uniform 404 on every rejection branch — denies enumeration oracle.
      if (
        !row ||
        row.user_id !== null ||                   // already claimed
        provided.length === 0 ||                  // missing session id
        provided.length !== stored.length ||
        !timingSafeEqual(provided, stored)        // wrong session id
      ) {
        return NextResponse.json({ error: "Not found" }, { status: 404 });
      }

      await createServiceRoleClient()
        .from("<resource>")
        .update({ user_id: user.id })
        .eq("id", body.id);

  Applies to any anonymous-to-authenticated ownership transfer: spec finalize,
  draft claim, session adoption, anonymous cart checkout. Cross-reference
  behavior.anonymous_allowed schema field (.claude/templates/experiment-yaml.md
  per #1126) — anonymous_allowed: true marks the create-route's page as public;
  the claim flow described here gates the OWNERSHIP transition.
prevention_mechanism: stack-knowledge-three-leg-pattern + uniform-404-rejection-collapses-enumeration-oracle
confidence_score: 0.9
occurrence_count: 1
linked_issues: [1376]
first_seen: 2026-05-11
last_seen: 2026-05-11
graduated_to: null
```

Anonymous flows that create resources (specs, drafts, sessions, carts) and let
authenticated users later claim them are vulnerable to horizontal privilege
escalation when the claim route trusts the row ID alone. Without `anon_session_id`
verification, any authenticated user can claim any anonymous resource by
submitting its UUID. Three failure shapes commonly seen during /verify on
anon→authed flows: (1) missing the column (Leg 1) — claim succeeds for everyone;
(2) missing the create-route write (Leg 2) — column exists but stays NULL,
claim either always passes or always fails depending on the comparison logic;
(3) differentiated rejection branches (403 for wrong session vs 404 for not
found vs 409 for already-claimed) — the response codes themselves leak resource
existence to enumeration attacks. Original incident: issue #1376, discovered
during /resolve open-issues round on a project with spec finalize + draft claim
flows.

### When a project extends /auth/callback to persist user_metadata to the database
Validate `user_metadata` fields with zod before any database write. The shipped `/auth/callback` template (above) only exchanges the PKCE code and redirects — it does NOT persist `user_metadata`. If a project adds a code path in the callback that reads `user_metadata` (e.g., to mirror signup into a `profiles` or `practices` table), the values cannot be trusted. An attacker can supply arbitrary values (e.g., a 50KB string in a name field) via a direct Supabase API call, bypassing UI form limits entirely. This is an A1 (OWASP) validation-bypass.

```ts
import { z } from "zod";

const metaSchema = z.object({
  practice_name: z.string().min(2).max(120),
  // add other user_metadata fields your callback persists
});

const parsed = metaSchema.safeParse(session.user.user_metadata);
if (!parsed.success) {
  return NextResponse.redirect(`${origin}/signup?error=invalid_metadata`);
}
// Use parsed.data for the database upsert
```

Apply this pattern whenever the callback route reads any `user_metadata` field and writes it to a database column. The shipped signup form already constrains values through UI length limits, but any direct Supabase API call bypasses those limits — zod validation on the server is the only defense.

### When stack.analytics is present, fire signup_complete from the callback route for OAuth/email-confirm/magic-link

The auth callback at `src/app/auth/callback/route.ts` is the shared chokepoint for three signup flows that bypass client-side analytics:

1. **OAuth signups** (Google, GitHub, etc.) — the page redirects to the provider before any client-side `trackSignupComplete()` can fire.
2. **Email-confirmation signups** — Supabase sends a confirmation link; the user lands on `/auth/callback` and the route redirects them. No client-side track call runs.
3. **Magic-link signups** — same callback path as email-confirmation.

If the activate-stage event (`signup_complete`) only fires from `signup/page.tsx` (which is what the legacy pattern documented), all three flows undercount: the activate-funnel KPI silently misses every OAuth / email-confirm / magic-link signup. Spec-reviewer flags this as a missing canonical event (S3/S4 failure).

The callback route is the right chokepoint to fire the event — it runs server-side for all three flows. Use the canonical event name `signup_complete` (singular, matches `experiment/EVENTS.yaml` and `analytics/posthog.md`).

**Filter by user.created_at recency** to avoid firing for returning users:

```ts
const { data: { user } } = await supabase.auth.getUser();
if (user && Date.now() - new Date(user.created_at).getTime() < 60_000) {
  const provider = (user.app_metadata?.provider as string | undefined) ?? "email";
  await trackServerEvent("signup_complete", user.id, { provider });
}
```

The 60-second recency check:
- **Catches** OAuth signup (user.created_at is set during the handshake), magic-link signup (same), prompt email-confirm signup (user clicks the confirmation link within seconds).
- **Skips** password-reset clickers (user.created_at is older), returning magic-link logins (same), and email-confirm clicks made >60s after signup.

**Edge case** — email confirmation with delayed click: if the user delays clicking the confirmation email past 60 seconds, `signup_complete` is missed. For projects where this matters, supplement with destination-page firing via `onAuthStateChange` (legacy pattern) or extend the recency window. The 60s default is tuned for the common case.

**Placement** — keep the `trackServerEvent` block AFTER the `DEMO_MODE` early return AND AFTER `exchangeCodeForSession` success. This matches the convention in `signup/page.tsx` and `login/page.tsx` (DEMO_MODE skips analytics calls). Firing under DEMO_MODE would pollute analytics during local dev / bootstrap demo walks.

**Conditional scaffolding** — when `stack.analytics` is absent, remove the `trackServerEvent` import line AND the entire `const { data: { user } } ...` block (lines 7 lines total in the callback template). Both shared-client and standalone-client variants follow the same pattern; the only diff between them is the `createServerSupabaseClient` import source.

## PR Instructions
- Email confirmation is enabled by default in Supabase. The signup form handles this: when `signUp()` returns `session: null`, it shows a "check your email" message instead of redirecting. Users who confirm their email can then log in normally.
- The signup form passes `emailRedirectTo` pointing to `/auth/callback`, which exchanges the PKCE code for a session and redirects to `/`. This requires the production URL to be in Supabase's redirect allow-list (configured by `/deploy`).
- The signup form detects duplicate emails by checking `data.user.identities` — when Supabase returns a user with zero identities, it means the email already exists. The form shows "An account with this email already exists" instead of the misleading "check your email" message.
- The login page includes a "Forgot password?" link that toggles an inline reset form. It calls `resetPasswordForEmail()` with a redirect to `/auth/callback?next=/auth/reset-password`. After clicking the email link, the callback route exchanges the code and redirects to the reset-password page where the user sets a new password.
- Test the signup flow end-to-end: create an account → see "check your email" message → confirm email → callback route exchanges code → auto-redirected into the app as a logged-in user
- Test duplicate email: sign up with an existing email → see "already exists" error instead of "check your email"
- Test forgot password: click "Forgot password?" on login → enter email → see "check your email for a reset link" → click link → land on reset-password page → set new password → redirected to app
- If the callback fails (expired or invalid code), the user is redirected to `/login?error=auth` and sees an error banner

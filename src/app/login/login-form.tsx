"use client";

import { useId, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, ArrowRight, Eye, EyeOff, LoaderCircle, MailCheck } from "lucide-react";
import { createClient } from "@/lib/supabase";
import { GOOGLE_SIGN_IN_ENABLED } from "@/lib/auth-providers";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";

/** Where a returning owner lands when the proxy did not ask for somewhere else. */
const DEFAULT_DESTINATION = "/dashboard";

/**
 * `src/proxy.ts` redirects unauthenticated requests to `/login?next=<path>`.
 * Only same-origin absolute paths are honoured — anything else turns a real
 * tipguard.app login into a phishing hop. Kept byte-for-byte in step with
 * `safeDestination()` in `src/app/auth/callback/route.ts`; the three bypasses
 * a naive `startsWith("//")` check misses:
 *   - `//evil.example` is protocol-relative — a host, not a path.
 *   - `/\evil.example` is the same thing: browsers normalize `\` to `/` while
 *     resolving, so the backslash form has to be rejected outright.
 *   - `%2f%2fevil.example` is already decoded by `searchParams.get()`, so the
 *     check must run on the decoded value (it does — `next` comes from
 *     searchParams, never from the raw query string).
 * Resolution against the page origin plus an origin comparison is the backstop
 * for anything not enumerated above.
 */
function safeDestination(next: string | null): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.includes("\\")) {
    return DEFAULT_DESTINATION;
  }
  if (typeof window === "undefined") return next;
  try {
    const resolved = new URL(next, window.location.origin);
    return resolved.origin === window.location.origin
      ? `${resolved.pathname}${resolved.search}${resolved.hash}`
      : DEFAULT_DESTINATION;
  } catch {
    return DEFAULT_DESTINATION;
  }
}

export function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const emailId = useId();
  const passwordId = useId();
  const resetEmailId = useId();

  const destination = safeDestination(searchParams.get("next"));
  const emailConfirmed = searchParams.get("confirmed") === "true";
  const errorParam = searchParams.get("error");

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [revealPassword, setRevealPassword] = useState(false);
  const [formError, setFormError] = useState("");
  const [submitting, setSubmitting] = useState<"password" | "google" | "reset" | null>(null);
  const [mode, setMode] = useState<"login" | "forgot">("login");
  const [resetSentTo, setResetSentTo] = useState("");

  async function handleLogin(event: React.SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting("password");
    setFormError("");
    const supabase = createClient();
    const { error: signInError } = await supabase.auth.signInWithPassword({
      email: email.trim(),
      password,
    });
    if (signInError) {
      setSubmitting(null);
      setFormError(signInError.message);
      return;
    }
    router.push(destination);
    router.refresh();
  }

  async function handleForgotPassword(event: React.SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting("reset");
    setFormError("");
    const supabase = createClient();
    const { error: resetError } = await supabase.auth.resetPasswordForEmail(email.trim(), {
      redirectTo: `${window.location.origin}/auth/callback?next=/auth/reset-password`,
    });
    setSubmitting(null);
    if (resetError) {
      setFormError(resetError.message);
      return;
    }
    setResetSentTo(email.trim());
  }

  async function handleGoogleLogin() {
    setSubmitting("google");
    setFormError("");
    // No signup_start here. EVENTS.yaml scopes that event to the /signup page
    // mount; the login page cannot tell a new account from a returning one at
    // click time, so firing it here would count every returning Google sign-in
    // as a signup start and deflate the activate-stage conversion rate.
    const supabase = createClient();
    const { error: oauthError } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: {
        redirectTo: `${window.location.origin}/auth/callback?next=${destination}`,
      },
    });
    if (oauthError) {
      setSubmitting(null);
      setFormError(oauthError.message);
    }
  }

  return (
    <div>
      {/* Arrival banners — rendered from query params present at first paint. */}
      {emailConfirmed ? (
        <Alert className="mb-6 border-transparent bg-seal/10 text-foreground ring-1 ring-seal/30">
          <AlertTitle className="text-seal">Email confirmed</AlertTitle>
          <AlertDescription>Log in to open your file.</AlertDescription>
        </Alert>
      ) : null}

      {errorParam === "oauth_email_missing" ? (
        <Alert className="mb-6 border-transparent bg-destructive/10 text-foreground ring-1 ring-destructive/30">
          <AlertTitle className="text-destructive">
            We need your email address to open an account
          </AlertTitle>
          <AlertDescription className="text-muted-foreground">
            Google did not share an email with us. Two ways forward:
            <ul className="ml-4 mt-2 list-disc space-y-1">
              <li>Use the email and password form below.</li>
              <li>
                Retry Google sign-in and allow access to your email address on the
                consent screen.
              </li>
            </ul>
          </AlertDescription>
        </Alert>
      ) : null}

      {errorParam && errorParam !== "oauth_email_missing" ? (
        <Alert className="mb-6 border-transparent bg-destructive/10 text-foreground ring-1 ring-destructive/30">
          <AlertTitle className="text-destructive">Sign-in link expired</AlertTitle>
          <AlertDescription className="text-muted-foreground">
            That link is no longer valid. Log in below, or request a fresh reset
            link with &ldquo;Forgot password&rdquo;.
          </AlertDescription>
        </Alert>
      ) : null}

      {mode === "forgot" ? (
        resetSentTo ? (
          <div className="animate-in fade-in-0 slide-in-from-bottom-2 duration-300">
            <div className="elev-1 rounded-xl bg-card p-6">
              <span className="inline-flex h-11 w-11 items-center justify-center rounded-full bg-seal/10">
                <MailCheck className="h-5 w-5 text-seal" aria-hidden="true" />
              </span>
              <p className="mt-4 text-base font-medium">Reset link sent</p>
              <p className="mt-2 text-sm leading-[1.5] text-muted-foreground">
                Check <span className="font-mono text-foreground">{resetSentTo}</span>{" "}
                for a link to set a new password. It expires in one hour.
              </p>
            </div>
            <Button
              type="button"
              variant="ghost"
              onClick={() => {
                setMode("login");
                setResetSentTo("");
                setFormError("");
              }}
              className="mt-4 h-11 px-3 text-sm"
            >
              <ArrowLeft className="h-4 w-4" aria-hidden="true" />
              Back to log in
            </Button>
          </div>
        ) : (
          <form
            onSubmit={handleForgotPassword}
            className="elev-1 animate-in fade-in-0 rounded-xl bg-card p-6 duration-200"
          >
            <div className="grid gap-2">
              <Label htmlFor={resetEmailId}>Email on the account</Label>
              <Input
                id={resetEmailId}
                name="reset-email"
                type="email"
                inputMode="email"
                autoComplete="email"
                placeholder="owner@yourrestaurant.com"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                required
                className="h-11 rounded-md bg-background text-base md:text-base"
              />
              <p className="text-sm text-muted-foreground">
                We send a one-hour link that lets you set a new password.
              </p>
            </div>

            <ErrorRegion message={formError} className="mt-5" />

            <Button
              type="submit"
              disabled={submitting !== null}
              aria-label={submitting === "reset" ? "Sending reset link" : undefined}
              className="mt-6 h-11 w-full rounded-full px-6 text-base font-medium transition-all duration-[140ms] hover:brightness-95"
            >
              {submitting === "reset" ? (
                <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : (
                "Send reset link"
              )}
            </Button>

            <Button
              type="button"
              variant="ghost"
              onClick={() => {
                setMode("login");
                setFormError("");
              }}
              className="mt-3 h-11 w-full px-3 text-sm"
            >
              <ArrowLeft className="h-4 w-4" aria-hidden="true" />
              Back to log in
            </Button>
          </form>
        )
      ) : (
        <form
          onSubmit={handleLogin}
          className="elev-1 animate-in fade-in-0 zoom-in-95 rounded-xl bg-card p-6 duration-500"
        >
          <div className="grid gap-2">
            <Label htmlFor={emailId}>Email</Label>
            <Input
              id={emailId}
              name="email"
              type="email"
              inputMode="email"
              autoComplete="email"
              placeholder="owner@yourrestaurant.com"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
              className="h-11 rounded-md text-base md:text-base"
            />
          </div>

          <div className="mt-5 grid gap-2">
            <div className="flex items-center justify-between gap-3">
              <Label htmlFor={passwordId}>Password</Label>
              {/* -my-3 keeps this label row on its 20px rhythm while the
                  button itself holds a 44px tap target on touch screens. */}
              <Button
                type="button"
                variant="link"
                onClick={() => {
                  setMode("forgot");
                  setFormError("");
                }}
                className="-my-3 h-11 px-1 text-sm text-muted-foreground hover:text-brass-deep"
              >
                Forgot password?
              </Button>
            </div>
            <div className="relative">
              <Input
                id={passwordId}
                name="password"
                type={revealPassword ? "text" : "password"}
                autoComplete="current-password"
                placeholder="Your password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
                className="h-11 rounded-md bg-background pr-12 text-base md:text-base"
              />
              <Button
                type="button"
                variant="ghost"
                size="icon"
                onClick={() => setRevealPassword((prev) => !prev)}
                aria-label={revealPassword ? "Hide password" : "Show password"}
                aria-pressed={revealPassword}
                className="absolute right-0 top-0 h-11 w-11 rounded-md text-muted-foreground hover:text-foreground"
              >
                {revealPassword ? (
                  <EyeOff className="h-4 w-4" aria-hidden="true" />
                ) : (
                  <Eye className="h-4 w-4" aria-hidden="true" />
                )}
              </Button>
            </div>
          </div>

          <ErrorRegion message={formError} className="mt-5" />

          <Button
            type="submit"
            disabled={submitting !== null}
            aria-label={submitting === "password" ? "Signing you in" : undefined}
            className="mt-6 h-11 w-full rounded-full px-6 text-base font-medium transition-all duration-[140ms] hover:brightness-95"
          >
            {submitting === "password" ? (
              <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : (
              <>
                Open my file
                <ArrowRight className="h-4 w-4" aria-hidden="true" />
              </>
            )}
          </Button>

          {/* Rendered only when the provider is actually enabled on Supabase —
              see src/lib/auth-providers.ts. A button that 400s is worse than no
              button at all on the primary auth path. */}
          {GOOGLE_SIGN_IN_ENABLED ? (
            <>
          <div className="relative my-7">
            <Separator />
            {/* bg must match the card the form sits in, not the page. nowrap
                because inside the card the column is ~279px on a 375px screen
                and a wrapped label collides with the rule it sits on. */}
            <span className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 whitespace-nowrap bg-card px-3 font-mono text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
              Or continue with
            </span>
          </div>

          <Button
            type="button"
            variant="outline"
            onClick={handleGoogleLogin}
            disabled={submitting !== null}
            aria-label={submitting === "google" ? "Redirecting to Google" : undefined}
            className="h-11 w-full rounded-md text-base font-medium"
          >
            {submitting === "google" ? (
              <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : (
              <>
                <GoogleGlyph />
                Continue with Google
              </>
            )}
          </Button>
            </>
          ) : null}
        </form>
      )}

      <p className="mt-8 text-sm text-muted-foreground">
        No account yet?{" "}
        <Link
          href="/score"
          className="font-medium text-foreground underline decoration-brass decoration-2 underline-offset-4 transition-colors duration-[140ms] hover:text-brass-deep"
        >
          Get your free audit-readiness score
        </Link>{" "}
        &mdash; it takes two minutes and needs no account.
      </p>
    </div>
  );
}

/* -------------------------------------------------------------------------- */

/**
 * Live region mounted from first paint (WCAG 4.1.3). Conditionally *inserting*
 * a `role="alert"` node means some screen readers never announce it.
 */
function ErrorRegion({ message, className }: { message: string; className?: string }) {
  return (
    <p
      role="alert"
      aria-live="assertive"
      className={cn(
        message
          ? "rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive"
          : "sr-only",
        message ? className : undefined,
      )}
    >
      {message}
    </p>
  );
}

/**
 * Monochrome Google mark. The project palette forbids cool hues, so the
 * four-colour brand mark is rendered in `currentColor` rather than dropped.
 */
function GoogleGlyph() {
  return (
    <svg viewBox="0 0 24 24" className="h-4 w-4" aria-hidden="true" focusable="false">
      <path
        fill="currentColor"
        d="M21.35 11.1h-9.17v2.73h6.51c-.33 3.81-3.5 5.44-6.5 5.44C8.36 19.27 5 16.25 5 12c0-4.1 3.2-7.27 7.2-7.27 3.09 0 4.9 1.97 4.9 1.97L19 4.72S16.56 2 12.1 2C6.42 2 2.03 6.8 2.03 12c0 5.05 4.13 10 10.22 10 5.35 0 9.25-3.67 9.25-9.09 0-1.15-.15-1.81-.15-1.81Z"
      />
    </svg>
  );
}

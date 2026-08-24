"use client";

import { useId, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  ArrowRight,
  Check,
  Eye,
  EyeOff,
  LoaderCircle,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react";
import { createClient } from "@/lib/supabase";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

const MIN_PASSWORD_LENGTH = 8;
const TOO_SHORT = `Password must be at least ${MIN_PASSWORD_LENGTH} characters`;

/**
 * Turn a raw Supabase auth message into something a locked-out owner can act
 * on. The most common failure here is a consumed or expired recovery link,
 * which surfaces as "Auth session missing!" — meaningless to the operator and
 * a dead end without a route back to a fresh link.
 */
function describeError(raw: string): {
  title: string;
  detail: string;
  recoverable: boolean;
} {
  if (raw === TOO_SHORT) {
    return {
      title: "That password is too short",
      detail: "Add a few more characters and try again.",
      recoverable: false,
    };
  }
  if (/session|expired|invalid|token|jwt|not\s*found/i.test(raw)) {
    return {
      title: "This reset link has expired",
      detail:
        "Reset links last one hour and work only once. Request a fresh one and we will email it right away.",
      recoverable: true,
    };
  }
  if (/different from the old|should be different|same.*password/i.test(raw)) {
    return {
      title: "Choose a different password",
      detail: "That is the password already on the account.",
      recoverable: false,
    };
  }
  return { title: "We could not save that password", detail: raw, recoverable: false };
}

/**
 * Set a new password after clicking the reset link. `/auth/callback` has
 * already exchanged the PKCE code, so an active session exists by the time
 * this page renders.
 *
 * Landmark note: this page deliberately does NOT render <main>.
 * `src/app/layout.tsx` owns the single `<main id="main-content">` landmark for
 * every route (axe `landmark-no-duplicate-main`).
 */
export default function ResetPasswordPage() {
  const passwordId = useId();
  const hintId = useId();
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [reveal, setReveal] = useState(false);
  const [saved, setSaved] = useState(false);

  const meetsLength = password.length >= MIN_PASSWORD_LENGTH;
  const described = error ? describeError(error) : null;

  async function handleReset(event: React.SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    if (password.length < MIN_PASSWORD_LENGTH) {
      setError(TOO_SHORT);
      return;
    }
    setLoading(true);
    setError("");
    const supabase = createClient();
    const { error: updateError } = await supabase.auth.updateUser({ password });
    setLoading(false);
    if (updateError) {
      setError(updateError.message);
      return;
    }
    setSaved(true);
    router.push("/dashboard");
  }

  return (
    <div className="texture-rule relative min-h-screen">
      <div aria-hidden="true" className="bloom-brass pointer-events-none absolute inset-0" />

      <div className="relative mx-auto flex min-h-screen max-w-md flex-col justify-start px-5 pt-10 pb-10 sm:px-8">
        <div className="duration-[420ms] animate-in fade-in slide-in-from-bottom-2 fill-mode-both">
          {/* Entry point is an emailed link — the operator arrives with no
              navigation context, so the page has to identify itself. The mark
              is also the only route out of here, so it links home. */}
          <Link
            href="/"
            className="-mx-1 inline-flex items-center gap-3 rounded-sm px-1 transition-opacity duration-[var(--duration-fast)] hover:opacity-80 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brass"
          >
            <span className="inline-flex h-11 w-11 items-center justify-center rounded-full bg-brass/15 ring-1 ring-brass/25">
              <ShieldCheck className="h-5 w-5 text-brass-deep" aria-hidden="true" />
            </span>
            <span className="font-display text-lg leading-none tracking-[-0.6px] [word-spacing:0.06em]">
              TipGuard
            </span>
          </Link>

          <p className="eyebrow mt-8">Account access</p>
          <h1 className="mt-2 font-display text-[26px] leading-[1.06] tracking-[-0.025em] [word-spacing:0.06em] sm:text-[32px]">
            Set a new password
          </h1>
          <p className="mt-4 text-base leading-[1.55] text-muted-foreground">
            Choose a new password for your TipGuard account. You will land back on
            your compliance file once it is saved.
          </p>

          <div className="mt-8 rounded-xl bg-card p-6 elev-1 sm:p-7">
            {/* Always-mounted status region: a conditionally inserted live
                region is not registered at load and the announcement drops. */}
            <p role="status" aria-live="polite" className="sr-only">
              {saved ? "Password updated. Returning to your compliance file." : ""}
            </p>

            {saved ? (
              <div className="duration-300 animate-in fade-in-0 slide-in-from-bottom-2">
                <span className="inline-flex h-11 w-11 items-center justify-center rounded-full bg-seal/10">
                  <ShieldCheck className="h-5 w-5 text-seal" aria-hidden="true" />
                </span>
                <p className="mt-4 text-base font-medium">Password updated</p>
                <p className="mt-2 text-sm leading-[1.5] text-muted-foreground">
                  Taking you back to your compliance file&hellip;
                </p>
              </div>
            ) : (
              <form onSubmit={handleReset} noValidate>
                <div className="grid gap-2">
                  <Label htmlFor={passwordId} className="text-sm font-medium">
                    New password
                  </Label>
                  <div className="relative">
                    <Input
                      id={passwordId}
                      name="password"
                      type={reveal ? "text" : "password"}
                      autoComplete="new-password"
                      placeholder="Enter a new password"
                      value={password}
                      onChange={(event) => {
                        setPassword(event.target.value);
                        if (error) setError("");
                      }}
                      required
                      minLength={MIN_PASSWORD_LENGTH}
                      aria-invalid={Boolean(error)}
                      aria-describedby={hintId}
                      className="h-11 rounded-md pr-12 text-base md:text-base"
                    />
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      onClick={() => setReveal((prev) => !prev)}
                      aria-label={reveal ? "Hide password" : "Show password"}
                      aria-pressed={reveal}
                      className="absolute right-0 top-0 h-11 w-11 rounded-md text-muted-foreground hover:text-foreground"
                    >
                      {reveal ? (
                        <EyeOff className="h-4 w-4" aria-hidden="true" />
                      ) : (
                        <Eye className="h-4 w-4" aria-hidden="true" />
                      )}
                    </Button>
                  </div>
                  {/* The rule stays visible while typing — a placeholder states
                      it only until the moment it starts to matter. */}
                  <p
                    id={hintId}
                    className="flex items-center gap-1.5 text-sm text-muted-foreground"
                  >
                    <Check
                      className={cn(
                        "h-3.5 w-3.5 transition-colors duration-[140ms]",
                        meetsLength ? "text-seal" : "text-muted-foreground/40"
                      )}
                      aria-hidden="true"
                    />
                    At least {MIN_PASSWORD_LENGTH} characters
                  </p>
                </div>

                {/* Live region mounted from first paint (WCAG 4.1.3) — only its
                    visibility flips when an error arrives. */}
                <p
                  role="alert"
                  aria-live="assertive"
                  className={cn(
                    described
                      ? "mt-5 flex items-start gap-2.5 rounded-md bg-destructive/10 px-3 py-2.5 text-sm ring-1 ring-destructive/25"
                      : "sr-only"
                  )}
                >
                  {described ? (
                    <>
                      <TriangleAlert
                        className="mt-0.5 h-4 w-4 shrink-0 text-destructive"
                        aria-hidden="true"
                      />
                      <span>
                        <span className="font-medium text-destructive">
                          {described.title}
                        </span>
                        <span className="mt-0.5 block leading-[1.5] text-muted-foreground">
                          {described.detail}
                          {described.recoverable ? (
                            <>
                              {" "}
                              <Link
                                href="/login"
                                className="font-medium text-foreground underline decoration-brass decoration-2 underline-offset-4 transition-colors duration-[140ms] hover:text-brass-deep"
                              >
                                Request a new link
                              </Link>
                            </>
                          ) : null}
                        </span>
                      </span>
                    </>
                  ) : (
                    ""
                  )}
                </p>

                <Button
                  type="submit"
                  disabled={loading}
                  aria-label={loading ? "Updating your password" : undefined}
                  className="mt-6 h-11 w-full rounded-full px-6 text-base font-medium transition-all duration-[140ms] hover:brightness-95"
                >
                  {loading ? (
                    <>
                      <LoaderCircle
                        className="h-4 w-4 animate-spin"
                        aria-hidden="true"
                      />
                      Saving your password
                    </>
                  ) : (
                    <>
                      Set new password
                      <ArrowRight className="h-4 w-4" aria-hidden="true" />
                    </>
                  )}
                </Button>
              </form>
            )}
          </div>

          <p className="mt-8 text-sm text-muted-foreground">
            Link not working?{" "}
            <Link
              href="/login"
              className="font-medium text-foreground underline decoration-brass decoration-2 underline-offset-4 transition-colors duration-[140ms] hover:text-brass-deep"
            >
              Request a fresh one
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}

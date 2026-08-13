"use client";

import { useId, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ArrowRight, Check, Eye, EyeOff, LoaderCircle, MailCheck } from "lucide-react";
import { createClient } from "@/lib/supabase";
import { trackSignupComplete } from "@/lib/events";
import { Button, buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";
import { clearPendingScore, type PendingScore } from "@/app/score/pending-score";
import { formatUsd, scoreBand } from "./score-format";

/**
 * Where the owner lands once a session exists. `/dashboard` is the first
 * authenticated surface and renders the carried score (b-03).
 */
const POST_AUTH_DESTINATION = "/dashboard";

/**
 * Persists the anonymous questionnaire result onto the freshly created account
 * row (b-03). Owned by scaffold-wire (STATE 14) alongside the other API routes;
 * until it exists this POST 404s, which is why the call is non-blocking and the
 * pending record is only cleared on a confirmed write.
 */
const ATTACH_SCORE_ENDPOINT = "/api/account/score";

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const MIN_PASSWORD_LENGTH = 8;

export function SignupForm({ pending }: { pending: PendingScore | null | undefined }) {
  const router = useRouter();
  const emailId = useId();
  const passwordId = useId();
  const passwordHintId = useId();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [revealPassword, setRevealPassword] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<{ email?: string; password?: string }>({});
  const [formError, setFormError] = useState("");
  const [confirmationSentTo, setConfirmationSentTo] = useState("");
  const [submitting, setSubmitting] = useState<"email" | "google" | null>(null);

  const passwordLongEnough = password.length >= MIN_PASSWORD_LENGTH;

  /**
   * Attaches the carried score to the new account. Never throws and never
   * blocks the redirect — a failed attach leaves the record in sessionStorage
   * so `/dashboard` can retry the claim.
   */
  async function attachPendingScore(record: PendingScore): Promise<void> {
    try {
      const response = await fetch(ATTACH_SCORE_ENDPOINT, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          state: record.state,
          claims_tip_credit: record.claimsTipCredit,
          staff_count: record.staffCount,
          readiness_score: record.readinessScore,
          gap_list: record.gaps,
          estimated_exposure_usd: record.estimatedExposureUsd,
          saved_at: record.savedAt,
        }),
      });
      if (response.ok) clearPendingScore();
    } catch {
      // Offline or route not yet deployed — keep the record for a later claim.
    }
  }

  async function handleSignup(event: React.SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();

    const nextFieldErrors: { email?: string; password?: string } = {};
    if (!EMAIL_PATTERN.test(email.trim())) {
      nextFieldErrors.email = "Enter a valid email address, e.g. owner@yourrestaurant.com";
    }
    if (!passwordLongEnough) {
      nextFieldErrors.password = `Use at least ${MIN_PASSWORD_LENGTH} characters.`;
    }
    setFieldErrors(nextFieldErrors);
    if (nextFieldErrors.email || nextFieldErrors.password) return;

    setSubmitting("email");
    setFormError("");

    const supabase = createClient();
    const { data, error: authError } = await supabase.auth.signUp({
      email: email.trim(),
      password,
      options: {
        emailRedirectTo: `${window.location.origin}/auth/callback?next=${POST_AUTH_DESTINATION}`,
      },
    });

    if (authError) {
      setSubmitting(null);
      setFormError(authError.message);
      return;
    }

    // Supabase returns a user with zero identities when the email is already
    // registered — surfacing "check your email" here would be a dead end.
    if (data.user?.identities?.length === 0) {
      setSubmitting(null);
      setFormError("An account with this email already exists. Log in instead.");
      return;
    }

    // Email confirmation is on: no session yet, so the callback route fires
    // signup_complete server-side once the owner clicks through.
    if (!data.session) {
      setSubmitting(null);
      setConfirmationSentTo(email.trim());
      return;
    }

    if (pending) await attachPendingScore(pending);
    trackSignupComplete({ auth_method: "email", had_score: Boolean(pending) });
    router.push(POST_AUTH_DESTINATION);
  }

  async function handleGoogleSignup() {
    setSubmitting("google");
    setFormError("");
    // `signup_start` already fired once on mount with auth_method "both" — the
    // page-level trigger EVENTS.yaml specifies. Re-firing here would
    // double-count every Google signup against the same visit.
    const supabase = createClient();
    const { error: oauthError } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: {
        redirectTo: `${window.location.origin}/auth/callback?next=${POST_AUTH_DESTINATION}`,
      },
    });
    if (oauthError) {
      setSubmitting(null);
      setFormError(oauthError.message);
    }
  }

  if (confirmationSentTo) {
    return <ConfirmationSent email={confirmationSentTo} />;
  }

  return (
    <div>
      {pending ? <CarrySummary pending={pending} /> : null}

      <form onSubmit={handleSignup} noValidate className="mt-8">
        <div className="grid gap-2">
          <Label htmlFor={emailId} className="text-sm font-medium">
            Work email
          </Label>
          <Input
            id={emailId}
            name="email"
            type="email"
            inputMode="email"
            autoComplete="email"
            placeholder="owner@yourrestaurant.com"
            value={email}
            onChange={(event) => {
              setEmail(event.target.value);
              if (fieldErrors.email) setFieldErrors((prev) => ({ ...prev, email: undefined }));
            }}
            required
            aria-invalid={Boolean(fieldErrors.email)}
            aria-describedby={fieldErrors.email ? `${emailId}-error` : undefined}
            className="h-11 rounded-md text-base md:text-base"
          />
          <p
            id={`${emailId}-error`}
            className={cn(
              "text-sm text-destructive",
              fieldErrors.email ? "" : "sr-only",
            )}
          >
            {fieldErrors.email ?? ""}
          </p>
        </div>

        <div className="mt-5 grid gap-2">
          <Label htmlFor={passwordId} className="text-sm font-medium">
            Password
          </Label>
          <div className="relative">
            <Input
              id={passwordId}
              name="password"
              type={revealPassword ? "text" : "password"}
              autoComplete="new-password"
              // Not "At least 8 characters" — the rule already lives in the
              // hint 8px below, and rendering the same sentence twice inside
              // one field group reads as a bug.
              placeholder="Create a password"
              value={password}
              onChange={(event) => {
                setPassword(event.target.value);
                if (fieldErrors.password) {
                  setFieldErrors((prev) => ({ ...prev, password: undefined }));
                }
              }}
              required
              minLength={MIN_PASSWORD_LENGTH}
              aria-invalid={Boolean(fieldErrors.password)}
              aria-describedby={`${passwordHintId}${fieldErrors.password ? ` ${passwordId}-error` : ""}`}
              className="h-11 rounded-md pr-12 text-base md:text-base"
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

          <p
            id={passwordHintId}
            className={cn(
              "flex items-center gap-1.5 text-sm transition-colors duration-[140ms]",
              passwordLongEnough ? "text-seal" : "text-muted-foreground",
            )}
          >
            <Check
              className={cn(
                "h-3.5 w-3.5 transition-all duration-[140ms] ease-[cubic-bezier(0.2,0.9,0.24,1)]",
                passwordLongEnough ? "scale-100 opacity-100" : "scale-75 opacity-40",
              )}
              aria-hidden="true"
            />
            At least {MIN_PASSWORD_LENGTH} characters
          </p>

          <p
            id={`${passwordId}-error`}
            className={cn(
              "text-sm text-destructive",
              fieldErrors.password ? "" : "sr-only",
            )}
          >
            {fieldErrors.password ?? ""}
          </p>
        </div>

        {/* Live region is mounted from first paint (WCAG 4.1.3) — only its
            visibility flips when an auth error arrives. */}
        <p
          role="alert"
          aria-live="assertive"
          className={cn(
            "mt-5 rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive",
            formError ? "" : "sr-only",
          )}
        >
          {formError}
        </p>

        <Button
          type="submit"
          disabled={submitting !== null}
          aria-label={submitting === "email" ? "Creating your account" : undefined}
          className="mt-7 h-11 w-full rounded-full px-6 text-base font-medium transition-all duration-[140ms] hover:brightness-95"
        >
          {submitting === "email" ? (
            <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" />
          ) : (
            <>
              {pending ? "Save my score and open my file" : "Create my compliance file"}
              <ArrowRight className="h-4 w-4" aria-hidden="true" />
            </>
          )}
        </Button>

        <p className="mt-4 text-center text-sm text-muted-foreground">
          Free while you close your gaps. No card required.
        </p>
      </form>

      <div className="relative my-8">
        <Separator />
        <span className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 bg-background px-3 font-mono text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
          Or continue with
        </span>
      </div>

      <Button
        type="button"
        variant="outline"
        onClick={handleGoogleSignup}
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

      <p className="mt-8 text-sm text-muted-foreground">
        Already have an account?{" "}
        <Link
          href="/login"
          className="font-medium text-foreground underline decoration-brass decoration-2 underline-offset-4 transition-colors duration-[140ms] hover:text-brass-deep"
        >
          Log in
        </Link>
      </p>
    </div>
  );
}

/* -------------------------------------------------------------------------- */

/**
 * Paper-scope band styling for the carry strip. The ink rail owns the dark
 * variants; these are the deep tokens, which are the ones that hold contrast
 * against `--paper`.
 */
const CARRY_BAND = {
  critical: { text: "text-ember", rule: "border-l-ember", label: "Critical exposure" },
  "at-risk": { text: "text-brass-deep", rule: "border-l-brass", label: "At risk" },
  clear: { text: "text-seal", rule: "border-l-seal", label: "Largely clear" },
} as const;

/**
 * Compact confirmation that the carried score survives the signup step.
 *
 * Mobile-only: below `lg` the evidence rail is a full screen away, so this
 * strip is the only carried-score evidence above the fold — and therefore the
 * one that has to carry the severity, not just the figure. A neutral "38/100"
 * reads as a receipt; the banded figure reads as the reason to finish signing
 * up (b-03 → h-03).
 */
function CarrySummary({ pending }: { pending: PendingScore }) {
  const { low, high } = pending.estimatedExposureUsd;
  const band = CARRY_BAND[scoreBand(pending.readinessScore)];
  return (
    <div
      className={cn(
        "elev-1 flex flex-wrap items-baseline gap-x-5 gap-y-2 rounded-lg border-l-2 bg-card px-4 py-3 lg:hidden",
        band.rule,
      )}
    >
      <span
        className={cn(
          "font-mono text-2xl font-medium tabular-nums tracking-[-0.2px]",
          band.text,
        )}
      >
        {pending.readinessScore}
        <span className="text-base text-muted-foreground">/100</span>
      </span>
      <span
        className={cn(
          "font-mono text-[11px] font-medium uppercase tracking-[0.1em]",
          band.text,
        )}
      >
        {band.label}
      </span>
      <span className="w-full font-mono text-sm tabular-nums text-muted-foreground">
        {pending.gaps.length} {pending.gaps.length === 1 ? "gap" : "gaps"}
        {high > 0 ? ` · ${formatUsd(low)}–${formatUsd(high)} exposure` : ""}
      </span>
      <span className="w-full font-mono text-[11px] uppercase tracking-[0.14em] text-brass-deep">
        Attaches to your account
      </span>
    </div>
  );
}

/** Terminal state when Supabase requires email confirmation before a session. */
function ConfirmationSent({ email }: { email: string }) {
  return (
    <div className="animate-in fade-in-0 slide-in-from-bottom-2 duration-300">
      <div className="elev-2 rounded-xl bg-card p-6">
        <span className="inline-flex h-11 w-11 items-center justify-center rounded-full bg-seal/10">
          <MailCheck className="h-5 w-5 text-seal" aria-hidden="true" />
        </span>
        <h2 className="mt-5 font-display text-2xl leading-[1.15] tracking-[-1.2px]">
          Confirm your email to open the file
        </h2>
        <p className="mt-3 text-base leading-[1.55] text-muted-foreground">
          We sent a confirmation link to{" "}
          <span className="font-mono text-foreground">{email}</span>. Click it and
          you land straight on your dashboard with your score attached.
        </p>
        <p className="mt-4 font-mono text-[11px] uppercase tracking-[0.14em] text-brass-deep">
          Your score is held on this device until you confirm
        </p>
      </div>

      <p className="mt-6 text-sm text-muted-foreground">
        Already confirmed?{" "}
        <Link
          href="/login"
          className="font-medium text-foreground underline decoration-brass decoration-2 underline-offset-4 transition-colors duration-[140ms] hover:text-brass-deep"
        >
          Log in
        </Link>
        {" · "}
        Wrong address?{" "}
        <Link
          href="/signup"
          className={cn(
            buttonVariants({ variant: "link" }),
            "h-auto p-0 text-sm text-foreground",
          )}
        >
          Start over
        </Link>
      </p>
    </div>
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

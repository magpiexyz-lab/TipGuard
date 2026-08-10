"use client";

import { useId, useState } from "react";
import { useRouter } from "next/navigation";
import { LoaderCircle } from "lucide-react";
import { createClient } from "@/lib/supabase";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

const MIN_PASSWORD_LENGTH = 8;

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
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleReset(event: React.SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    if (password.length < MIN_PASSWORD_LENGTH) {
      setError(`Password must be at least ${MIN_PASSWORD_LENGTH} characters`);
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
    router.push("/dashboard");
  }

  return (
    <div className="texture-rule min-h-screen">
      <div className="mx-auto flex max-w-md flex-col justify-center px-5 py-16 sm:px-8">
        <p className="eyebrow">Account access</p>
        <h1 className="mt-3 font-display text-[34px] leading-[1.06] tracking-[-1.6px]">
          Set a new password
        </h1>
        <p className="mt-4 text-base leading-[1.55] text-muted-foreground">
          Choose a new password for your TipGuard account. You will land back on
          your compliance file once it is saved.
        </p>

        <form onSubmit={handleReset} noValidate className="mt-8">
          <div className="grid gap-2">
            <Label htmlFor={passwordId} className="text-sm font-medium">
              New password
            </Label>
            <Input
              id={passwordId}
              name="password"
              type="password"
              autoComplete="new-password"
              placeholder={`At least ${MIN_PASSWORD_LENGTH} characters`}
              value={password}
              onChange={(event) => {
                setPassword(event.target.value);
                if (error) setError("");
              }}
              required
              minLength={MIN_PASSWORD_LENGTH}
              aria-invalid={Boolean(error)}
              className="h-11 rounded-md text-base md:text-base"
            />
          </div>

          {/* Live region mounted from first paint (WCAG 4.1.3) — only its
              visibility flips when an error arrives. */}
          <p
            role="alert"
            aria-live="assertive"
            className={cn(
              "mt-5 rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive",
              error ? "" : "sr-only"
            )}
          >
            {error}
          </p>

          <Button
            type="submit"
            disabled={loading}
            aria-label={loading ? "Updating your password" : undefined}
            className="mt-7 h-11 w-full rounded-full px-6 text-base font-medium"
          >
            {loading ? (
              <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : (
              "Set new password"
            )}
          </Button>
        </form>
      </div>
    </div>
  );
}

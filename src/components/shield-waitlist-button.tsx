"use client";

import { useState } from "react";
import { Check, Loader2, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { trackCheckoutStarted, trackWaitlistJoined } from "@/lib/events";
import { cn } from "@/lib/utils";

/**
 * Upgrade CTA for behavior b-10, and the waitlist fake door for b-11.
 *
 * Shield is not purchasable yet. The experiment measures whether owners *want*
 * it at $79/mo, and h-06 is scored on `checkout_started / notice_sent` — an
 * event that always fired on the click, before any redirect. So the click
 * still produces the hypothesis metric; what used to be a Stripe redirect is
 * now a panel that captures the address.
 *
 * `checkout_started` fires on the click and NOT on the join, deliberately: the
 * denominator of h-06 must not move because we changed what happens after the
 * click. The gap between `checkout_started` and `waitlist_joined` is the read
 * on how much of that intent survives being asked for something.
 *
 * Contract with `src/app/api/waitlist/route.ts`:
 *   POST /api/waitlist  body { email?: string }
 *     200 { joined: true, email: string }
 *     400 { error: "email_required" | "Invalid request" }
 *     401 { error: "Unauthorized" }
 *     429 { error: "Too many requests" }
 */
export function ShieldWaitlistButton({
  noticesSent,
  openViolations,
  accountEmail,
  signedIn = true,
  label = "Protect my tip credit — $79/mo",
  className,
  tone = "brass",
}: {
  noticesSent: number;
  openViolations: number;
  /** Pre-fills the panel. Empty when logged out or the session carries none. */
  accountEmail?: string | null;
  signedIn?: boolean;
  label?: string;
  className?: string;
  tone?: "brass" | "outline";
}) {
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState(accountEmail ?? "");
  const [pending, setPending] = useState(false);
  const [joined, setJoined] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function openWaitlist() {
    // Intent is recorded here — before the panel, before any address is typed,
    // and regardless of whether they go on to join.
    trackCheckoutStarted({
      notices_sent_at_upgrade: noticesSent,
      open_violation_count: openViolations,
    });
    setError(null);
    setOpen(true);
  }

  async function join() {
    setPending(true);
    setError(null);

    try {
      const response = await fetch("/api/waitlist", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(email ? { email } : {}),
      });
      const result: { joined?: boolean; email?: string; error?: string } =
        await response.json();

      if (!response.ok || !result.joined) {
        setError(
          response.status === 401
            ? "Sign in to your TipGuard account to join the list."
            : response.status === 429
              ? "Too many attempts — wait a moment and try again."
              : result.error === "email_required"
                ? "Enter an email address so we can reach you."
                : "Could not add you to the list. Try again in a moment."
        );
        setPending(false);
        return;
      }

      trackWaitlistJoined({ notices_sent_at_join: noticesSent });
      setJoined(true);
      setPending(false);
    } catch {
      setError("Could not add you to the list — check your connection.");
      setPending(false);
    }
  }

  return (
    <div className={cn("flex flex-col gap-2", className)}>
      <Button
        onClick={openWaitlist}
        className={cn(
          // Primary CTA: brass pill, 44px min height (visual brief, Component Style).
          "h-11 w-full rounded-full px-6 text-base font-medium",
          tone === "outline" &&
            "border-border bg-transparent text-foreground hover:bg-muted"
        )}
      >
        <ShieldCheck className="size-4" aria-hidden="true" />
        <span>{label}</span>
      </Button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-md">
          {joined ? (
            <>
              <DialogHeader>
                <DialogTitle className="flex items-center gap-2">
                  <Check className="size-5 text-primary" aria-hidden="true" />
                  You are on the list
                </DialogTitle>
                <DialogDescription>
                  We will email {email} the day TipGuard Shield opens. Nothing
                  has been charged, and there is nothing else to do.
                </DialogDescription>
              </DialogHeader>
              <DialogFooter>
                <Button onClick={() => setOpen(false)} className="rounded-full">
                  Back to my file
                </Button>
              </DialogFooter>
            </>
          ) : (
            <>
              <DialogHeader>
                <DialogTitle>TipGuard Shield is launching soon</DialogTitle>
                <DialogDescription>
                  Shield is $79/mo and not open yet. Leave your address and you
                  will be the first to know — no card, no charge.
                </DialogDescription>
              </DialogHeader>

              <div className="flex flex-col gap-2">
                <Label htmlFor="waitlist-email">Email</Label>
                <Input
                  id="waitlist-email"
                  type="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  placeholder="owner@restaurant.com"
                  autoComplete="email"
                  disabled={pending}
                />
                {!signedIn && (
                  <p className="text-sm text-muted-foreground">
                    Sign in first and we will attach this to your account.
                  </p>
                )}
              </div>

              <DialogFooter>
                <Button
                  onClick={join}
                  disabled={pending}
                  className="h-11 rounded-full px-6"
                >
                  {pending ? (
                    <>
                      <Loader2 className="size-4 animate-spin" aria-hidden="true" />
                      <span>Adding you</span>
                    </>
                  ) : (
                    <span>Notify me when it opens</span>
                  )}
                </Button>
              </DialogFooter>
            </>
          )}

          {/* Always-mounted live region — a conditionally mounted role=alert is
              not registered as a live region at load and drops the announcement. */}
          <p
            role="alert"
            aria-live="assertive"
            aria-atomic="true"
            className={error ? "text-sm text-destructive" : "sr-only"}
          >
            {error ?? ""}
          </p>
        </DialogContent>
      </Dialog>
    </div>
  );
}

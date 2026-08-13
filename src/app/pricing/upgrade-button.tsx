"use client";

import { useState } from "react";
import { Loader2, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { trackCheckoutStarted } from "@/lib/events";
import { cn } from "@/lib/utils";

/**
 * Upgrade CTA for behavior b-10.
 *
 * Contract with `src/app/api/checkout/route.ts` (owned by scaffold-wire):
 *   POST /api/checkout  body { plan: "shield" }
 *     200 { url: string }            -> Stripe Checkout session URL; redirect here
 *     401 { error: "unauthenticated" }
 *     4xx/5xx { error: string }
 *
 * `checkout_started` fires on the click — before the redirect — so the event is
 * recorded even when the user abandons on Stripe's page. h-06 measures intent
 * to pay, and the redirect is the last thing this app controls.
 */
export function UpgradeButton({
  noticesSent,
  openViolations,
  label = "Protect my tip credit — $79/mo",
  className,
  tone = "brass",
}: {
  noticesSent: number;
  openViolations: number;
  label?: string;
  className?: string;
  tone?: "brass" | "outline";
}) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function startCheckout() {
    setPending(true);
    setError(null);

    trackCheckoutStarted({
      notices_sent_at_upgrade: noticesSent,
      open_violation_count: openViolations,
    });

    try {
      const response = await fetch("/api/checkout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ plan: "shield" }),
      });
      const result: { url?: string; error?: string } = await response.json();

      if (!response.ok || !result.url) {
        setError(
          response.status === 401
            ? "Sign in to your TipGuard account to start the subscription."
            : "Checkout could not start. Try again in a moment."
        );
        setPending(false);
        return;
      }

      window.location.href = result.url;
    } catch {
      setError("Checkout could not start — check your connection and try again.");
      setPending(false);
    }
  }

  return (
    <div className={cn("flex flex-col gap-2", className)}>
      <Button
        onClick={startCheckout}
        disabled={pending}
        aria-label={pending ? "Opening secure checkout" : undefined}
        className={cn(
          // Primary CTA: brass pill, 44px min height (visual brief, Component Style).
          "h-11 w-full rounded-full px-6 text-base font-medium",
          tone === "outline" &&
            "border-border bg-transparent text-foreground hover:bg-muted"
        )}
      >
        {pending ? (
          <>
            <Loader2 className="size-4 animate-spin" aria-hidden="true" />
            <span>Opening secure checkout</span>
          </>
        ) : (
          <>
            <ShieldCheck className="size-4" aria-hidden="true" />
            <span>{label}</span>
          </>
        )}
      </Button>

      {/* Always-mounted live region — a conditionally mounted role=alert is not
          registered as a live region at load and drops the announcement. */}
      <p
        role="alert"
        aria-live="assertive"
        aria-atomic="true"
        className={
          error
            ? "text-sm text-destructive"
            : "sr-only"
        }
      >
        {error ?? ""}
      </p>
    </div>
  );
}

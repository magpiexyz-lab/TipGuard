"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowRight, LoaderCircle, TriangleAlert } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button, buttonVariants } from "@/components/ui/button";
import { trackCheckoutStarted } from "@/lib/events";
import { cn } from "@/lib/utils";

const SHIELD_PRICE_USD = 79;

/**
 * b-10: rendered by /dashboard for free-tier accounts only. The paid branch is
 * decided on the server, so a `plan = 'shield'` account never ships this markup.
 */
export function UpgradeCta({
  noticesSent,
  openViolationCount,
  exposureLabel,
}: {
  noticesSent: number;
  openViolationCount: number;
  exposureLabel: string;
}) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function startCheckout() {
    setPending(true);
    setError(null);
    trackCheckoutStarted({
      notices_sent_at_upgrade: noticesSent,
      open_violation_count: openViolationCount,
    });
    try {
      const response = await fetch("/api/checkout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ plan: "shield" }),
      });
      if (!response.ok) {
        const body = (await response.json().catch(() => ({}))) as { error?: string };
        throw new Error(body.error ?? "Checkout could not be started.");
      }
      const session = (await response.json()) as { url?: string };
      if (!session.url) throw new Error("Checkout could not be started.");
      window.location.href = session.url;
    } catch (caught) {
      setPending(false);
      setError(
        caught instanceof Error
          ? caught.message
          : "Checkout could not be started. Please try again."
      );
    }
  }

  return (
    <div className="dark surface-ink texture-grain bloom-brass-soft rounded-xl p-6 md:p-10">
      <div className="grid gap-8 lg:grid-cols-[1.25fr_1fr] lg:items-center">
        <div>
          <p className="eyebrow">TipGuard Shield &middot; ${SHIELD_PRICE_USD}/mo</p>
          <h3 className="mt-4 font-display text-3xl leading-[1.1] tracking-[-1.6px] md:text-[40px]">
            Convert an open-ended wage claim into a fixed line item
          </h3>
          <p className="mt-4 max-w-xl text-base leading-[1.55] text-muted-foreground">
            You are carrying {exposureLabel} in estimated exposure across{" "}
            {openViolationCount} open finding{openViolationCount === 1 ? "" : "s"}.
            Shield keeps notices current as staff and state rules change, and unlocks
            the one-click audit file.
          </p>

          <ul className="mt-6 grid gap-2 text-sm text-muted-foreground sm:grid-cols-2">
            <li className="border-t border-border pt-2">Unlimited notices and re-issues</li>
            <li className="border-t border-border pt-2">Continuous violation scanning</li>
            <li className="border-t border-border pt-2">One-click dated audit file</li>
            <li className="border-t border-border pt-2">Rule-version tracking per state</li>
          </ul>
        </div>

        <div>
          <p className="figure text-5xl leading-[1.1] md:text-6xl">
            ${SHIELD_PRICE_USD}
            <span className="ml-2 font-sans text-base tracking-normal text-muted-foreground">
              / month
            </span>
          </p>
          <p className="mt-3 text-sm leading-[1.5] text-muted-foreground">
            Roughly one hour of wage-and-hour defense counsel. Cancel any time.
          </p>

          <div className="mt-6 flex flex-col gap-3">
            <Button
              className="h-11 rounded-full px-6 text-base"
              onClick={startCheckout}
              disabled={pending}
              aria-label={pending ? "Opening secure checkout" : "Protect my tip credit"}
            >
              {pending ? (
                <LoaderCircle className="size-4 animate-spin" aria-hidden="true" />
              ) : null}
              {pending ? "Opening checkout…" : "Protect my tip credit"}
              {pending ? null : <ArrowRight className="size-4" aria-hidden="true" />}
            </Button>
            <Link
              href="/pricing"
              className={cn(
                buttonVariants({ variant: "outline" }),
                "h-11 px-5 text-base"
              )}
            >
              Compare free and Shield
            </Link>
          </div>

          {error ? (
            <Alert variant="destructive" className="mt-4">
              <TriangleAlert aria-hidden="true" />
              <AlertTitle>Checkout did not open</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          ) : null}
        </div>
      </div>
    </div>
  );
}

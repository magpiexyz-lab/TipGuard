"use client";

import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { LedgerSkeleton } from "./ledger-skeleton";
import { ShieldWaitlistButton } from "@/components/shield-waitlist-button";
import type { AccountSnapshot } from "./account-snapshot";

/**
 * The CTA adapts to who is reading:
 *   loading  — ruled skeleton, never a flash of the wrong call to action
 *   anonymous — the free score is the honest next step; checkout would 401
 *   signed in — the upgrade CTA (fires `checkout_started`, opens the waitlist)
 *
 * There is no paid branch: Shield is a fake door for this experiment, so no
 * account ever reaches plan = "shield".
 */
export function PricingCta({
  snapshot,
  onInk = false,
  label,
}: {
  snapshot: AccountSnapshot | null;
  onInk?: boolean;
  label?: string;
}) {
  const muted = onInk ? "text-paper/70" : "text-ink-soft";

  if (snapshot === null) {
    return <LedgerSkeleton rows={2} />;
  }

  if (!snapshot.signedIn) {
    return (
      <div className="flex flex-col gap-3">
        <Link
          href="/score"
          className={cn(
            buttonVariants(),
            "h-11 w-full rounded-full px-6 text-base font-medium"
          )}
        >
          Get my free audit-readiness score
          <ArrowRight className="size-4" aria-hidden="true" />
        </Link>
        <p className={cn("text-sm leading-[1.5]", muted)}>
          Two minutes, free account, no card. Already have an account?{" "}
          <Link
            href="/login"
            className={cn(
              "underline underline-offset-4",
              onInk ? "text-brass" : "text-brass-deep"
            )}
          >
            Sign in to join the list
          </Link>
          .
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <ShieldWaitlistButton
        noticesSent={snapshot.noticesSent}
        openViolations={snapshot.openViolations}
        accountEmail={snapshot.email}
        label={label}
      />
      <p className={cn("text-sm leading-[1.5]", muted)}>
        Shield opens soon. Join the list and we will email you — no card, no
        charge.
      </p>
    </div>
  );
}

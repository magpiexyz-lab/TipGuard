"use client";

import Link from "next/link";
import { ArrowRight, ShieldCheck } from "lucide-react";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { LedgerSkeleton } from "./ledger-skeleton";
import { UpgradeButton } from "./upgrade-button";
import type { AccountSnapshot } from "./account-snapshot";

/**
 * The CTA adapts to who is reading:
 *   loading  — ruled skeleton, never a flash of the wrong call to action
 *   anonymous — the free score is the honest next step; checkout would 401
 *   free      — the upgrade CTA (fires `checkout_started`, calls /api/checkout)
 *   shield    — already paid; point at the thing they bought
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
          Two minutes, no account, no card. Already have an account?{" "}
          <Link
            href="/login"
            className={cn(
              "underline underline-offset-4",
              onInk ? "text-brass" : "text-brass-deep"
            )}
          >
            Sign in to upgrade
          </Link>
          .
        </p>
      </div>
    );
  }

  if (snapshot.plan === "shield") {
    return (
      <div className="flex flex-col gap-3">
        <p
          className={cn(
            "flex items-center gap-2 text-sm font-medium",
            onInk ? "text-seal-soft" : "text-seal dark:text-seal-soft"
          )}
        >
          <ShieldCheck className="size-4" aria-hidden="true" />
          TipGuard Shield is active on this account
        </p>
        <Link
          href="/audit-file"
          className={cn(
            buttonVariants(),
            "h-11 w-full rounded-full px-6 text-base font-medium"
          )}
        >
          Build my audit file
          <ArrowRight className="size-4" aria-hidden="true" />
        </Link>
        <p className={cn("text-sm leading-[1.5]", muted)}>
          Billed monthly. Your signed acknowledgments stay in the vault either
          way.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <UpgradeButton
        noticesSent={snapshot.noticesSent}
        openViolations={snapshot.openViolations}
        label={label}
      />
      <p className={cn("text-sm leading-[1.5]", muted)}>
        Secure checkout by Stripe. Month to month — no annual commitment.
      </p>
    </div>
  );
}

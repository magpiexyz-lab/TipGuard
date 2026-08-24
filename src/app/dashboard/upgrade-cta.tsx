"use client";

import Link from "next/link";

import { buttonVariants } from "@/components/ui/button";
import { ShieldWaitlistButton } from "@/components/shield-waitlist-button";
import { cn } from "@/lib/utils";

const SHIELD_PRICE_USD = 79;

/**
 * b-10 / b-11: the dashboard upgrade block. Shield is a fake door for this
 * experiment, so every account sees it — the click fires `checkout_started`
 * (the h-06 numerator) and opens the waitlist panel instead of a checkout.
 */
export function UpgradeCta({
  noticesSent,
  openViolationCount,
  exposureLabel,
  accountEmail,
}: {
  noticesSent: number;
  openViolationCount: number;
  exposureLabel: string;
  accountEmail?: string | null;
}) {
  return (
    <div className="dark surface-ink texture-grain bloom-brass-soft rounded-xl p-6 md:p-10">
      <div className="grid gap-8 lg:grid-cols-[1.25fr_1fr] lg:items-center">
        <div>
          <p className="eyebrow">TipGuard Shield &middot; ${SHIELD_PRICE_USD}/mo</p>
          <h3 className="mt-4 font-display text-3xl leading-[1.1] tracking-[-1.6px] [word-spacing:0.072em] md:text-[40px]">
            Convert an open-ended wage claim into a fixed line item
          </h3>
          <p className="mt-4 max-w-xl text-base leading-[1.55] text-muted-foreground">
            You are carrying {exposureLabel} in estimated exposure across{" "}
            {openViolationCount} open finding{openViolationCount === 1 ? "" : "s"}.
            Shield keeps notices current as staff and state rules change. The
            one-click audit file is already yours — free, no plan required.
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
            <ShieldWaitlistButton
              noticesSent={noticesSent}
              openViolations={openViolationCount}
              accountEmail={accountEmail}
              label="Protect my tip credit"
            />
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
        </div>
      </div>
    </div>
  );
}

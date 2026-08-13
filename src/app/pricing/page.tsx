"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowRight, FileCheck2, ScrollText } from "lucide-react";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";
import {
  ANONYMOUS_SNAPSHOT,
  loadAccountSnapshot,
  type AccountSnapshot,
} from "./account-snapshot";
import { ExposureLedger } from "./exposure-ledger";
import { PlanComparison } from "./plan-comparison";
import { PricingCta } from "./pricing-cta";
import { PricingFaq } from "./pricing-faq";
import { SHIELD_MONTHLY_PRICE, SHIELD_TIMELINE } from "./pricing-data";

/**
 * `/pricing` — behavior b-10, hypothesis h-06.
 *
 * The conversion surface for the paid hypothesis. The argument is a single
 * contrast held across the whole page: an itemised, statute-cited back-pay
 * exposure on one side, a $79 line item on the other — and an explicit
 * statement of what the free tier keeps, so the upgrade is not read as a
 * hostage situation.
 *
 * Wire dependency (scaffold-wire, STATE 14): `POST /api/checkout` — see the
 * contract comment in `./upgrade-button.tsx`. This page renders and reads
 * correctly without it; only the redirect needs it.
 */
export default function PricingPage() {
  const [snapshot, setSnapshot] = useState<AccountSnapshot | null>(null);

  useEffect(() => {
    let cancelled = false;

    loadAccountSnapshot()
      .then((result) => {
        if (!cancelled) setSnapshot(result);
      })
      .catch(() => {
        if (!cancelled) setSnapshot(ANONYMOUS_SNAPSHOT);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="min-h-screen">
      {/* ---------------- 1. Hero (paper) ---------------- */}
      <section
        aria-labelledby="pricing-heading"
        className="relative isolate mx-auto max-w-[1120px] px-6 pt-24 pb-20 sm:pt-32"
      >
        {/* Ledger rule bleeding out of the top edge — ties the paper hero to the
            ruled surfaces further down instead of leaving it bare. */}
        <div
          className="texture-rule pointer-events-none absolute inset-x-0 top-0 -z-10 h-64 [mask-image:linear-gradient(to_bottom,black,transparent)]"
          aria-hidden="true"
        />
        <div
          className="bloom-brass-soft pointer-events-none absolute inset-x-0 top-0 -z-10 h-80"
          aria-hidden="true"
        />

        <p className="eyebrow">Pricing</p>

        <h1
          id="pricing-heading"
          className="mt-6 max-w-4xl text-4xl leading-[1.04] font-bold sm:text-[68px]"
        >
          One fixed line item against an unbounded one
        </h1>

        <p className="mt-8 max-w-2xl text-xl leading-[1.55] text-ink-soft">
          TipGuard Shield is{" "}
          <span className="font-mono tabular-nums">${SHIELD_MONTHLY_PRICE}</span>{" "}
          a month. Below is the arithmetic it stands against — worked from the
          federal rates, with the citation on every figure — and an exact
          statement of what stays yours for free.
        </p>

        <div className="mt-12 grid gap-10 border-t border-border pt-10 lg:grid-cols-[1fr_1fr] lg:gap-16">
          <div className="max-w-md">
            <PricingCta snapshot={snapshot} />
          </div>

          <ul className="grid gap-4 self-center sm:grid-cols-2 lg:grid-cols-1">
            <li className="flex gap-3">
              <ScrollText
                className="mt-0.5 size-4 shrink-0 text-brass-deep dark:text-brass"
                aria-hidden="true"
              />
              <span className="text-sm leading-[1.5] text-ink-soft">
                Notices are generated from a versioned per-state rule library and
                stamped with the rule version used.
              </span>
            </li>
            <li className="flex gap-3">
              <FileCheck2
                className="mt-0.5 size-4 shrink-0 text-seal dark:text-seal-soft"
                aria-hidden="true"
              />
              <span className="text-sm leading-[1.5] text-ink-soft">
                Signed acknowledgments are immutable — signer, UTC timestamp, and
                a frozen copy of the exact text acknowledged.
              </span>
            </li>
          </ul>
        </div>
      </section>

      {/* ---------------- 2. The arithmetic (full-bleed ink) ---------------- */}
      <ExposureLedger>
        <PricingCta snapshot={snapshot} onInk label="Protect my tip credit — $79/mo" />
      </ExposureLedger>

      {/* ---------------- 3. Plans (paper + ruled) ---------------- */}
      <PlanComparison>
        <PricingCta snapshot={snapshot} label="Start TipGuard Shield — $79/mo" />
      </PlanComparison>

      {/* ---------------- 4. What Shield does, on a clock (raised inset) ---------------- */}
      <section aria-labelledby="timeline-heading" className="bg-card">
        <div className="mx-auto max-w-[1120px] px-6 py-20 sm:py-24">
          <p className="eyebrow">After you turn it on</p>
          <h2 id="timeline-heading" className="mt-4 max-w-3xl text-3xl sm:text-[44px]">
            What the subscription actually does between audits
          </h2>

          <ol className="mt-12 grid gap-8 md:grid-cols-3">
            {SHIELD_TIMELINE.map((step, index) => (
              <li key={step.marker} className="flex flex-col">
                <p className="flex items-center gap-3">
                  <span className="font-mono text-sm tabular-nums text-brass-deep dark:text-brass">
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  <span className="h-px flex-1 bg-brass/40" aria-hidden="true" />
                  <span className="size-1.5 bg-brass" aria-hidden="true" />
                </p>
                <p className="eyebrow mt-5">{step.marker}</p>
                <h3 className="mt-3 font-heading text-xl leading-[1.15]">
                  {step.title}
                </h3>
                <p className="mt-3 text-sm leading-[1.55] text-ink-soft">
                  {step.body}
                </p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* ---------------- 5. FAQ (paper, sticky rail) ---------------- */}
      <PricingFaq />

      {/* ---------------- 6. Close (full-bleed ink) ---------------- */}
      <section
        aria-labelledby="closing-heading"
        className="surface-ink texture-grain relative overflow-hidden"
      >
        <div className="bloom-brass pointer-events-none absolute inset-0" aria-hidden="true" />

        <div className="relative mx-auto grid max-w-[1120px] gap-10 px-6 py-20 sm:py-24 lg:grid-cols-[1.2fr_0.8fr] lg:gap-16">
          <div>
            <p className="eyebrow text-brass">The decision</p>
            <h2 id="closing-heading" className="mt-4 max-w-2xl text-3xl sm:text-[44px]">
              The file either exists, dated and signed, or it does not
            </h2>
            <p className="mt-5 max-w-xl text-lg leading-[1.55] text-paper/70">
              Back-pay liability accrues on every shift you run without the
              signed file, and it is not something you can reconstruct after the
              notice arrives. Start free, see where you stand, and turn Shield on
              when you want the assembled export.
            </p>

            <Separator className="my-8 bg-paper/12" />

            <p className="max-w-xl text-sm leading-[1.55] text-paper/70">
              TipGuard is compliance software, not a law firm. Notices are
              generated from a versioned state rule library, have not been
              reviewed or certified by an attorney, and carry an explicit
              instruction to have your counsel review them before distribution.
            </p>
          </div>

          <div className="lg:self-center">
            <PricingCta snapshot={snapshot} onInk label="Protect my tip credit — $79/mo" />

            <Link
              href="/score"
              className={cn(
                // py-3 keeps the tap target at 44px on mobile; the negative
                // top margin holds the optical spacing the design asks for.
                "mt-3 inline-flex items-center gap-2 py-3 text-sm text-brass underline underline-offset-4"
              )}
            >
              Not ready? Score your restaurant first
              <ArrowRight className="size-4" aria-hidden="true" />
            </Link>
          </div>
        </div>
      </section>
    </div>
  );
}

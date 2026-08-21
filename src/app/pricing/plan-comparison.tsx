"use client";

import { Check, Lock } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import {
  FREE_PLAN_LINES,
  SHIELD_MONTHLY_PRICE,
  SHIELD_PLAN_LINES,
  type PlanLine,
} from "./pricing-data";

function PlanLineItem({ line }: { line: PlanLine }) {
  return (
    <li className="flex gap-3 border-t border-border py-3 first:border-t-0 first:pt-0">
      {line.state === "kept" ? (
        <Check
          className="mt-0.5 size-4 shrink-0 text-seal dark:text-seal-soft"
          aria-hidden="true"
        />
      ) : (
        <Lock
          className="mt-0.5 size-4 shrink-0 text-brass-deep dark:text-brass"
          aria-hidden="true"
        />
      )}
      <span className="text-sm leading-[1.5]">
        {line.label}
        {line.state === "locked" ? (
          <span className="sr-only"> — not included on this plan</span>
        ) : null}
      </span>
    </li>
  );
}

export function PlanComparison({ children }: { children?: React.ReactNode }) {
  return (
    <section
      aria-labelledby="plans-heading"
      className="texture-rule mx-auto max-w-[1120px] px-6 py-12 sm:py-16"
    >
      <p className="eyebrow">The two plans</p>
      <h2 id="plans-heading" className="mt-4 max-w-3xl text-3xl sm:text-[44px]">
        Nothing you have already done gets taken away
      </h2>
      <p className="mt-5 max-w-2xl text-lg leading-[1.55] text-ink-soft">
        The free tier is not a trial that expires. Your score, your roster, your
        generated notices and every signed acknowledgment stay readable and
        exportable-by-hand forever. Shield buys the assembled file and the
        ongoing watch.
      </p>

      <div className="mt-12 grid gap-6 lg:grid-cols-2">
        {/* ---------------- Free ---------------- */}
        {/* NOTE: `ring-*` cannot be used on these cards. `.elev-*` declares
            `box-shadow` outright in globals.css `@layer utilities`, which lands
            after Tailwind's ring utilities and wipes `--tw-ring-shadow`. The
            edge is drawn with `outline-*` (a separate property) so it survives. */}
        <Card className="elev-1 p-2 outline-1 outline-foreground/10 transition-shadow duration-[140ms] hover:elev-2">
          <CardHeader className="gap-3">
            <div className="flex items-center justify-between gap-4">
              <h3 className="font-heading text-2xl">Free</h3>
              <Badge
                variant="outline"
                className="h-6 rounded-md font-mono text-[11px] tracking-[0.1em] uppercase"
              >
                Always on
              </Badge>
            </div>
            <p className="flex items-baseline gap-2">
              <span className="font-mono text-4xl leading-[1.1] tabular-nums">$0</span>
              <span className="text-sm text-ink-soft">/ month, no card</span>
            </p>
            <p className="text-sm leading-[1.5] text-ink-soft">
              Find out where you stand and close the biggest gaps the same
              afternoon.
            </p>
          </CardHeader>
          <CardContent>
            <ul className="mt-2">
              {FREE_PLAN_LINES.map((line) => (
                <PlanLineItem key={line.label} line={line} />
              ))}
            </ul>
          </CardContent>
        </Card>

        {/* ---------------- Shield ---------------- */}
        <Card className="elev-2 relative p-2 outline-2 outline-brass transition-shadow duration-[140ms] hover:elev-3">
          <CardHeader className="gap-3">
            <div className="flex items-center justify-between gap-4">
              <h3 className="font-heading text-2xl">TipGuard Shield</h3>
              <Badge className="h-6 rounded-md font-mono text-[11px] tracking-[0.1em] uppercase">
                Audit ready
              </Badge>
            </div>
            <p className="flex items-baseline gap-2">
              <span className="font-mono text-4xl leading-[1.1] tabular-nums">
                ${SHIELD_MONTHLY_PRICE}
              </span>
              <span className="text-sm text-ink-soft">/ month, month to month</span>
            </p>
            <p className="text-sm leading-[1.5] text-ink-soft">
              Hand an investigator one dated file instead of a week of
              reconstruction.
            </p>
          </CardHeader>
          <CardContent>
            <ul className="mt-2">
              {SHIELD_PLAN_LINES.map((line) => (
                <PlanLineItem key={line.label} line={line} />
              ))}
            </ul>
            <div className="mt-6">{children}</div>
          </CardContent>
        </Card>
      </div>
    </section>
  );
}

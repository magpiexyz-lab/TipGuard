"use client";

import { useMemo, useState } from "react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  DEFAULT_TIPPED_STAFF,
  DEFAULT_WEEKLY_TIPPED_HOURS,
  FEDERAL_CASH_WAGE_FLOOR,
  FEDERAL_MAX_TIP_CREDIT,
  FEDERAL_MINIMUM_WAGE,
  LOOKBACK_WEEKS,
  MAX_TIPPED_STAFF,
  MAX_WEEKLY_TIPPED_HOURS,
  MIN_TIPPED_STAFF,
  MIN_WEEKLY_TIPPED_HOURS,
  SHIELD_ANNUAL_PRICE,
  SHIELD_MONTHLY_PRICE,
  formatUsd,
  modelExposure,
} from "./pricing-data";

function clamp(value: number, min: number, max: number): number {
  if (!Number.isFinite(value)) return min;
  return Math.min(max, Math.max(min, Math.round(value)));
}

/**
 * The whole argument of this page: an itemised exposure ledger on the ink band,
 * with the $79 line item set against it. Every input rate carries its citation;
 * the totals are arithmetic derived from those rates, recomputed live as the
 * operator sizes it to their own room.
 */
export function ExposureLedger({ children }: { children?: React.ReactNode }) {
  const [tippedStaff, setTippedStaff] = useState(DEFAULT_TIPPED_STAFF);
  const [weeklyHours, setWeeklyHours] = useState(DEFAULT_WEEKLY_TIPPED_HOURS);

  const model = useMemo(
    () => modelExposure(tippedStaff, weeklyHours),
    [tippedStaff, weeklyHours]
  );

  return (
    <section
      aria-labelledby="exposure-heading"
      className="surface-ink texture-grain relative overflow-hidden"
    >
      <div className="bloom-brass pointer-events-none absolute inset-0" aria-hidden="true" />
      <div
        className="texture-rule pointer-events-none absolute inset-0 [mask-image:linear-gradient(to_bottom,black,transparent)]"
        aria-hidden="true"
      />

      <div className="relative mx-auto max-w-[1120px] px-6 py-20 sm:py-28">
        <p className="eyebrow text-brass">The arithmetic</p>
        <h2 id="exposure-heading" className="mt-4 max-w-3xl text-3xl sm:text-[44px]">
          What one missing signature costs
        </h2>
        <p className="mt-5 max-w-2xl text-lg leading-[1.55] text-paper/70">
          The tip credit is conditional on the notice. Without a signed
          acknowledgment on file, the sub-minimum cash wage was never validly
          claimed — not going forward, but retroactively, for every tipped hour
          inside the lookback window.
        </p>

        <div className="mt-12 grid gap-10 lg:grid-cols-[1.3fr_1fr] lg:gap-14">
          {/* ---------------- The exposure ledger ---------------- */}
          <div>
            <div className="grid gap-5 sm:grid-cols-2">
              <div className="flex flex-col gap-2">
                <Label htmlFor="tipped-staff" className="text-paper/70">
                  Tipped staff on the books
                </Label>
                <Input
                  id="tipped-staff"
                  type="number"
                  inputMode="numeric"
                  min={MIN_TIPPED_STAFF}
                  max={MAX_TIPPED_STAFF}
                  value={tippedStaff}
                  onChange={(event) =>
                    setTippedStaff(
                      clamp(Number(event.target.value), MIN_TIPPED_STAFF, MAX_TIPPED_STAFF)
                    )
                  }
                  className="h-11 border-paper/20 bg-ink-raised font-mono text-base tabular-nums text-paper md:text-base"
                />
              </div>
              <div className="flex flex-col gap-2">
                <Label htmlFor="weekly-hours" className="text-paper/70">
                  Tipped hours each, per week
                </Label>
                <Input
                  id="weekly-hours"
                  type="number"
                  inputMode="numeric"
                  min={MIN_WEEKLY_TIPPED_HOURS}
                  max={MAX_WEEKLY_TIPPED_HOURS}
                  value={weeklyHours}
                  onChange={(event) =>
                    setWeeklyHours(
                      clamp(
                        Number(event.target.value),
                        MIN_WEEKLY_TIPPED_HOURS,
                        MAX_WEEKLY_TIPPED_HOURS
                      )
                    )
                  }
                  className="h-11 border-paper/20 bg-ink-raised font-mono text-base tabular-nums text-paper md:text-base"
                />
              </div>
            </div>

            <dl className="mt-10">
              <div className="flex items-baseline justify-between gap-6 border-t border-paper/12 py-3">
                <dt className="text-sm text-paper/70">Federal cash wage floor, tipped</dt>
                <dd className="text-right font-mono text-base tabular-nums">
                  ${FEDERAL_CASH_WAGE_FLOOR.toFixed(2)}/hr
                  <span className="mt-0.5 block text-[11px] tracking-[0.14em] text-brass uppercase">
                    29 U.S.C. §203(m)
                  </span>
                </dd>
              </div>

              <div className="flex items-baseline justify-between gap-6 border-t border-paper/12 py-3">
                <dt className="text-sm text-paper/70">Full minimum wage owed if the credit is void</dt>
                <dd className="text-right font-mono text-base tabular-nums">
                  ${FEDERAL_MINIMUM_WAGE.toFixed(2)}/hr
                  <span className="mt-0.5 block text-[11px] tracking-[0.14em] text-brass uppercase">
                    29 U.S.C. §206(a)
                  </span>
                </dd>
              </div>

              <div className="flex items-baseline justify-between gap-6 border-t border-paper/12 py-3">
                <dt className="text-sm text-paper/70">Gap you become liable for, per tipped hour</dt>
                <dd className="text-right font-mono text-base tabular-nums text-brass">
                  ${FEDERAL_MAX_TIP_CREDIT.toFixed(2)}/hr
                  <span className="mt-0.5 block text-[11px] tracking-[0.14em] text-paper/60 uppercase">
                    maximum federal tip credit
                  </span>
                </dd>
              </div>

              <div className="flex items-baseline justify-between gap-6 border-t border-paper/12 py-3">
                <dt className="text-sm text-paper/70">Tipped hours inside the lookback</dt>
                <dd className="text-right font-mono text-base tabular-nums">
                  {model.tippedHours.toLocaleString("en-US")} hrs
                  <span className="mt-0.5 block text-[11px] tracking-[0.14em] text-brass uppercase">
                    {LOOKBACK_WEEKS} wks · 29 U.S.C. §255(a)
                  </span>
                </dd>
              </div>

              <div className="flex items-baseline justify-between gap-6 border-t border-paper/12 py-3">
                <dt className="text-sm text-paper/70">Unpaid wages</dt>
                <dd className="text-right font-mono text-lg tabular-nums">
                  {formatUsd(model.backPay)}
                </dd>
              </div>

              <div className="flex items-baseline justify-between gap-6 border-t border-paper/12 py-3">
                <dt className="text-sm text-paper/70">Liquidated damages, equal amount</dt>
                <dd className="text-right font-mono text-lg tabular-nums">
                  {formatUsd(model.liquidatedDamages)}
                  <span className="mt-0.5 block text-[11px] tracking-[0.14em] text-brass uppercase">
                    29 U.S.C. §216(b)
                  </span>
                </dd>
              </div>

              <div className="flex items-baseline justify-between gap-6 border-t border-paper/12 py-3">
                <dt className="text-sm text-paper/70">Plaintiff&rsquo;s attorney fees</dt>
                <dd className="text-right font-mono text-base tabular-nums text-ember-soft">
                  shifted to you
                  <span className="mt-0.5 block text-[11px] tracking-[0.14em] text-brass uppercase">
                    29 U.S.C. §216(b)
                  </span>
                </dd>
              </div>

              <div className="flex items-baseline justify-between gap-6 border-t border-paper/12 py-3">
                <dt className="text-sm text-paper/70">Your own defense counsel</dt>
                <dd className="text-right font-mono text-base tabular-nums text-ember-soft">
                  hourly, win or lose
                  <span className="mt-0.5 block text-[11px] tracking-[0.14em] text-paper/60 uppercase">
                    accrues from the day the notice arrives
                  </span>
                </dd>
              </div>

              <div className="mt-2 flex items-baseline justify-between gap-6 border-t-2 border-brass py-5">
                <dt className="eyebrow text-brass">Minimum exposure</dt>
                <dd
                  key={model.minimumExposure}
                  className="animate-in fade-in slide-in-from-bottom-1 text-right font-mono text-4xl leading-[1.1] tabular-nums duration-200 sm:text-5xl"
                >
                  {formatUsd(model.minimumExposure)}
                </dd>
              </div>
            </dl>

            <p className="mt-5 max-w-xl text-sm leading-[1.5] text-paper/70">
              Illustrative model at federal rates. Your state&rsquo;s maximum tip
              credit may be lower — several states permit none at all, which
              raises the per-hour gap rather than lowering it. The free
              audit-readiness score reads your state and scores against its
              current rule version.
            </p>
          </div>

          {/* ---------------- The line item ---------------- */}
          <div className="lg:sticky lg:top-8 lg:self-start">
            <div className="rounded-xl bg-ink-raised p-8 ring-1 ring-paper/12">
              <p className="eyebrow text-brass">TipGuard Shield</p>

              <p className="mt-5 flex items-baseline gap-2">
                <span className="font-mono text-6xl leading-[1.05] tabular-nums text-paper">
                  ${SHIELD_MONTHLY_PRICE}
                </span>
                <span className="text-base text-paper/70">/ month</span>
              </p>
              <p className="mt-2 font-mono text-sm tabular-nums text-paper/70">
                {formatUsd(SHIELD_ANNUAL_PRICE)} a year · month to month
              </p>

              <div className="mt-8 border-t border-paper/12 pt-6">
                <p className="text-sm text-paper/70">
                  The exposure above is worth
                </p>
                <p
                  key={model.priceRatio}
                  className="mt-2 animate-in fade-in slide-in-from-bottom-1 font-mono text-5xl leading-[1.05] tabular-nums text-brass duration-200"
                >
                  <span aria-hidden="true">{model.priceRatio.toLocaleString("en-US")}×</span>
                  <span className="sr-only">
                    {model.priceRatio.toLocaleString("en-US")} times
                  </span>
                </p>
                <p className="mt-2 text-sm text-paper/70">
                  a year of TipGuard Shield — and that total is before either
                  side&rsquo;s legal bills.
                </p>
              </div>

              <div className="mt-6 border-t border-paper/12 pt-6">
                <p className="text-sm leading-[1.55] text-paper/70">
                  Put the other way:{" "}
                  <span className="font-mono tabular-nums text-paper">
                    ${SHIELD_MONTHLY_PRICE}
                  </span>{" "}
                  is roughly one hour of wage-and-hour defense counsel. The
                  paperwork it maintains is the first thing that counsel would
                  ask you for.
                </p>
              </div>

              <div className="mt-8">{children}</div>

              <p className="mt-6 text-sm leading-[1.5] text-seal-soft">
                The paperwork is the whole defense. It either exists, dated and
                signed, or it does not.
              </p>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

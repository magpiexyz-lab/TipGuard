import { AnimatedShinyText } from "@/components/magicui/animated-shiny-text";
import { BlurFade } from "@/components/magicui/blur-fade";
import { GridPattern } from "@/components/magicui/grid-pattern";
import { NumberTicker } from "@/components/magicui/number-ticker";
import type { Variant } from "@/lib/variants";
import { CtaButton } from "./cta-button";
import { EXPOSURE_MATH, FILE_CONTENTS, SECTION_IDS } from "./content";

/**
 * The price, anchored against the arithmetic.
 *
 * Two panels on a full-bleed ink surface: the illustrative federal-floor
 * exposure on the left (ember, capped to figures and one hairline — never a
 * red surface), the $79/mo line item and what the file contains on the right.
 * Every number on the left is shown with its own working so the anchor is
 * checkable rather than asserted.
 */
export function PricingSection({ variant }: { variant: Variant }) {
  const { staff, hoursPerWeek, creditPerHour, weeks, backWages, liquidated } = EXPOSURE_MATH;

  return (
    <section
      id={SECTION_IDS.pricing}
      className="dark surface-ink relative isolate scroll-mt-24 overflow-hidden py-8 sm:py-8 lg:py-10"
      aria-labelledby="pricing-heading"
    >
      <GridPattern
        variant="rule"
        size={32}
        stroke="var(--paper)"
        fade="radial"
        className="-z-10 opacity-[0.06]"
      />
      <div aria-hidden="true" className="bloom-brass absolute inset-0 -z-10" />

      <div className="mx-auto max-w-[1160px] px-5 sm:px-8">
        <BlurFade className="max-w-2xl">
          <AnimatedShinyText
            tone="ink"
            className="font-mono text-[11px] font-medium uppercase tracking-[0.14em]"
          >
            The line item versus the liability
          </AnimatedShinyText>
          <h2
            id="pricing-heading"
            className="mt-3 font-display text-[24px] font-semibold leading-[1.1] tracking-[-1.6px] [word-spacing:0.072em] text-paper sm:text-[28px] lg:text-[32px]"
          >
            Price the paperwork, or price the claim.
          </h2>
        </BlurFade>

        <div className="mt-5 grid grid-cols-1 gap-4 lg:mt-6 lg:grid-cols-2 lg:gap-5">
          {/* Left: the exposure, with its working shown. Flex column so the
              footnote sits on the floor of the panel rather than leaving the
              bottom third of a stretched grid cell empty. */}
          <BlurFade className="flex h-full flex-col rounded-xl border border-paper/12 p-7 sm:p-9">
            <p className="font-mono text-[11px] font-medium uppercase tracking-[0.14em] text-ember-soft">
              If the credit is disallowed
            </p>

            <dl className="mt-4">
              {[
                { k: "Tipped staff", v: String(staff) },
                { k: "Tipped hours each", v: `${hoursPerWeek} / wk` },
                { k: "Credit at risk", v: `$${creditPerHour.toFixed(2)} / hr` },
                { k: "Lookback", v: `${weeks} wks` },
              ].map((row) => (
                <div
                  key={row.k}
                  className="flex items-baseline justify-between gap-4 border-t border-paper/12 py-2"
                >
                  <dt className="font-mono text-[11px] uppercase tracking-[0.14em] text-paper/60">
                    {row.k}
                  </dt>
                  <dd className="figure text-sm text-paper/85">{row.v}</dd>
                </div>
              ))}
            </dl>

            <div className="mt-4 border-t border-paper/12 pt-4">
              <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-paper/60">
                Back wages recomputed
              </p>
              <p className="mt-1.5 font-mono text-xl font-medium tracking-[-0.2px] text-paper tabular-nums">
                <NumberTicker value={backWages} prefix="$" />
              </p>

              <p className="mt-3 font-mono text-[11px] uppercase tracking-[0.14em] text-ember-soft">
                Plus liquidated damages{" "}
                {/* normal-case: the subsection letter is part of the cite. */}
                <span className="normal-case tracking-[0.06em]">
                  · 29 U.S.C. §216(b)
                </span>
              </p>
              <p className="mt-2 font-mono text-[30px] font-medium leading-[1.1] tracking-[-0.2px] text-ember-soft tabular-nums sm:text-[36px]">
                <NumberTicker value={liquidated} prefix="$" />
              </p>
            </div>

            <div className="mt-auto pt-4">
              <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-paper/45">
                The claim, against the line item
              </p>
              <p className="mt-2 font-mono text-sm leading-[1.5] text-paper/70 tabular-nums">
                That is{" "}
                <span className="text-brass">
                  {Math.round(
                    liquidated / (variant.pricingAmount * 12)
                  ).toLocaleString("en-US")}
                  ×
                </span>{" "}
                one year of TipGuard.
              </p>
              <p className="mt-3 border-t border-paper/12 pt-3 text-xs leading-[1.5] text-paper/60">
                Illustrative federal-floor arithmetic ($7.25 minimum less the
                $2.13 cash wage), before attorney fees or state penalties. Your
                state may be stricter.
              </p>
            </div>
          </BlurFade>

          {/* Right: the fixed line item. */}
          <BlurFade
            delay={55}
            className="relative rounded-xl bg-paper-raised p-7 text-ink shadow-ledger-3 sm:p-9"
          >
            <div className="flex flex-wrap items-baseline justify-between gap-3">
              <p className="eyebrow">TipGuard Shield</p>
              <span className="rounded-sm bg-seal/12 px-2.5 py-1 font-mono text-[11px] font-medium uppercase tracking-[0.1em] text-seal">
                Score stays free
              </span>
            </div>

            <p className="mt-3 flex items-baseline gap-2">
              <span className="font-mono text-[36px] font-medium leading-[1.1] tracking-[-0.2px] text-ink tabular-nums">
                ${variant.pricingAmount}
              </span>
              <span className="font-mono text-sm text-ink-soft">/ month</span>
            </p>
            <p className="mt-2.5 max-w-[46ch] text-sm leading-[1.5] text-ink-soft">
              Every employee, every state, every rule update — and the export.
              One line item on the books, sitting next to the POS subscription.
            </p>

            <div className="tg-tick-rule my-7" />

            <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-ink-soft">
              What the audit file contains
            </p>
            <ul className="mt-3 space-y-1.5">
              {FILE_CONTENTS.map((item) => (
                <li key={item} className="flex gap-3 text-[13px] leading-[1.45] text-ink">
                  <svg
                    aria-hidden="true"
                    viewBox="0 0 16 16"
                    className="mt-0.5 size-4 shrink-0"
                    fill="none"
                  >
                    <path
                      d="M3 8.5l3.2 3.5L13 4.5"
                      stroke="var(--seal)"
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                  {item}
                </li>
              ))}
            </ul>

            <div className="mt-5 flex flex-col items-start gap-2.5">
              <CtaButton
                variantSlug={variant.slug}
                position="pricing"
                label={variant.cta}
                size="lg"
              />
              <span className="font-mono text-[11px] uppercase tracking-[0.14em] text-ink-soft">
                Start free · upgrade when the gaps are real
              </span>
              <p className="max-w-[46ch] text-sm leading-[1.55] text-ink-soft">
                {variant.proof}
              </p>
            </div>
          </BlurFade>
        </div>
      </div>
    </section>
  );
}

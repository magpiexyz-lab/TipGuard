import Image from "next/image";
import { BlurFade } from "@/components/magicui/blur-fade";
import { cn } from "@/lib/utils";
import type { Variant } from "@/lib/variants";
import { CtaButton } from "./cta-button";
import { FEATURES, SECTION_IDS } from "./content";

/**
 * How the file gets built — an asymmetric bento on a raised paper inset.
 *
 * Feature 01 runs wide (engraving left, copy right); 02 and 03 sit below as a
 * pair of stacked cards, so the section reads as a form rather than a row of
 * three identical tiles. Every illustration comes from the same archival
 * engraving system (two inks, identical stroke weight).
 */
export function FeaturesSection({ variant }: { variant: Variant }) {
  const [lead, ...rest] = FEATURES;

  return (
    <section
      id={SECTION_IDS.how}
      className="relative scroll-mt-24 bg-paper-raised py-20 shadow-[inset_0_1px_0_0_var(--border),inset_0_-1px_0_0_var(--border)] sm:py-28 lg:py-32"
      aria-labelledby="how-heading"
    >
      <div className="mx-auto max-w-[1160px] px-5 sm:px-8">
        <BlurFade className="max-w-2xl">
          <p className="eyebrow">Roster in, audit file out</p>
          <h2
            id="how-heading"
            className="mt-5 font-display text-[30px] font-semibold leading-[1.1] tracking-[-1.6px] text-ink sm:text-[38px] lg:text-[44px]"
          >
            Three moving parts. None of them are your evening.
          </h2>
        </BlurFade>

        <BlurFade
          delay={55}
          className="mt-12 overflow-hidden rounded-xl bg-paper shadow-ledger-2 lg:mt-16"
        >
          <div className="grid grid-cols-1 items-stretch lg:grid-cols-[minmax(0,44%)_minmax(0,56%)]">
            {/* `bg-paper` (not `brass-soft/25`): the engraving field is drawn
                on exactly #f3f0e6, so matching the well means the plate bleeds
                into the card instead of sitting in a warmer letterbox band.
                `object-contain` because `cover` cropped 35% off the top and
                bottom of the notice stack at mobile widths — the subject was
                being decapitated to fill a 1.7:1 box. */}
            <div className="relative aspect-[4/3] border-b border-border bg-paper lg:aspect-auto lg:min-h-[220px] lg:border-b-0 lg:border-r">
              <Image
                src={lead.image}
                alt={lead.alt}
                width={lead.width}
                height={lead.height}
                sizes="(min-width: 1024px) 480px, 100vw"
                className="h-full w-full object-contain"
              />
            </div>
            <div className="p-7 sm:p-10">
              <div className="flex items-center gap-3">
                <span className="figure text-sm text-brass-deep">{lead.index}</span>
                <span className="eyebrow">{lead.eyebrow}</span>
              </div>
              <h3 className="mt-5 max-w-[22ch] font-display text-2xl font-semibold leading-[1.15] tracking-[-1.2px] text-ink sm:text-[28px]">
                {lead.title}
              </h3>
              <p className="mt-4 max-w-[54ch] text-base leading-[1.55] text-ink-soft">
                {lead.body}
              </p>
              <ul className="mt-6 space-y-3">
                {lead.bullets.map((bullet) => (
                  <li key={bullet} className="flex gap-3 text-sm leading-[1.5] text-ink">
                    <span aria-hidden="true" className="mt-2 size-1.5 shrink-0 bg-seal" />
                    {bullet}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </BlurFade>

        <div className="mt-6 grid grid-cols-1 gap-6 md:grid-cols-2">
          {rest.map((feature, index) => (
            <BlurFade
              key={feature.index}
              delay={(index + 1) * 55}
              className={cn(
                "group flex flex-col overflow-hidden rounded-xl bg-paper shadow-ledger-1",
                "transition-all duration-[140ms] hover:-translate-y-0.5 hover:shadow-ledger-2"
              )}
            >
              {/* Engraved plate. The well is `bg-paper` because the engravings
                  are drawn on exactly #f3f0e6 — matching it means the plate
                  bleeds into the card with no pillarbox band, which is what the
                  old `brass-soft/20` well produced either side of the artwork. */}
              <div className="overflow-hidden border-b border-border bg-paper">
                <Image
                  src={feature.image}
                  alt={feature.alt}
                  width={feature.width}
                  height={feature.height}
                  sizes="(min-width: 768px) 560px, 100vw"
                  className="h-56 w-full object-contain transition-transform duration-[240ms] group-hover:scale-[1.03]"
                  style={{ transitionTimingFunction: "var(--ease-ledger)" }}
                />
              </div>
              <div className="flex flex-1 flex-col p-7">
                <div className="flex items-center gap-3">
                  <span className="figure text-sm text-brass-deep">{feature.index}</span>
                  <span className="eyebrow">{feature.eyebrow}</span>
                </div>
                <h3 className="mt-4 font-display text-xl font-semibold leading-[1.15] tracking-[-1.2px] text-ink sm:text-2xl">
                  {feature.title}
                </h3>
                <p className="mt-3 text-sm leading-[1.55] text-ink-soft">{feature.body}</p>
                <ul className="mt-5 space-y-2.5 border-t border-border pt-5">
                  {feature.bullets.map((bullet) => (
                    <li key={bullet} className="flex gap-3 text-sm leading-[1.5] text-ink">
                      <span aria-hidden="true" className="mt-2 size-1.5 shrink-0 bg-seal" />
                      {bullet}
                    </li>
                  ))}
                </ul>
              </div>
            </BlurFade>
          ))}
        </div>

        <BlurFade
          delay={110}
          className="mt-12 flex flex-col items-start gap-5 sm:flex-row sm:items-center sm:justify-between"
        >
          <p className="max-w-[52ch] text-base text-ink-soft">
            Start with the free score — seven questions, no account. The gap list
            it produces is the same checklist the product then closes.
          </p>
          <CtaButton
            variantSlug={variant.slug}
            position="feature_section"
            label={variant.cta}
            size="lg"
            className="shrink-0"
          />
        </BlurFade>
      </div>
    </section>
  );
}

import Image from "next/image";
import { BlurFade } from "@/components/magicui/blur-fade";
import type { Variant } from "@/lib/variants";

/**
 * Where the credit breaks — the objection-and-fear section.
 *
 * Layout deliberately breaks the centred column: a sticky left rail holds the
 * section thesis and the "empty drawer" engraving while the right column
 * scrolls a ruled ledger of the three variant pain points. Surface is paper
 * with full-strength rules — a temperature flip out of the ink plinth above.
 */
export function ExposureSection({ variant }: { variant: Variant }) {
  return (
    <section
      className="texture-rule relative bg-paper py-14 sm:py-18 lg:py-20"
      aria-labelledby="exposure-heading"
    >
      <div className="mx-auto grid max-w-[1160px] grid-cols-1 gap-14 px-5 sm:px-8 lg:grid-cols-[minmax(0,360px)_minmax(0,1fr)] lg:gap-20">
        <div className="lg:sticky lg:top-28 lg:self-start">
          <BlurFade reveal="slide">
            <p className="eyebrow">The gap nobody audits until it is audited</p>
            <h2
              id="exposure-heading"
              className="mt-5 font-display text-[30px] font-semibold leading-[1.1] tracking-[-1.6px] text-ink sm:text-[38px] lg:text-[44px]"
            >
              The credit is conditional. The paperwork is the condition.
            </h2>
            <p className="mt-5 text-base leading-[1.55] text-ink-soft">
              An hour paid at $2.13 is only valid while the signed notice, the
              tip-pool composition and the overtime basis all hold. Break one and
              the credit is recomputed backward — not from today.
            </p>

            {/* Filed plate: the engraving prints straight onto the section's
                paper (multiply) inside a hairline frame, rather than floating
                in a small shadowed card of a slightly different cream. */}
            <figure className="relative mt-10 hidden lg:block">
              <div className="tg-tick-rule mb-6" data-align="start" />
              <div className="rounded-lg border border-border bg-paper px-5 pb-4 pt-5 shadow-ledger-1">
                <Image
                  src="/images/empty-state.webp"
                  alt="Engraved illustration of an open empty file drawer holding one hanging folder with a brass tab"
                  width={400}
                  height={400}
                  sizes="360px"
                  className="w-full"
                />
                <figcaption className="mt-4 flex items-center gap-3 border-t border-border pt-4 font-mono text-[11px] uppercase leading-[1.4] tracking-[0.14em] text-ink-soft">
                  <span aria-hidden="true" className="size-1.5 shrink-0 bg-brass" />
                  Today&rsquo;s notice file, in most kitchens
                </figcaption>
              </div>
            </figure>
          </BlurFade>
        </div>

        <ol className="min-w-0">
          {variant.painPoints.map((point, index) => (
            <BlurFade
              as="li"
              key={point}
              reveal="slide"
              delay={index * 55}
              className="tg-row group border-t border-border first:border-t-0"
            >
              <div className="flex gap-6 py-8 pl-5 transition-transform duration-[140ms] group-hover:translate-x-1 sm:gap-8 sm:py-10">
                <span className="figure shrink-0 pt-1 text-sm text-brass-deep">
                  {String(index + 1).padStart(2, "0")}
                </span>
                <p className="max-w-[46ch] font-display text-xl font-semibold leading-[1.3] tracking-[-0.6px] text-ink sm:text-2xl">
                  {point}
                </p>
              </div>
            </BlurFade>
          ))}

          <BlurFade
            as="li"
            reveal="slide"
            delay={165}
            className="mt-10 rounded-xl bg-paper-raised p-7 shadow-ledger-2 sm:p-9"
          >
            <p className="eyebrow">What changes</p>
            <p className="mt-4 font-display text-2xl leading-[1.2] tracking-[-1.2px] text-ink sm:text-[28px]">
              {variant.promise}
            </p>
            <div className="tg-tick-rule mt-7" />
          </BlurFade>
        </ol>
      </div>
    </section>
  );
}

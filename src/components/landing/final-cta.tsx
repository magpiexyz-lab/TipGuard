import { BlurFade } from "@/components/magicui/blur-fade";
import { GridPattern } from "@/components/magicui/grid-pattern";
import type { Variant } from "@/lib/variants";
import { CtaButton } from "./cta-button";
import { COUNSEL_DISCLAIMER } from "./content";

/**
 * Closing ask — a raised paper plinth with the brass bloom overhead. The only
 * centred section on the page, which is why it lands: after five asymmetric
 * sections, the sudden symmetry reads as the end of the document.
 *
 * Motion: `reveal="settle"` — the block drops the last few pixels and lands
 * flat, the stamp verb, not the blur used by the two sections above it.
 */
export function FinalCta({ variant }: { variant: Variant }) {
  return (
    <section
      className="relative isolate overflow-hidden bg-paper-raised py-20 sm:py-28 lg:py-32"
      aria-labelledby="final-cta-heading"
    >
      <GridPattern
        variant="grid"
        size={32}
        stroke="var(--rule-color)"
        fade="radial"
        className="-z-10"
      />
      <div aria-hidden="true" className="bloom-brass absolute inset-0 -z-10" />

      <BlurFade
        reveal="settle"
        className="mx-auto max-w-[720px] px-5 text-center sm:px-8"
      >
        <p className="eyebrow">Two minutes, seven questions</p>
        <h2
          id="final-cta-heading"
          className="mx-auto mt-5 max-w-[18ch] font-display text-[32px] font-bold leading-[1.06] tracking-[-1.6px] text-ink sm:text-[44px] lg:text-[52px] lg:tracking-[-2px]"
        >
          Find out what is missing before someone else does.
        </h2>
        <p className="mx-auto mt-6 max-w-[56ch] text-lg leading-[1.55] text-ink-soft">
          Seven questions against the same checklist an investigator opens with.
          You see your readiness score, your ranked gaps and an exposure range
          before you decide anything.
        </p>

        <div className="mt-9 flex flex-col items-center gap-4">
          <CtaButton
            variantSlug={variant.slug}
            position="footer"
            label={variant.cta}
            size="lg"
          />
          <span className="font-mono text-[11px] uppercase tracking-[0.14em] text-ink-soft">
            No account · no card · your answers stay yours
          </span>
        </div>

        <div className="tg-perf mx-auto mt-12 max-w-[420px]" aria-hidden="true" />
        <p className="mx-auto mt-6 max-w-[58ch] text-xs leading-[1.5] text-ink-soft">
          {COUNSEL_DISCLAIMER}
        </p>
      </BlurFade>
    </section>
  );
}

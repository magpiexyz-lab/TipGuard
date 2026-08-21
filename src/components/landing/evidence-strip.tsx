import { BlurFade } from "@/components/magicui/blur-fade";
import { GridPattern } from "@/components/magicui/grid-pattern";
import { NumberTicker } from "@/components/magicui/number-ticker";
import { EVIDENCE, SECTION_IDS } from "./content";

/**
 * Evidence strip — the proof plinth.
 *
 * TipGuard is pre-launch, so there are no testimonials, logos or star ratings
 * on this page. Authority is borrowed from the statute instead: four figures,
 * each divided by an oat hairline, each carrying its own citation. A figure
 * without a source may not appear here.
 */
export function EvidenceStrip() {
  return (
    <section
      id={SECTION_IDS.exposure}
      className="surface-ink relative isolate scroll-mt-24 border-t border-paper/10"
      aria-label="What the statute says"
    >
      <GridPattern
        variant="grid"
        size={32}
        stroke="var(--paper)"
        fade="none"
        className="-z-10 opacity-[0.05]"
      />

      <div className="mx-auto max-w-[1160px] px-5 py-10 sm:px-8 sm:py-12">
        <div className="flex flex-wrap items-baseline justify-between gap-x-8 gap-y-2">
          <p className="font-mono text-[11px] font-medium uppercase tracking-[0.14em] text-brass">
            The arithmetic of a disallowed credit
          </p>
          <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-paper/60">
            Federal floor · states may be stricter
          </p>
        </div>

        <dl className="mt-10 grid grid-cols-2 gap-x-8 gap-y-10 lg:grid-cols-4 lg:gap-x-0">
          {EVIDENCE.map((cell, index) => (
            <BlurFade
              key={cell.citation}
              reveal="settle"
              delay={index * 55}
              className={
                "lg:px-8 " +
                (index === 0 ? "lg:pl-0" : "lg:border-l lg:border-paper/15")
              }
            >
              <dt className="sr-only">{cell.caption}</dt>
              {/* Flex column so the citation sits on the floor of every cell:
                  captions run 3–4 lines, and a citation that floats with its
                  own caption leaves the strip with a ragged 21px baseline. */}
              <dd className="flex h-full flex-col">
                <span className="block font-mono text-[40px] font-medium leading-[1.1] tracking-[-0.2px] text-paper tabular-nums sm:text-[52px]">
                  <NumberTicker
                    value={cell.value}
                    from={cell.from}
                    decimals={cell.decimals}
                    prefix={cell.prefix}
                    suffix={cell.suffix}
                  />
                </span>
                <span
                  aria-hidden="true"
                  className="mt-4 block h-px w-10 bg-brass"
                />
                <span className="mt-4 block max-w-[34ch] text-sm leading-[1.5] text-paper/75">
                  {cell.caption}
                </span>
                {/* Never uppercase: the subsection letter is part of the
                    citation — §203(m) and §203(M) are not the same cite. */}
                <span className="mt-auto block pt-4 font-mono text-[11px] normal-case tracking-[0.06em] text-brass">
                  {cell.citation}
                </span>
              </dd>
            </BlurFade>
          ))}
        </dl>
      </div>
    </section>
  );
}

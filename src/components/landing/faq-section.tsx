import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { BlurFade } from "@/components/magicui/blur-fade";
import { FAQ, SECTION_IDS } from "./content";

/** The statutes the answers above are measured against — same citation
 *  discipline as the evidence plinth: no figure without a source. */
const SOURCES = [
  { cite: "29 U.S.C. §203(m)", label: "tip credit" },
  { cite: "29 CFR §531.59(b)", label: "notice elements" },
  { cite: "29 U.S.C. §216(b)", label: "liquidated damages" },
  { cite: "29 U.S.C. §255(a)", label: "lookback" },
];

/**
 * Objection handling. Layout is a two-column split with the heading held in a
 * left rail, so it does not repeat the centred stack used by the final CTA
 * directly below it. Question one is the legal-scope objection, answered
 * plainly: TipGuard is not a law firm and never claims certification — and it
 * ships OPEN, because that answer is the one an operator needs before any of
 * the others matter.
 *
 * The rail carries a sources plaque so it is not 300px of empty paper next to
 * a full column, and the rows are numbered in the same mono ledger figures used
 * by the exposure section — an accordion, but this page's accordion.
 *
 * Motion: `reveal="slide"` (drawer pull, left to right), deliberately NOT the
 * blur used by the features and price sections above it.
 */
export function FaqSection() {
  return (
    <section
      id={SECTION_IDS.faq}
      className="relative scroll-mt-24 bg-paper py-14 sm:py-18 lg:py-20"
      aria-labelledby="faq-heading"
    >
      <div className="mx-auto grid max-w-[1160px] grid-cols-1 gap-12 px-5 sm:px-8 lg:grid-cols-[minmax(0,340px)_minmax(0,1fr)] lg:gap-20">
        <BlurFade reveal="settle" className="lg:sticky lg:top-28 lg:self-start">
          <p className="eyebrow">Straight answers</p>
          <h2
            id="faq-heading"
            className="mt-5 font-display text-[30px] font-semibold leading-[1.1] tracking-[-1.6px] text-ink sm:text-[38px] lg:text-[44px]"
          >
            The questions an operator actually asks.
          </h2>
          <div className="tg-tick-rule mt-8" data-align="start" />

          <div className="mt-8 rounded-xl border border-border bg-paper-raised p-6">
            <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-brass-deep">
              What the answers are measured against
            </p>
            <ul className="mt-4 space-y-2.5">
              {SOURCES.map((source) => (
                <li
                  key={source.cite}
                  className="flex gap-3 font-mono text-[11px] leading-[1.5] tracking-[0.06em] text-ink-soft"
                >
                  <span aria-hidden="true" className="mt-1.5 size-1.5 shrink-0 bg-brass" />
                  {/* The cite keeps its real casing — §203(m), not §203(M);
                      only the plain-English label is set in small caps. */}
                  <span className="min-w-0">
                    <span className="text-ink">{source.cite}</span>{" "}
                    <span className="uppercase tracking-[0.1em]">
                      · {source.label}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
            <p className="mt-5 border-t border-border pt-4 text-sm leading-[1.55] text-ink-soft">
              Federal floor shown. Your state may set a higher cash wage, a
              smaller credit, or none at all — the rule library resolves that
              before a notice is drafted.
            </p>
          </div>
        </BlurFade>

        <div className="min-w-0">
          <Accordion className="w-full" defaultValue={["faq-0"]}>
            {FAQ.map((item, index) => (
              <BlurFade
                key={item.q}
                reveal="slide"
                delay={Math.min(index, 5) * 45}
              >
                <AccordionItem
                  value={`faq-${index}`}
                  className="tg-row group border-b border-border"
                >
                  <AccordionTrigger className="items-center gap-6 py-6 pl-4 text-left font-display text-lg font-semibold leading-[1.25] tracking-[-0.6px] text-ink transition-colors duration-[140ms] hover:no-underline hover:text-brass-deep sm:text-xl **:data-[slot=accordion-trigger-icon]:size-5 **:data-[slot=accordion-trigger-icon]:text-brass-deep">
                    <span className="flex min-w-0 items-baseline gap-5">
                      <span
                        aria-hidden="true"
                        className="figure shrink-0 text-xs text-brass-deep"
                      >
                        {String(index + 1).padStart(2, "0")}
                      </span>
                      {item.q}
                    </span>
                  </AccordionTrigger>
                  <AccordionContent className="max-w-[62ch] pb-7 pl-4 text-base leading-[1.55] text-ink-soft sm:pl-[3.25rem]">
                    {item.a}
                  </AccordionContent>
                </AccordionItem>
              </BlurFade>
            ))}
          </Accordion>
        </div>
      </div>
    </section>
  );
}

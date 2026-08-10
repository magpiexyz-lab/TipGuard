import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { BlurFade } from "@/components/magicui/blur-fade";
import { FAQ, SECTION_IDS } from "./content";

/**
 * Objection handling. Layout is a two-column split with the heading held in a
 * left rail, so it does not repeat the centred stack used by the final CTA
 * directly below it. Question one is the legal-scope objection, answered
 * plainly: TipGuard is not a law firm and never claims certification.
 */
export function FaqSection() {
  return (
    <section
      id={SECTION_IDS.faq}
      className="relative scroll-mt-24 bg-paper py-20 sm:py-28 lg:py-32"
      aria-labelledby="faq-heading"
    >
      <div className="mx-auto grid max-w-[1160px] grid-cols-1 gap-12 px-5 sm:px-8 lg:grid-cols-[minmax(0,340px)_minmax(0,1fr)] lg:gap-20">
        <BlurFade className="lg:sticky lg:top-28 lg:self-start">
          <p className="eyebrow">Straight answers</p>
          <h2
            id="faq-heading"
            className="mt-5 font-display text-[30px] font-semibold leading-[1.1] tracking-[-1.6px] text-ink sm:text-[38px] lg:text-[44px]"
          >
            The questions an operator actually asks.
          </h2>
          <div className="tg-tick-rule mt-8" data-align="start" />
        </BlurFade>

        <BlurFade delay={55} className="min-w-0">
          <Accordion className="w-full">
            {FAQ.map((item, index) => (
              <AccordionItem
                key={item.q}
                value={`faq-${index}`}
                className="border-b border-border"
              >
                <AccordionTrigger className="py-6 text-left font-display text-lg font-semibold leading-[1.25] tracking-[-0.6px] text-ink hover:no-underline sm:text-xl">
                  {item.q}
                </AccordionTrigger>
                <AccordionContent className="max-w-[62ch] pb-6 text-base leading-[1.55] text-ink-soft">
                  {item.a}
                </AccordionContent>
              </AccordionItem>
            ))}
          </Accordion>
        </BlurFade>
      </div>
    </section>
  );
}

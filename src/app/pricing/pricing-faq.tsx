"use client";

import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { PRICING_FAQ } from "./pricing-data";

export function PricingFaq() {
  return (
    <section
      aria-labelledby="faq-heading"
      className="border-t border-border"
    >
      <div className="mx-auto grid max-w-[1120px] gap-10 px-6 py-12 sm:py-14 lg:grid-cols-[0.8fr_1.2fr] lg:gap-16">
        <div className="lg:sticky lg:top-8 lg:self-start">
          <p className="eyebrow">Before you decide</p>
          <h2 id="faq-heading" className="mt-4 text-3xl sm:text-[44px]">
            The questions an operator actually asks
          </h2>
          <p className="mt-5 text-base leading-[1.55] text-ink-soft">
            Including the one about whether any of this counts as legal advice.
            It does not, and the product says so on every notice it generates.
          </p>
        </div>

        <Accordion defaultValue={["free-tier"]} className="gap-0">
          {PRICING_FAQ.map((entry) => (
            <AccordionItem key={entry.id} value={entry.id} className="border-b border-border">
              {/* The trigger is an <h3>, so it inherits the display serif at
                  letter-spacing:-1.2px — tuned for 44px+ section heads and far
                  too tight at UI size. Set the size and tracking explicitly. */}
              <AccordionTrigger className="py-5 text-lg font-medium tracking-[-0.3px] [word-spacing:0.06em]">
                {entry.question}
              </AccordionTrigger>
              <AccordionContent>
                <p className="max-w-2xl pb-5 text-sm leading-[1.6] text-ink-soft">
                  {entry.answer}
                </p>
              </AccordionContent>
            </AccordionItem>
          ))}
        </Accordion>
      </div>
    </section>
  );
}

import Image from "next/image";
import { AnimatedShinyText } from "@/components/magicui/animated-shiny-text";
import { GridPattern } from "@/components/magicui/grid-pattern";
import type { Variant } from "@/lib/variants";
import { CtaButton } from "./cta-button";
import { SignatureCard } from "./signature-card";
import { HERO_IMAGE, SECTION_IDS } from "./content";

const ASSURANCES = ["7 questions", "No account", "No card"];

/**
 * Hero — full-bleed ink over real photography.
 *
 * The photograph is graded warm and holds its low-detail weight on the left,
 * which is where the headline sits; an explicit `--ink` scrim (not reduced
 * image opacity) carries the type to 4.5:1. Three z-layers are visible at once:
 * photograph → ink scrim + brass bloom + ledger rules → copy and the live
 * notice card.
 */
export function Hero({ variant }: { variant: Variant }) {
  return (
    <section
      id="top"
      className="surface-ink relative isolate overflow-hidden"
      aria-labelledby="hero-headline"
    >
      <Image
        src={HERO_IMAGE.src}
        alt={HERO_IMAGE.alt}
        fill
        priority
        sizes="100vw"
        className="-z-30 object-cover object-[70%_center]"
      />

      {/* Ink scrim — heavy on the left where the copy lives. */}
      <div
        aria-hidden="true"
        className="absolute inset-0 -z-20"
        style={{
          backgroundImage:
            "linear-gradient(100deg, var(--ink) 0%, color-mix(in srgb, var(--ink) 96%, transparent) 26%, color-mix(in srgb, var(--ink) 80%, transparent) 46%, color-mix(in srgb, var(--ink) 46%, transparent) 72%, color-mix(in srgb, var(--ink) 22%, transparent) 100%)",
        }}
      />
      <div
        aria-hidden="true"
        className="absolute inset-0 -z-20"
        style={{
          backgroundImage:
            "linear-gradient(to top, var(--ink) 2%, color-mix(in srgb, var(--ink) 30%, transparent) 26%, transparent 55%)",
        }}
      />
      <div aria-hidden="true" className="bloom-brass absolute inset-0 -z-10" />
      <GridPattern
        variant="rule"
        size={32}
        stroke="var(--paper)"
        fade="bottom"
        className="-z-10 opacity-[0.07]"
      />

      <div className="mx-auto grid max-w-[1160px] grid-cols-1 items-center gap-14 px-5 pb-24 pt-32 sm:px-8 sm:pb-28 sm:pt-36 lg:grid-cols-[minmax(0,1fr)_minmax(0,430px)] lg:gap-16 lg:pb-36 lg:pt-44">
        <div className="min-w-0">
          <div className="tg-rise flex items-center gap-3">
            <span aria-hidden="true" className="h-px w-8 shrink-0 bg-brass" />
            <AnimatedShinyText
              tone="ink"
              className="whitespace-nowrap font-mono text-[11px] font-medium uppercase tracking-[0.14em]"
            >
              U.S. tip-credit compliance
            </AnimatedShinyText>
          </div>

          <h1
            id="hero-headline"
            className="tg-rise mt-7 max-w-[15ch] font-display text-[38px] font-bold leading-[1.04] tracking-[-1.4px] text-paper sm:text-[52px] sm:tracking-[-1.8px] lg:text-[62px] lg:tracking-[-2px] xl:text-[72px]"
            style={{ animationDelay: "70ms" }}
          >
            {variant.headline}
          </h1>

          <p
            className="tg-rise mt-7 max-w-xl text-lg leading-[1.55] text-paper/80 sm:text-xl"
            style={{ animationDelay: "140ms" }}
          >
            {variant.subheadline}
          </p>

          <div
            className="tg-rise mt-9 flex flex-col items-start gap-4 sm:flex-row sm:items-center"
            style={{ animationDelay: "210ms" }}
          >
            <CtaButton
              variantSlug={variant.slug}
              position="hero"
              label={variant.cta}
              size="lg"
            />
            {/* The secondary path needs a standing affordance: next to a solid
                brass button, unadorned text reads as a caption. The chevron is
                always drawn and travels down 2px on hover. */}
            <a
              href={`#${SECTION_IDS.how}`}
              style={{ ["--tg-underline" as string]: "11px" }}
              className="tg-link group inline-flex min-h-11 items-center gap-2 text-sm text-paper/75 transition-colors duration-[140ms] hover:text-paper"
            >
              See what lands in the file
              <svg
                aria-hidden="true"
                viewBox="0 0 16 16"
                fill="none"
                className="size-3.5 shrink-0 text-brass transition-transform duration-[240ms] group-hover:translate-y-0.5"
                style={{ transitionTimingFunction: "var(--ease-ledger)" }}
              >
                <path
                  d="M8 2.5v11M3.5 9.5L8 14l4.5-4.5"
                  stroke="currentColor"
                  strokeWidth="1.6"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </a>
          </div>

          <ul
            className="tg-rise mt-8 flex flex-wrap items-center gap-x-6 gap-y-2"
            style={{ animationDelay: "280ms" }}
          >
            {ASSURANCES.map((item) => (
              <li
                key={item}
                className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.14em] text-paper/70"
              >
                <span aria-hidden="true" className="size-1.5 bg-brass" />
                {item}
              </li>
            ))}
          </ul>

          <p
            className="tg-rise mt-8 max-w-md border-l-2 border-brass pl-4 text-sm leading-[1.55] text-paper/70"
            style={{ animationDelay: "350ms" }}
          >
            {variant.urgency}
          </p>
        </div>

        <div className="tg-rise w-full min-w-0" style={{ animationDelay: "300ms" }}>
          <SignatureCard />
        </div>
      </div>
    </section>
  );
}

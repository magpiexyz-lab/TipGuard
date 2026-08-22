"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ScrollProgress } from "@/components/magicui/scroll-progress";
import { cn } from "@/lib/utils";
import type { VariantSlug } from "@/lib/variants";
import { CtaButton } from "./cta-button";
import { LOGO, SECTION_IDS } from "./content";

const NAV = [
  { href: `#${SECTION_IDS.exposure}`, label: "Exposure" },
  { href: `#${SECTION_IDS.how}`, label: "How it works" },
  { href: `#${SECTION_IDS.pricing}`, label: "Pricing" },
];

/**
 * Sticky header. Two scroll-triggered events live here:
 *   1. the bar itself flips surface temperature (transparent over the ink hero
 *      → oat paper glass once the reader leaves the hero)
 *   2. a brass scroll-progress filament fills along its bottom edge
 */
export function SiteHeader({
  variantSlug,
  ctaLabel,
}: {
  variantSlug: VariantSlug;
  ctaLabel: string;
}) {
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 24);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <header
      className={cn(
        "fixed inset-x-0 top-0 z-50 transition-all duration-[240ms]",
        scrolled
          ? "bg-paper-raised/90 text-ink shadow-ledger-1 backdrop-blur-md"
          : "bg-transparent text-paper"
      )}
      style={{ transitionTimingFunction: "var(--ease-ledger)" }}
    >
      <div
        className={cn(
          "mx-auto flex max-w-[1160px] items-center gap-6 px-5 sm:px-8",
          scrolled ? "h-16" : "h-20"
        )}
      >
        {/* min-h-11: the brand mark is the only tap target on the left of the
            mobile bar, so it has to clear the 44px touch floor rather than
            inherit the 36px height of the logo badge. */}
        <a
          href="#top"
          className="-mx-1 flex min-h-11 items-center gap-3 px-1"
          aria-label="TipGuard — home"
        >
          <span className="grid size-9 shrink-0 place-items-center rounded-md bg-paper shadow-ledger-1">
            {/* SVG asset — rendered with <img> per the image manifest contract. */}
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={LOGO.src} alt={LOGO.alt} width={24} height={24} className="size-6" />
          </span>
          <span className="font-display text-xl font-semibold tracking-[-0.6px]">
            TipGuard
          </span>
        </a>

        <nav className="ml-auto hidden items-center gap-8 md:flex" aria-label="Landing sections">
          {NAV.map((item) => (
            <a
              key={item.href}
              href={item.href}
              style={{ ["--tg-underline" as string]: "10px" }}
              className={cn(
                // min-h-11 clears the pointer-target floor; --tg-underline
                // re-seats the brass draw under the text, not the padded box.
                "tg-link inline-flex min-h-11 items-center text-sm transition-colors duration-[140ms]",
                scrolled ? "text-ink-soft hover:text-ink" : "text-paper/75 hover:text-paper"
              )}
            >
              {item.label}
            </a>
          ))}
        </nav>

        <div className={cn("flex items-center gap-4", "md:ml-0 ml-auto")}>
          {/* Two named doors. The score CTA beside them is still the measured
              funnel entrance (h-01 -> h-03), so both of these stay quiet text
              links rather than competing buttons — but a visitor who already
              knows what they want must be able to say so. "Sign in" alone was
              not enough: it is the wrong word for someone who has no account
              yet, and /signup was otherwise reachable only from the score
              results page. */}
          <Link
            href="/login"
            className={cn(
              "hidden min-h-11 items-center text-sm transition-colors duration-[140ms] sm:inline-flex",
              scrolled ? "text-ink-soft hover:text-ink" : "text-paper/75 hover:text-paper"
            )}
          >
            Sign in
          </Link>
          <Link
            href="/signup"
            className={cn(
              "hidden min-h-11 items-center text-sm font-medium transition-colors duration-[140ms] sm:inline-flex",
              scrolled ? "text-ink hover:text-brass-deep" : "text-paper hover:text-brass"
            )}
          >
            Sign up
          </Link>
          <CtaButton
            variantSlug={variantSlug}
            position="header"
            label={ctaLabel}
            size="sm"
            className="max-w-[52vw] truncate"
          />
        </div>
      </div>

      <div className="relative h-px w-full">
        <div
          className={cn(
            "absolute inset-0 transition-opacity duration-[240ms]",
            scrolled ? "bg-border opacity-100" : "opacity-0"
          )}
        />
        <ScrollProgress />
      </div>
    </header>
  );
}

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
  { href: `#${SECTION_IDS.faq}`, label: "FAQ" },
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
          <span
            className={cn(
              "hidden font-mono text-[11px] uppercase tracking-[0.14em] lg:inline",
              scrolled ? "text-brass-deep" : "text-brass"
            )}
          >
            Free · No account
          </span>
          {/* The score CTA is the measured funnel entrance and stays primary.
              This is the door for someone who already has an account (or wants
              one) — before it existed, /login was unreachable from the landing
              page and /signup from anywhere but the score results. */}
          <Link
            href="/login"
            className={cn(
              "hidden min-h-11 items-center text-sm transition-colors duration-[140ms] sm:inline-flex",
              scrolled ? "text-ink-soft hover:text-ink" : "text-paper/75 hover:text-paper"
            )}
          >
            Sign in
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

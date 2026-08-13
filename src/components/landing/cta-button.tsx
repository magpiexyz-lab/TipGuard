"use client";

import Link from "next/link";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { trackCtaClick } from "@/lib/events";
import type { VariantSlug } from "@/lib/variants";

/**
 * The single conversion control on this page (b-01).
 *
 * Fires `cta_click` with the variant slug and the position of the control that
 * was clicked, then navigates to `/score` — the free, unauthenticated
 * audit-readiness hook. Tracking is synchronous (the analytics lib queues
 * before the SDK resolves), so the click is never lost to the navigation.
 */
export function CtaButton({
  variantSlug,
  position,
  label,
  size = "lg",
  tone = "brass",
  className,
}: {
  variantSlug: VariantSlug;
  /** EVENTS.yaml cta_position — hero | feature_section | pricing | footer | header */
  position: string;
  label: string;
  size?: "sm" | "lg";
  tone?: "brass" | "outline-ink" | "outline-paper";
  className?: string;
}) {
  return (
    <Link
      href="/score"
      data-cta={position}
      onClick={() => trackCtaClick({ variant: variantSlug, cta_position: position })}
      className={cn(
        buttonVariants({ variant: "default" }),
        // Primary CTA is the one soft gesture on the page: a brass pill.
        "rounded-full font-medium tracking-[-0.1px] transition-all duration-[140ms]",
        "focus-visible:ring-brass/50",
        // 44px minimum on touch viewports; the compact 40px header pill only
        // applies from sm up, where the pointer is a mouse.
        size === "lg" ? "h-12 px-7 text-base" : "h-11 px-5 text-sm sm:h-10",
        tone === "brass" &&
          "bg-brass text-ink shadow-ledger-2 hover:bg-brass hover:brightness-95 active:translate-y-px",
        tone === "outline-ink" &&
          "border border-border bg-transparent text-ink hover:bg-brass-soft/40",
        tone === "outline-paper" &&
          "border border-paper/30 bg-transparent text-paper hover:border-brass hover:text-brass",
        className
      )}
    >
      {label}
    </Link>
  );
}

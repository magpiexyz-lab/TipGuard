import Image from "next/image";
import Link from "next/link";

import { cn } from "@/lib/utils";

/**
 * Minimal brand bar for the pages NavBar deliberately suppresses
 * (CHROMELESS_EXACT / CHROMELESS_PREFIXES in src/components/nav-bar.tsx):
 * /sign, /login, /signup and /auth/*.
 *
 * Those pages are chromeless for good reasons - an employee opening a signing
 * link has no TipGuard account, so "Staff", "Notices" and "Dashboard" would be
 * dead ends, and an auth screen should not advertise the app it is gating. But
 * suppressing the whole NavBar also left them with no route back to the
 * marketing site at all, which is a dead end of its own: the signer cannot find
 * out what TipGuard is, and an owner who lands on /login by mistake is stuck.
 *
 * So this is a brand mark, not navigation: one link, to the landing page.
 */
export function BrandHeader({
  tone = "paper",
  className,
}: {
  /** `ink` for dark surfaces, `paper` for light ones. */
  tone?: "paper" | "ink";
  className?: string;
}) {
  return (
    <div className={cn("flex items-center", className)}>
      <Link
        href="/"
        className={cn(
          "-mx-1 inline-flex min-h-11 items-center gap-2 rounded-sm px-1",
          "transition-opacity duration-[var(--duration-fast)] hover:opacity-80",
          "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brass",
        )}
      >
        {/* Decorative: the brand name is announced by the adjacent <span>.
            unoptimized: next/image rejects SVG by default (HTTP 400). */}
        <Image
          src="/images/logo.svg"
          alt=""
          aria-hidden
          width={26}
          height={26}
          unoptimized
        />
        <span
          className={cn(
            "font-display text-lg tracking-[-0.6px]",
            tone === "ink" ? "text-[#ECE8DA]" : "text-foreground",
          )}
        >
          TipGuard
        </span>
      </Link>
    </div>
  );
}

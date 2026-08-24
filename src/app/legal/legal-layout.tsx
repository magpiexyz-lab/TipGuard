import type { ReactNode } from "react";
import Link from "next/link";

/**
 * Shared chrome for /privacy and /terms.
 *
 * These are reference documents, not conversion surfaces: a single measure
 * column, generous leading, and no CTA competing with the text. The global
 * NavBar renders above (they are not in CHROMELESS_EXACT), so the page starts
 * straight into the title.
 */
export function LegalPage({
  title,
  updated,
  intro,
  children,
}: {
  title: string;
  updated: string;
  intro: string;
  children: ReactNode;
}) {
  return (
    <div className="mx-auto max-w-[70ch] px-5 py-14 sm:px-8 sm:py-20">
      <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
        TipGuard
      </p>
      <h1 className="mt-4 font-display text-[34px] leading-[1.1] tracking-[-1.2px] [word-spacing:0.06em] sm:text-[44px]">
        {title}
      </h1>
      <p className="mt-3 font-mono text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
        Last updated {updated}
      </p>
      <p className="mt-6 text-base leading-[1.6] text-muted-foreground">{intro}</p>

      <div className="mt-10 flex flex-col gap-8">{children}</div>

      <p className="mt-14 border-t border-border pt-6 text-sm leading-[1.6] text-muted-foreground">
        Questions about this document? Email{" "}
        <a
          href="mailto:privacy@draftlabs.org"
          className="font-medium text-foreground underline decoration-brass decoration-2 underline-offset-4"
        >
          privacy@draftlabs.org
        </a>
        . See also our{" "}
        <Link
          href={title.startsWith("Privacy") ? "/terms" : "/privacy"}
          className="font-medium text-foreground underline decoration-border decoration-2 underline-offset-4"
        >
          {title.startsWith("Privacy") ? "Terms of Service" : "Privacy Policy"}
        </Link>
        .
      </p>
    </div>
  );
}

export function Section({ heading, children }: { heading: string; children: ReactNode }) {
  return (
    <section>
      <h2 className="font-heading text-xl leading-[1.25] tracking-[-0.01em] [word-spacing:0.03em]">{heading}</h2>
      <div className="mt-3 flex flex-col gap-3 text-[15px] leading-[1.65] text-muted-foreground">
        {children}
      </div>
    </section>
  );
}

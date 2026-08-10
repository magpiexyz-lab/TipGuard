import Link from "next/link";
import { COUNSEL_DISCLAIMER, LOGO, SECTION_IDS } from "./content";

const YEAR = 2026;

/**
 * Footer — the closing ink band. Carries the counsel-review disclaimer at 12px
 * in a solid token colour (never an opacity wash), per the legal constraint in
 * experiment.yaml.
 */
export function SiteFooter() {
  return (
    <footer className="surface-ink border-t border-paper/10">
      <div className="mx-auto max-w-[1160px] px-5 py-14 sm:px-8">
        <div className="flex flex-col gap-10 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <div className="flex items-center gap-3">
              <span className="grid size-9 shrink-0 place-items-center rounded-md bg-paper">
                {/* SVG asset — rendered with <img> per the image manifest contract. */}
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={LOGO.src} alt={LOGO.alt} width={24} height={24} className="size-6" />
              </span>
              <span className="font-display text-xl font-semibold tracking-[-0.6px] text-paper">
                TipGuard
              </span>
            </div>
            <p className="mt-5 max-w-[42ch] text-sm leading-[1.55] text-paper/70">
              Tip-credit compliance for independent restaurants, bars and cafes:
              state-specific notices, signed acknowledgments, and the dated file
              behind them.
            </p>
          </div>

          <nav className="flex flex-col gap-3" aria-label="Footer">
            {[
              { href: `#${SECTION_IDS.exposure}`, label: "Exposure" },
              { href: `#${SECTION_IDS.how}`, label: "How it works" },
              { href: `#${SECTION_IDS.pricing}`, label: "Pricing" },
              { href: `#${SECTION_IDS.faq}`, label: "FAQ" },
            ].map((item) => (
              <a
                key={item.href}
                href={item.href}
                className="tg-link w-fit text-sm text-paper/75 transition-colors duration-[140ms] hover:text-paper"
              >
                {item.label}
              </a>
            ))}
            <Link
              href="/score"
              className="tg-link w-fit text-sm text-brass transition-colors duration-[140ms]"
            >
              Free audit-readiness score
            </Link>
          </nav>
        </div>

        <div className="mt-12 flex flex-col gap-4 border-t border-paper/10 pt-8 sm:flex-row sm:items-center sm:justify-between">
          <p className="max-w-[70ch] text-xs leading-[1.5] text-paper/70">
            {COUNSEL_DISCLAIMER}
          </p>
          <p className="figure shrink-0 text-[11px] text-paper/60">
            © {YEAR} TipGuard
          </p>
        </div>
      </div>
    </footer>
  );
}

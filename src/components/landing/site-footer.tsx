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
      <div className="mx-auto max-w-[1160px] px-5 py-10 sm:px-8">
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

          {/* Links are 44px tall so they clear the mobile touch-target floor;
              `--tg-underline` re-seats the brass draw under the text rather
              than under the padded box. */}
          <nav className="flex flex-col" aria-label="Footer">
            {[
              { href: `#${SECTION_IDS.exposure}`, label: "Exposure" },
              { href: `#${SECTION_IDS.how}`, label: "How it works" },
              { href: `#${SECTION_IDS.pricing}`, label: "Pricing" },
              { href: `#${SECTION_IDS.faq}`, label: "FAQ" },
            ].map((item) => (
              <a
                key={item.href}
                href={item.href}
                style={{ ["--tg-underline" as string]: "9px" }}
                className="tg-link inline-flex min-h-11 w-fit items-center text-sm text-paper/75 transition-colors duration-[140ms] hover:text-paper"
              >
                {item.label}
              </a>
            ))}
            <Link
              href="/score"
              style={{ ["--tg-underline" as string]: "9px" }}
              className="tg-link inline-flex min-h-11 w-fit items-center text-sm text-brass transition-colors duration-[140ms]"
            >
              Free audit-readiness score
            </Link>
            {/* The header's Sign in / Sign up links are sm-and-up only, so on a
                phone this footer is the only place an account is reachable
                without first completing the questionnaire. */}
            <Link
              href="/signup"
              style={{ ["--tg-underline" as string]: "9px" }}
              className="tg-link inline-flex min-h-11 w-fit items-center text-sm text-paper/75 transition-colors duration-[140ms] hover:text-paper"
            >
              Create an account
            </Link>
            <Link
              href="/login"
              style={{ ["--tg-underline" as string]: "9px" }}
              className="tg-link inline-flex min-h-11 w-fit items-center text-sm text-paper/75 transition-colors duration-[140ms] hover:text-paper"
            >
              Sign in
            </Link>
            {/* Google's OAuth consent screen will not publish an app without
                reachable privacy and terms URLs, and a product that asks for a
                payroll roster should be linking these anyway. */}
            <Link
              href="/privacy"
              style={{ ["--tg-underline" as string]: "9px" }}
              className="tg-link inline-flex min-h-11 w-fit items-center text-sm text-paper/60 transition-colors duration-[140ms] hover:text-paper"
            >
              Privacy
            </Link>
            <Link
              href="/terms"
              style={{ ["--tg-underline" as string]: "9px" }}
              className="tg-link inline-flex min-h-11 w-fit items-center text-sm text-paper/60 transition-colors duration-[140ms] hover:text-paper"
            >
              Terms
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

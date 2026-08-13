import Image from "next/image";
import Link from "next/link";
import { Clock, Link2Off, Mail, TriangleAlert } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { formatUtcDate } from "./format";

type LinkErrorKind = "missing_token" | "not_found" | "expired" | "unavailable";

/**
 * Terminal states for a signing link. Every one of these renders WITHOUT a
 * name field and WITHOUT a submit control — behavior b-07 requires that an
 * invalid, expired, or already-consumed token cannot sign. There is no code
 * path from this component to `/api/notices/sign`.
 *
 * The audience is an employee who has never heard of TipGuard, standing in a
 * break room on a phone. Each state therefore says (a) what happened in one
 * sentence, (b) that nothing is wrong with them, (c) the single next action.
 */
export function SigningLinkError({
  kind,
  employerName,
  expiresAt,
}: {
  kind: LinkErrorKind;
  employerName?: string;
  expiresAt?: string;
}) {
  const employer = employerName?.trim() || "your employer";

  const copy: Record<
    LinkErrorKind,
    { heading: string; lead: string; steps: string[]; tone: "neutral" | "warning" }
  > = {
    missing_token: {
      heading: "This signing link is incomplete",
      lead: `The address you opened is missing the private code that identifies your notice. Email apps sometimes cut long links across two lines, which drops the end of the address.`,
      steps: [
        "Go back to the email and tap the full button or link rather than copying the address by hand.",
        `If the link still will not open, ask ${employer} to resend it — a fresh link takes them one click.`,
      ],
      tone: "neutral",
    },
    not_found: {
      heading: "We could not find this signing request",
      lead: `This link does not match any notice we are holding. That usually means it was already replaced by a newer link, or a character was lost when the address was copied.`,
      steps: [
        "Open the most recent email from your employer — the newest link is the live one.",
        `Ask ${employer} to send a new signing link if you no longer have the email.`,
      ],
      tone: "neutral",
    },
    expired: {
      heading: "This signing link has expired",
      lead: `Signing links are time-limited so an old link cannot be used later by someone else. This one closed on ${formatUtcDate(expiresAt)}.`,
      steps: [
        `Ask ${employer} to resend the notice. Your new link will contain the same notice text.`,
        "Nothing you did caused this, and nothing has been recorded against your name.",
      ],
      tone: "warning",
    },
    unavailable: {
      heading: "We cannot open this notice right now",
      lead: "The signing service is temporarily unreachable, so we cannot confirm your link. Your link has not been used up and is still valid.",
      steps: [
        "Reload this page in a minute or two.",
        `If it keeps failing, tell ${employer} — they can resend the notice.`,
      ],
      tone: "warning",
    },
  };

  const { heading, lead, steps, tone } = copy[kind];
  const Icon = kind === "expired" ? Clock : kind === "unavailable" ? TriangleAlert : Link2Off;

  return (
    <section aria-labelledby="signing-link-error" className="mt-8">
      <div className="overflow-hidden rounded-xl bg-paper-raised elev-2">
        <div className="flex flex-col items-center px-5 pt-8 text-center sm:px-10 sm:pt-10">
          {/* The illustration is rendered on its own inset plate. The asset is
              matted on --paper (#f3f0e6); dropping it straight onto the
              --paper-raised card (#fbf9f2) leaves a visible lighter square
              around it. Matching the plate to the mat turns that seam into a
              deliberate mounted stamp. */}
          <div className="rounded-2xl bg-paper p-3 ring-1 ring-foreground/10 shadow-[inset_0_1px_2px_rgba(23,28,19,0.06)]">
            <Image
              src="/images/empty-state.webp"
              alt=""
              aria-hidden="true"
              width={400}
              height={400}
              className="h-32 w-32 object-contain sm:h-36 sm:w-36"
              priority
            />
          </div>
          <p className="eyebrow mt-5 flex items-center gap-1.5">
            <Icon className="size-3.5" aria-hidden="true" />
            Nothing was signed
          </p>
          {/* This is the page's only <h1> in every terminal state — the ready
              view owns the h1 otherwise, and the two never render together. */}
          <h1
            id="signing-link-error"
            className="mt-3 font-display text-[26px] leading-[1.15] tracking-[-1.2px] text-foreground sm:text-[32px]"
          >
            {heading}
          </h1>
          <p className="mt-3 max-w-[46ch] text-[15px] leading-[1.55] text-ink-soft">
            {lead}
          </p>
        </div>

        <div className="px-5 py-8 sm:px-10">
          <h2 className="eyebrow">What to do next</h2>
          <ol className="mt-4 space-y-4">
            {steps.map((step, index) => (
              <li key={step} className="flex gap-3.5">
                <span
                  aria-hidden="true"
                  className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-md bg-brass/15 font-mono text-[12px] tabular-nums text-brass-deep dark:text-brass"
                >
                  {index + 1}
                </span>
                <span className="text-[15px] leading-[1.55] text-foreground">
                  {step}
                </span>
              </li>
            ))}
          </ol>

          {tone === "warning" ? (
            <Alert className="mt-6 rounded-lg border-transparent bg-ember/10 ring-1 ring-ember/20">
              <Mail className="text-destructive" aria-hidden="true" />
              <AlertTitle className="text-[14px] text-foreground">
                Your employer still needs this signature
              </AlertTitle>
              <AlertDescription className="text-sm leading-[1.6] text-ink-soft">
                The notice is a wage-and-hour record your employer is required
                to keep. Letting them know the link failed is the fastest way to
                close it out.
              </AlertDescription>
            </Alert>
          ) : null}
        </div>
      </div>

      <div className="mt-6 flex flex-col items-start gap-3 sm:flex-row sm:items-center">
        <Link
          href="/"
          className={cn(
            buttonVariants({ variant: "outline" }),
            "h-11 w-full rounded-lg px-5 text-base sm:w-auto"
          )}
        >
          What is TipGuard?
        </Link>
        <span className="text-sm leading-[1.5] text-ink-soft">
          TipGuard is the record-keeping software your employer uses. You are
          not signing up for anything here.
        </span>
      </div>
    </section>
  );
}

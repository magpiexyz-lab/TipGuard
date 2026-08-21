import type { Metadata } from "next";
import Link from "next/link";
import { FileText, Info, Mail, PenLine, ShieldCheck } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";
import { formatUtcStamp } from "./format";
import { SigningLinkError } from "./link-error";
import { loadSigningLink, type SigningLinkState } from "./notice-lookup";
import { NoticeDocument } from "./notice-document";
import { SignForm } from "./sign-form";

// The signing link is single-use and time-limited, and its validity is
// resolved per request against `expires_at` / `used_at`. Nothing on this route
// may ever be prerendered or cached.
export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Sign notice · TipGuard",
  description:
    "Read the tip-credit notice your employer sent you and confirm you received it. Your signature is stored with the date and the exact text you read.",
};

export default async function SignPage({
  searchParams,
}: {
  searchParams: Promise<{ token?: string | string[] }>;
}) {
  const params = await searchParams;
  const rawToken = Array.isArray(params.token) ? params.token[0] : params.token;

  // Server-side resolution. The browser is never asked whether the token is
  // valid, and an invalid/expired/consumed token never reaches a form.
  const link: SigningLinkState = await loadSigningLink(rawToken);

  const employerName =
    link.status === "ready" ||
    link.status === "expired" ||
    link.status === "already_signed"
      ? link.employerName
      : null;

  return (
    // No `overflow-x-hidden` here: an overflow clip on this wrapper makes it the
    // scrollport for everything inside, which silently disables the sticky
    // evidence strip in NoticeDocument. The only absolutely-positioned child is
    // `inset-x-0`, so it cannot overflow horizontally on its own.
    <div className="relative min-h-screen">
      {/* Scroll-driven reveal for the two explanatory sections. Pure CSS view()
          timelines — no client component, no observer. Guarded by @supports so
          browsers without scroll-linked animations simply render the final
          state, and by prefers-reduced-motion for the same reason. */}
      <style>{`
@supports (animation-timeline: view()) {
  @media (prefers-reduced-motion: no-preference) {
    @keyframes sign-ledger-in {
      from { opacity: 0; transform: translateY(16px); }
      to   { opacity: 1; transform: none; }
    }
    .reveal-ledger {
      animation: sign-ledger-in linear both;
      animation-timeline: view();
      animation-range: entry 8% cover 24%;
    }
  }
}
      `}</style>

      {/* Depth layer 1 — ruled ledger hairlines + brass bar-light bloom,
          faded out down the page so the document sits on paper, not on a grid. */}
      <div
        aria-hidden="true"
        className="texture-rule bloom-brass pointer-events-none absolute inset-x-0 top-0 h-[380px]"
        style={{
          maskImage: "linear-gradient(to bottom, black, transparent)",
          WebkitMaskImage: "linear-gradient(to bottom, black, transparent)",
        }}
      />

      <div className="relative mx-auto w-full max-w-[760px] px-5 pt-6 pb-12 sm:px-8 sm:pt-8">
        <Masthead employerName={employerName} status={link.status} />

        {link.status === "ready" ? (
          <ReadyView link={link} />
        ) : link.status === "already_signed" ? (
          <AlreadySignedView link={link} />
        ) : (
          <SigningLinkError
            kind={link.status}
            employerName={employerName ?? undefined}
            expiresAt={link.status === "expired" ? link.expiresAt : undefined}
          />
        )}

        <PageFooter />
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */

function Masthead({
  employerName,
  status,
}: {
  employerName: string | null;
  status: SigningLinkState["status"];
}) {
  const chip =
    status === "ready"
      ? { label: "Awaiting signature", tone: "brass" as const }
      : status === "already_signed"
        ? { label: "Signed", tone: "seal" as const }
        : { label: "Not signable", tone: "muted" as const };

  return (
    <header className="flex flex-wrap items-start justify-between gap-4">
      <div className="min-w-0">
        <p className="eyebrow">Tip-credit notice · signature request</p>
        <p className="mt-2 text-[15px] leading-[1.5] text-ink-soft">
          Sent by{" "}
          <span className="font-medium text-foreground">
            {employerName ?? "your employer"}
          </span>{" "}
          through TipGuard
        </p>
      </div>
      <Badge
        variant="outline"
        className={cn(
          "h-6 shrink-0 rounded-md border-transparent px-2.5 font-mono text-[11px] tracking-[0.1em] uppercase",
          chip.tone === "brass" && "bg-brass/15 text-brass-deep dark:text-brass",
          chip.tone === "seal" && "bg-seal/15 text-seal dark:text-seal-soft",
          chip.tone === "muted" && "bg-muted text-ink-soft"
        )}
      >
        {chip.label}
      </Badge>
    </header>
  );
}

function ReadyView({
  link,
}: {
  link: Extract<SigningLinkState, { status: "ready" }>;
}) {
  return (
    <>
      <h1 className="mt-7 max-w-[18ch] font-display text-[38px] leading-[1.04] tracking-[-1.4px] text-foreground sm:text-[52px] sm:tracking-[-2px]">
        Sign your tip-credit notice
      </h1>
      <p className="mt-5 max-w-[54ch] text-[17px] leading-[1.55] text-ink-soft sm:text-xl">
        {link.employeeName ? `${link.employeeName}, y` : "Y"}our employer is
        required to give you this notice in writing before paying a tipped cash
        wage. Read it below, then type your name to confirm you received it.
      </p>

      {link.isDemo ? <DemoNotice /> : null}

      <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-1.5">
        <p className="font-mono text-[13px] tabular-nums text-ink-soft">
          Link valid until {formatUtcStamp(link.expiresAt)}
        </p>
        <p className="font-mono text-[13px] tabular-nums text-ink-soft">
          Sent {formatUtcStamp(link.sentAt)}
        </p>
      </div>

      <Orientation />

      <section aria-labelledby="the-notice" className="mt-12">
        <p className="eyebrow">Step 1 of 2</p>
        <h2
          id="the-notice"
          className="mt-2 font-display text-[28px] leading-[1.1] tracking-[-1.6px] text-foreground sm:text-[34px]"
        >
          The notice from {link.employerName}
        </h2>
        <p className="mt-2 max-w-[58ch] text-[15px] leading-[1.55] text-ink-soft">
          This is the exact text your employer sent. A copy of it is frozen
          into your signature record, so it cannot be changed afterwards.
        </p>
        <NoticeDocument
          headingId="the-notice"
          recordId={link.recordId}
          state={link.state}
          ruleVersion={link.ruleVersion}
          cashWagePaid={link.cashWagePaid}
          tipCreditClaimed={link.tipCreditClaimed}
          noticeText={link.noticeText}
        />
      </section>

      <section aria-labelledby="acknowledge" className="mt-12">
        <h2 id="acknowledge" className="sr-only">
          Acknowledge this notice
        </h2>
        <SignForm
          token={link.token}
          noticeId={link.noticeId}
          employeeName={link.employeeName}
          employerName={link.employerName}
          sentAt={link.sentAt}
        />
      </section>

      <RecordedFacts />
    </>
  );
}

function AlreadySignedView({
  link,
}: {
  link: Extract<SigningLinkState, { status: "already_signed" }>;
}) {
  return (
    <>
      <h1 className="mt-7 max-w-[20ch] font-display text-[38px] leading-[1.04] tracking-[-1.4px] text-foreground sm:text-[52px] sm:tracking-[-2px]">
        This notice is already signed
      </h1>
      <p className="mt-5 max-w-[54ch] text-[17px] leading-[1.55] text-ink-soft sm:text-xl">
        Nothing further is needed from you. Signing links work once, so this one
        is now closed — the record below is what your employer holds.
      </p>

      <section aria-labelledby="signed-record" className="mt-8">
        <h2
          id="signed-record"
          className="font-display text-[28px] leading-[1.1] tracking-[-1.6px] text-foreground sm:text-[34px]"
        >
          Your signature record
        </h2>

        <dl className="mt-5 grid grid-cols-1 gap-px overflow-hidden rounded-xl bg-border elev-1 sm:grid-cols-3">
          <div className="bg-paper-raised px-5 py-4">
            <dt className="eyebrow">Signed by</dt>
            <dd className="mt-1.5 text-[15px] leading-[1.4] text-foreground">
              {link.signerName ?? link.employeeName ?? "—"}
            </dd>
          </div>
          <div className="bg-paper-raised px-5 py-4">
            <dt className="eyebrow">Recorded at</dt>
            <dd className="mt-1.5 font-mono text-[15px] tabular-nums tracking-[-0.2px] text-foreground">
              {formatUtcStamp(link.signedAt)}
            </dd>
          </div>
          <div className="bg-paper-raised px-5 py-4">
            <dt className="eyebrow">Held by</dt>
            <dd className="mt-1.5 text-[15px] leading-[1.4] text-foreground">
              {link.employerName}
            </dd>
          </div>
        </dl>

        <Alert className="mt-5 rounded-lg border-transparent bg-seal/10 ring-1 ring-seal/25">
          <ShieldCheck className="text-seal dark:text-seal-soft" aria-hidden="true" />
          <AlertTitle className="text-[14px] text-foreground">
            The text below is the copy frozen at signature time
          </AlertTitle>
          <AlertDescription className="text-sm leading-[1.6] text-ink-soft">
            It is stored separately from the live notice. If your employer edits
            the notice later, this copy — the one your signature refers to — does
            not change.
          </AlertDescription>
        </Alert>

        {link.noticeTextSnapshot ? (
          <NoticeDocument
            headingId="signed-record"
            variant="frozen"
            recordId={link.recordId}
            state={link.state}
            ruleVersion={link.ruleVersion}
            cashWagePaid={null}
            tipCreditClaimed={false}
            noticeText={link.noticeTextSnapshot}
          />
        ) : (
          <p className="mt-6 rounded-xl bg-paper-raised px-5 py-6 text-[15px] leading-[1.55] text-ink-soft elev-1">
            The signed copy is held in your employer&rsquo;s audit file. Ask{" "}
            {link.employerName} for a copy of the notice you acknowledged.
          </p>
        )}
      </section>

      <div className="mt-8 flex flex-col items-start gap-3 sm:flex-row sm:items-center">
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
          You can close this page. There is no account to create.
        </span>
      </div>
    </>
  );
}

/* -------------------------------------------------------------------------- */

function DemoNotice() {
  return (
    <Alert className="mt-6 rounded-lg border-transparent bg-muted ring-1 ring-foreground/10">
      <Info className="text-ink-soft" aria-hidden="true" />
      <AlertTitle className="text-[14px] text-foreground">
        Demo mode — sample notice
      </AlertTitle>
      <AlertDescription className="text-sm leading-[1.6] text-ink-soft">
        This environment has no database connected, so the notice below is
        generated sample data for a fictional restaurant. No real signature can
        be recorded here.
      </AlertDescription>
    </Alert>
  );
}

function Orientation() {
  const steps: { icon: typeof FileText; title: string; body: string }[] = [
    {
      icon: FileText,
      title: "Read the notice",
      body: "It states the cash wage you are paid, the tip credit your employer claims, and the rules that apply in your state.",
    },
    {
      icon: PenLine,
      title: "Type your legal name",
      body: "That is your signature. It confirms you received the notice — it is not a contract and it does not waive any right you have.",
    },
    {
      icon: Mail,
      title: "Your employer keeps a dated copy",
      body: "Federal rules require them to hold proof that you were told before the tipped wage applies. That is the only purpose of this page.",
    },
  ];

  return (
    <section aria-labelledby="what-this-is" className="reveal-ledger mt-10">
      <h2
        id="what-this-is"
        className="font-display text-[24px] leading-[1.15] tracking-[-1.2px] text-foreground sm:text-[28px]"
      >
        What you are being asked to do
      </h2>
      <ol className="mt-5 grid gap-px overflow-hidden rounded-xl bg-border elev-1 sm:grid-cols-3">
        {steps.map((step, index) => {
          const Icon = step.icon;
          return (
            <li key={step.title} className="bg-paper-raised px-5 py-5">
              <p className="eyebrow flex items-center gap-1.5">
                <Icon className="size-3.5" aria-hidden="true" />
                Step {index + 1}
              </p>
              <h3 className="mt-2.5 font-display text-[18px] leading-[1.15] tracking-[-0.6px] text-foreground">
                {step.title}
              </h3>
              <p className="mt-1.5 text-sm leading-[1.5] text-ink-soft">
                {step.body}
              </p>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function RecordedFacts() {
  const items = [
    { label: "Your typed name", value: "exactly as you enter it" },
    { label: "Date and time", value: "recorded in UTC by our server" },
    { label: "IP address", value: "of the device you sign from" },
    { label: "Browser and device", value: "the user agent string" },
    { label: "The notice text", value: "an exact frozen copy" },
  ];

  return (
    <section aria-labelledby="what-is-recorded" className="reveal-ledger mt-12">
      <h2
        id="what-is-recorded"
        className="font-display text-[24px] leading-[1.15] tracking-[-1.2px] text-foreground sm:text-[28px]"
      >
        What gets recorded when you sign
      </h2>
      <p className="mt-2 max-w-[58ch] text-[15px] leading-[1.55] text-ink-soft">
        A wage-and-hour record has to show who acknowledged what, and when. This
        is the complete list — nothing else about you is collected, and none of
        it is used for advertising.
      </p>
      <dl className="mt-5 divide-y divide-border overflow-hidden rounded-xl bg-paper-raised elev-1">
        {items.map((item) => (
          <div
            key={item.label}
            className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 px-5 py-3.5"
          >
            <dt className="font-mono text-[13px] tracking-[-0.2px] text-foreground">
              {item.label}
            </dt>
            <dd className="text-sm leading-[1.5] text-ink-soft">{item.value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function PageFooter() {
  return (
    <footer className="mt-14">
      <Separator />
      <p className="mt-6 text-sm leading-[1.55] text-ink-soft">
        TipGuard is the compliance record-keeping software your employer uses.
        Notices are generated from a published state rule library, are not
        reviewed or certified by an attorney, and TipGuard does not provide
        legal advice. Employers are instructed to have counsel review every
        notice before distribution.
      </p>
      <p className="mt-3 text-sm leading-[1.55] text-ink-soft">
        Signing creates no account and no ongoing relationship between you and
        TipGuard.{" "}
        <Link
          href="/"
          className="font-medium text-brass-deep underline underline-offset-4 transition-opacity duration-150 hover:opacity-80 dark:text-brass"
        >
          Learn what TipGuard does
        </Link>
        .
      </p>
    </footer>
  );
}

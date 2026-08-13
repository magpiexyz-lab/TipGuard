"use client";

import { useId, useRef, useState } from "react";
import Link from "next/link";
import { Check, Loader2, PenLine, Printer, ShieldCheck } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { trackNoticeSigned } from "@/lib/events";
import { cn } from "@/lib/utils";
import { formatUtcStamp } from "./format";

type SubmitPhase = "idle" | "submitting" | "signed";

const MIN_NAME_LENGTH = 2;
const MAX_NAME_LENGTH = 120;

/**
 * The acknowledgment form (behavior b-07).
 *
 * WHAT THIS COMPONENT SENDS: `{ token, signer_name }` — and nothing else.
 *
 * The three other things the signature record must contain are deliberately
 * NOT sent from here, because a browser is not a trustworthy source for any of
 * them. `POST /api/notices/sign` derives them server-side:
 *   - UTC timestamp    → server clock, not the device clock
 *   - IP address       → request headers
 *   - user agent       → request headers
 *   - frozen notice text → copied out of the `notices` row the token resolves
 *                          to, so a tampered client cannot alter what is
 *                          recorded as legally acknowledged
 *
 * The route also re-validates the token (existence, `expires_at`, `used_at`)
 * before inserting. A token can expire or be consumed between the moment this
 * page rendered and the moment Submit is pressed; the render-time check in
 * `notice-lookup.ts` is a UX affordance, not the security boundary.
 *
 * DEPENDENCY: `/api/notices/sign` is owned by scaffold-wire (STATE 14) and does
 * not exist yet. Until it lands, submitting surfaces the inline error state.
 */
export function SignForm({
  token,
  noticeId,
  employeeName,
  employerName,
  sentAt,
}: {
  token: string;
  noticeId: string;
  employeeName: string;
  employerName: string;
  /** When the link was minted — drives the `hours_to_sign` analytics property. */
  sentAt: string;
}) {
  const nameFieldId = useId();
  const hintId = useId();
  const [signerName, setSignerName] = useState("");
  const [phase, setPhase] = useState<SubmitPhase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [signedAt, setSignedAt] = useState<string | null>(null);
  // `notice_signed` must fire exactly once per signature (b-07 test 4).
  const trackedRef = useRef(false);

  const trimmed = signerName.trim();
  const canSubmit = trimmed.length >= MIN_NAME_LENGTH && phase === "idle";

  async function handleSubmit(event: React.SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    if (phase !== "idle") return;
    if (trimmed.length < MIN_NAME_LENGTH) {
      setError("Enter your full legal name as it appears on your paycheck.");
      return;
    }

    setError(null);
    setPhase("submitting");

    try {
      const response = await fetch("/api/notices/sign", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, signer_name: trimmed }),
      });
      const result = (await response.json().catch(() => null)) as
        | { signed_at?: string; error?: string }
        | null;

      if (!response.ok) {
        setPhase("idle");
        setError(
          result?.error ??
            "We could not record your signature. Check your connection and try again."
        );
        return;
      }

      // The authoritative timestamp is the server's. Fall back to the local
      // clock only so the confirmation is never blank.
      const stamp = result?.signed_at ?? new Date().toISOString();
      setSignedAt(stamp);
      setPhase("signed");

      if (!trackedRef.current) {
        trackedRef.current = true;
        const sentMs = new Date(sentAt).getTime();
        const hoursToSign = Number.isNaN(sentMs)
          ? undefined
          : Math.max(0, Math.round((Date.now() - sentMs) / 36e5));
        trackNoticeSigned({ notice_id: noticeId, hours_to_sign: hoursToSign });
      }
    } catch {
      setPhase("idle");
      setError(
        "We could not reach the signing service. Check your connection and try again."
      );
    }
  }

  if (phase === "signed") {
    return (
      <SignedConfirmation
        signerName={trimmed}
        signedAt={signedAt}
        employerName={employerName}
      />
    );
  }

  return (
    <form onSubmit={handleSubmit} noValidate className="mt-6">
      <div className="overflow-hidden rounded-xl bg-paper-raised elev-2">
        <div className="border-b border-border px-5 py-5 sm:px-7">
          <p className="eyebrow">Step 2 of 2</p>
          <h3 className="mt-2 font-display text-[22px] leading-[1.15] tracking-[-1.2px] text-foreground sm:text-[26px]">
            Confirm you received this notice
          </h3>
          <p className="mt-2 text-[15px] leading-[1.55] text-ink-soft">
            Typing your name below is your signature. It confirms you read the
            notice above — it is not a contract, it does not change your pay,
            and it does not give up any right you have.
          </p>
        </div>

        <div className="px-5 py-6 sm:px-7">
          <div className="flex flex-col gap-2">
            <Label htmlFor={nameFieldId} className="text-[15px] text-foreground">
              Your full legal name
            </Label>
            {/* The placeholder is instructional, never a name. A greyed real
                name in a signature field reads as already filled in, and this
                is the one control on the page carrying legal weight. The
                employee's name is already shown in the lead paragraph above. */}
            <Input
              id={nameFieldId}
              name="signer_name"
              value={signerName}
              onChange={(event) => {
                setSignerName(event.target.value);
                if (error) setError(null);
              }}
              disabled={phase === "submitting"}
              autoComplete="name"
              enterKeyHint="done"
              maxLength={MAX_NAME_LENGTH}
              aria-describedby={hintId}
              aria-invalid={error ? true : undefined}
              placeholder="Type your full legal name"
              className="h-12 rounded-lg px-3.5 text-base md:text-base placeholder:text-ink-soft/60"
            />
            <p id={hintId} className="text-sm leading-[1.5] text-ink-soft">
              Use the name your employer has on file for you
              {employeeName ? `: ${employeeName}` : ""}.
            </p>
          </div>

          {/* Live signature line — the acknowledgment made visible before it
              is committed, mirroring the product's signature motif. */}
          <div className="mt-6 rounded-lg bg-paper px-4 pt-5 pb-3 ring-1 ring-foreground/10">
            <div
              aria-hidden="true"
              className={cn(
                "min-h-[2.75rem] font-display text-[26px] leading-[1.1] tracking-[-0.5px] transition-all duration-200 ease-out sm:text-[30px]",
                trimmed ? "text-foreground opacity-100" : "text-ink-soft opacity-40"
              )}
            >
              {trimmed || "Your name"}
            </div>
            <div className="mt-1 border-t border-foreground/25" />
            <p className="mt-2 font-mono text-[11px] tracking-[0.14em] text-ink-soft uppercase">
              Signature of employee
            </p>
          </div>

          {/* Always-mounted live region: a conditionally-mounted role="alert" is
              absent from the a11y tree at load and drops announcements. */}
          <Alert
            variant="destructive"
            aria-live="assertive"
            aria-atomic="true"
            className={cn(
              "mt-5 rounded-lg border-transparent bg-ember/10 ring-1 ring-destructive/25",
              error ? "" : "sr-only"
            )}
          >
            <AlertTitle className="text-[14px]">
              {error ? "Signature not recorded" : ""}
            </AlertTitle>
            <AlertDescription className="text-sm leading-[1.6] text-destructive">
              {error ?? ""}
            </AlertDescription>
          </Alert>

          <div className="mt-6 flex flex-col gap-3 sm:flex-row sm:items-center">
            {phase === "submitting" ? (
              <Button
                type="submit"
                disabled
                aria-label="Recording your signature"
                className="h-12 w-full rounded-full px-7 text-base sm:w-auto"
              >
                <Loader2 className="size-4 animate-spin" aria-hidden="true" />
                Recording…
              </Button>
            ) : (
              // The default 50%-opacity disabled treatment ghosts the brass out
              // to near-invisibility, which reads as "broken" rather than "not
              // yet". A solid inert fill keeps the control legible while it
              // waits for a name.
              <Button
                type="submit"
                disabled={!canSubmit}
                className="h-12 w-full rounded-full px-7 text-base transition-all duration-150 hover:opacity-90 disabled:bg-muted disabled:text-ink-soft disabled:opacity-100 disabled:ring-1 disabled:ring-foreground/10 sm:w-auto"
              >
                <PenLine className="size-4" aria-hidden="true" />
                Sign and acknowledge
              </Button>
            )}
            <span className="font-mono text-sm tabular-nums text-ink-soft">
              Takes one tap · nothing else is required of you
            </span>
          </div>
        </div>
      </div>
    </form>
  );
}

function SignedConfirmation({
  signerName,
  signedAt,
  employerName,
}: {
  signerName: string;
  signedAt: string | null;
  employerName: string;
}) {
  return (
    <section
      aria-labelledby="signature-recorded"
      className="mt-6 animate-in fade-in slide-in-from-bottom-2 duration-300 ease-out"
    >
      <div className="overflow-hidden rounded-xl bg-paper-raised elev-2">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-5 sm:px-7">
          <div className="min-w-0">
            <p className="eyebrow">Acknowledgment complete</p>
            <h3
              id="signature-recorded"
              className="mt-2 font-display text-[24px] leading-[1.15] tracking-[-1.2px] text-foreground sm:text-[28px]"
            >
              Your signature is on file
            </h3>
          </div>
          <Badge
            variant="outline"
            className="h-7 shrink-0 animate-in zoom-in-95 rounded-md border-transparent bg-seal/15 px-3 font-mono text-[11px] tracking-[0.1em] text-seal uppercase duration-300 ease-out dark:text-seal-soft"
          >
            <Check className="size-3" aria-hidden="true" />
            Signed
          </Badge>
        </div>

        <div className="px-5 py-6 sm:px-7">
          <div className="rounded-lg bg-paper px-4 pt-5 pb-3 ring-1 ring-foreground/10">
            <p className="font-display text-[26px] leading-[1.1] tracking-[-0.5px] text-foreground sm:text-[30px]">
              {signerName}
            </p>
            <div className="mt-1 border-t border-foreground/25" />
            <p className="mt-2 font-mono text-[11px] tracking-[0.14em] text-ink-soft uppercase">
              Signature of employee
            </p>
          </div>

          <dl className="mt-5 grid grid-cols-1 gap-px overflow-hidden rounded-lg bg-border sm:grid-cols-2">
            <div className="bg-paper-raised px-4 py-3.5">
              <dt className="eyebrow">Recorded at</dt>
              <dd className="mt-1.5 font-mono text-[15px] tabular-nums tracking-[-0.2px] text-foreground">
                {formatUtcStamp(signedAt)}
              </dd>
            </div>
            <div className="bg-paper-raised px-4 py-3.5">
              <dt className="eyebrow">Held by</dt>
              <dd className="mt-1.5 text-[15px] leading-[1.4] text-foreground">
                {employerName}
              </dd>
            </div>
          </dl>

          <Alert className="mt-5 rounded-lg border-transparent bg-seal/10 ring-1 ring-seal/25">
            <ShieldCheck className="text-seal dark:text-seal-soft" aria-hidden="true" />
            <AlertTitle className="text-[14px] text-foreground">
              This record cannot be edited
            </AlertTitle>
            <AlertDescription className="text-sm leading-[1.6] text-ink-soft">
              An exact copy of the notice text you just read was stored with
              your signature. Later edits to the notice cannot change what your
              signature refers to, and no one — including your employer — has a
              way to rewrite this record.
            </AlertDescription>
          </Alert>

          <div className="mt-6 flex flex-col gap-3 sm:flex-row sm:items-center">
            <Button
              type="button"
              onClick={() => window.print()}
              className="h-12 w-full rounded-full px-7 text-base transition-all duration-150 hover:opacity-90 sm:w-auto"
            >
              <Printer className="size-4" aria-hidden="true" />
              Save a copy for your records
            </Button>
            <Link
              href="/"
              className={cn(
                buttonVariants({ variant: "ghost" }),
                "h-11 w-full rounded-lg px-4 text-base sm:w-auto"
              )}
            >
              What is TipGuard?
            </Link>
          </div>
          <p className="mt-3 text-sm leading-[1.5] text-ink-soft">
            You can close this page now. There is no account to create and
            nothing further for you to do.
          </p>
        </div>
      </div>
    </section>
  );
}

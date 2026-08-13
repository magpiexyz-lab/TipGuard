import { ScrollText } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { formatUsd } from "./format";

/**
 * The notice itself, rendered as a document rather than as UI chrome.
 *
 * `noticeText` is printed VERBATIM with `whitespace-pre-wrap` — it is the
 * string that was emailed and, once signed, the string frozen into the
 * signature row. It is never re-generated, re-wrapped, or summarised here:
 * behavior b-07 requires that what the employee reads is byte-identical to
 * what they legally acknowledged.
 */
export function NoticeDocument({
  recordId,
  state,
  ruleVersion,
  cashWagePaid,
  tipCreditClaimed,
  noticeText,
  headingId,
  variant = "live",
}: {
  recordId: string;
  state: string;
  ruleVersion: string;
  cashWagePaid: number | null;
  tipCreditClaimed: boolean;
  noticeText: string;
  headingId: string;
  /** `frozen` = the immutable snapshot stored at signature time. */
  variant?: "live" | "frozen";
}) {
  const isFrozen = variant === "frozen";

  // The frozen snapshot carries only the notice text — the wage figures are not
  // re-read from the live `notices` row, because that row can legally diverge
  // from what was signed. Asserting "Cash wage —" / "Tip credit not claimed"
  // beside a frozen body that says otherwise would contradict the very document
  // this page exists to make trustworthy, so those cells are omitted entirely.
  const facts: { label: string; value: string }[] = isFrozen
    ? [
        { label: "State", value: state || "—" },
        { label: "Rule version", value: ruleVersion || "—" },
      ]
    : [
        { label: "State", value: state || "—" },
        { label: "Rule version", value: ruleVersion || "—" },
        {
          label: "Cash wage",
          value: cashWagePaid === null ? "—" : `${formatUsd(cashWagePaid)}/hr`,
        },
        {
          label: "Tip credit",
          value: tipCreditClaimed ? "Claimed" : "Not claimed",
        },
      ];

  return (
    <article
      aria-labelledby={headingId}
      className="mt-6 rounded-xl bg-paper-raised elev-2"
    >
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-t-xl border-b border-border px-5 py-4 sm:px-7">
        <div className="min-w-0">
          <p className="eyebrow">
            {isFrozen ? "Acknowledged text — frozen copy" : "Tip credit notice"}
          </p>
          <p className="mt-1.5 font-mono text-[13px] tracking-[-0.2px] text-ink-soft">
            {recordId}
          </p>
        </div>
        <Badge
          variant="outline"
          className={cn(
            "h-6 rounded-md border-transparent px-2.5 font-mono text-[11px] tracking-[0.1em] uppercase",
            isFrozen
              ? "bg-seal/15 text-seal dark:text-seal-soft"
              : "bg-brass/15 text-brass-deep dark:text-brass"
          )}
        >
          {isFrozen ? "Frozen" : tipCreditClaimed ? "Tip credit claimed" : "No tip credit"}
        </Badge>
      </div>

      {/* Evidence strip — 1px ledger hairlines via the gap-px grid, per brief.
          Pinned while the notice body scrolls past: the state and rule version
          the text is being read under stay on screen for the whole document. */}
      <div className="sticky top-0 z-10 border-b border-border bg-paper-raised">
        <dl
          className={cn(
            "grid gap-px bg-border",
            isFrozen ? "grid-cols-2" : "grid-cols-2 sm:grid-cols-4"
          )}
        >
          {facts.map((fact) => (
            <div key={fact.label} className="bg-paper-raised px-5 py-4 sm:px-4">
              <dt className="eyebrow">{fact.label}</dt>
              <dd className="mt-1.5 font-mono text-[15px] tabular-nums tracking-[-0.2px] text-foreground">
                {fact.value}
              </dd>
            </div>
          ))}
        </dl>
      </div>

      <div className="texture-rule px-5 py-6 sm:px-7 sm:py-8">
        {/* 14px on phones: this is the text being legally acknowledged, and it
            is read on a handset. Reverts to 13px where the measure is wide
            enough to hold the notice's own line breaks. */}
        <div className="max-h-none whitespace-pre-wrap break-words font-mono text-sm leading-[1.75] tracking-[-0.2px] text-foreground sm:text-[13px]">
          {noticeText || "This notice has no recorded text."}
        </div>
      </div>

      <div className="px-5 pb-6 sm:px-7">
        <Alert className="rounded-lg border-transparent bg-brass/10 ring-1 ring-brass/20">
          <ScrollText className="text-brass-deep dark:text-brass" aria-hidden="true" />
          <AlertTitle className="text-[14px] text-foreground">
            Generated from a rule library — not attorney-certified
          </AlertTitle>
          <AlertDescription className="text-sm leading-[1.6] text-ink-soft">
            TipGuard produces this notice from its published state tip-credit
            rule library. It has not been reviewed or certified by an attorney,
            and TipGuard does not provide legal advice. Employers are directed
            to have counsel review every notice before distribution.
          </AlertDescription>
        </Alert>
      </div>
    </article>
  );
}

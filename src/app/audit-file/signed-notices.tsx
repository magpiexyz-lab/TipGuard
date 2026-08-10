"use client";

import Link from "next/link";
import { FileLock2, PenLine } from "lucide-react";
import { Button, buttonVariants } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";
import { formatUtc, type SignedNoticeEntry } from "./audit-file-contract";

/**
 * Section 2 of the export: every signed notice with its signer name, UTC
 * timestamp, and the frozen copy of the exact text acknowledged — b-12's
 * first test. The text is the snapshot taken at signature time, never a
 * re-render of the current template, which is what makes the file evidence
 * rather than a summary.
 */
export function SignedNotices({ entries }: { entries: SignedNoticeEntry[] }) {
  if (entries.length === 0) {
    return (
      <div className="rounded-xl bg-card px-6 py-10 text-center ring-1 ring-foreground/10">
        <h3 className="font-heading text-xl">No acknowledgments in the vault yet</h3>
        <p className="mx-auto mt-2 max-w-md text-sm leading-[1.55] text-ink-soft">
          A notice becomes evidence the moment an employee signs it. Send the
          notices you have generated and each signature lands here with its
          signer, timestamp, and frozen text.
        </p>
        <Link
          href="/notices"
          className={cn(
            buttonVariants({ variant: "outline" }),
            "mt-6 h-11 rounded-md px-6 text-base font-medium"
          )}
        >
          Send notices for signature
        </Link>
      </div>
    );
  }

  return (
    <ul className="grid gap-4 md:grid-cols-2">
      {entries.map((entry) => (
        <li
          key={entry.noticeId}
          className="flex flex-col rounded-xl bg-card p-5 ring-1 ring-foreground/10 transition-shadow duration-[140ms] hover:elev-2"
        >
          <div className="flex items-start justify-between gap-4">
            <div>
              <h3 className="font-heading text-lg leading-[1.15]">
                {entry.employeeName}
              </h3>
              <p className="mt-1 flex items-center gap-2 text-sm text-ink-soft">
                <PenLine
                  className="size-3.5 shrink-0 text-seal dark:text-seal-soft"
                  aria-hidden="true"
                />
                Signed by {entry.signerName}
              </p>
            </div>
            <p className="shrink-0 text-right font-mono text-[11px] tracking-[0.1em] text-brass-deep uppercase dark:text-brass">
              {entry.state} · {entry.ruleVersion}
            </p>
          </div>

          <Separator className="my-4" />

          <dl className="grid gap-2">
            <div className="flex items-baseline justify-between gap-4">
              <dt className="text-sm text-ink-soft">Acknowledged</dt>
              <dd className="font-mono text-sm tabular-nums">
                {formatUtc(entry.signedAt)}
              </dd>
            </div>
            <div className="flex items-baseline justify-between gap-4">
              <dt className="text-sm text-ink-soft">Record</dt>
              <dd className="font-mono text-sm tabular-nums text-ink-soft">
                {entry.noticeId.slice(0, 8).toUpperCase()}
              </dd>
            </div>
          </dl>

          <div className="mt-4">
            {entry.noticeText ? (
              <Dialog>
                <DialogTrigger
                  render={<Button variant="outline" className="h-11 w-full rounded-md text-sm" />}
                >
                  View the exact text acknowledged
                </DialogTrigger>
                <DialogContent className="max-h-[80vh] overflow-y-auto sm:max-w-2xl">
                  <DialogHeader>
                    <DialogTitle>
                      Frozen notice text — {entry.employeeName}
                    </DialogTitle>
                    <DialogDescription>
                      Captured at signature on {formatUtc(entry.signedAt)} under{" "}
                      {entry.state} rule version {entry.ruleVersion}. This copy is
                      immutable; no path in TipGuard edits notice text after
                      acknowledgment.
                    </DialogDescription>
                  </DialogHeader>
                  <pre className="max-h-[50vh] overflow-auto rounded-lg bg-muted p-4 font-mono text-[13px] leading-[1.6] whitespace-pre-wrap">
                    {entry.noticeText}
                  </pre>
                </DialogContent>
              </Dialog>
            ) : (
              <p className="flex items-center gap-2 rounded-md bg-brass/12 px-3 py-2.5 text-sm text-brass-deep dark:text-brass">
                <FileLock2 className="size-4 shrink-0" aria-hidden="true" />
                Frozen text is part of the Shield export
              </p>
            )}
          </div>
        </li>
      ))}
    </ul>
  );
}

export function SignedNoticesLockNote({ locked }: { locked: boolean }) {
  if (!locked) return null;
  return (
    <p className="mt-4 text-sm leading-[1.55] text-ink-soft">
      The index above is yours on the free tier — who signed, when, under which
      rule version. The frozen notice text and the assembled export unlock with
      TipGuard Shield.
    </p>
  );
}

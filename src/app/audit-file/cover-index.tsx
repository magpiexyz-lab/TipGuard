"use client";

import Link from "next/link";
import Image from "next/image";
import { ArrowRight } from "lucide-react";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { NoticeStatusBadge } from "./notice-status-badge";
import { formatUtc, type CoverIndexEntry } from "./audit-file-contract";

/**
 * Section 1 of the export: the cover index. Lists every employee, the status
 * of their notice, and the state rule version the notice was generated under
 * — b-12's second test, rendered on screen exactly as it lands in the file.
 */
export function CoverIndex({ entries }: { entries: CoverIndexEntry[] }) {
  if (entries.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center rounded-xl bg-card px-6 py-14 text-center ring-1 ring-foreground/10 elev-1">
        {/* The illustration ships with a baked #f3f0e6 (--paper) field. Seated
            on --paper-raised it reads as a pasted-on square, so it gets a
            paper plate of the exact same value — the frame is intentional and
            the seam disappears. */}
        <div className="rounded-2xl bg-paper p-6 ring-1 ring-foreground/[0.07] elev-1">
          <Image
            src="/images/empty-state.webp"
            alt="An open, empty file drawer holding a single hanging folder"
            width={400}
            height={400}
            className="h-40 w-auto"
          />
        </div>
        <h3 className="mt-7 font-heading text-xl tracking-[-0.015em] text-balance">
          The file has no cover index yet
        </h3>
        <p className="mt-2 max-w-md text-sm leading-[1.55] text-ink-soft">
          The index is built from your tipped staff. Import your roster and
          TipGuard generates a state-specific notice for each person on it.
        </p>
        <Link
          href="/staff"
          className={cn(
            buttonVariants(),
            "mt-6 h-11 rounded-full px-6 text-base font-medium"
          )}
        >
          Import your roster to start the file
          <ArrowRight className="size-4" aria-hidden="true" />
        </Link>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-xl bg-card ring-1 ring-foreground/10">
      <table className="w-full min-w-[42rem] border-collapse text-left">
        <caption className="sr-only">
          Cover index: every employee with their notice status and the state
          rule version applied
        </caption>
        <thead>
          <tr className="border-b border-border">
            <th
              scope="col"
              className="px-4 py-3 font-mono text-[11px] font-medium tracking-[0.14em] text-ink-soft uppercase"
            >
              Employee
            </th>
            <th
              scope="col"
              className="px-4 py-3 font-mono text-[11px] font-medium tracking-[0.14em] text-ink-soft uppercase"
            >
              Role
            </th>
            <th
              scope="col"
              className="px-4 py-3 font-mono text-[11px] font-medium tracking-[0.14em] text-ink-soft uppercase"
            >
              State
            </th>
            <th
              scope="col"
              className="px-4 py-3 font-mono text-[11px] font-medium tracking-[0.14em] text-ink-soft uppercase"
            >
              Notice status
            </th>
            <th
              scope="col"
              className="px-4 py-3 font-mono text-[11px] font-medium tracking-[0.14em] text-ink-soft uppercase"
            >
              Rule version
            </th>
            <th
              scope="col"
              className="px-4 py-3 text-right font-mono text-[11px] font-medium tracking-[0.14em] text-ink-soft uppercase"
            >
              Acknowledged
            </th>
          </tr>
        </thead>
        <tbody>
          {entries.map((entry) => (
            <tr
              key={entry.employeeId}
              className="border-b border-border transition-colors duration-[140ms] last:border-b-0 hover:bg-muted/50 hover:shadow-[inset_2px_0_0_0_var(--brass)]"
            >
              <th
                scope="row"
                className="min-h-11 px-4 py-3 text-sm font-medium text-foreground"
              >
                {entry.employeeName}
              </th>
              <td className="px-4 py-3 text-sm text-ink-soft">{entry.role}</td>
              <td className="px-4 py-3 font-mono text-sm tabular-nums">
                {entry.state}
              </td>
              <td className="px-4 py-3">
                <NoticeStatusBadge status={entry.noticeStatus} />
              </td>
              <td className="px-4 py-3 font-mono text-sm tabular-nums text-ink-soft">
                {entry.ruleVersion ?? "—"}
              </td>
              <td className="px-4 py-3 text-right font-mono text-sm tabular-nums text-ink-soft">
                {formatUtc(entry.signedAt)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

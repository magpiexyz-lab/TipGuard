"use client";

import { useState } from "react";
import Link from "next/link";
import { Check, CheckCircle2, Download, Loader2, Lock } from "lucide-react";
import { Button, buttonVariants } from "@/components/ui/button";
import { trackAuditFileExported } from "@/lib/events";
import { cn } from "@/lib/utils";
import type { AuditFileCounts, AuditFileExport } from "./audit-file-contract";

type BuildState = "idle" | "building" | "done";

/**
 * The one-click export (b-12).
 *
 * Paid accounts get the real build: `POST /api/audit-file` assembles the dated
 * file and the browser downloads it. `audit_file_exported` fires on a
 * successful build with the three required counts.
 *
 * Free accounts get an explicit locked prompt — never a disabled button with
 * no explanation, never a download that 402s in the user's face.
 */
export function ExportPanel({
  plan,
  counts,
  generatedAtLabel,
}: {
  plan: "free" | "shield";
  counts: AuditFileCounts;
  generatedAtLabel: string;
}) {
  const [state, setState] = useState<BuildState>("idle");
  const [error, setError] = useState<string | null>(null);

  async function buildExport() {
    setState("building");
    setError(null);

    try {
      const response = await fetch("/api/audit-file", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });

      if (response.status === 401) {
        setError("Your session expired. Sign in again to build the file.");
        setState("idle");
        return;
      }

      if (response.status === 402 || response.status === 403) {
        setError(
          "The assembled export is a TipGuard Shield feature. Your records are unchanged."
        );
        setState("idle");
        return;
      }

      const body = (await response.json()) as Partial<AuditFileExport>;

      if (!response.ok || typeof body.content !== "string") {
        setError(
          "The file could not be assembled. Nothing was changed — try again in a moment."
        );
        setState("idle");
        return;
      }

      const exportedCounts: AuditFileCounts = body.counts ?? counts;
      trackAuditFileExported({
        employee_count: exportedCounts.employee_count,
        signed_notice_count: exportedCounts.signed_notice_count,
        open_violation_count: exportedCounts.open_violation_count,
      });

      const blob = new Blob([body.content], {
        type: body.contentType ?? "text/markdown;charset=utf-8",
      });
      const objectUrl = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = body.filename ?? "tipguard-audit-file.md";
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(objectUrl);

      setState("done");
    } catch {
      setError(
        "Could not reach the audit file service. Check your connection and try again."
      );
      setState("idle");
    }
  }

  if (plan === "free") {
    // An account with nothing in it must not be told its file "is assembled" —
    // the two empty sections directly below would contradict the claim on
    // sight. Same lock, same upgrade prompt, honest framing.
    const isEmpty =
      counts.employee_count === 0 && counts.signed_notice_count === 0;

    return (
      <div className="relative overflow-hidden rounded-xl bg-card p-6 ring-2 ring-brass elev-2 sm:p-8">
        {/* The locked panel is the one section a free account must feel. A
            brass wash off the top edge separates it from the plain ruled
            cards below without a second border treatment. */}
        <div
          className="bloom-brass-soft pointer-events-none absolute inset-0"
          aria-hidden="true"
        />

        <div className="relative lg:grid lg:grid-cols-[minmax(0,1fr)_16rem] lg:gap-12">
          <div>
            <p className="eyebrow flex items-center gap-2">
              <Lock className="size-3.5" aria-hidden="true" />
              Locked preview
            </p>
            <h2 className="mt-3 max-w-2xl font-heading text-2xl leading-[1.15] tracking-[-0.02em] text-balance">
              {isEmpty
                ? "Your file starts the moment your first notice is signed."
                : "Your file is assembled. The export is the paid part."}
            </h2>
            <p className="mt-3 max-w-xl text-sm leading-[1.55] text-ink-soft">
              {isEmpty
                ? "Nothing has landed in it yet. Import your roster and send the notices — every signature files itself below, on any plan. TipGuard Shield is what turns that record into one dated export you can hand an auditor."
                : "Everything below is real and yours — the cover index, every acknowledgment, every rule version. TipGuard Shield builds it into one dated export you can hand over, and keeps rebuilding it as staff and state rules change."}
            </p>

            <div className="mt-6 flex flex-col gap-3 sm:flex-row sm:items-center">
              <Link
                href="/pricing"
                className={cn(
                  buttonVariants(),
                  "h-11 rounded-full px-6 text-base font-medium"
                )}
              >
                <Lock className="size-4" aria-hidden="true" />
                Unlock the export — $79/mo
              </Link>
              <span className="max-w-xs text-sm leading-[1.45] text-ink-soft sm:max-w-none sm:border-l sm:border-foreground/12 sm:pl-4">
                Month to month · nothing you have already done is taken away
              </span>
            </div>
          </div>

          {/* Ruled manifest — what the sealed export actually contains. Fills
              the dead right half of a full-width banner card with the one
              thing that earns the upgrade: the shape of the deliverable. */}
          <div className="mt-8 border-t border-foreground/10 pt-6 lg:mt-0 lg:border-t-0 lg:border-l lg:border-foreground/10 lg:pt-0 lg:pl-10">
            <p className="font-mono text-[11px] font-medium tracking-[0.14em] text-ink-soft uppercase">
              One file contains
            </p>
            <ul className="mt-4 grid gap-3">
              {[
                "Cover index of every employee",
                "Every signed acknowledgment",
                "Frozen notice text, UTC-dated",
              ].map((item) => (
                <li
                  key={item}
                  className="flex items-start gap-2.5 text-sm leading-[1.45] text-ink-soft"
                >
                  <Check
                    className="mt-0.5 size-4 shrink-0 text-brass-deep dark:text-brass"
                    aria-hidden="true"
                  />
                  {item}
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-xl bg-card p-6 ring-1 ring-foreground/10">
      <p className="eyebrow">Export</p>
      <h2 className="mt-3 font-heading text-2xl leading-[1.15] tracking-[-0.02em]">
        Build the dated audit file
      </h2>
      <p className="mt-3 max-w-xl text-sm leading-[1.55] text-ink-soft">
        One file: the cover index, then every signed acknowledgment with its
        signer name, UTC timestamp, and the exact text acknowledged. Stamped{" "}
        <span className="font-mono tabular-nums">{generatedAtLabel}</span>.
      </p>

      <div className="mt-6 flex flex-col gap-3 sm:flex-row sm:items-center">
        <Button
          onClick={buildExport}
          disabled={state === "building"}
          aria-label={state === "building" ? "Assembling your audit file" : undefined}
          className="h-11 rounded-full px-6 text-base font-medium"
        >
          {state === "building" ? (
            <>
              <Loader2 className="size-4 animate-spin" aria-hidden="true" />
              <span>Assembling the file</span>
            </>
          ) : (
            <>
              <Download className="size-4" aria-hidden="true" />
              <span>Build my audit file</span>
            </>
          )}
        </Button>

        {state === "done" ? (
          <span className="flex items-center gap-2 text-sm font-medium text-seal dark:text-seal-soft">
            <CheckCircle2 className="size-4" aria-hidden="true" />
            Downloaded. Rebuild any time — the file re-assembles from live records.
          </span>
        ) : null}
      </div>

      {/* Always-mounted live region: a conditionally mounted role=alert is not
          registered at load and the announcement drops. */}
      <p
        role="alert"
        aria-live="assertive"
        aria-atomic="true"
        className={error ? "mt-4 text-sm text-destructive" : "sr-only"}
      >
        {error ?? ""}
      </p>
    </div>
  );
}

"use client";

import { useState } from "react";
import Link from "next/link";
import { CheckCircle2, Download, Loader2, Lock } from "lucide-react";
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
    return (
      <div className="rounded-xl bg-card p-6 ring-2 ring-brass">
        <p className="eyebrow">Locked preview</p>
        <h2 className="mt-3 font-heading text-2xl leading-[1.15]">
          Your file is assembled. The export is the paid part.
        </h2>
        <p className="mt-3 max-w-xl text-sm leading-[1.55] text-ink-soft">
          Everything below is real and yours — the cover index, every
          acknowledgment, every rule version. TipGuard Shield builds it into one
          dated export you can hand over, and keeps rebuilding it as staff and
          state rules change.
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
          <span className="font-mono text-sm tabular-nums text-ink-soft">
            Month to month · nothing you have already done is taken away
          </span>
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-xl bg-card p-6 ring-1 ring-foreground/10">
      <p className="eyebrow">Export</p>
      <h2 className="mt-3 font-heading text-2xl leading-[1.15]">
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

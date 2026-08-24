"use client";

import { useState } from "react";
import { CheckCircle2, Download, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { trackAuditFileExported } from "@/lib/events";
import type { AuditFileCounts, AuditFileExport } from "./audit-file-contract";

type BuildState = "idle" | "building" | "done";

/**
 * The one-click export (b-12).
 *
 * `POST /api/audit-file` assembles the dated file and the browser downloads
 * it; `audit_file_exported` fires on a successful build with the three
 * required counts.
 *
 * There is no plan gate. Shield is a fake door for this experiment (b-10/b-11)
 * and the export was the only thing behind the paywall, so gating it would
 * only manufacture a dead end without producing a data point.
 */
export function ExportPanel({
  counts,
  generatedAtLabel,
}: {
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

      if (response.status === 409) {
        setError(
          "There is nothing to export yet. Import your roster and send a notice first."
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

  return (
    <div className="rounded-xl bg-card p-6 ring-1 ring-foreground/10">
      <p className="eyebrow">Export</p>
      <h2 className="mt-3 font-heading text-2xl leading-[1.15] tracking-[-0.02em] [word-spacing:0.048em]">
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

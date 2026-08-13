"use client";

import { useMemo, useState } from "react";
import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ArrowRight,
  CircleCheckBig,
  LoaderCircle,
  RefreshCw,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { trackViolationResolved } from "@/lib/events";
import { cn } from "@/lib/utils";

import {
  byExposureDesc,
  exposureLabel,
  formatUsd,
  RULE_CLASS_META,
  SEVERITY_META,
  totalExposure,
  type FindingView,
} from "./findings";

export function ViolationsClient({
  initialFindings,
  hasEverScanned,
}: {
  initialFindings: FindingView[];
  hasEverScanned: boolean;
}) {
  const router = useRouter();
  const [findings, setFindings] = useState<FindingView[]>(initialFindings);
  const [confirming, setConfirming] = useState<FindingView | null>(null);
  const [resolvingId, setResolvingId] = useState<string | null>(null);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const open = useMemo(
    () => findings.filter((item) => item.status === "open").sort(byExposureDesc),
    [findings]
  );
  const resolved = useMemo(
    () => findings.filter((item) => item.status === "resolved").sort(byExposureDesc),
    [findings]
  );
  const exposure = totalExposure(open);

  async function resolveFinding(finding: FindingView) {
    setResolvingId(finding.id);
    setError(null);
    setNotice(null);
    try {
      const response = await fetch("/api/violations/resolve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ violation_id: finding.id }),
      });
      if (!response.ok) {
        const body = (await response.json().catch(() => ({}))) as { error?: string };
        throw new Error(body.error ?? "The finding could not be resolved.");
      }
      // The server owns detected_at, so it is authoritative for days_open; fall
      // back to the value computed at render time when the route omits it.
      const result = (await response.json()) as { days_open?: number };
      const daysOpen =
        typeof result.days_open === "number" ? result.days_open : finding.daysOpen;

      trackViolationResolved({ rule_class: finding.ruleClass, days_open: daysOpen });

      // Status flips to resolved — the audit record is kept, never deleted.
      setFindings((previous) =>
        previous.map((item) =>
          item.id === finding.id ? { ...item, status: "resolved", daysOpen } : item
        )
      );
      setNotice(
        `Resolved: ${RULE_CLASS_META[finding.ruleClass].title}. The entry stays in your audit record.`
      );
      router.refresh();
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "The finding could not be resolved. Please try again."
      );
    } finally {
      setResolvingId(null);
      setConfirming(null);
    }
  }

  async function runScan() {
    setScanning(true);
    setError(null);
    setNotice(null);
    try {
      const response = await fetch("/api/violations/scan", { method: "POST" });
      if (!response.ok) {
        const body = (await response.json().catch(() => ({}))) as { error?: string };
        throw new Error(body.error ?? "The compliance scan could not be started.");
      }
      const result = (await response.json()) as { open_finding_count?: number };
      setNotice(
        typeof result.open_finding_count === "number"
          ? `Scan complete: ${result.open_finding_count} open finding${
              result.open_finding_count === 1 ? "" : "s"
            } across your roster and pay periods.`
          : "Scan complete. Your findings are up to date."
      );
      router.refresh();
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "The compliance scan could not be started. Please try again."
      );
    } finally {
      setScanning(false);
    }
  }

  return (
    <div className="min-h-screen">
      {/* ---------- Authority band: total exposure + scan control ---------- */}
      <div className="dark surface-ink texture-grain bloom-brass border-b border-border">
        <div className="mx-auto max-w-[1180px] px-5 py-10 md:px-8 md:py-14">
          <p className="eyebrow">Compliance findings &middot; Live scan</p>
          <div className="mt-4 flex flex-col gap-8 lg:flex-row lg:items-end lg:justify-between">
            <div className="max-w-2xl">
              <h1 className="font-display text-4xl leading-[1.04] tracking-[-2px] md:text-[56px]">
                {open.length > 0
                  ? "Findings open against your file"
                  : "Your file has no open findings"}
              </h1>
              <p className="mt-5 text-lg leading-[1.55] text-muted-foreground">
                Every finding below is a specific, dated gap between what your payroll
                and roster show and what the tip credit requires. Worked top to bottom,
                the largest liability closes first.
              </p>
            </div>

            <dl className="flex shrink-0 gap-10 border-t border-border pt-6 lg:border-t-0 lg:pt-0">
              <div>
                <dt className="eyebrow">Open exposure</dt>
                <dd className="figure mt-2 text-4xl leading-[1.1] md:text-5xl">
                  {formatUsd(exposure)}
                </dd>
              </div>
              <div>
                <dt className="eyebrow">Open findings</dt>
                <dd className="figure mt-2 text-4xl leading-[1.1] md:text-5xl">
                  {open.length}
                </dd>
              </div>
            </dl>
          </div>

          <div className="mt-9 flex flex-col gap-3 sm:flex-row sm:items-center">
            <Button
              className="h-11 rounded-full px-6 text-base"
              onClick={runScan}
              disabled={scanning}
              aria-label={scanning ? "Running compliance scan" : "Re-run compliance scan"}
            >
              {scanning ? (
                <LoaderCircle className="size-4 animate-spin" aria-hidden="true" />
              ) : (
                <RefreshCw className="size-4" aria-hidden="true" />
              )}
              {scanning ? "Scanning…" : "Re-run compliance scan"}
            </Button>
            <Link
              href="/dashboard"
              className={cn(
                buttonVariants({ variant: "outline" }),
                "h-11 rounded-md px-5 text-base"
              )}
            >
              Back to dashboard
            </Link>
          </div>
        </div>
      </div>

      <div className="mx-auto max-w-[1180px] px-5 py-8 md:px-8 md:py-10">
        {error ? (
          <Alert variant="destructive" className="mb-6">
            <TriangleAlert aria-hidden="true" />
            <AlertTitle>That did not go through</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : null}

        {notice ? (
          <Alert role="status" className="mb-6 bg-seal/10">
            <CircleCheckBig aria-hidden="true" className="text-seal dark:text-seal-soft" />
            <AlertTitle>Record updated</AlertTitle>
            <AlertDescription>{notice}</AlertDescription>
          </Alert>
        ) : null}

        <Tabs defaultValue="open">
          {/* The ledger runs past three screens. The filter and the ranking legend
              ride along with it so the owner never loses which list they are in —
              and the bar frosting on scroll is the page's one moving signal that
              the record continues below. */}
          <div className="sticky top-0 z-20 -mx-5 flex items-center justify-between gap-3 border-b border-border/70 bg-background/85 px-5 py-3 backdrop-blur-md md:-mx-8 md:px-8">
            <TabsList className="h-auto! max-w-full overflow-x-auto rounded-full bg-secondary p-1">
              <TabsTrigger
                value="open"
                className="h-11 rounded-full px-5 text-sm data-active:bg-primary data-active:text-primary-foreground data-active:shadow-none"
              >
                Open ({open.length})
              </TabsTrigger>
              <TabsTrigger
                value="resolved"
                className="h-11 rounded-full px-5 text-sm data-active:bg-primary data-active:text-primary-foreground data-active:shadow-none"
              >
                Resolved ({resolved.length})
              </TabsTrigger>
            </TabsList>
            <p className="eyebrow hidden sm:block">Ranked by estimated exposure</p>
          </div>

          <TabsContent value="open" className="mt-6">
            <h2 className="sr-only">Open findings, ranked by estimated exposure</h2>
            {open.length > 0 ? (
              <ol className="grid gap-4">
                {open.map((finding, index) => (
                  <li
                    key={finding.id}
                    // Ledger rows enter in sequence like a printer: 55ms apart,
                    // capped at 6 so a long list does not crawl in. Globally
                    // short-circuited under prefers-reduced-motion.
                    className="animate-in fade-in slide-in-from-bottom-2 fill-mode-both duration-300"
                    style={{ animationDelay: `${Math.min(index, 5) * 55}ms` }}
                  >
                    <FindingCard
                      finding={finding}
                      rank={index + 1}
                      busy={resolvingId === finding.id}
                      onResolve={() => setConfirming(finding)}
                    />
                  </li>
                ))}
              </ol>
            ) : hasEverScanned ? (
              <CleanLedger resolvedCount={resolved.length} />
            ) : (
              <NeverScanned onScan={runScan} scanning={scanning} />
            )}
          </TabsContent>

          <TabsContent value="resolved" className="mt-6">
            <h2 className="sr-only">Resolved findings kept in the audit record</h2>
            {resolved.length > 0 ? (
              <ol className="grid gap-4">
                {resolved.map((finding) => (
                  <li key={finding.id}>
                    <FindingCard finding={finding} busy={false} />
                  </li>
                ))}
              </ol>
            ) : (
              <div className="rounded-lg bg-card p-8 text-center elev-1">
                <h3 className="font-display text-2xl tracking-[-1.2px]">
                  Nothing resolved yet
                </h3>
                <p className="mx-auto mt-3 max-w-md text-sm leading-[1.55] text-muted-foreground">
                  Findings you close stay here permanently with the date they were
                  closed. The audit record is never deleted, only marked.
                </p>
              </div>
            )}
          </TabsContent>
        </Tabs>
      </div>

      {/* ---------- Resolve confirmation ---------- */}
      <Dialog
        open={confirming !== null}
        onOpenChange={(next) => {
          if (!next) setConfirming(null);
        }}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="font-display text-xl tracking-[-1.2px]">
              Mark this finding resolved?
            </DialogTitle>
            <DialogDescription>
              {confirming
                ? `Confirm you have completed the fix for "${
                    RULE_CLASS_META[confirming.ruleClass].title
                  }". It leaves your open list but stays in the audit record, dated today.`
                : ""}
            </DialogDescription>
          </DialogHeader>
          {/* Closing a finding is a money decision — show the number being retired
              so the confirmation is not an abstract yes/no. */}
          {confirming ? (
            <div className="flex items-center justify-between rounded-md bg-muted/60 px-4 py-3">
              <span className="eyebrow">Exposure closed</span>
              <span className="figure text-xl leading-none">
                {exposureLabel(confirming)}
              </span>
            </div>
          ) : null}
          <DialogFooter className="gap-2">
            <Button
              variant="outline"
              className="h-11 px-5"
              onClick={() => setConfirming(null)}
            >
              Not yet
            </Button>
            <Button
              className="h-11 rounded-full px-6"
              disabled={resolvingId !== null}
              aria-label={
                resolvingId !== null ? "Resolving finding" : "Confirm finding resolved"
              }
              onClick={() => {
                if (confirming) void resolveFinding(confirming);
              }}
            >
              {resolvingId !== null ? (
                <LoaderCircle className="size-4 animate-spin" aria-hidden="true" />
              ) : (
                <CircleCheckBig className="size-4" aria-hidden="true" />
              )}
              {resolvingId !== null ? "Recording…" : "Yes, it is fixed"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

// --- One finding -------------------------------------------------------------

function FindingCard({
  finding,
  rank,
  busy,
  onResolve,
}: {
  finding: FindingView;
  rank?: number;
  busy: boolean;
  onResolve?: () => void;
}) {
  const meta = RULE_CLASS_META[finding.ruleClass];
  const severity = SEVERITY_META[finding.severity];
  const isResolved = finding.status === "resolved";

  return (
    <article
      className={cn(
        "relative overflow-hidden rounded-lg bg-card transition-all duration-150 elev-1",
        !isResolved && "hover:-translate-y-0.5 hover:ring-1 hover:ring-primary/30",
        busy && "opacity-70"
      )}
    >
      {/* Ledger edge: brass while the finding is open, seal once it is closed. */}
      <span
        aria-hidden="true"
        className={cn(
          "absolute inset-y-0 left-0 w-[3px]",
          isResolved ? "bg-seal" : "bg-primary"
        )}
      />

      <div className="grid gap-6 p-5 pl-6 md:grid-cols-[1fr_auto] md:items-start md:gap-8">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Badge
              className={cn(
                "rounded-sm font-mono text-[11px] tracking-[0.1em] uppercase",
                isResolved ? "bg-seal/10 text-seal dark:text-seal-soft" : severity.chipClass
              )}
            >
              {isResolved ? "Resolved" : severity.label}
            </Badge>
            {/* Rank is the organizing idea of this page (b-09: ordered by dollar
                exposure), so it is set as a ledger numeral rather than as one more
                11px label indistinguishable from "Affected" and "Detected". */}
            {rank ? (
              <span className="inline-flex items-baseline gap-1.5">
                <span className="eyebrow">Priority</span>
                <span className="figure text-sm text-brass-deep dark:text-primary">
                  {String(rank).padStart(2, "0")}
                </span>
              </span>
            ) : (
              <span className="eyebrow">Closed after {finding.daysOpen} days</span>
            )}
          </div>

          <h3 className="mt-3 font-display text-[22px] leading-[1.15] tracking-[-1.2px] md:text-[26px]">
            {meta.title}
          </h3>
          <p className="mt-2 text-sm leading-[1.5] text-muted-foreground">
            {meta.summary}
          </p>

          <dl className="mt-4 flex flex-wrap gap-x-10 gap-y-3">
            <div>
              <dt className="eyebrow">Affected</dt>
              <dd className="mt-1 text-sm">
                {finding.employeeName ?? "Roster-wide"}
                <span className="block text-xs text-muted-foreground">
                  {finding.employeeRole ?? "All tipped staff"}
                </span>
              </dd>
            </div>
            <div>
              <dt className="eyebrow">Detected</dt>
              <dd className="figure mt-1 text-sm">{finding.detectedLabel}</dd>
            </div>
            <div>
              <dt className="eyebrow">{isResolved ? "Days to close" : "Days open"}</dt>
              <dd className="figure mt-1 text-sm">{finding.daysOpen}</dd>
            </div>
          </dl>
        </div>

        <div className="shrink-0 border-t border-border pt-4 md:min-w-[200px] md:border-t-0 md:pt-0 md:text-right">
          <p className="eyebrow">Estimated exposure</p>
          <p
            className={cn(
              "figure mt-2 leading-[1.1]",
              finding.estimatedExposureUsd > 0
                ? "text-3xl md:text-[38px]"
                : "text-[26px] md:text-[30px]",
              isResolved && "text-muted-foreground"
            )}
          >
            {exposureLabel(finding)}
          </p>
          {finding.estimatedExposureUsd > 0 || isResolved ? null : (
            // "Unquantified" in muted grey read as "harmless" — the exact opposite
            // of what it means. A finding with no computable delta voids the credit
            // outright, so it carries the severity marker the dollar figure would
            // otherwise supply.
            <>
              <span className="mt-3 inline-flex items-center gap-1.5 rounded-sm bg-destructive/10 px-2 py-1 font-mono text-[11px] tracking-[0.1em] text-destructive uppercase">
                <TriangleAlert className="size-3" aria-hidden="true" />
                Credit voided
              </span>
              <p className="mt-2 max-w-[264px] text-[13px] leading-[1.5] text-muted-foreground md:ml-auto">
                No dollar figure is computable here. This finding voids the credit
                itself, which puts every tipped hour back on the table.
              </p>
            </>
          )}
        </div>
      </div>

      <Separator />

      <div className="grid gap-6 p-5 pl-6 md:grid-cols-2 md:gap-8">
        <div>
          <h4 className="eyebrow">What happened</h4>
          <p className="mt-3 rounded-md bg-muted/60 p-3 font-mono text-[13px] leading-[1.5] tabular-nums">
            {finding.detail}
          </p>
          <p className="mt-3 text-sm leading-[1.55] text-muted-foreground">
            {meta.explanation}
          </p>
        </div>

        <div>
          {/* A closed finding must not present its fix as still-pending work. */}
          <h4 className="eyebrow">{isResolved ? "The fix that closed it" : "How to fix it"}</h4>
          <p
            className={cn(
              "mt-3 text-sm leading-[1.55]",
              isResolved && "text-muted-foreground"
            )}
          >
            {meta.fixAction}
          </p>

          {isResolved ? (
            <p className="mt-5 flex items-center gap-2 text-sm text-seal dark:text-seal-soft">
              <CircleCheckBig className="size-4" aria-hidden="true" />
              Fix recorded. This entry stays in your audit file.
            </p>
          ) : (
            <div className="mt-5 flex flex-col gap-2 sm:flex-row sm:items-center">
              <Link
                href={meta.fixHref}
                className={cn(buttonVariants(), "h-11 rounded-full px-5 text-base")}
              >
                {meta.fixLabel}
                <ArrowRight className="size-4" aria-hidden="true" />
              </Link>
              <Button
                variant="outline"
                className="h-11 px-5 text-base"
                onClick={onResolve}
                disabled={busy}
                aria-label={busy ? `Resolving ${meta.title}` : `Mark resolved: ${meta.title}`}
              >
                {busy ? (
                  <LoaderCircle className="size-4 animate-spin" aria-hidden="true" />
                ) : (
                  <CircleCheckBig className="size-4" aria-hidden="true" />
                )}
                {busy ? "Recording…" : "Mark resolved"}
              </Button>
            </div>
          )}
        </div>
      </div>
    </article>
  );
}

// --- Empty states ------------------------------------------------------------

/** Findings existed and every one has been closed — a reward state, not a void. */
function CleanLedger({ resolvedCount }: { resolvedCount: number }) {
  return (
    <div className="rounded-lg bg-card p-8 text-center elev-1 md:p-12">
      <span className="mx-auto flex size-14 items-center justify-center rounded-full bg-seal/10">
        <ShieldCheck className="size-7 text-seal dark:text-seal-soft" aria-hidden="true" />
      </span>
      <h3 className="mt-6 font-display text-3xl tracking-[-1.6px]">Clean ledger</h3>
      <p className="mx-auto mt-3 max-w-lg text-base leading-[1.55] text-muted-foreground">
        {resolvedCount > 0
          ? `All ${resolvedCount} finding${
              resolvedCount === 1 ? "" : "s"
            } raised against this file have been closed. Keep the roster current and TipGuard flags the next gap the moment it appears.`
          : "The last scan found nothing to flag across overtime basis, tip-pool composition, minimum-wage shortfalls, and notice coverage."}
      </p>
      <div className="mt-7 flex flex-col justify-center gap-3 sm:flex-row">
        <Link
          href="/audit-file"
          className={cn(buttonVariants(), "h-11 rounded-full px-6 text-base")}
        >
          Build my audit file
          <ArrowRight className="size-4" aria-hidden="true" />
        </Link>
        <Link
          href="/staff"
          className={cn(buttonVariants({ variant: "outline" }), "h-11 px-5 text-base")}
        >
          Add a new hire
        </Link>
      </div>
    </div>
  );
}

/** No scan has ever produced a record — the drawer is genuinely empty. */
function NeverScanned({
  onScan,
  scanning,
}: {
  onScan: () => void;
  scanning: boolean;
}) {
  return (
    <div className="rounded-lg bg-card p-8 text-center elev-1 md:p-12">
      <Image
        src="/images/empty-state.webp"
        alt="An open file drawer holding a single empty folder"
        width={400}
        height={400}
        className="mx-auto h-auto w-40 md:w-52"
      />
      <h3 className="mt-6 font-display text-3xl tracking-[-1.6px]">
        No compliance scan on file
      </h3>
      <p className="mx-auto mt-3 max-w-lg text-base leading-[1.55] text-muted-foreground">
        TipGuard checks four things against your roster and pay periods: the overtime
        basis, who is in the tip pool, minimum-wage shortfalls after tips, and whether
        every employee has a current signed notice. Run the first scan to see where you
        stand.
      </p>
      <div className="mt-7 flex flex-col justify-center gap-3 sm:flex-row">
        <Button
          className="h-11 rounded-full px-6 text-base"
          onClick={onScan}
          disabled={scanning}
          aria-label={scanning ? "Running first compliance scan" : "Run first compliance scan"}
        >
          {scanning ? (
            <LoaderCircle className="size-4 animate-spin" aria-hidden="true" />
          ) : (
            <RefreshCw className="size-4" aria-hidden="true" />
          )}
          {scanning ? "Scanning…" : "Run my first scan"}
        </Button>
        <Link
          href="/staff"
          className={cn(buttonVariants({ variant: "outline" }), "h-11 px-5 text-base")}
        >
          Import my roster first
        </Link>
      </div>
    </div>
  );
}

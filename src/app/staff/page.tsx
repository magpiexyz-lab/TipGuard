"use client";

/**
 * /staff — golden path step 5, behavior b-04.
 *
 * API contract this page codes against (routes owned by scaffold-wire, STATE 14 —
 * they do not exist yet; the page renders its documented loading / error / empty
 * states until they do, and never fabricates roster rows):
 *
 *   GET  /api/staff         -> 200 { employees: EmployeeRow[] }        (RLS: owner's account only)
 *   POST /api/staff/import  -> body { rows: RosterRowValid[] }
 *                              200 { employees: EmployeeRow[], imported: number, failed: number }
 *
 * Parsing/validation is done client-side by src/lib/roster-csv.ts (unit-tested):
 * malformed rows are reported inline and the valid rows still import.
 */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ArrowRight, CircleCheck, ShieldCheck } from "lucide-react";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { EmployeeRow } from "@/lib/types";
import { PayrollConnectFakeDoor } from "./payroll-connect-fake-door";
import { RosterImportCard } from "./roster-import-card";
import { RosterTable } from "./roster-table";

const ROSTER_FEEDS = [
  {
    title: "State-specific notices",
    body: "Each employee's state and cash wage resolve the rule set that renders their tip-credit notice.",
  },
  {
    title: "Continuous violation scan",
    body: "Hire dates and hourly rates feed overtime-basis and sub-minimum shortfall detection.",
  },
  {
    title: "The audit file",
    body: "The roster becomes the cover index an investigator reads first: who, since when, at what wage.",
  },
];

export default function StaffPage() {
  const [employees, setEmployees] = useState<EmployeeRow[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const loadRoster = useCallback(async () => {
    setEmployees(null);
    setLoadError(null);
    try {
      const res = await fetch("/api/staff", { cache: "no-store" });
      if (!res.ok) {
        throw new Error(`Roster request failed with status ${res.status}`);
      }
      const data = (await res.json()) as { employees?: EmployeeRow[] };
      setEmployees(Array.isArray(data.employees) ? data.employees : []);
    } catch {
      setLoadError(
        "We could not read your roster just now. Your imported staff are safe — this is a read error, not a data loss."
      );
    }
  }, []);

  useEffect(() => {
    void loadRoster();
  }, [loadRoster]);

  const handleImported = useCallback((imported: EmployeeRow[]) => {
    setLoadError(null);
    setEmployees((previous) => {
      const seen = new Set(imported.map((row) => row.id));
      const kept = (previous ?? []).filter((row) => !seen.has(row.id));
      return [...kept, ...imported];
    });
  }, []);

  const onFileCount = employees?.length ?? 0;
  const hasRoster = onFileCount > 0;

  return (
    <div className="min-h-screen">
      {/* Dossier header — full-bleed ink band (surface temperature flip vs. the
          paper body below), ruled + brass bloom per the visual brief. */}
      <div className="surface-ink texture-rule">
        <div className="bloom-brass">
          <div className="mx-auto flex max-w-[1180px] flex-col gap-6 px-5 py-10 sm:px-8 lg:flex-row lg:items-end lg:justify-between">
            <div className="max-w-2xl">
              <p className="eyebrow">Step 05 / 06 &middot; Roster</p>
              <h1 className="mt-3 font-display text-[34px] leading-[1.06] tracking-[-1.6px] text-[#ECE8DA] sm:text-[44px]">
                Import your tipped staff
              </h1>
              <p className="mt-4 max-w-xl text-base leading-[1.55] text-[#A8AF9B]">
                Every notice, every violation check, and the audit file are built
                from this roster. Import it once &mdash; malformed rows are
                reported back to you, they never block the rest of the file.
              </p>
            </div>

            <div className="flex flex-col items-start gap-4 lg:items-end">
              <dl className="flex items-center gap-6">
                <div>
                  <dt className="eyebrow text-[#A8AF9B]">On file</dt>
                  <dd className="figure mt-1 text-3xl text-[#ECE8DA]">
                    {onFileCount.toString().padStart(2, "0")}
                  </dd>
                </div>
                <div className="border-l border-[rgba(243,240,230,0.18)] pl-6">
                  <dt className="eyebrow text-[#A8AF9B]">Next step</dt>
                  <dd className="mt-1 text-sm text-[#ECE8DA]">Send notices</dd>
                </div>
              </dl>

              {/* Forward CTA — /staff is golden-path step 5 of 6; next step is /notices. */}
              <Link
                href="/notices"
                className={cn(
                  buttonVariants(),
                  "h-11 gap-2 rounded-full px-6 text-base transition-[filter,transform] duration-[140ms] hover:brightness-95"
                )}
              >
                Continue to notices
                <ArrowRight aria-hidden="true" className="size-4" />
              </Link>
            </div>
          </div>
        </div>
      </div>

      <div className="mx-auto grid max-w-[1180px] gap-8 px-5 py-8 sm:px-8 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="flex flex-col gap-8">
          <section aria-labelledby="import-heading">
            <h2
              id="import-heading"
              className="font-display text-2xl tracking-[-1.2px]"
            >
              Import the roster
            </h2>
            <p className="mt-2 max-w-2xl text-sm text-muted-foreground">
              A CSV with six columns: name, email, role, hire date, hourly cash
              wage, and the state the employee works in.
            </p>
            <div className="mt-4">
              <RosterImportCard onImported={handleImported} />
            </div>
          </section>

          <section aria-labelledby="roster-heading">
            <div className="flex flex-wrap items-baseline justify-between gap-3">
              <h2
                id="roster-heading"
                className="font-display text-2xl tracking-[-1.2px]"
              >
                Staff on file
              </h2>
              {hasRoster ? (
                <p className="figure text-xs uppercase tracking-[0.14em] text-muted-foreground">
                  {onFileCount} record{onFileCount === 1 ? "" : "s"}
                </p>
              ) : null}
            </div>
            <div className="mt-4">
              <RosterTable
                employees={employees}
                error={loadError}
                onRetry={() => void loadRoster()}
              />
            </div>
          </section>
        </div>

        {/* Layout column — <div>, never <aside> (landmark-complementary-is-top-level). */}
        <div className="flex flex-col gap-4 lg:sticky lg:top-8 lg:self-start">
          <Card className="elev-1 rounded-[10px] bg-card">
            <CardHeader>
              <h2 className="font-display text-lg tracking-[-1.2px]">
                What the roster feeds
              </h2>
            </CardHeader>
            <CardContent>
              <ul className="flex flex-col gap-4">
                {ROSTER_FEEDS.map((feed) => (
                  <li key={feed.title} className="flex gap-3">
                    <CircleCheck
                      aria-hidden="true"
                      className="mt-0.5 size-4 shrink-0 text-seal"
                    />
                    <div>
                      <p className="text-sm font-medium">{feed.title}</p>
                      <p className="mt-1 text-sm text-muted-foreground">
                        {feed.body}
                      </p>
                    </div>
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>

          <Card className="elev-1 rounded-[10px] bg-card">
            <CardHeader>
              <p className="eyebrow">Roadmap</p>
              <h2 className="mt-2 font-display text-lg tracking-[-1.2px]">
                Skip the CSV
              </h2>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              <p className="text-sm text-muted-foreground">
                Direct payroll sync keeps the roster current as you hire and as
                wages change. Tell us which platform you run and we will build
                that connector first.
              </p>
              <PayrollConnectFakeDoor />
            </CardContent>
          </Card>

          <div className="flex gap-3 rounded-[10px] bg-accent px-4 py-3">
            <ShieldCheck
              aria-hidden="true"
              className="mt-0.5 size-4 shrink-0 text-brass-deep dark:text-brass"
            />
            <p className="text-sm text-muted-foreground">
              Roster rows are scoped to your restaurant by row-level security.
              Staff never see each other&rsquo;s records &mdash; only their own
              notice.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

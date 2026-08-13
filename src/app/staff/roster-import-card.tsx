"use client";

/**
 * Roster CSV import (b-04).
 *
 * Parsing is delegated to the unit-tested pure function in src/lib/roster-csv.ts.
 * Contract honoured here: valid rows import even when sibling rows are malformed;
 * invalid rows are surfaced with their row number and reason, never dropped
 * silently. `roster_imported` fires once per completed import with
 * rows_total / rows_imported / rows_failed.
 */

import { useCallback, useRef, useState, type ChangeEvent } from "react";
import Link from "next/link";
import {
  ArrowRight,
  CircleCheck,
  FileDown,
  LoaderCircle,
  Sparkles,
  TriangleAlert,
  Upload,
} from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { trackRosterImported } from "@/lib/events";
import { parseRosterCsv, type RosterParseResult } from "@/lib/roster-csv";
import type { EmployeeRow } from "@/lib/types";
import { cn } from "@/lib/utils";

const TEMPLATE_HEADER = "name,email,role,hire_date,hourly_rate,state";

const SAMPLE_CSV = [
  TEMPLATE_HEADER,
  "Marisol Vega,marisol.vega@northbayoyster.test,Server,2024-03-11,2.13,TX",
  "Devon Achebe,devon.achebe@northbayoyster.test,Bartender,2023-11-02,2.13,TX",
  "Priya Raman,priya.raman@northbayoyster.test,Server,2025-01-20,2.13,TX",
  "Cole Whitaker,,Busser,2025-02-04,2.13,TX",
  "Alex Moreau,alex.moreau@northbayoyster.test,Barback,2024-08-17,two dollars,TX",
].join("\n");

const TEMPLATE_CSV = [
  TEMPLATE_HEADER,
  "Jane Doe,jane@example.com,Server,2025-01-15,2.13,TX",
].join("\n");

const PREVIEW_LIMIT = 6;

type ImportPhase = "idle" | "importing" | "done";

interface RosterImportCardProps {
  onImported: (employees: EmployeeRow[]) => void;
}

function currency(value: number): string {
  return `$${value.toFixed(2)}`;
}

export function RosterImportCard({ onImported }: RosterImportCardProps) {
  const [csvText, setCsvText] = useState("");
  const [fileName, setFileName] = useState<string | null>(null);
  const [parsed, setParsed] = useState<RosterParseResult | null>(null);
  const [phase, setPhase] = useState<ImportPhase>("idle");
  const [importError, setImportError] = useState("");
  const [lastImport, setLastImport] = useState<RosterParseResult | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const ingest = useCallback((text: string, name: string | null) => {
    setCsvText(text);
    setFileName(name);
    setPhase("idle");
    setImportError("");
    setParsed(text.trim().length > 0 ? parseRosterCsv(text) : null);
  }, []);

  const onFileChange = useCallback(
    async (event: ChangeEvent<HTMLInputElement>) => {
      const file = event.target.files?.[0];
      if (!file) return;
      const text = await file.text();
      ingest(text, file.name);
    },
    [ingest]
  );

  const onImport = useCallback(async () => {
    if (!parsed || parsed.rowsImported === 0) return;
    setPhase("importing");
    setImportError("");
    try {
      const res = await fetch("/api/staff/import", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rows: parsed.validRows }),
      });
      if (!res.ok) {
        throw new Error(`Import failed with status ${res.status}`);
      }
      const data = (await res.json()) as {
        employees?: EmployeeRow[];
        imported?: number;
        failed?: number;
      };
      const created = Array.isArray(data.employees) ? data.employees : [];
      const rowsImported =
        typeof data.imported === "number" ? data.imported : created.length;
      const rowsFailed =
        typeof data.failed === "number"
          ? data.failed + parsed.rowsFailed
          : parsed.rowsFailed;

      trackRosterImported({
        rows_total: parsed.rowsTotal,
        rows_imported: rowsImported,
        rows_failed: rowsFailed,
      });

      onImported(created);
      setLastImport(parsed);
      setPhase("done");
      setCsvText("");
      setFileName(null);
      setParsed(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
    } catch {
      setPhase("idle");
      setImportError(
        "The import did not go through. Nothing was written — check your connection and try again."
      );
    }
  }, [onImported, parsed]);

  const ready = parsed?.rowsImported ?? 0;
  const failed = parsed?.rowsFailed ?? 0;

  return (
    <Card className="elev-1 overflow-hidden rounded-[10px] bg-card p-0">
      <CardContent className="p-5">
        <Tabs defaultValue="upload" className="gap-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            {/* Sized to the 44px touch floor (shadcn default is a 32px strip)
                and re-tinted onto the ledger palette. */}
            <TabsList className="h-auto rounded-md bg-accent p-1 group-data-horizontal/tabs:h-auto">
              <TabsTrigger
                value="upload"
                className="h-auto min-h-11 rounded-md px-4 data-active:text-brass-deep data-active:ring-1 data-active:ring-brass/30 dark:data-active:text-brass"
              >
                Upload a CSV
              </TabsTrigger>
              <TabsTrigger
                value="paste"
                className="h-auto min-h-11 rounded-md px-4 data-active:text-brass-deep data-active:ring-1 data-active:ring-brass/30 dark:data-active:text-brass"
              >
                Paste rows
              </TabsTrigger>
            </TabsList>
            <a
              href={`data:text/csv;charset=utf-8,${encodeURIComponent(TEMPLATE_CSV)}`}
              download="tipguard-roster-template.csv"
              className="inline-flex min-h-11 items-center gap-2 text-sm font-medium text-brass-deep underline-offset-4 transition-colors duration-[140ms] hover:underline dark:text-brass"
            >
              <FileDown aria-hidden="true" className="size-4" />
              Download the template
            </a>
          </div>

          <TabsContent value="upload">
            <div className="flex flex-col gap-2">
              <Label htmlFor="roster-file" className="text-sm font-medium">
                Roster file
              </Label>
              {/* Deposit plinth — the whole dashed frame is the target. The real
                  <input> is laid over the plinth at opacity 0 (a native file
                  input is itself a drop target), so the plinth reads as one
                  designed affordance on a single centre axis instead of bare OS
                  chrome — "Choose File / No file chosen" — sitting off-axis. */}
              <div className="group/drop relative flex flex-col items-center gap-3 rounded-md border border-dashed border-brass/45 bg-accent/50 px-4 py-7 text-center transition-colors duration-[140ms] hover:border-brass/75 hover:bg-accent focus-within:border-brass focus-within:ring-2 focus-within:ring-ring">
                <span className="flex size-11 items-center justify-center rounded-full bg-brass/15 ring-1 ring-brass/25 transition-transform duration-[140ms] group-hover/drop:-translate-y-0.5">
                  <Upload
                    aria-hidden="true"
                    className="size-5 text-brass-deep dark:text-brass"
                  />
                </span>
                <div>
                  <p className="text-sm font-medium text-foreground">
                    Drop your roster CSV here
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    or choose a file from your computer
                  </p>
                </div>
                {/* Decorative twin of the native button — the input above it is
                    invisible, so this carries the affordance. */}
                <span
                  aria-hidden="true"
                  className="inline-flex min-h-11 items-center rounded-full bg-card px-5 text-sm font-medium text-foreground ring-1 ring-border transition-colors duration-[140ms] group-hover/drop:ring-brass/50"
                >
                  Choose a file
                </span>
                <Input
                  ref={fileInputRef}
                  id="roster-file"
                  type="file"
                  accept=".csv,text/csv"
                  onChange={(event) => {
                    void onFileChange(event);
                  }}
                  className="absolute inset-0 h-full w-full cursor-pointer rounded-md border-0 p-0 opacity-0"
                />
              </div>
              <p className="text-sm text-muted-foreground">
                {fileName ? (
                  <span className="figure">{fileName}</span>
                ) : (
                  "Exports from Gusto, Toast, Square, and ADP all work — column order does not matter."
                )}
              </p>
            </div>
          </TabsContent>

          <TabsContent value="paste">
            <div className="flex flex-col gap-2">
              <Label htmlFor="roster-paste" className="text-sm font-medium">
                Roster rows
              </Label>
              <textarea
                id="roster-paste"
                value={csvText}
                spellCheck={false}
                rows={7}
                onChange={(event) => ingest(event.target.value, null)}
                placeholder={TEMPLATE_HEADER}
                className="w-full rounded-md bg-background p-3 font-mono text-base leading-[1.55] tabular-nums text-foreground ring-1 ring-input transition-shadow duration-[140ms] placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
              />
              <div className="flex flex-wrap items-center gap-3">
                <Button
                  type="button"
                  variant="outline"
                  className="min-h-11 gap-2 rounded-md px-4"
                  onClick={() => ingest(SAMPLE_CSV, null)}
                >
                  <Sparkles aria-hidden="true" className="size-4" />
                  Load a sample roster
                </Button>
                <span className="text-sm text-muted-foreground">
                  Five rows, two of them deliberately broken.
                </span>
              </div>
            </div>
          </TabsContent>
        </Tabs>

        {/* Unconditionally mounted live region — error text toggles, container stays. */}
        <p
          role="alert"
          aria-live="assertive"
          className="mt-3 min-h-5 text-sm text-destructive"
        >
          {importError}
        </p>

        {parsed ? (
          <div className="mt-2 flex flex-col gap-4 border-t border-border pt-4 duration-[240ms] animate-in fade-in-0 slide-in-from-top-1">
            <div className="flex flex-wrap items-center gap-3">
              <Badge className="figure rounded-sm bg-seal/15 px-2 py-1 text-seal">
                {ready} ready
              </Badge>
              {failed > 0 ? (
                <Badge
                  variant="destructive"
                  className="figure rounded-sm px-2 py-1"
                >
                  {failed} to fix
                </Badge>
              ) : null}
              <span className="text-sm text-muted-foreground">
                Parsed {parsed.rowsTotal} row{parsed.rowsTotal === 1 ? "" : "s"}.
                {failed > 0
                  ? " Rejected rows are listed below — the ready rows still import."
                  : " Every row passed validation."}
              </span>
            </div>

            {ready > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full border-separate border-spacing-0 text-left text-sm">
                  <caption className="sr-only">
                    Preview of rows ready to import
                  </caption>
                  <thead>
                    <tr>
                      {["Name", "Role", "State", "Cash wage", "Hired"].map(
                        (heading) => (
                          <th
                            key={heading}
                            scope="col"
                            className="eyebrow border-b border-border pb-2 pr-4 text-left"
                          >
                            {heading}
                          </th>
                        )
                      )}
                    </tr>
                  </thead>
                  <tbody>
                    {parsed.validRows.slice(0, PREVIEW_LIMIT).map((row) => (
                      <tr key={`${row.email}-${row.name}`}>
                        <td className="border-b border-border py-2 pr-4 font-medium">
                          {row.name}
                        </td>
                        <td className="border-b border-border py-2 pr-4 text-muted-foreground">
                          {row.role}
                        </td>
                        <td className="figure border-b border-border py-2 pr-4">
                          {row.state}
                        </td>
                        <td className="figure border-b border-border py-2 pr-4">
                          {currency(row.hourlyRate)}
                        </td>
                        <td className="figure border-b border-border py-2 text-muted-foreground">
                          {row.hireDate}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {ready > PREVIEW_LIMIT ? (
                  <p className="mt-2 text-sm text-muted-foreground">
                    + {ready - PREVIEW_LIMIT} more ready to import.
                  </p>
                ) : null}
              </div>
            ) : null}

            {failed > 0 ? (
              <Alert variant="destructive" className="rounded-md">
                <TriangleAlert aria-hidden="true" />
                <AlertTitle>
                  {failed} row{failed === 1 ? "" : "s"} need a fix
                </AlertTitle>
                <AlertDescription>
                  <ul className="mt-1 flex flex-col gap-1">
                    {parsed.errors.map((error) => (
                      <li key={error.row} className="flex gap-2 text-sm">
                        <span className="figure shrink-0 text-destructive">
                          Row {error.row}
                        </span>
                        <span className="text-muted-foreground">
                          {error.reason}
                        </span>
                      </li>
                    ))}
                  </ul>
                </AlertDescription>
              </Alert>
            ) : null}

            <div className="flex flex-wrap items-center gap-3">
              <Button
                type="button"
                onClick={() => void onImport()}
                disabled={ready === 0 || phase === "importing"}
                aria-label={
                  phase === "importing"
                    ? "Importing roster rows"
                    : `Import ${ready} employees`
                }
                className="min-h-11 gap-2 rounded-full px-6 text-base"
              >
                {phase === "importing" ? (
                  <>
                    <LoaderCircle
                      aria-hidden="true"
                      className="size-4 animate-spin"
                    />
                    Importing&hellip;
                  </>
                ) : (
                  <>
                    Import {ready} employee{ready === 1 ? "" : "s"}
                  </>
                )}
              </Button>
              <Button
                type="button"
                variant="ghost"
                className="min-h-11 rounded-md px-4"
                onClick={() => ingest("", null)}
              >
                Clear
              </Button>
            </div>
          </div>
        ) : null}

        {/* Seal-stamp entrance — deliberately a different motion verb from the
            parse block (slide-down) and the ledger rows (rise). */}
        {phase === "done" && lastImport ? (
          <Alert className="mt-4 rounded-md bg-seal/[0.06] ring-1 ring-seal/30 duration-[240ms] ease-[cubic-bezier(0.2,0.9,0.24,1)] animate-in fade-in-0 zoom-in-95">
            <CircleCheck aria-hidden="true" className="text-seal" />
            <AlertTitle>
              <span className="figure">{lastImport.rowsImported}</span> employee
              {lastImport.rowsImported === 1 ? "" : "s"} on file
            </AlertTitle>
            <AlertDescription>
              <span className="block">
                {lastImport.rowsFailed > 0
                  ? `${lastImport.rowsFailed} row${lastImport.rowsFailed === 1 ? "" : "s"} were skipped and are listed above — fix and re-import them any time.`
                  : "Every row imported cleanly."}{" "}
                Their tip-credit notices are next.
              </span>
              <Link
                href="/notices"
                className={cn(
                  buttonVariants(),
                  // AlertDescription forces `[&_a]:underline` + `[&_a]:hover:text-foreground`
                  // on descendant anchors; both corrupt a primary button-link.
                  "mt-3 h-11 gap-2 rounded-full px-6 text-base no-underline transition-[filter] duration-[140ms] hover:text-primary-foreground hover:brightness-95 hover:no-underline"
                )}
              >
                Generate and send notices
                <ArrowRight aria-hidden="true" className="size-4" />
              </Link>
            </AlertDescription>
          </Alert>
        ) : null}
      </CardContent>
    </Card>
  );
}

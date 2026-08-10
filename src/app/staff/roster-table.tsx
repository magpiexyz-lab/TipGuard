"use client";

/**
 * Staff-on-file ledger. Four states, all designed: loading (ruled skeleton
 * rows on the 32px ledger rhythm), read error (with retry), empty (directive
 * CTA, never "No data found"), and populated.
 */

import Image from "next/image";
import { RefreshCw, TriangleAlert } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import type { EmployeeRow } from "@/lib/types";

interface RosterTableProps {
  employees: EmployeeRow[] | null;
  error: string | null;
  onRetry: () => void;
}

const COLUMNS = ["Employee", "Role", "State", "Cash wage", "Hired"] as const;

function formatRate(rate: number): string {
  return Number.isFinite(rate) ? `$${rate.toFixed(2)}` : "—";
}

export function RosterTable({ employees, error, onRetry }: RosterTableProps) {
  if (error) {
    return (
      <Alert variant="destructive" className="rounded-[10px]">
        <TriangleAlert aria-hidden="true" />
        <AlertTitle>Roster unavailable</AlertTitle>
        <AlertDescription>
          <span className="block">{error}</span>
          <Button
            type="button"
            variant="outline"
            onClick={onRetry}
            className="mt-3 min-h-11 gap-2 rounded-md px-4"
          >
            <RefreshCw aria-hidden="true" className="size-4" />
            Try again
          </Button>
        </AlertDescription>
      </Alert>
    );
  }

  if (employees === null) {
    return (
      <Card className="elev-1 rounded-[10px] bg-card p-5" aria-busy="true">
        <p className="sr-only" role="status">
          Loading your roster
        </p>
        <div className="flex flex-col">
          {Array.from({ length: 5 }).map((_, index) => (
            <div
              key={index}
              style={{ animationDelay: `${index * 55}ms` }}
              className="flex h-11 items-center gap-4 border-b border-border duration-[240ms] animate-in fade-in-0"
            >
              <span className="h-3 w-40 animate-pulse rounded-sm bg-muted" />
              <span className="h-3 w-24 animate-pulse rounded-sm bg-muted" />
              <span className="ml-auto h-3 w-16 animate-pulse rounded-sm bg-muted" />
            </div>
          ))}
        </div>
      </Card>
    );
  }

  if (employees.length === 0) {
    return (
      <Card className="elev-1 rounded-[10px] bg-card">
        <div className="flex flex-col items-center gap-4 px-6 py-10 text-center">
          <Image
            src="/images/empty-state.webp"
            alt="An open, empty file drawer holding a single hanging folder"
            width={400}
            height={400}
            className="h-40 w-40 object-contain"
            priority={false}
          />
          <div className="max-w-md">
            <h3 className="font-display text-xl tracking-[-1.2px]">
              The file is empty
            </h3>
            <p className="mt-2 text-sm text-muted-foreground">
              Import your roster to start the file. Notices, the violation scan,
              and the audit export all read from these rows.
            </p>
          </div>
        </div>
      </Card>
    );
  }

  return (
    <Card className="elev-1 overflow-hidden rounded-[10px] bg-card p-0">
      <div className="overflow-x-auto">
        <table className="w-full border-separate border-spacing-0 text-left text-sm">
          <caption className="sr-only">
            Tipped staff currently on file, with cash wage and hire date
          </caption>
          <thead>
            <tr>
              {COLUMNS.map((column, index) => (
                <th
                  key={column}
                  scope="col"
                  className={`eyebrow border-b border-border bg-accent/40 px-4 py-3 text-left ${
                    index === 0 ? "pl-5" : ""
                  }`}
                >
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {employees.map((employee, index) => (
              <tr
                key={employee.id}
                style={{ animationDelay: `${Math.min(index, 6) * 55}ms` }}
                className="group duration-[240ms] animate-in fade-in-0 slide-in-from-bottom-1"
              >
                <td className="border-b border-l-2 border-border border-l-transparent px-4 py-3 pl-5 transition-colors duration-[140ms] group-hover:border-l-brass group-hover:bg-accent/50">
                  <span className="block font-medium">{employee.name}</span>
                  <span className="figure block text-xs text-muted-foreground">
                    {employee.email}
                  </span>
                </td>
                <td className="border-b border-border px-4 py-3 text-muted-foreground transition-colors duration-[140ms] group-hover:bg-accent/50">
                  {employee.role}
                </td>
                <td className="figure border-b border-border px-4 py-3 transition-colors duration-[140ms] group-hover:bg-accent/50">
                  {employee.state}
                </td>
                <td className="figure border-b border-border px-4 py-3 text-right transition-colors duration-[140ms] group-hover:bg-accent/50">
                  {formatRate(employee.hourly_rate)}
                </td>
                <td className="figure border-b border-border px-4 py-3 text-muted-foreground transition-colors duration-[140ms] group-hover:bg-accent/50">
                  {employee.hire_date}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

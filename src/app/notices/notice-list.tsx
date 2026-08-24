"use client";

/**
 * The notice ledger: one row per employee with notice status
 * (draft | sent | signed), the signing-link expiry once dispatched, a preview
 * of the rendered notice, and the send action.
 *
 * Signed notices expose no send control and state the block in plain language —
 * b-06: "Re-sending an already-signed notice is blocked and surfaces a clear
 * message."
 */

import Image from "next/image";
import Link from "next/link";
import {
  Eye,
  FileSignature,
  Lock,
  LoaderCircle,
  RefreshCw,
  Send,
  TriangleAlert,
} from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import type { NoticeStatus } from "@/lib/types";
import { cn } from "@/lib/utils";
import type { NoticeWithEmployee } from "./notice-types";

interface NoticeListProps {
  notices: NoticeWithEmployee[] | null;
  error: string | null;
  generating: boolean;
  pendingIds: readonly string[];
  expiries: Readonly<Record<string, string>>;
  onRetry: () => void;
  onGenerate: () => void;
  onPreview: (notice: NoticeWithEmployee) => void;
  onSend: (notice: NoticeWithEmployee) => void;
}

const STATUS_CHIP: Record<NoticeStatus, string> = {
  draft: "bg-muted text-muted-foreground",
  sent: "bg-brass/20 text-brass-deep dark:text-brass",
  signed: "bg-seal/15 text-seal dark:text-seal-soft",
};

const STATUS_LABEL: Record<NoticeStatus, string> = {
  draft: "Draft",
  sent: "Sent",
  signed: "Signed",
};

function formatDate(iso: string | undefined): string | null {
  if (!iso) return null;
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return null;
  return parsed.toISOString().slice(0, 10);
}

export function StatusChip({ status }: { status: NoticeStatus }) {
  return (
    <span
      className={cn(
        "figure inline-flex shrink-0 items-center justify-center rounded-sm px-2 py-1 text-[11px] uppercase tracking-[0.1em] sm:w-[68px]",
        STATUS_CHIP[status]
      )}
    >
      {STATUS_LABEL[status]}
    </span>
  );
}

export function NoticeList({
  notices,
  error,
  generating,
  pendingIds,
  expiries,
  onRetry,
  onGenerate,
  onPreview,
  onSend,
}: NoticeListProps) {
  if (error) {
    return (
      <Alert variant="destructive" className="rounded-[10px]">
        <TriangleAlert aria-hidden="true" />
        <AlertTitle>Notices unavailable</AlertTitle>
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

  if (notices === null) {
    return (
      <Card className="elev-1 rounded-[10px] bg-card p-5" aria-busy="true">
        <p className="sr-only" role="status">
          Loading your notices
        </p>
        <div className="flex flex-col">
          {Array.from({ length: 5 }).map((_, index) => (
            <div
              key={index}
              style={{ animationDelay: `${index * 55}ms` }}
              className="flex h-16 items-center gap-4 border-b border-border duration-[240ms] animate-in fade-in-0"
            >
              <span className="h-3 w-48 animate-pulse rounded-sm bg-muted" />
              <span className="h-5 w-16 animate-pulse rounded-sm bg-muted" />
              <span className="ml-auto h-8 w-28 animate-pulse rounded-md bg-muted" />
            </div>
          ))}
        </div>
      </Card>
    );
  }

  if (notices.length === 0) {
    return (
      <Card className="elev-1 rounded-[10px] bg-card">
        <div className="flex flex-col items-center gap-4 px-6 py-10 text-center">
          {/* The illustration ships with a baked #F3F0E6 (--background) plate.
              Seating it on a `bg-background` medallion makes that plate read as
              an intentional frame instead of a seam against the lighter card. */}
          <span className="flex size-44 shrink-0 items-center justify-center rounded-full bg-background ring-1 ring-border">
            <Image
              src="/images/empty-state.webp"
              alt="An open, empty file drawer holding a single hanging folder"
              width={400}
              height={400}
              className="size-32 object-contain"
            />
          </span>
          <div className="max-w-md">
            <h3 className="font-display text-xl tracking-[-1.2px] [word-spacing:0.06em]">
              No notices drafted yet
            </h3>
            <p className="mt-2 text-sm text-muted-foreground">
              TipGuard reads each employee&rsquo;s state and cash wage and drafts
              their notice from that state&rsquo;s rule set. Nothing is sent
              until you review it.
            </p>
          </div>
          <div className="flex flex-col items-center gap-3 sm:flex-row">
            <Button
              type="button"
              onClick={onGenerate}
              disabled={generating}
              className="min-h-11 gap-2 rounded-full px-6 text-base"
            >
              {generating ? (
                <>
                  <LoaderCircle
                    aria-hidden="true"
                    className="size-4 animate-spin"
                  />
                  Drafting&hellip;
                </>
              ) : (
                <>
                  <FileSignature aria-hidden="true" className="size-4" />
                  Draft notices from my roster
                </>
              )}
            </Button>
            <Link
              href="/staff"
              className={cn(
                buttonVariants({ variant: "ghost" }),
                "min-h-11 rounded-md border-border px-4 text-base"
              )}
            >
              Import the roster first
            </Link>
          </div>
        </div>
      </Card>
    );
  }

  return (
    <Card className="elev-1 overflow-hidden rounded-[10px] bg-card p-0">
      <ul className="flex flex-col">
        {notices.map((notice, index) => {
          const pending = pendingIds.includes(notice.id);
          const expiresAt = formatDate(expiries[notice.id]);
          const signed = notice.status === "signed";

          return (
            <li
              key={notice.id}
              style={{ animationDelay: `${Math.min(index, 6) * 55}ms` }}
              className="group flex flex-col gap-3 border-b border-l-2 border-border border-l-transparent px-5 py-4 transition-colors duration-[240ms] last:border-b-0 hover:border-l-brass hover:bg-accent/40 animate-in fade-in-0 slide-in-from-bottom-1 sm:flex-row sm:items-center sm:gap-4"
            >
              <div className="min-w-0 flex-1">
                <h3 className="truncate text-base font-medium">
                  {notice.employee.name}
                </h3>
                <p className="figure truncate text-xs text-muted-foreground">
                  {notice.employee.email}
                </p>
              </div>

              <div className="flex shrink-0 items-center gap-3 sm:w-64">
                <StatusChip status={notice.status} />
                <span className="figure truncate text-xs text-muted-foreground">
                  {signed
                    ? "In the vault"
                    : notice.status === "sent"
                      ? expiresAt
                        ? `Link expires ${expiresAt}`
                        : "Awaiting signature"
                      : `${notice.employee.role} · ${notice.state}`}
                </span>
              </div>

              <div className="flex shrink-0 flex-wrap items-center gap-2 sm:w-[292px] sm:flex-nowrap sm:justify-end">
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() => onPreview(notice)}
                  aria-label={`Preview the notice for ${notice.employee.name}`}
                  className="min-h-11 gap-2 rounded-md px-4 sm:w-[112px]"
                >
                  <Eye aria-hidden="true" className="size-4" />
                  Preview
                </Button>

                <span className="flex items-center sm:w-[172px] sm:justify-end">
                {signed ? (
                  <span className="figure inline-flex min-h-11 items-center gap-2 px-2 text-xs text-muted-foreground">
                    <Lock aria-hidden="true" className="size-4 text-seal" />
                    Cannot be re-sent
                  </span>
                ) : (
                  <Button
                    type="button"
                    variant={notice.status === "sent" ? "outline" : "default"}
                    onClick={() => onSend(notice)}
                    disabled={pending}
                    aria-label={
                      pending
                        ? `Sending the notice for ${notice.employee.name}`
                        : `Send the notice for ${notice.employee.name} for signature`
                    }
                    className="min-h-11 gap-2 rounded-full px-5"
                  >
                    {pending ? (
                      <LoaderCircle
                        aria-hidden="true"
                        className="size-4 animate-spin"
                      />
                    ) : (
                      <Send aria-hidden="true" className="size-4" />
                    )}
                    {notice.status === "sent" ? "Resend" : "Send"}
                  </Button>
                )}
                </span>
              </div>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}

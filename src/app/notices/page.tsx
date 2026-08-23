"use client";

/**
 * /notices — golden path step 6 (final), behavior b-06.
 *
 * `notice_sent` is the activation event for the whole experiment: this page's
 * send action is the single most important interaction in the product.
 *
 * API contract this page codes against (routes owned by scaffold-wire, STATE 14 —
 * they do not exist yet; until they do the page renders its documented loading /
 * error / empty states and never fabricates notice rows):
 *
 *   GET  /api/notices          -> 200 { notices: NoticeWithEmployee[] }   (RLS: owner's account)
 *   POST /api/notices/generate -> 200 { notices: NoticeWithEmployee[], generated: number }
 *   POST /api/notices/send     -> body { notice_ids: string[] }
 *                                 200 {
 *                                   sent: [{ notice_id, expires_at }],   // single-use signing
 *                                   blocked: [{ notice_id, reason }],    // e.g. already signed
 *                                   delivery_channel: "email" | "link_copy"
 *                                 }
 *
 * The server owns token minting, expiry, and the Resend dispatch; this page owns
 * review, the send trigger, and firing `notice_sent` once per dispatched notice.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  ArrowRight,
  CircleCheck,
  FileSignature,
  LoaderCircle,
  Scale,
  Send,
  TriangleAlert,
} from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Progress,
  ProgressLabel,
  ProgressValue,
} from "@/components/ui/progress";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { trackNoticeSent } from "@/lib/events";
import { COUNSEL_REVIEW_DISCLAIMER } from "@/lib/notice-generator";
import type { NoticeStatus } from "@/lib/types";
import { cn } from "@/lib/utils";
import { NoticeList } from "./notice-list";
import { NoticePreviewDialog } from "./notice-preview-dialog";
import type {
  NoticeWithEmployee,
  SendBlock,
  SendDispatch,
} from "./notice-types";

type LedgerFilter = "all" | NoticeStatus;

const FILTERS: readonly LedgerFilter[] = ["all", "draft", "sent", "signed"];

const FILTER_LABEL: Record<LedgerFilter, string> = {
  all: "Everyone",
  draft: "Draft",
  sent: "Awaiting signature",
  signed: "Signed",
};

export default function NoticesPage() {
  const [notices, setNotices] = useState<NoticeWithEmployee[] | null>(null);
  const [filter, setFilter] = useState<LedgerFilter>("all");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [pendingIds, setPendingIds] = useState<string[]>([]);
  const [expiries, setExpiries] = useState<Record<string, string>>({});
  const [blocked, setBlocked] = useState<SendBlock[]>([]);
  const [sendError, setSendError] = useState("");
  const [dispatchedCount, setDispatchedCount] = useState(0);
  const [preview, setPreview] = useState<NoticeWithEmployee | null>(null);

  const loadNotices = useCallback(async () => {
    setNotices(null);
    setLoadError(null);
    try {
      const res = await fetch("/api/notices", { cache: "no-store" });
      if (!res.ok) {
        throw new Error(`Notices request failed with status ${res.status}`);
      }
      const data = (await res.json()) as { notices?: NoticeWithEmployee[] };
      setNotices(Array.isArray(data.notices) ? data.notices : []);
    } catch {
      setLoadError(
        "We could not read your notices just now. Nothing was sent — this is a read error."
      );
    }
  }, []);

  useEffect(() => {
    void loadNotices();
  }, [loadNotices]);

  const counts = useMemo(() => {
    const list = notices ?? [];
    return {
      total: list.length,
      draft: list.filter((notice) => notice.status === "draft").length,
      sent: list.filter((notice) => notice.status === "sent").length,
      signed: list.filter((notice) => notice.status === "signed").length,
    };
  }, [notices]);

  const drafts = useMemo(
    () => (notices ?? []).filter((notice) => notice.status === "draft"),
    [notices]
  );

  const visible = useMemo(() => {
    const list = notices ?? [];
    return filter === "all"
      ? list
      : list.filter((notice) => notice.status === filter);
  }, [filter, notices]);

  const signedPct =
    counts.total === 0 ? 0 : Math.round((counts.signed / counts.total) * 100);

  const onGenerate = useCallback(async () => {
    setGenerating(true);
    setSendError("");
    try {
      const res = await fetch("/api/notices/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      if (!res.ok) {
        throw new Error(`Generate failed with status ${res.status}`);
      }
      const data = (await res.json()) as { notices?: NoticeWithEmployee[] };
      if (Array.isArray(data.notices)) {
        setNotices(data.notices);
      } else {
        await loadNotices();
      }
    } catch {
      setSendError(
        "Drafting the notices did not complete. Nothing was sent to your staff — try again."
      );
    } finally {
      setGenerating(false);
    }
  }, [loadNotices]);

  /**
   * Sends one or many notices. Signed notices are excluded client-side and the
   * server's `blocked[]` entries are surfaced verbatim. `notice_sent` fires
   * exactly once per notice the server confirms it dispatched.
   */
  const sendNotices = useCallback(
    async (targets: NoticeWithEmployee[]) => {
      const sendable = targets.filter((notice) => notice.status !== "signed");
      if (sendable.length === 0) {
        setBlocked(
          targets.map((notice) => ({
            notice_id: notice.id,
            reason: `${notice.employee.name} has already signed. A signed notice is an immutable record and cannot be re-sent.`,
          }))
        );
        return;
      }

      const ids = sendable.map((notice) => notice.id);
      setPendingIds(ids);
      setSendError("");
      setBlocked([]);

      try {
        const res = await fetch("/api/notices/send", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ notice_ids: ids }),
        });
        if (!res.ok) {
          throw new Error(`Send failed with status ${res.status}`);
        }
        const data = (await res.json()) as {
          sent?: SendDispatch[];
          blocked?: SendBlock[];
          delivery_channel?: string;
        };

        const dispatched = Array.isArray(data.sent) ? data.sent : [];
        const deliveryChannel = data.delivery_channel ?? "email";

        // ACTIVATION EVENT — once per notice actually dispatched.
        dispatched.forEach((dispatch) => {
          trackNoticeSent({
            notice_id: dispatch.notice_id,
            employee_count: dispatched.length,
            delivery_channel: deliveryChannel,
          });
        });

        const dispatchedIds = new Set(
          dispatched.map((dispatch) => dispatch.notice_id)
        );

        setExpiries((previous) => {
          const next = { ...previous };
          dispatched.forEach((dispatch) => {
            if (dispatch.expires_at) next[dispatch.notice_id] = dispatch.expires_at;
          });
          return next;
        });

        setNotices((previous) =>
          (previous ?? []).map((notice) =>
            dispatchedIds.has(notice.id)
              ? { ...notice, status: "sent" as const }
              : notice
          )
        );

        setDispatchedCount((previous) => previous + dispatched.length);
        setBlocked(Array.isArray(data.blocked) ? data.blocked : []);
        setPreview(null);
      } catch {
        setSendError(
          "The send did not go through. No signing links were issued — check your connection and try again."
        );
      } finally {
        setPendingIds([]);
      }
    },
    []
  );

  const sendingAll = pendingIds.length > 1;

  return (
    <div className="min-h-screen">
      {/* Authority band — the send action lives here because it is the single
          most consequential control in the product. */}
      <div className="dark surface-ink texture-rule">
        <div className="bloom-brass">
          <div className="mx-auto flex max-w-[1180px] flex-col gap-4 px-5 py-6 sm:px-8 md:py-8 lg:flex-row lg:items-end lg:justify-between">
            <div className="max-w-2xl">
              <p className="eyebrow">Step 06 / 06 &middot; Notices</p>
              <h1 className="mt-2 font-display text-[26px] leading-[1.06] tracking-[-0.025em] text-[#ECE8DA] sm:text-[32px]">
                Send the notices for signature
              </h1>
              <p className="mt-3 max-w-xl text-base leading-[1.55] text-[#A8AF9B]">
                Each employee gets a single-use, expiring link. The exact text
                they acknowledge is frozen into your vault with their name, UTC
                timestamp, and IP.
              </p>
            </div>

            <div className="flex flex-col items-start gap-4 lg:items-end">
              <dl className="flex items-center gap-6">
                <div>
                  <dt className="eyebrow text-[#A8AF9B]">Drafts waiting</dt>
                  <dd className="figure mt-1 text-3xl text-[#ECE8DA]">
                    {counts.draft.toString().padStart(2, "0")}
                  </dd>
                </div>
                <div className="border-l border-[rgba(243,240,230,0.18)] pl-6">
                  <dt className="eyebrow text-[#A8AF9B]">Signed</dt>
                  <dd className="figure mt-1 text-3xl text-[#ECE8DA]">
                    {counts.signed.toString().padStart(2, "0")}
                  </dd>
                </div>
              </dl>

              <Button
                type="button"
                onClick={() => void sendNotices(drafts)}
                disabled={drafts.length === 0 || pendingIds.length > 0}
                aria-label={
                  sendingAll
                    ? "Sending all draft notices"
                    : `Send all ${drafts.length} draft notices for signature`
                }
                className={cn(
                  "min-h-11 gap-2 rounded-full px-6 text-base",
                  // On the ink band a 50%-opacity brass fill still reads as an
                  // enabled CTA while its label falls to ~2.5:1. With nothing to
                  // send, present an explicitly inert outline instead.
                  drafts.length === 0 &&
                    "border-[rgba(243,240,230,0.24)] bg-transparent text-[#A8AF9B] disabled:opacity-100"
                )}
              >
                {sendingAll ? (
                  <>
                    <LoaderCircle
                      aria-hidden="true"
                      className="size-4 animate-spin"
                    />
                    Sending&hellip;
                  </>
                ) : (
                  <>
                    <Send aria-hidden="true" className="size-4" />
                    Send all drafts
                    {drafts.length > 0 ? (
                      <span className="figure">({drafts.length})</span>
                    ) : null}
                  </>
                )}
              </Button>
            </div>
          </div>
        </div>
      </div>

      <div className="mx-auto flex max-w-[1180px] flex-col gap-8 px-5 py-6 sm:px-8">
        {/* Evidence strip — status distribution on ledger hairlines. */}
        <section aria-label="Notice status summary">
          <Card className="elev-1 rounded-[10px] bg-card p-0">
            <CardContent className="grid grid-cols-2 gap-0 p-0 sm:grid-cols-4">
              {(
                [
                  ["Employees", counts.total, "text-foreground"],
                  ["Draft", counts.draft, "text-muted-foreground"],
                  ["Sent", counts.sent, "text-brass-deep dark:text-brass"],
                  ["Signed", counts.signed, "text-seal dark:text-seal-soft"],
                ] as const
              ).map(([label, value, tone], index) => (
                <dl
                  key={label}
                  className={cn(
                    "px-5 py-4",
                    index % 2 === 1 && "border-l border-border",
                    index > 1 && "border-t border-border sm:border-t-0",
                    index > 0 && "sm:border-l sm:border-border"
                  )}
                >
                  <div>
                    <dt className="eyebrow">{label}</dt>
                    <dd className={cn("figure mt-1 text-2xl", tone)}>
                      {notices === null ? "--" : value}
                    </dd>
                  </div>
                </dl>
              ))}
            </CardContent>
          </Card>

          {counts.total > 0 ? (
            <Progress
              value={signedPct}
              className="mt-4"
              aria-label="Share of notices signed"
            >
              <ProgressLabel className="text-sm text-muted-foreground">
                Acknowledgments in the vault
              </ProgressLabel>
              <ProgressValue className="figure" />
            </Progress>
          ) : null}
        </section>

        {/* Unconditionally mounted live region — text toggles, container stays. */}
        <p
          role="alert"
          aria-live="assertive"
          className="min-h-5 text-sm text-destructive"
        >
          {sendError}
        </p>

        {dispatchedCount > 0 ? (
          <Alert className="rounded-[10px] ring-1 ring-seal/30 duration-[240ms] animate-in fade-in-0 slide-in-from-bottom-1">
            <CircleCheck aria-hidden="true" className="text-seal" />
            <AlertTitle>
              <span className="figure">{dispatchedCount}</span> signing link
              {dispatchedCount === 1 ? "" : "s"} dispatched
            </AlertTitle>
            <AlertDescription>
              <span className="block">
                Each link is single-use and expires. You will see the status flip
                to <span className="figure">SIGNED</span> here as
                acknowledgments land in the vault.
              </span>
              <span className="mt-3 flex flex-wrap gap-3">
                <Link
                  href="/dashboard"
                  className={cn(
                    buttonVariants(),
                    "h-11 gap-2 rounded-full px-6 text-base"
                  )}
                >
                  See your compliance state
                  <ArrowRight aria-hidden="true" className="size-4" />
                </Link>
                <Link
                  href="/audit-file"
                  className={cn(
                    buttonVariants({ variant: "outline" }),
                    "h-11 rounded-md px-4 text-base"
                  )}
                >
                  Build the audit file
                </Link>
              </span>
            </AlertDescription>
          </Alert>
        ) : null}

        {blocked.length > 0 ? (
          <Alert variant="destructive" className="rounded-[10px]">
            <TriangleAlert aria-hidden="true" />
            <AlertTitle>
              {blocked.length} notice{blocked.length === 1 ? "" : "s"} were not
              sent
            </AlertTitle>
            <AlertDescription>
              <ul className="mt-1 flex flex-col gap-1">
                {blocked.map((block) => (
                  <li key={block.notice_id} className="text-sm">
                    {block.reason}
                  </li>
                ))}
              </ul>
            </AlertDescription>
          </Alert>
        ) : null}

        <section aria-labelledby="notice-ledger-heading">
          <div className="flex flex-wrap items-baseline justify-between gap-3">
            <h2
              id="notice-ledger-heading"
              className="font-display text-2xl tracking-[-1.2px]"
            >
              Every employee, every notice
            </h2>
            {notices !== null && notices.length > 0 ? (
              <Button
                type="button"
                variant="ghost"
                onClick={() => void onGenerate()}
                disabled={generating}
                className="min-h-11 gap-2 rounded-md px-4"
              >
                {generating ? (
                  <LoaderCircle
                    aria-hidden="true"
                    className="size-4 animate-spin"
                  />
                ) : (
                  <FileSignature aria-hidden="true" className="size-4" />
                )}
                Draft notices for new hires
              </Button>
            ) : null}
          </div>
          <p className="mt-2 max-w-2xl text-sm text-muted-foreground">
            Preview the exact text before it goes out. Once an employee signs,
            the record is immutable &mdash; it cannot be edited or re-sent.
          </p>

          {counts.total > 0 ? (
            <Tabs
              value={filter}
              onValueChange={(value) => setFilter(value as LedgerFilter)}
              className="mt-4 overflow-x-auto"
            >
              <TabsList variant="line">
                {FILTERS.map((value) => (
                  <TabsTrigger key={value} value={value} className="gap-2">
                    {FILTER_LABEL[value]}
                    <span className="figure text-xs text-muted-foreground">
                      {value === "all" ? counts.total : counts[value]}
                    </span>
                  </TabsTrigger>
                ))}
              </TabsList>
            </Tabs>
          ) : null}

          <div className="mt-4">
            {notices !== null && counts.total > 0 && visible.length === 0 ? (
              <Card className="elev-1 rounded-[10px] bg-card">
                <div className="flex flex-col items-center gap-3 px-6 py-10 text-center">
                  <h3 className="font-display text-xl tracking-[-1.2px]">
                    Nothing sitting in {FILTER_LABEL[filter].toLowerCase()}
                  </h3>
                  <p className="max-w-md text-sm text-muted-foreground">
                    {filter === "signed"
                      ? "No acknowledgments have landed in the vault yet. They appear here the moment an employee signs."
                      : "Every notice has moved past this stage."}
                  </p>
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => setFilter("all")}
                    className="min-h-11 rounded-md px-4"
                  >
                    Show everyone
                  </Button>
                </div>
              </Card>
            ) : (
              <NoticeList
                notices={notices === null ? null : visible}
                error={loadError}
                generating={generating}
                pendingIds={pendingIds}
                expiries={expiries}
                onRetry={() => void loadNotices()}
                onGenerate={() => void onGenerate()}
                onPreview={setPreview}
                onSend={(notice) => void sendNotices([notice])}
              />
            )}
          </div>
        </section>

        <Alert className="rounded-[10px]">
          <Scale aria-hidden="true" />
          <AlertTitle>Review by your counsel before distribution</AlertTitle>
          <AlertDescription className="text-sm">
            {COUNSEL_REVIEW_DISCLAIMER}
          </AlertDescription>
        </Alert>
      </div>

      <NoticePreviewDialog
        notice={preview}
        sending={preview !== null && pendingIds.includes(preview.id)}
        onOpenChange={(open) => {
          if (!open) setPreview(null);
        }}
        onSend={(notice) => void sendNotices([notice])}
      />
    </div>
  );
}

"use client";

/**
 * Rendered-notice preview (b-06: "…and a preview of the rendered notice").
 *
 * The counsel-review disclaimer is rendered as a first-class element of this
 * dialog and is never conditional. TipGuard does not claim attorney review or
 * certification anywhere in this component.
 */

import { LoaderCircle, Scale, Send } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { COUNSEL_REVIEW_DISCLAIMER } from "@/lib/notice-generator";
import type { NoticeWithEmployee } from "./notice-types";

interface NoticePreviewDialogProps {
  notice: NoticeWithEmployee | null;
  sending: boolean;
  onOpenChange: (open: boolean) => void;
  onSend: (notice: NoticeWithEmployee) => void;
}

export function NoticePreviewDialog({
  notice,
  sending,
  onOpenChange,
  onSend,
}: NoticePreviewDialogProps) {
  return (
    <Dialog open={notice !== null} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
        {notice ? (
          <>
            <DialogHeader>
              <p className="eyebrow">
                Tip-credit notice &middot; {notice.state} &middot; rule{" "}
                {notice.rule_version}
              </p>
              <DialogTitle className="font-display text-2xl tracking-[-1.2px] [word-spacing:0.06em]">
                {notice.employee.name}
              </DialogTitle>
              <DialogDescription>
                This is the exact text the employee will read and acknowledge.
                The signed copy is frozen at signature time and cannot be edited
                afterwards.
              </DialogDescription>
            </DialogHeader>

            <dl className="grid grid-cols-2 gap-3 rounded-md bg-accent/60 p-4 sm:grid-cols-4">
              <div>
                <dt className="eyebrow">Cash wage</dt>
                <dd className="figure mt-1 text-base">
                  ${notice.cash_wage_paid.toFixed(2)}/hr
                </dd>
              </div>
              <div>
                <dt className="eyebrow">Tip credit</dt>
                <dd className="figure mt-1 text-base">
                  {notice.tip_credit_claimed ? "Claimed" : "Not claimed"}
                </dd>
              </div>
              <div>
                <dt className="eyebrow">State</dt>
                <dd className="figure mt-1 text-base">{notice.state}</dd>
              </div>
              <div>
                <dt className="eyebrow">Rule version</dt>
                <dd className="figure mt-1 text-base">{notice.rule_version}</dd>
              </div>
            </dl>

            <div className="rounded-md bg-background p-4 ring-1 ring-border">
              <pre className="whitespace-pre-wrap font-mono text-sm leading-[1.6] text-foreground">
                {notice.notice_text}
              </pre>
            </div>

            <Alert className="rounded-md">
              <Scale aria-hidden="true" />
              <AlertTitle>Review by your counsel before distribution</AlertTitle>
              <AlertDescription className="text-sm">
                {COUNSEL_REVIEW_DISCLAIMER}
              </AlertDescription>
            </Alert>

            {notice.status === "signed" ? (
              <p className="text-sm text-muted-foreground">
                This notice is signed. Signed notices cannot be re-sent or
                edited &mdash; that immutability is what makes the record
                evidence.
              </p>
            ) : (
              <Button
                type="button"
                onClick={() => onSend(notice)}
                disabled={sending}
                className="min-h-11 gap-2 self-start rounded-full px-6 text-base"
              >
                {sending ? (
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
                    {notice.status === "sent"
                      ? "Send the link again"
                      : "Send for signature"}
                  </>
                )}
              </Button>
            )}
          </>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

"use client";

import { useId, useState } from "react";
import { usePathname } from "next/navigation";
import { LoaderCircle, MessageSquare } from "lucide-react";
import { Button, buttonVariants } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

type Phase = "idle" | "sending" | "sent";

const SOURCES = [
  { value: "google", label: "Search" },
  { value: "social", label: "Social / forum" },
  { value: "friend", label: "Another operator" },
  { value: "other", label: "Somewhere else" },
] as const;

/**
 * Post-activation feedback (`feedback_submitted`).
 *
 * Rendered only on `/dashboard` — the surface an owner returns to after
 * sending notices. `POST /api/feedback` enforces the activation precondition
 * server-side (the account must have dispatched at least one notice) and fires
 * the analytics event with `trackServerEvent`, so the event reflects an
 * account fact rather than a client claim.
 */
export function FeedbackWidget() {
  const pathname = usePathname();
  const feedbackId = useId();
  const [open, setOpen] = useState(false);
  const [source, setSource] = useState<string | null>(null);
  const [feedback, setFeedback] = useState("");
  const [phase, setPhase] = useState<Phase>("idle");
  const [message, setMessage] = useState("");

  if (pathname !== "/dashboard") return null;

  async function submit() {
    setPhase("sending");
    setMessage("");
    try {
      const response = await fetch("/api/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...(source ? { source } : {}),
          ...(feedback.trim() ? { feedback: feedback.trim() } : {}),
          activation_action: "notice_sent",
        }),
      });

      if (!response.ok) {
        const body = (await response.json().catch(() => ({}))) as { error?: string };
        setPhase("idle");
        setMessage(body.error ?? "That did not go through. Try again in a moment.");
        return;
      }

      setPhase("sent");
      setMessage("Thank you — that goes straight to the people building this.");
    } catch {
      setPhase("idle");
      setMessage("Could not reach us just now. Check your connection and try again.");
    }
  }

  return (
    <div className="fixed right-4 bottom-4 z-40 print:hidden">
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogTrigger
          className={cn(
            buttonVariants({ variant: "outline" }),
            "h-11 gap-2 rounded-full bg-background px-5 text-sm shadow-lg"
          )}
        >
          <MessageSquare className="size-4" aria-hidden="true" />
          Share feedback
        </DialogTrigger>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>How is TipGuard working for you?</DialogTitle>
            <DialogDescription>
              You sent your first notices. Tell us what was harder than it should
              have been.
            </DialogDescription>
          </DialogHeader>

          <fieldset className="mt-2">
            <legend className="eyebrow">How did you find TipGuard?</legend>
            <div className="mt-2 flex flex-wrap gap-2">
              {SOURCES.map((option) => (
                <Button
                  key={option.value}
                  type="button"
                  variant={source === option.value ? "default" : "outline"}
                  aria-pressed={source === option.value}
                  onClick={() => setSource(option.value)}
                  className="h-10 rounded-full px-4 text-sm"
                >
                  {option.label}
                </Button>
              ))}
            </div>
          </fieldset>

          <div className="mt-4 grid gap-2">
            <Label htmlFor={feedbackId} className="text-sm font-medium">
              Anything else? (optional)
            </Label>
            <textarea
              id={feedbackId}
              rows={4}
              maxLength={2000}
              value={feedback}
              onChange={(event) => setFeedback(event.target.value)}
              placeholder="The part that took longest was…"
              className="w-full rounded-md bg-background p-3 text-base leading-[1.55] ring-1 ring-input focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
            />
          </div>

          {/* Always-mounted live region — a conditionally-mounted role="alert"
              is absent from the a11y tree at load and drops announcements. */}
          <p
            role="status"
            aria-live="polite"
            className={cn("mt-3 text-sm", message ? "text-foreground" : "sr-only")}
          >
            {message}
          </p>

          <div className="mt-4 flex justify-end gap-2">
            <Button
              type="button"
              variant="ghost"
              onClick={() => setOpen(false)}
              className="h-11 rounded-md px-4"
            >
              {phase === "sent" ? "Close" : "Not now"}
            </Button>
            <Button
              type="button"
              disabled={phase !== "idle"}
              onClick={() => void submit()}
              className="h-11 rounded-full px-6"
            >
              {phase === "sending" ? (
                <LoaderCircle className="size-4 animate-spin" aria-hidden="true" />
              ) : (
                "Send feedback"
              )}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}

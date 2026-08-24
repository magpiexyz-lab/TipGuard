"use client";

/**
 * "Connect Gusto / Toast" fake door (b-04, action_label `connect-payroll`).
 *
 * Instantiated from the Fake Door template in .claude/stacks/ui/shadcn.md with two
 * project-required deltas:
 *   1. Analytics goes through the typed wrapper `trackPayrollConnectClicked`
 *      instead of a raw `track("activate", …)` string (CLAUDE.md Rule 2 — the
 *      event and its required `provider` property are declared in EVENTS.yaml).
 *   2. The dialog carries a provider picker because `provider` is a required
 *      event property. It implements the WAI-ARIA radiogroup contract
 *      (roving tabindex + Arrow/Home/End) per shadcn.md.
 *
 * Intent capture only: no PII is collected and no fake success is shown — the
 * click is recorded and the roadmap position is explained honestly.
 */

import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { CircleCheck, PlugZap } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Button, buttonVariants } from "@/components/ui/button";
import { trackPayrollConnectClicked } from "@/lib/events";
import { cn } from "@/lib/utils";

const PROVIDERS = ["gusto", "toast", "square", "adp", "other"] as const;
type Provider = (typeof PROVIDERS)[number];

const PROVIDER_LABELS: Record<Provider, string> = {
  gusto: "Gusto",
  toast: "Toast",
  square: "Square",
  adp: "ADP",
  other: "Something else",
};

type Status = "idle" | "submitting" | "success" | "error";

function handleRadioGroupKey(
  event: KeyboardEvent<HTMLElement>,
  values: ReadonlyArray<Provider>,
  current: Provider | null,
  onChange: (value: Provider) => void
): void {
  const last = values.length - 1;
  if (last < 0) return;
  const currentIdx = current === null ? 0 : Math.max(0, values.indexOf(current));
  let nextIdx: number;
  switch (event.key) {
    case "ArrowRight":
    case "ArrowDown":
      nextIdx = currentIdx === last ? 0 : currentIdx + 1;
      break;
    case "ArrowLeft":
    case "ArrowUp":
      nextIdx = currentIdx === 0 ? last : currentIdx - 1;
      break;
    case "Home":
      nextIdx = 0;
      break;
    case "End":
      nextIdx = last;
      break;
    default:
      return;
  }
  event.preventDefault();
  onChange(values[nextIdx]);
  const container = (event.currentTarget as HTMLElement).parentElement;
  (container?.children[nextIdx] as HTMLElement | undefined)?.focus();
}

function rovingTabIndex(
  values: ReadonlyArray<Provider>,
  current: Provider | null,
  index: number
): 0 | -1 {
  if (current === null) return index === 0 ? 0 : -1;
  return values[index] === current ? 0 : -1;
}

export function PayrollConnectFakeDoor() {
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState<Status>("idle");
  const [provider, setProvider] = useState<Provider>("gusto");
  const [errorMessage, setErrorMessage] = useState("");
  const successRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (status === "success") successRef.current?.focus();
  }, [status]);

  function onActivate() {
    setStatus("submitting");
    try {
      trackPayrollConnectClicked({ provider });
      setStatus("success");
    } catch {
      setStatus("error");
      setErrorMessage("Something went wrong. Please try again.");
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      {/* Trigger via the render-callback form so the primitive keeps focus
          return on Esc / overlay close (element form drops children on Base UI). */}
      <DialogTrigger
        render={(props) => (
          <Button
            type="button"
            variant="ghost"
            {...props}
            className={cn(
              buttonVariants({ variant: "ghost" }),
              "min-h-11 w-full justify-center gap-2 rounded-md border border-border/40 px-4 text-base"
            )}
          >
            <PlugZap aria-hidden="true" className="size-4" />
            Connect Gusto / Toast
          </Button>
        )}
      />

      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="font-display text-xl tracking-[-1.2px] [word-spacing:0.06em]">
            Payroll sync is on the roadmap
          </DialogTitle>
          <DialogDescription>
            Direct payroll sync is not live yet. CSV import is the working path
            today and produces exactly the same notices, violation scan, and
            audit file.
          </DialogDescription>
        </DialogHeader>

        {status !== "success" ? (
          <div className="flex flex-col gap-4">
            <div>
              <span
                id="payroll-provider-label"
                className="block text-sm font-medium"
              >
                Which platform do you run payroll on?
              </span>
              <div
                role="radiogroup"
                aria-labelledby="payroll-provider-label"
                className="mt-2 flex flex-wrap gap-2"
              >
                {PROVIDERS.map((value, index) => {
                  const active = provider === value;
                  return (
                    <button
                      key={value}
                      type="button"
                      role="radio"
                      aria-checked={active}
                      tabIndex={rovingTabIndex(PROVIDERS, provider, index)}
                      onClick={() => setProvider(value)}
                      onKeyDown={(event) =>
                        handleRadioGroupKey(
                          event,
                          PROVIDERS,
                          provider,
                          setProvider
                        )
                      }
                      className={cn(
                        "min-h-11 rounded-md px-4 text-sm font-medium ring-1 transition-all duration-[140ms] focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
                        active
                          ? "bg-brass/15 text-brass-deep ring-brass dark:text-brass"
                          : "bg-background text-muted-foreground ring-border hover:text-foreground"
                      )}
                    >
                      {PROVIDER_LABELS[value]}
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Unconditionally mounted live region — text toggles, container stays. */}
            <p
              role="alert"
              aria-live="assertive"
              className="min-h-5 text-sm text-destructive"
            >
              {status === "error" ? errorMessage : ""}
            </p>

            <Button
              type="button"
              onClick={onActivate}
              disabled={status === "submitting"}
              className="min-h-11 rounded-full px-6 text-base"
            >
              {status === "submitting"
                ? "Recording…"
                : `Tell us to build ${PROVIDER_LABELS[provider]} first`}
            </Button>
          </div>
        ) : (
          <div
            ref={successRef}
            tabIndex={-1}
            aria-live="polite"
            className="flex flex-col gap-3 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
          >
            <div className="flex items-start gap-3">
              <CircleCheck
                aria-hidden="true"
                className="mt-0.5 size-5 shrink-0 text-seal"
              />
              <div>
                <h3 className="font-display text-lg tracking-[-1.2px] [word-spacing:0.06em]">
                  Noted &mdash; {PROVIDER_LABELS[provider]} is on the list
                </h3>
                <p className="mt-1 text-sm text-muted-foreground">
                  We build connectors in the order operators ask for them.
                  Nothing was connected and no credentials were requested.
                </p>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <Button
                type="button"
                variant="outline"
                className="min-h-11 rounded-md px-4"
                onClick={() => {
                  setStatus("idle");
                  setOpen(false);
                }}
              >
                Back to Staff
              </Button>
              <span className="text-sm text-muted-foreground">
                CSV import is live &mdash; keep going.
              </span>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

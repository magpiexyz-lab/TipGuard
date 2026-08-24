"use client";

import { useEffect, useRef, useState, type CSSProperties } from "react";
import { BorderBeam } from "@/components/magicui/border-beam";
import { cn } from "@/lib/utils";

/**
 * "The Signature" — the hero micro-interaction, and the whole product in three
 * seconds: unsigned exposure → signed evidence → dated record.
 *
 *   1. a handwritten stroke draws itself across the acknowledgment line
 *   2. a brass seal presses down and pulses once
 *   3. the status chip flips DRAFT → SIGNED and a UTC timestamp fades in
 *
 * Safety: the server render and the first paint are the FINAL "sealed" state,
 * so the card is complete and legible before any JS runs and for anyone with
 * `prefers-reduced-motion: reduce`. The loop only ever runs client-side.
 *
 * The record shown is an illustration of the notice format (federal floor:
 * $2.13 cash wage + $5.12 credit = $7.25), not customer data.
 */

type Stage = "sealed" | "clearing" | "blank" | "drawing";

const TIMELINE: Record<Stage, { next: Stage; hold: number }> = {
  sealed: { next: "clearing", hold: 4200 },
  clearing: { next: "blank", hold: 320 },
  blank: { next: "drawing", hold: 460 },
  drawing: { next: "sealed", hold: 660 },
};

const RECORD = {
  id: "REC-2026-0416-04",
  employee: "Marisol Vega",
  role: "Server · Austin, TX",
  signedAt: "2026-04-16 21:04:38 UTC",
  rows: [
    { label: "Cash wage", value: "$2.13 / hr" },
    { label: "Tip credit claimed", value: "$5.12 / hr" },
    { label: "Rule version", value: "TX v2026.2" },
  ],
};

export function SignatureCard() {
  const [stage, setStage] = useState<Stage>("sealed");
  const [cycle, setCycle] = useState(0);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const pathRef = useRef<SVGPathElement | null>(null);

  // Measure the real stroke length so the draw finishes exactly on time
  // instead of against a hard-coded dash estimate. Set on the <svg> (stable)
  // rather than the keyed <g>, which remounts on every cycle.
  useEffect(() => {
    const svg = svgRef.current;
    const path = pathRef.current;
    if (!svg || !path) return;
    svg.style.setProperty("--tg-dash", String(Math.ceil(path.getTotalLength())));
  }, []);

  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    let timer = 0;
    const advance = (current: Stage) => {
      const { next, hold } = TIMELINE[current];
      timer = window.setTimeout(() => {
        setStage(next);
        if (next === "drawing") setCycle((c) => c + 1);
        advance(next);
      }, hold);
    };
    advance("sealed");

    return () => window.clearTimeout(timer);
  }, []);

  const signed = stage === "sealed";
  const inkVisible = stage === "drawing" || stage === "sealed" || stage === "clearing";

  return (
    <div className="relative isolate">
      {/* Sheet stack behind the live notice — depth layer 1 of 3. */}
      <div
        aria-hidden="true"
        className="absolute -right-3 -top-3 h-full w-full rounded-xl bg-paper-raised/45 shadow-ledger-1"
      />
      <div
        aria-hidden="true"
        className="absolute -right-1.5 -top-1.5 h-full w-full rounded-xl bg-paper-raised/70 shadow-ledger-1"
      />

      <div className="relative overflow-hidden rounded-xl p-px shadow-ledger-3">
        <BorderBeam duration={9} />

        <div className="relative rounded-[13px] bg-paper-raised p-6 text-ink sm:p-7">
          <div className="flex items-start justify-between gap-4">
            <span className="eyebrow">Tip-credit notice</span>
            <span className="figure text-[11px] tracking-[0.06em] text-ink-soft">
              {RECORD.id}
            </span>
          </div>

          <p className="mt-4 font-display text-2xl font-semibold tracking-[-1.2px] [word-spacing:0.06em]">
            {RECORD.employee}
          </p>
          <p className="mt-1 text-sm text-ink-soft">{RECORD.role}</p>

          <dl className="mt-6">
            {RECORD.rows.map((row) => (
              <div
                key={row.label}
                className="flex items-baseline justify-between gap-4 border-t border-border py-2.5"
              >
                <dt className="font-mono text-[11px] uppercase tracking-[0.14em] text-ink-soft">
                  {row.label}
                </dt>
                <dd className="figure text-sm text-ink">{row.value}</dd>
              </div>
            ))}
          </dl>

          {/* Acknowledgment line — the stroke draws across this rule. */}
          <div className="mt-5">
            <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-ink-soft">
              Employee acknowledgment
            </p>

            <div className="mt-2 flex items-end gap-4">
              <div className="relative min-w-0 flex-1">
                <svg
                  ref={svgRef}
                  viewBox="0 0 320 56"
                  className="h-14 w-full"
                  fill="none"
                  aria-hidden="true"
                  style={{ "--tg-dash": "520" } as CSSProperties}
                >
                  <g
                    key={`sig-${cycle}`}
                    className={cn(
                      stage === "drawing" && "tg-sig-draw",
                      stage === "sealed" && "tg-sig-done",
                      stage === "clearing" && "tg-sig-done tg-clear",
                      stage === "blank" && "opacity-0"
                    )}
                  >
                    <path
                      ref={pathRef}
                      className="tg-sig-path"
                      d="M6 47C12 31 21 12 30 11c6-1 6 8 1 16-5 8-13 16-17 20-3 3-1 5 3 4 7-2 15-9 21-16 4-5 9-3 7 4-2 6-5 11-2 12 4 1 9-6 12-12 3-5 8-3 6 4-2 8-3 13 2 13 7 0 15-11 20-20 3-6 9-4 7 4-2 9-3 15 3 15 8 0 18-12 25-22 4-6 11-4 9 5-2 10-4 17 3 17 9 0 20-12 27-21 5-7 13-5 11 5-2 9-4 15 4 15 11 0 25-14 36-25 6-6 14-4 10 6-4 10-8 16 1 17 12 1 28-12 42-24"
                      stroke="var(--ink)"
                      strokeWidth={2}
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      style={{ opacity: inkVisible ? 1 : 0 }}
                    />
                  </g>
                </svg>
                <div className="h-px w-full bg-ink/25" />
                <p className="mt-2 font-mono text-[11px] uppercase tracking-[0.14em] text-ink-soft">
                  Signature of employee
                </p>
              </div>

              {/* Brass seal — presses down on completion. */}
              <div className="relative mb-6 shrink-0">
                <svg
                  key={`seal-${cycle}`}
                  viewBox="0 0 64 64"
                  className={cn(
                    "size-14 rounded-full",
                    signed && "tg-seal-press",
                    stage === "clearing" && "tg-clear",
                    !signed && stage !== "clearing" && "opacity-0"
                  )}
                  aria-hidden="true"
                >
                  <circle cx="32" cy="32" r="29" fill="none" stroke="var(--brass)" strokeWidth="2" />
                  <circle
                    cx="32"
                    cy="32"
                    r="23"
                    fill="none"
                    stroke="var(--brass)"
                    strokeWidth="1"
                    strokeDasharray="2 4"
                  />
                  <path
                    d="M22 33l7 8 14-18"
                    fill="none"
                    stroke="var(--seal)"
                    strokeWidth="3.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </div>
            </div>
          </div>

          <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-border pt-4">
            <span
              key={`chip-${cycle}-${signed ? "s" : "d"}`}
              className={cn(
                "rounded-sm px-2.5 py-1 font-mono text-[11px] font-medium uppercase tracking-[0.1em]",
                signed
                  ? "tg-chip-in bg-seal/12 text-seal"
                  : "bg-muted text-ink-soft"
              )}
            >
              {signed ? "Signed" : "Draft"}
            </span>
            <span
              className={cn(
                "figure text-[11px] text-ink-soft transition-opacity duration-[240ms]",
                signed ? "opacity-100" : "opacity-0"
              )}
            >
              {RECORD.signedAt}
            </span>
          </div>

          <div className="tg-perf mt-5" aria-hidden="true" />
          <p className="mt-4 text-xs leading-[1.5] text-ink-soft">
            Review by your counsel before distribution. TipGuard generates this
            notice from a per-state rule library; it is not legal advice.
          </p>
        </div>
      </div>
    </div>
  );
}

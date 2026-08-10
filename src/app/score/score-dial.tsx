"use client";

// The readiness dial: a 270-degree gauge arc that sweeps through the compliance
// ramp (ember -> brass -> seal) while the figure counts up. Mechanical, not
// bouncy — the arc commits to its value and stops.
//
// The numeral is rendered in HTML rather than SVG <text> so it inherits the
// Plex Mono tabular-nums treatment from globals.css (SVG text does not pick up
// font-variant-numeric reliably across engines).

import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";

const SWEEP = 0.75; // 270 degrees of a full circle
const DURATION_MS = 900;

export interface ScoreBand {
  label: string;
  color: string;
  textClass: string;
}

export function bandForScore(score: number): ScoreBand {
  if (score >= 85)
    return { label: "Audit-ready", color: "var(--seal)", textClass: "text-seal dark:text-seal-soft" };
  if (score >= 60)
    return { label: "Exposed", color: "var(--brass)", textClass: "text-brass-deep dark:text-brass" };
  return { label: "At risk", color: "var(--ember)", textClass: "text-ember dark:text-ember-soft" };
}

function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || !window.matchMedia) return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export function ScoreDial({ score, className }: { score: number; className?: string }) {
  const [displayed, setDisplayed] = useState(() => (prefersReducedMotion() ? score : 0));
  const frameRef = useRef<number | null>(null);

  useEffect(() => {
    if (prefersReducedMotion()) {
      setDisplayed(score);
      return;
    }
    const start = performance.now();
    const step = (now: number) => {
      const t = Math.min(1, (now - start) / DURATION_MS);
      // Matches --ease-ledger: decelerating, no overshoot.
      const eased = 1 - Math.pow(1 - t, 3);
      setDisplayed(score * eased);
      if (t < 1) frameRef.current = requestAnimationFrame(step);
    };
    frameRef.current = requestAnimationFrame(step);
    return () => {
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
    };
  }, [score]);

  const band = bandForScore(score);
  const dash = SWEEP * Math.max(0, Math.min(100, displayed));

  return (
    <div className={cn("relative aspect-square w-full max-w-[240px]", className)}>
      <svg viewBox="0 0 200 200" className="size-full" aria-hidden="true">
        {/* Track: the unfilled 270-degree channel. */}
        <circle
          cx="100"
          cy="100"
          r="82"
          fill="none"
          stroke="var(--border)"
          strokeWidth="10"
          strokeLinecap="round"
          pathLength={100}
          strokeDasharray={`${SWEEP * 100} 100`}
          transform="rotate(135 100 100)"
        />
        {/* Value arc. */}
        <circle
          cx="100"
          cy="100"
          r="82"
          fill="none"
          stroke={band.color}
          strokeWidth="10"
          strokeLinecap="round"
          pathLength={100}
          strokeDasharray={`${dash} 100`}
          transform="rotate(135 100 100)"
        />
        {/* Stamp ticks at the gauge terminals. */}
        <circle cx="100" cy="100" r="94" fill="none" stroke="var(--border)" strokeWidth="1" />
      </svg>

      <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
        <span
          data-evidence
          className={cn("text-6xl leading-none font-medium", band.textClass)}
        >
          {Math.round(displayed)}
        </span>
        <span data-evidence className="mt-2 text-sm text-muted-foreground">
          / 100
        </span>
      </div>
    </div>
  );
}

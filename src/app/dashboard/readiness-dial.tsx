"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

// Semicircular gauge: centre (110, 112), radius 92, swept 180deg -> 0deg.
const ARC_PATH = "M 18 112 A 92 92 0 0 1 202 112";
const ARC_LENGTH = Math.PI * 92;
const SWEEP_MS = 900;

/**
 * Compliance ramp from the visual brief: ember (critical) -> brass (at risk)
 * -> deep brass (watch) -> seal (compliant). Never a red/green traffic light.
 */
function bandFor(score: number): { stroke: string; text: string; label: string } {
  if (score < 40) {
    return { stroke: "stroke-chart-1", text: "text-chart-1", label: "Critical exposure" };
  }
  if (score < 60) {
    return { stroke: "stroke-chart-2", text: "text-chart-2", label: "At risk" };
  }
  if (score < 80) {
    return { stroke: "stroke-chart-3", text: "text-chart-3", label: "Gaps remaining" };
  }
  return { stroke: "stroke-chart-4", text: "text-chart-4", label: "Audit ready" };
}

function easeOutCubic(t: number): number {
  return 1 - Math.pow(1 - t, 3);
}

/**
 * b-03 / b-14: the readiness score carried from the anonymous /score
 * questionnaire, so a brand-new account is never an empty shell.
 */
export function ReadinessDial({
  score,
  gapCount,
}: {
  score: number | null;
  gapCount: number;
}) {
  const target = score ?? 0;
  const [swept, setSwept] = useState(0);

  useEffect(() => {
    if (score === null) return;

    const reduced =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced) {
      setSwept(target);
      return;
    }

    let frame = 0;
    const start = performance.now();
    const tick = (stamp: number) => {
      const progress = Math.min(1, (stamp - start) / SWEEP_MS);
      setSwept(target * easeOutCubic(progress));
      if (progress < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [score, target]);

  if (score === null) {
    return (
      <div className="flex h-full flex-col justify-between rounded-lg bg-card p-5 elev-1">
        <div>
          <p className="eyebrow">Audit-readiness score</p>
          <h3 className="mt-4 font-display text-2xl leading-[1.15] tracking-[-1.2px] [word-spacing:0.06em]">
            You have not scored this restaurant yet
          </h3>
          <p className="mt-3 text-sm leading-[1.55] text-muted-foreground">
            The score is the fastest read on where you stand: seven questions about
            notices, tip-pool composition, and how overtime is calculated, and it takes
            about two minutes.
          </p>
        </div>
        <Link
          href="/score"
          className={cn(buttonVariants(), "mt-6 h-11 rounded-full px-6 text-base")}
        >
          Score my restaurant
        </Link>
      </div>
    );
  }

  const band = bandFor(score);
  const offset = ARC_LENGTH * (1 - swept / 100);

  return (
    <div className="flex h-full flex-col rounded-lg bg-card p-5 elev-1">
      <p className="eyebrow">Audit-readiness score</p>

      <div
        role="img"
        aria-label={`Audit-readiness score: ${score} out of 100. ${band.label}.`}
        className="relative mx-auto mt-4 w-full max-w-[280px]"
      >
        <svg viewBox="0 0 220 130" className="w-full" aria-hidden="true">
          <path
            d={ARC_PATH}
            fill="none"
            strokeWidth={14}
            strokeLinecap="round"
            className="stroke-muted"
          />
          <path
            d={ARC_PATH}
            fill="none"
            strokeWidth={14}
            strokeLinecap="round"
            strokeDasharray={ARC_LENGTH}
            strokeDashoffset={offset}
            className={band.stroke}
          />
          <text
            x={110}
            y={104}
            textAnchor="middle"
            className={cn("font-mono text-[52px] font-medium", band.text)}
            fill="currentColor"
            style={{ fontFeatureSettings: '"tnum"' }}
          >
            {Math.round(swept)}
          </text>
        </svg>
      </div>

      <p className={cn("text-center font-display text-xl tracking-[-1.2px] [word-spacing:0.06em]", band.text)}>
        {band.label}
      </p>
      <p className="mt-2 text-center text-sm leading-[1.5] text-muted-foreground">
        {gapCount > 0
          ? `${gapCount} gap${gapCount === 1 ? "" : "s"} are holding this number down.`
          : "No open gaps from your questionnaire answers."}
      </p>

      <Link
        href="/score"
        className={cn(
          buttonVariants({ variant: "outline" }),
          "mt-5 h-11 w-full px-5 text-base"
        )}
      >
        Re-score after a change
      </Link>
    </div>
  );
}

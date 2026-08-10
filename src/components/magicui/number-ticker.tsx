"use client";

import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";

/**
 * NumberTicker — counts a tabular-numeral figure up when it scrolls into view.
 *
 * Safety contract: the server render and the first client paint both show the
 * FINAL value. The count-up only starts once the client has confirmed motion is
 * allowed and the element is intersecting, so the figure is never blank and
 * never stranded mid-count (a failsafe snaps it to `value`).
 *
 * All figures on this product are evidence — they render in IBM Plex Mono with
 * tabular-nums (visual brief guardrail 5).
 */
export function NumberTicker({
  value,
  from = 0,
  decimals = 0,
  prefix = "",
  suffix = "",
  duration = 1400,
  className,
}: {
  value: number;
  from?: number;
  decimals?: number;
  prefix?: string;
  suffix?: string;
  duration?: number;
  className?: string;
}) {
  const ref = useRef<HTMLSpanElement | null>(null);
  const [display, setDisplay] = useState(value);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    let raf = 0;
    let done = false;

    const run = () => {
      const start = performance.now();
      const tick = (now: number) => {
        const t = Math.min(1, (now - start) / duration);
        // easeOutExpo — mechanical settle, no overshoot.
        const eased = t === 1 ? 1 : 1 - Math.pow(2, -9 * t);
        setDisplay(from + (value - from) * eased);
        if (t < 1) raf = requestAnimationFrame(tick);
        else done = true;
      };
      raf = requestAnimationFrame(tick);
    };

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting && !done) {
            setDisplay(from);
            run();
            observer.disconnect();
          }
        }
      },
      { threshold: 0.35 }
    );
    observer.observe(el);

    const failsafe = window.setTimeout(() => {
      if (!done) setDisplay(value);
    }, duration + 4000);

    return () => {
      cancelAnimationFrame(raf);
      window.clearTimeout(failsafe);
      observer.disconnect();
    };
  }, [value, from, duration]);

  return (
    <span
      ref={ref}
      className={cn("figure tabular-nums", className)}
      aria-label={`${prefix}${value.toFixed(decimals)}${suffix}`}
    >
      {prefix}
      {display.toLocaleString("en-US", {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
      })}
      {suffix}
    </span>
  );
}

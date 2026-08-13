"use client";

import { useEffect, useRef } from "react";
import { cn } from "@/lib/utils";

/**
 * ScrollProgress — a 2px brass filament across the top of the sticky header
 * that fills as the document is read.
 *
 * Written directly to the DOM node via rAF instead of React state: this fires
 * on every scroll frame and must not re-render the tree. Renders at scaleX(0)
 * with nothing else hidden, so it is purely additive.
 */
export function ScrollProgress({ className }: { className?: string }) {
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    let raf = 0;
    const update = () => {
      raf = 0;
      const doc = document.documentElement;
      const max = doc.scrollHeight - doc.clientHeight;
      const ratio = max > 0 ? Math.min(1, Math.max(0, doc.scrollTop / max)) : 0;
      el.style.transform = `scaleX(${ratio})`;
    };
    const onScroll = () => {
      if (!raf) raf = requestAnimationFrame(update);
    };

    update();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
    };
  }, []);

  return (
    <div
      ref={ref}
      aria-hidden="true"
      className={cn(
        "pointer-events-none absolute inset-x-0 bottom-0 h-[2px] origin-left scale-x-0 bg-brass",
        className
      )}
    />
  );
}

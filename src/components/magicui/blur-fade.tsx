"use client";

import {
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";
import { cn } from "@/lib/utils";

type RevealTag = "div" | "section" | "li" | "ul" | "article" | "header" | "figure";

/**
 * BlurFade — scroll reveal (blur 5px → 0, translateY 14px → 0).
 *
 * Safety contract (design.md quality invariant 3):
 *   - The reveal is ADDITIVE only — blur and translate, never opacity or
 *     visibility. Content can never be blank, in any capture mode.
 *   - The SSR / no-JS render is the FINAL settled state. Nothing is hidden by
 *     markup, only by a class the client applies after mount.
 *   - Elements already inside the viewport at mount are never hidden — they
 *     render static. This is the "initial isIntersecting === true" case.
 *   - `prefers-reduced-motion: reduce` skips the mechanism entirely.
 *   - A failsafe timer forces the visible state even if the observer never
 *     fires (bfcache restore, observer starvation, print).
 *
 * Requires <MagicEffects /> mounted in the tree (see ./effects.tsx).
 */
export function BlurFade({
  children,
  className,
  delay = 0,
  as = "div",
  once = true,
}: {
  children: ReactNode;
  className?: string;
  /** Stagger delay in ms — brief calls for 55ms between siblings, cap 6. */
  delay?: number;
  as?: RevealTag;
  once?: boolean;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  const [state, setState] = useState<"static" | "hidden" | "visible">("static");

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    // Already on screen → leave it static (visible, no animation).
    if (el.getBoundingClientRect().top < window.innerHeight - 40) return;

    setState("hidden");

    const failsafe = window.setTimeout(() => setState("visible"), 1200);
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            setState("visible");
            if (once) observer.disconnect();
          } else if (!once) {
            setState("hidden");
          }
        }
      },
      { rootMargin: "0px 0px -8% 0px", threshold: 0.06 }
    );
    observer.observe(el);

    return () => {
      window.clearTimeout(failsafe);
      observer.disconnect();
    };
  }, [once]);

  const Tag = as as "div";

  return (
    <Tag
      ref={ref}
      data-blur-fade=""
      data-state={state}
      style={delay ? ({ "--bf-delay": `${delay}ms` } as CSSProperties) : undefined}
      className={cn(className)}
    >
      {children}
    </Tag>
  );
}

import type { CSSProperties, ReactNode } from "react";
import { cn } from "@/lib/utils";

/**
 * AnimatedShinyText — a slow brass light sweep across a text run.
 *
 * Reads as the bar light passing over a foil seal. Used on the hero eyebrow and
 * the pricing anchor label only — never on body copy.
 *
 * `tone` picks the pair of brand tokens so the run always clears contrast:
 *   - "ink"   → brass (#C89230, 6.33:1 on ink) with an oat-brass highlight
 *   - "paper" → brass-deep (#8A5F14, 4.89:1 on paper) with a brass highlight
 *
 * Requires <MagicEffects /> mounted in the tree (see ./effects.tsx).
 */
export function AnimatedShinyText({
  children,
  className,
  tone = "paper",
}: {
  children: ReactNode;
  className?: string;
  tone?: "ink" | "paper";
}) {
  const style =
    tone === "ink"
      ? ({ "--tg-shiny-base": "var(--brass)", "--tg-shiny-hi": "#f4e7c6" } as CSSProperties)
      : ({ "--tg-shiny-base": "var(--brass-deep)", "--tg-shiny-hi": "var(--brass)" } as CSSProperties);

  return (
    <span className={cn("tg-shiny", className)} style={style}>
      {children}
    </span>
  );
}

import type { CSSProperties, ReactNode } from "react";
import { cn } from "@/lib/utils";

/**
 * Marquee — a continuously advancing tape. Used for the evidence tape band
 * (record chips), which is the one place on this page where motion is ambient
 * rather than confirmatory.
 *
 * The track is duplicated once and the copy is aria-hidden so screen readers
 * read the run a single time. Hovering pauses the tape so a chip stays readable.
 *
 * Requires <MagicEffects /> mounted in the tree (see ./effects.tsx).
 */
export function Marquee({
  children,
  className,
  durationSeconds = 52,
  gap = "2rem",
}: {
  children: ReactNode;
  className?: string;
  durationSeconds?: number;
  gap?: string;
}) {
  const style = {
    "--tg-duration": `${durationSeconds}s`,
    "--tg-gap": gap,
  } as CSSProperties;

  return (
    <div className={cn("tg-marquee", className)} style={style}>
      <div className="tg-marquee-track">{children}</div>
      <div className="tg-marquee-track" aria-hidden="true">
        {children}
      </div>
    </div>
  );
}

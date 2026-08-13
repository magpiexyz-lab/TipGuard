import type { CSSProperties } from "react";

/**
 * BorderBeam — a single brass filament that travels the perimeter of a card.
 *
 * Restricted by the visual brief to the signed-notice card in the hero: it is
 * the "live record" signal, and it loses all meaning if it decorates every card.
 *
 * Usage: the parent must be `relative`, `overflow-hidden`, radius-bearing, and
 * padded by 1px with an opaque inner surface — the beam paints the ring that
 * the inner surface does not cover.
 *
 * Requires <MagicEffects /> mounted in the tree (see ./effects.tsx).
 */
export function BorderBeam({ duration = 9 }: { duration?: number }) {
  return (
    <div className="tg-beam-wrap" aria-hidden="true">
      <div
        className="tg-beam"
        style={{ "--tg-beam-duration": `${duration}s` } as CSSProperties}
      />
    </div>
  );
}

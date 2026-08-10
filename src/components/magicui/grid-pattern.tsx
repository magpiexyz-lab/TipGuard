import { cn } from "@/lib/utils";

/**
 * GridPattern — the ledger rule, rendered as SVG so a section can control rule
 * density, direction and edge fade independently of the `.texture-rule`
 * utility in globals.css.
 *
 * `variant="rule"`  → horizontal ledger lines only (the 32px writing rhythm)
 * `variant="grid"`  → ledger + column rules (the ruled account book)
 *
 * Purely decorative — always aria-hidden, never interactive.
 */
export function GridPattern({
  size = 32,
  variant = "rule",
  className,
  stroke = "var(--rule-color)",
  fade = "bottom",
}: {
  size?: number;
  variant?: "rule" | "grid";
  className?: string;
  /** Any CSS color — pass a token var, never a literal hex. */
  stroke?: string;
  fade?: "bottom" | "top" | "none" | "radial";
}) {
  const id = `tg-grid-${variant}-${size}`;
  const mask =
    fade === "bottom"
      ? "linear-gradient(to bottom, black 0%, black 55%, transparent 100%)"
      : fade === "top"
        ? "linear-gradient(to top, black 0%, black 55%, transparent 100%)"
        : fade === "radial"
          ? "radial-gradient(ellipse 70% 70% at 50% 40%, black 30%, transparent 100%)"
          : undefined;

  return (
    <svg
      aria-hidden="true"
      className={cn("pointer-events-none absolute inset-0 h-full w-full", className)}
      style={mask ? { maskImage: mask, WebkitMaskImage: mask } : undefined}
    >
      <defs>
        <pattern id={id} width={size} height={size} patternUnits="userSpaceOnUse">
          <path
            d={variant === "grid" ? `M ${size} 0 L 0 0 0 ${size}` : `M 0 0 L ${size} 0`}
            fill="none"
            strokeWidth={1}
            stroke={stroke}
          />
        </pattern>
      </defs>
      <rect width="100%" height="100%" fill={`url(#${id})`} />
    </svg>
  );
}

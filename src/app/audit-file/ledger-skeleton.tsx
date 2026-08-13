/**
 * Ruled loading skeleton — oat bars on the 32px ledger rhythm, revealed
 * top-to-bottom on a 55ms stagger (visual brief, "Loading states"). `skeleton`
 * is not in this project's installed shadcn set; the brief specifies a bespoke
 * ruled treatment rather than a generic pulsing block.
 */
export function LedgerSkeleton({
  rows = 4,
  label = "Assembling your audit file",
  className = "",
}: {
  rows?: number;
  label?: string;
  className?: string;
}) {
  return (
    <div
      className={`flex flex-col ${className}`}
      role="status"
      aria-live="polite"
      aria-busy="true"
    >
      <span className="sr-only">{label}</span>
      {Array.from({ length: rows }).map((_, index) => (
        <div
          key={`audit-skeleton-row-${index}`}
          className="flex h-11 items-center border-b border-border"
          aria-hidden="true"
        >
          <div
            className="h-3 animate-pulse rounded-sm bg-muted"
            style={{
              animationDelay: `${index * 55}ms`,
              width: `${72 - (index % 4) * 11}%`,
            }}
          />
        </div>
      ))}
    </div>
  );
}

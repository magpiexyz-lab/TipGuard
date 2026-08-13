/**
 * Ruled loading skeleton — oat bars on the 32px ledger rhythm, revealed
 * top-to-bottom on a 55ms stagger (visual brief, "Loading states"). Not a
 * substitute for a shadcn primitive: `skeleton` is not part of this project's
 * installed component set and the brief specifies a bespoke ruled treatment.
 */
export function LedgerSkeleton({
  rows = 3,
  className = "",
}: {
  rows?: number;
  className?: string;
}) {
  return (
    <div
      className={`flex flex-col gap-3 ${className}`}
      role="status"
      aria-live="polite"
      aria-busy="true"
    >
      <span className="sr-only">Loading your account status</span>
      {Array.from({ length: rows }).map((_, index) => (
        <div
          key={`ledger-skeleton-row-${index}`}
          className="h-8 animate-pulse rounded-md bg-muted"
          style={{ animationDelay: `${index * 55}ms`, width: `${100 - index * 12}%` }}
          aria-hidden="true"
        />
      ))}
    </div>
  );
}

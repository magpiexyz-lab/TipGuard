/**
 * Ruled skeleton for /dashboard — oat bars on the 32px ledger rhythm, revealed
 * top-to-bottom on a 55ms stagger rather than a single pop. Static markup only
 * (no client hooks) so it streams immediately while the loader runs.
 */
export default function Loading() {
  return (
    <div className="min-h-screen" aria-busy="true" aria-live="polite">
      <span className="sr-only">Loading your compliance dashboard…</span>

      <div className="dark surface-ink texture-grain bloom-brass border-b border-border">
        <div className="mx-auto max-w-[1180px] px-5 py-10 md:px-8 md:py-14">
          <div className="h-3 w-40 animate-pulse rounded-sm bg-muted" />
          <div className="mt-6 h-11 w-72 animate-pulse rounded-md bg-muted md:h-14" />
          <div className="mt-4 h-4 w-full max-w-md animate-pulse rounded-sm bg-muted" />
          <div className="mt-9 h-11 w-56 animate-pulse rounded-full bg-muted" />
        </div>
      </div>

      <div className="mx-auto max-w-[1180px] px-5 py-8 md:px-8 md:py-10">
        <div className="h-8 w-52 animate-pulse rounded-md bg-muted" />
        <div className="mt-5 grid gap-4 lg:grid-cols-[minmax(0,340px)_1fr]">
          <div className="rounded-lg bg-card p-5 elev-1">
            <div className="h-3 w-36 animate-pulse rounded-sm bg-muted" />
            <div className="mx-auto mt-6 h-32 w-full max-w-[260px] animate-pulse rounded-t-full bg-muted" />
            <div className="mx-auto mt-5 h-4 w-32 animate-pulse rounded-sm bg-muted" />
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            {[0, 1, 2, 3].map((tile) => (
              <div
                key={tile}
                className="rounded-lg bg-card p-5 elev-1"
                style={{ animationDelay: `${tile * 55}ms` }}
              >
                <div className="h-3 w-28 animate-pulse rounded-sm bg-muted" />
                <div className="mt-4 h-10 w-24 animate-pulse rounded-md bg-muted" />
                <div className="mt-4 h-3 w-full animate-pulse rounded-sm bg-muted" />
              </div>
            ))}
          </div>
        </div>

        <div className="texture-rule mt-10 h-40 rounded-lg bg-card elev-1" />
      </div>
    </div>
  );
}

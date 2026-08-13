/**
 * Ruled skeleton for /violations — oat bars on the 32px ledger rhythm,
 * revealed top-to-bottom on a 55ms stagger rather than a single pop.
 * Static markup only (no client hooks) so it streams instantly.
 */
export default function Loading() {
  return (
    <div className="min-h-screen" aria-busy="true" aria-live="polite">
      <span className="sr-only">Loading your open compliance findings…</span>

      <div className="dark surface-ink texture-grain bloom-brass border-b border-border">
        <div className="mx-auto max-w-[1180px] px-5 py-10 md:px-8 md:py-14">
          <div className="h-3 w-48 animate-pulse rounded-sm bg-muted" />
          <div className="mt-6 h-11 w-full max-w-xl animate-pulse rounded-md bg-muted md:h-14" />
          <div className="mt-4 h-4 w-full max-w-lg animate-pulse rounded-sm bg-muted" />
          <div className="mt-9 h-11 w-56 animate-pulse rounded-full bg-muted" />
        </div>
      </div>

      <div className="mx-auto max-w-[1180px] px-5 py-8 md:px-8 md:py-10">
        <div className="h-11 w-56 animate-pulse rounded-full bg-muted" />
        <div className="mt-6 grid gap-4">
          {[0, 1, 2].map((row) => (
            // The stagger has to live on an element that actually animates —
            // animationDelay on an un-animated wrapper is inert, which made all
            // three bars pulse in unison instead of reading top-to-bottom.
            <div
              key={row}
              className="animate-in fade-in slide-in-from-bottom-2 fill-mode-both overflow-hidden rounded-lg bg-card p-5 duration-300 elev-1"
              style={{ animationDelay: `${row * 55}ms` }}
            >
              <div className="h-5 w-24 animate-pulse rounded-sm bg-muted" />
              <div className="mt-4 h-7 w-2/3 animate-pulse rounded-md bg-muted" />
              <div className="texture-rule mt-6 h-32 rounded-md bg-muted/40" />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
